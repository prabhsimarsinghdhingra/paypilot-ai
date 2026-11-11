"""Bridge between AG Studio's Agent Framework and Gemini.

Studio runs the agent loop in the browser and executes ITS tools (add widget, configure widget, ...) there. Its model adapter
calls this endpoint once per turn with the conversation so far; we call Gemini server-side (the key never reaches the browser)
and return the model's text and tool calls. Nothing here executes a tool, and nothing here can touch PayPal."""
import json, time, uuid
from typing import Any, Protocol
from pydantic import BaseModel, Field
from google.genai import types
from app.core.config import settings

MAX_ITEMS, MAX_TOOLS, MAX_INSTR, MAX_SCHEMA_CHARS = 200, 80, 60_000, 30_000
_SIGS: dict[str, tuple[float, bytes]] = {}  # callId -> (expiry, Gemini thought signature). In-memory: fine for one instance.
SKIP_SIG = b"skip_thought_signature_validator"  # Google's documented placeholder when a signature is unavailable


class ToolSchema(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.:\-]{0,63}$")
    description: str = Field(default="", max_length=4000)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    kind: str | None = None


class TurnIn(BaseModel):
    input: list[dict[str, Any]] = Field(max_length=MAX_ITEMS)
    instructions: str = Field(default="", max_length=MAX_INSTR)
    tools: list[ToolSchema] = Field(default_factory=list, max_length=MAX_TOOLS)
    toolChoice: Any = None


class StudioModel(Protocol):
    def complete(self, system: str, contents: list[types.Content], tools: list[ToolSchema]) -> tuple[str, list[dict]]: ...


def _remember(call_id: str, sig: bytes | None):
    now = time.time()
    for k in [k for k, (exp, _) in _SIGS.items() if exp < now]: _SIGS.pop(k, None)
    if sig: _SIGS[call_id] = (now + 3600, sig)


def _args(raw: Any) -> dict:
    if isinstance(raw, dict): return raw
    try: v = json.loads(raw or "{}"); return v if isinstance(v, dict) else {"value": v}
    except (TypeError, ValueError): return {}


def to_gemini(body: TurnIn, model: str) -> tuple[str, list[types.Content]]:
    """Studio conversation items -> (system text, Gemini contents). Consecutive tool calls / results are merged, as Gemini requires."""
    system, out, names = [body.instructions] if body.instructions else [], [], {}
    def add(role: str, part: types.Part):
        if out and out[-1].role == role and (role == "model" and part.function_call or role == "user" and part.function_response):
            if (out[-1].parts[-1].function_call is not None) == (part.function_call is not None) and (out[-1].parts[-1].function_response is not None) == (part.function_response is not None):
                out[-1].parts.append(part); return
        out.append(types.Content(role=role, parts=[part]))
    for it in body.input:
        t = it.get("type")
        if t == "message" and it.get("role") in ("user", "system"):
            text = "\n".join(c.get("text", "") for c in it.get("content", []) if c.get("type") == "text")
            if it["role"] == "system": system.append(text)
            elif text: out.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        elif t == "message" and it.get("role") == "assistant":
            text = "".join(c.get("text", "") for c in it.get("content", []) if c.get("type") == "text")
            if text: out.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
        elif t == "function_call":
            cid = it.get("callId", ""); names[cid] = it.get("name", "")
            part = types.Part(function_call=types.FunctionCall(name=it["name"], args=_args(it.get("arguments"))))
            first_of_turn = not (out and out[-1].role == "model" and out[-1].parts and out[-1].parts[-1].function_call is not None)
            sig = _SIGS.get(cid, (0, None))[1] or (SKIP_SIG if first_of_turn and "gemini-3" in model else None)
            if sig: part.thought_signature = sig
            add("model", part)
        elif t == "function_call_output":
            raw = it.get("output", "")
            try: resp = json.loads(raw); resp = resp if isinstance(resp, dict) else {"result": resp}
            except (TypeError, ValueError): resp = {"result": str(raw)[:20000]}
            add("user", types.Part.from_function_response(name=names.get(it.get("callId", ""), "unknown_tool"), response=resp))
        # reasoning items and anything else are dropped on purpose
    if not out: out.append(types.Content(role="user", parts=[types.Part.from_text(text="Hello")]))
    return "\n\n".join(s for s in system if s), out


class GeminiStudioModel:
    def __init__(self):
        from app.services.agent import GeminiLLM
        self.llm = GeminiLLM()

    def complete(self, system, contents, tools):
        decls = [types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters) for t in tools if t.kind in (None, "client", "server")]
        cfg = types.GenerateContentConfig(system_instruction=system or None, temperature=0.2, tools=[types.Tool(function_declarations=decls)] if decls else None,
                                          automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                                          **({"thinking_config": types.ThinkingConfig(thinking_level=settings.gemini_thinking_level.upper())} if settings.gemini_thinking_level else {}))
        resp = self.llm._call(contents, cfg)
        parts = (resp.candidates[0].content.parts if resp.candidates and resp.candidates[0].content else None) or []
        text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
        calls = [{"name": p.function_call.name, "args": dict(p.function_call.args or {}), "sig": getattr(p, "thought_signature", None)} for p in parts if p.function_call]
        return text, calls


def run_turn(body: TurnIn, model: StudioModel, model_name: str | None = None) -> dict:
    for t in body.tools:
        if len(json.dumps(t.parameters)) > MAX_SCHEMA_CHARS: raise ValueError(f"Tool schema for {t.name} is too large")
    system, contents = to_gemini(body, model_name or settings.gemini_model)
    text, calls = model.complete(system, contents, body.tools)
    output = []
    if text: output.append({"type": "message", "text": text})
    for c in calls:
        cid = "call_" + uuid.uuid4().hex[:24]; _remember(cid, c.get("sig"))
        output.append({"type": "function_call", "callId": cid, "name": c["name"], "arguments": json.dumps(c["args"])})
    return {"id": "resp_" + uuid.uuid4().hex[:16], "output": output}
