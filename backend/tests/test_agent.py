from app.services.agent import Turn
from app.main import app
from app import deps
from test_approvals import overdue, demo


class Scripted:
    def __init__(self, *turns): self.turns, self.seen = list(turns), []
    def generate(self, system, contents, tools):
        self.seen.append(contents); return self.turns.pop(0)


LLM = {}
def use(llm): LLM['x'] = llm; app.dependency_overrides[deps.get_llm] = lambda: llm


def test_chat_503_without_gemini_key(client, synced):
    assert client.post("/api/v1/ai/chat", json={"message": "hello there"}, headers=synced).status_code == 503


def test_read_tool_round_trip_uses_real_data(client, synced):
    use(Scripted(Turn(None, [{"name": "get_revenue_summary", "args": {"days": 90}}]), Turn("Revenue looks fine.", [])))
    r = client.post("/api/v1/ai/chat", json={"message": "How is revenue?"}, headers=synced).json()
    assert r["reply"] == "Revenue looks fine." and r["tool_calls"][0]["ok"] and r["tool_calls"][0]["kind"] == "read"
    llm_saw = LLM['x']
    tool_msg = llm_saw.seen[1][-1]["results"][0]["response"]
    assert {c["currency"] for c in tool_msg["by_currency"]} == {"USD", "EUR"}  # real DB data reached the model
    h = client.get(f"/api/v1/ai/conversations/{r['conversation_id']}", headers=synced).json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant"]


def test_agent_reminder_workflow_proposes_but_never_sends(client, synced):
    inv = overdue(client, synced)[0]
    use(Scripted(Turn(None, [{"name": "get_overdue_invoices", "args": {}}]),
                 Turn(None, [{"name": "propose_payment_reminder", "args": {"invoice_id": inv["id"], "subject": "Friendly reminder", "note": "Hi, invoice is overdue."}}]),
                 Turn("I prepared one reminder for your approval.", [])))
    r = client.post("/api/v1/ai/chat", json={"message": "Find overdue invoices and prepare reminders"}, headers=synced).json()
    assert len(r["actions"]) == 1 and r["actions"][0]["status"] == "PENDING" and r["actions"][0]["source"] == "ai"
    assert demo(synced, client).calls == []
    assert client.post(f"/api/v1/actions/{r['actions'][0]['id']}/approve", headers=synced).json()["status"] == "COMPLETED"


def test_malformed_and_unauthorized_tool_calls_are_contained(client, synced):
    other_inv = overdue(client, synced)[0]["id"]
    use(Scripted(Turn(None, [{"name": "get_transactions", "args": {"days": "banana", "status": "X"}},
                             {"name": "drop_database", "args": {}},
                             {"name": "propose_payment_reminder", "args": {"invoice_id": "does-not-exist", "subject": "hello", "note": "hello there"}},
                             {"name": "propose_send_invoice", "args": {"invoice_id": other_inv}}]),   # SENT invoice, not DRAFT
                 Turn("Done.", [])))
    r = client.post("/api/v1/ai/chat", json={"message": "do bad things"}, headers=synced).json()
    assert [t["ok"] for t in r["tool_calls"]] == [False, False, False, False] and r["actions"] == []
    assert client.get("/api/v1/actions", headers=synced).json() == []


def test_step_limit(client, synced):
    use(Scripted(*[Turn(None, [{"name": "get_failed_payments", "args": {}}])] * 10))
    r = client.post("/api/v1/ai/chat", json={"message": "loop forever"}, headers=synced).json()
    assert "step limit" in r["reply"]
