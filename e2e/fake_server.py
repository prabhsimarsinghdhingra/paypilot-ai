"""Test-only backend entrypoint: the real app, with Gemini replaced by a deterministic rule-based model so the
agent -> proposal -> approval -> PayPal flow can be tested without a Gemini key. Production code is untouched."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app import deps  # noqa: E402
from app.main import app  # noqa: E402
from app.services.agent import Turn  # noqa: E402


class RuleLLM:
    def generate(self, system, contents, tools):
        last = contents[-1]
        if last["role"] == "user":
            if "overdue" in last["text"].lower(): return Turn(None, [{"name": "get_overdue_invoices", "args": {}}])
            if "failed" in last["text"].lower(): return Turn(None, [{"name": "get_failed_payments", "args": {"days": 30}}])
            return Turn("Here is a summary of your activity.", [])
        res = last["results"]
        if res[0]["name"] == "get_overdue_invoices":
            inv = res[0]["response"]["overdue_invoices"][:2]
            return Turn(None, [{"name": "propose_payment_reminder", "args": {"invoice_id": i["id"], "subject": f"Friendly reminder: invoice {i['number']}",
                       "note": f"Hi {i['customer']}, invoice {i['number']} is {i['days_overdue']} days overdue. Could you settle it this week? Thank you!"}} for i in inv])
        if res[0]["name"] == "propose_payment_reminder": return Turn(f"I prepared {len(res)} reminder(s). Nothing is sent until you approve them.", [])
        return Turn(f"You have {res[0]['response'].get('count', 0)} failed payments.", [])


app.dependency_overrides[deps.get_llm] = lambda: RuleLLM()


class StudioFake:
    """Deterministic stand-in for Gemini on /ai/studio-turn. Records what Studio sent so tests can assert on it."""
    log: list = []

    def complete(self, system, contents, tools):
        self.log.append({"system": system, "n_contents": len(contents), "tools": [t.name for t in tools],
                         "last_role": contents[-1].role, "last_is_result": bool(contents[-1].parts[0].function_response)})
        return "Hello from the PayPilot test model.", []


_studio = StudioFake()
app.dependency_overrides[deps.get_studio_model] = lambda: _studio


@app.get("/__test__/studio-log")
def studio_log(): return _studio.log
