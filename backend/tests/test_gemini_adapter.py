import pytest
from google.genai import errors, types
from app.core.config import settings
from app.services.agent import GeminiLLM, REGISTRY


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key"); monkeypatch.setattr("time.sleep", lambda s: None)
    return GeminiLLM()


def resp(*parts): return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])
def err(code): return errors.APIError(code, {"error": {"message": "x", "status": "S"}})


def test_parses_function_calls_and_text(llm):
    llm.client.models.generate_content = lambda **kw: resp(types.Part.from_function_call(name="get_revenue_summary", args={"days": 30}))
    t = llm.generate("sys", [{"role": "user", "text": "hi"}], list(REGISTRY.values()))
    assert t.calls == [{"name": "get_revenue_summary", "args": {"days": 30}}] and t.raw is not None
    llm.client.models.generate_content = lambda **kw: resp(types.Part.from_text(text="All good."))
    assert llm.generate("sys", [{"role": "user", "text": "hi"}], []).text == "All good."


def test_tool_results_go_back_as_one_user_content_and_raw_model_turn_is_kept(llm):
    seen = {}
    raw = types.Content(role="model", parts=[types.Part.from_function_call(name="a", args={}), types.Part.from_function_call(name="b", args={})])
    def fake(**kw): seen.update(kw); return resp(types.Part.from_text(text="done"))
    llm.client.models.generate_content = fake
    llm.generate("sys", [{"role": "user", "text": "q"}, {"role": "model", "text": None, "raw": raw},
                         {"role": "tool", "results": [{"name": "a", "response": {"x": 1}}, {"name": "b", "response": {"y": 2}}]}], [])
    conv = seen["contents"]
    assert conv[1] is raw  # thought signatures live inside the raw content; it must be passed back untouched
    assert conv[2].role == "user" and [p.function_response.name for p in conv[2].parts] == ["a", "b"]


def test_every_tool_declaration_is_accepted_by_the_sdk():
    for t in REGISTRY.values():
        types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.params)


def test_overload_retries_then_falls_back(llm, monkeypatch):
    monkeypatch.setattr(settings, "gemini_model", "main"); monkeypatch.setattr(settings, "gemini_fallback_models", "backup")
    seen = []
    def fake(model, **kw):
        seen.append(model)
        if model == "main": raise err(503)
        return resp(types.Part.from_text(text="ok"))
    llm.client.models.generate_content = fake
    assert llm.generate("s", [{"role": "user", "text": "q"}], []).text == "ok"
    assert seen == ["main", "main", "backup"]


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_auth_and_model_errors_fail_fast(llm, monkeypatch, code):
    seen = []
    def fake(model, **kw): seen.append(model); raise err(code)
    llm.client.models.generate_content = fake
    with pytest.raises(errors.APIError) as e: llm.generate("s", [{"role": "user", "text": "q"}], [])
    assert e.value.code == code and len(seen) == 1


def test_chat_endpoint_reports_busy_and_real_errors(client, synced):
    from app.main import app; from app import deps
    class Busy:
        def generate(self, *a): raise err(503)
    class BadKey:
        def generate(self, *a): raise err(401)
    app.dependency_overrides[deps.get_llm] = lambda: Busy()
    r = client.post("/api/v1/ai/chat", json={"message": "hello there"}, headers=synced)
    assert r.status_code == 503 and "busy" in r.json()["detail"].lower()
    app.dependency_overrides[deps.get_llm] = lambda: BadKey()
    r = client.post("/api/v1/ai/chat", json={"message": "hello there"}, headers=synced)
    assert r.status_code == 502 and "401" in r.json()["detail"]
