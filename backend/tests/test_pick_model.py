import importlib.util, os
from google.genai import types

spec = importlib.util.spec_from_file_location("pick_model", os.path.join(os.path.dirname(__file__), "..", "scripts", "pick_model.py"))
pm = importlib.util.module_from_spec(spec); spec.loader.exec_module(pm)


class M:
    def __init__(self, name, acts=("generateContent",)): self.name, self.supported_actions = name, list(acts)


class Fake:
    def __init__(self, behave): self.behave = behave; self.models = self
    def list(self): return [M("models/gemini-3.8-flash"), M("models/gemini-flash-latest"), M("models/gemini-3.8-flash-image"), M("models/gemini-3.8-pro"), M("models/text-embedding", ("embedContent",))]
    def generate_content(self, model, contents, config=None):
        self.behave(model, config)
        parts = [types.Part.from_function_call(name="get_failed_payments", args={"days": 30})] if config else [types.Part.from_text(text="ok")]
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=parts))])


def test_only_usable_flash_models_are_candidates():
    assert pm.candidates(Fake(lambda *a: None)) == ["gemini-flash-latest", "gemini-3.8-flash"]


def test_failures_are_reported_and_fastest_passing_model_recommended():
    class Err(Exception): code = 503; message = "overloaded"
    def behave(model, cfg):
        if model == "gemini-3.8-flash": raise Err()
    ticks = iter(range(0, 1000, 2)); clock = lambda: next(ticks)
    res = [pm.probe(Fake(behave), n, types, clock) for n in pm.candidates(Fake(behave))]
    bad = [r for r in res if not r["tool_ok"]][0]
    assert bad["model"] == "gemini-3.8-flash" and "503" in bad["error"]
    assert [r["model"] for r in pm.recommend(res)] == ["gemini-flash-latest"]
