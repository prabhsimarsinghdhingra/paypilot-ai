import type { AgAiEvent, AgAiOutputItem, AgLlmAdapter, AgLlmRequest, AgLlmResponse } from "ag-studio";
import { API_BASE, tokenStore } from "./api";

type Out = { type: "message"; text: string } | { type: "function_call"; callId: string; name: string; arguments: string };
type TurnResult = { id: string; output: Out[] };

async function callBackend(req: AgLlmRequest, signal?: AbortSignal): Promise<TurnResult> {
  let r: Response;
  try {
    r = await fetch(`${API_BASE}/ai/studio-turn`, {
      method: "POST", signal, cache: "no-store",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${tokenStore.get() ?? ""}` },
      body: JSON.stringify({ input: req.input, instructions: req.instructions, tools: req.tools, toolChoice: req.toolChoice }),
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new Error("Cannot reach the PayPilot API. Is the backend running?");
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `The assistant failed (${r.status})`);
  return d as TurnResult;
}

/** Studio's model adapter. The model call happens on OUR backend (Gemini key stays server-side); Studio executes the tool calls it returns. */
export function pilotAdapter(): AgLlmAdapter {
  return {
    executeTurn(request, options) {
      const settled = callBackend(request, options?.signal).then(ok => ({ ok }), (err: Error) => ({ err }));
      const ev = <T extends AgAiEvent>(e: T) => ({ ...e, timestamp: Date.now() }) as T;
      async function* stream(): AsyncGenerator<AgAiEvent> {
        const r = await settled;
        if (!("ok" in r)) return;                       // failure is reported through `complete`, as the contract asks
        let n = 0;
        for (const o of r.ok.output) {
          if (o.type === "message") {
            const messageId = `${r.ok.id}_m${n++}`;
            yield ev({ type: "TEXT_MESSAGE_START", messageId, role: "assistant" } as AgAiEvent);
            yield ev({ type: "TEXT_MESSAGE_CONTENT", messageId, delta: o.text } as AgAiEvent);
            yield ev({ type: "TEXT_MESSAGE_END", messageId } as AgAiEvent);
          } else {
            yield ev({ type: "TOOL_CALL_START", toolCallId: o.callId, toolCallName: o.name } as AgAiEvent);
            yield ev({ type: "TOOL_CALL_ARGS", toolCallId: o.callId, delta: o.arguments } as AgAiEvent);
            yield ev({ type: "TOOL_CALL_END", toolCallId: o.callId } as AgAiEvent);
          }
        }
      }
      const complete = settled.then((r): AgLlmResponse => {
        if (!("ok" in r)) return { id: `err_${Date.now()}`, createdAt: Date.now(), output: [], status: "failed", error: { code: "backend_error", message: r.err.message } } as AgLlmResponse;
        const output = r.ok.output.map((o, i): AgAiOutputItem => o.type === "message"
          ? { id: `${r.ok.id}_m${i}`, kind: "output", type: "message", role: "assistant", status: "completed", content: [{ type: "text", text: o.text, annotations: [] }] }
          : { id: o.callId, kind: "output", type: "function_call", callId: o.callId, name: o.name, arguments: o.arguments, status: "completed" });
        return { id: r.ok.id, createdAt: Date.now(), output, status: "completed" } as AgLlmResponse;
      });
      return { stream: stream(), complete };
    },
  };
}
