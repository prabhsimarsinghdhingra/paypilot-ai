import json
from google.genai import errors, types
from app import deps
from app.main import app
from app.services import studio_bridge as sb


def user(text, id="u1"): return {"id": id, "kind": "input", "type": "message", "role": "user", "status": "completed", "content": [{"type": "text", "text": text}]}
def asst(text): return {"id": "a", "kind": "output", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "text", "text": text, "annotations": []}]}
def call(cid, name, args): return {"id": cid, "kind": "output", "type": "function_call", "callId": cid, "name": name, "arguments": json.dumps(args), "status": "completed"}
def result(cid, out): return {"type": "function_call_output", "callId": cid, "output": json.dumps(out), "status": "completed"}


def test_conversation_translation_merges_parallel_calls_and_maps_result_names():
    body = sb.TurnIn(input=[user("hi"), asst("hello"), user("chart it"), call("c1", "view_schema", {}), call("c2", "add_widget", {"type": "bar"}),
                            result("c1", {"fields": ["a"]}), result("c2", {"ok": True})], instructions="Be brief.")
    system, contents = sb.to_gemini(body, "gemini-2.5-flash")
    assert system == "Be brief."
    assert [c.role for c in contents] == ["user", "model", "user", "model", "user"]
    assert [p.function_call.name for p in contents[3].parts] == ["view_schema", "add_widget"]          # parallel calls stay in ONE model turn
    assert [p.function_response.name for p in contents[4].parts] == ["view_schema", "add_widget"]      # result names found via callId
    assert contents[4].parts[0].function_response.response == {"fields": ["a"]}


def test_system_items_go_to_instructions_and_reasoning_is_dropped():
    sysmsg = {**user("Rule: never invent numbers."), "role": "system"}
    system, contents = sb.to_gemini(sb.TurnIn(input=[sysmsg, {"type": "reasoning", "summary": []}, user("q")], instructions="A"), "m")
    assert system == "A\n\nRule: never invent numbers." and [c.role for c in contents] == ["user"]


def test_gemini3_gets_a_signature_on_the_first_call_of_a_turn_only(monkeypatch):
    body = sb.TurnIn(input=[user("q"), call("x1", "a", {}), call("x2", "b", {}), result("x1", {}), result("x2", {})])
    _, c = sb.to_gemini(body, "gemini-3.8-flash")
    assert c[1].parts[0].thought_signature == sb.SKIP_SIG and c[1].parts[1].thought_signature is None
    sb._SIGS["x1"] = (9e12, b"REAL")
    _, c = sb.to_gemini(body, "gemini-3.8-flash"); assert c[1].parts[0].thought_signature == b"REAL"
    _, c = sb.to_gemini(body, "gemini-2.5-flash"); assert c[1].parts[1].thought_signature is None


def test_malformed_arguments_and_outputs_do_not_crash():
    body = sb.TurnIn(input=[user("q"), {**call("c", "t", {}), "arguments": "{not json"}, {"type": "function_call_output", "callId": "c", "output": "plain text"}])
    _, c = sb.to_gemini(body, "m")
    assert c[1].parts[0].function_call.args == {} and c[2].parts[0].function_response.response == {"result": "plain text"}


class FakeModel:
    def __init__(self, *turns): self.turns, self.seen = list(turns), []
    def complete(self, system, contents, tools): self.seen.append((system, contents, tools)); return self.turns.pop(0)


def use(m): app.dependency_overrides[deps.get_studio_model] = lambda: m


TOOLS = [{"name": "add_widget", "description": "Adds a widget", "parameters": {"type": "object", "properties": {"type": {"type": "string"}}}}]


def test_endpoint_round_trip(client, auth):
    m = FakeModel(("Sure, adding it.", [{"name": "add_widget", "args": {"type": "bar"}, "sig": b"S1"}]), ("Done!", []))
    use(m)
    r = client.post("/api/v1/ai/studio-turn", json={"input": [{"type": "message", "role": "user", "content": [{"type": "text", "text": "add a bar chart"}]}], "tools": TOOLS}, headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()["output"]; assert out[0] == {"type": "message", "text": "Sure, adding it."} and out[1]["type"] == "function_call" and json.loads(out[1]["arguments"]) == {"type": "bar"}
    cid = out[1]["callId"]; assert sb._SIGS[cid][1] == b"S1"                                      # signature remembered for the next turn
    hist = [user("add a bar chart"), call(cid, "add_widget", {"type": "bar"}), result(cid, {"ok": True})]
    r2 = client.post("/api/v1/ai/studio-turn", json={"input": hist, "tools": TOOLS}, headers=auth).json()
    assert r2["output"] == [{"type": "message", "text": "Done!"}]
    assert m.seen[1][1][-1].parts[0].function_response.name == "add_widget"


def test_endpoint_requires_login_and_enforces_limits(client, auth):
    use(FakeModel())
    base = {"input": [{"type": "message", "role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    assert client.post("/api/v1/ai/studio-turn", json=base).status_code == 401
    assert client.post("/api/v1/ai/studio-turn", json={**base, "input": base["input"] * 201}, headers=auth).status_code == 422
    assert client.post("/api/v1/ai/studio-turn", json={**base, "tools": [{"name": "bad name!", "description": ""}]}, headers=auth).status_code == 422
    assert client.post("/api/v1/ai/studio-turn", json={**base, "instructions": "x" * 60_001}, headers=auth).status_code == 422
    big = {"name": "t", "parameters": {"type": "object", "description": "y" * 31_000}}
    assert client.post("/api/v1/ai/studio-turn", json={**base, "tools": [big]}, headers=auth).status_code == 422


def test_endpoint_reports_busy_and_real_errors(client, auth):
    body = {"input": [{"type": "message", "role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    class Boom:
        def __init__(self, code): self.code = code
        def complete(self, *a): raise errors.APIError(self.code, {"error": {"message": "nope", "status": "S"}})
    use(Boom(503)); r = client.post("/api/v1/ai/studio-turn", json=body, headers=auth); assert r.status_code == 503 and "busy" in r.json()["detail"].lower()
    use(Boom(401)); r = client.post("/api/v1/ai/studio-turn", json=body, headers=auth); assert r.status_code == 502 and "401" in r.json()["detail"]


def test_every_studio_style_schema_is_accepted_by_the_gemini_sdk():
    complex_schema = {"type": "object", "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]}, "b": {"$ref": "#/$defs/B"}}, "$defs": {"B": {"type": "string", "enum": ["x"]}}}
    types.FunctionDeclaration(name="t", description="d", parameters_json_schema=complex_schema)
