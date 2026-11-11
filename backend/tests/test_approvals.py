from conftest import signup
from app import deps
from app.db import SessionLocal


def overdue(client, h):
    return [i for i in client.get("/api/v1/invoices", headers=h).json() if i["days_overdue"] > 0]


def demo(user_headers, client):
    return next(iter(deps._clients.values()))


def test_proposal_does_not_execute_until_approved(client, synced):
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    assert a["status"] == "PENDING" and demo(synced, client).calls == []  # nothing sent yet
    done = client.post(f"/api/v1/actions/{a['id']}/approve", headers=synced).json()
    assert done["status"] == "COMPLETED" and done["executed_at"]
    assert demo(synced, client).calls[-1][0] == "remind_invoice"
    ev = [l["event"] for l in client.get("/api/v1/audit", headers=synced).json() if l["action_id"] == a["id"]]
    assert {"proposed", "approved", "executed"} <= set(ev)


def test_double_approve_executes_once(client, synced):
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    assert client.post(f"/api/v1/actions/{a['id']}/approve", headers=synced).status_code == 200
    assert client.post(f"/api/v1/actions/{a['id']}/approve", headers=synced).status_code == 409
    assert sum(c[0] == "remind_invoice" for c in demo(synced, client).calls) == 1


def test_reject_and_cancel_block_execution(client, synced):
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    assert client.post(f"/api/v1/actions/{a['id']}/reject", headers=synced).json()["status"] == "REJECTED"
    assert client.post(f"/api/v1/actions/{a['id']}/approve", headers=synced).status_code == 409
    assert demo(synced, client).calls == []


def test_other_user_cannot_decide_my_action(client, synced):
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    other = signup(client, "b@example.com")
    assert client.post(f"/api/v1/actions/{a['id']}/approve", headers=other).status_code == 404
    assert client.get("/api/v1/actions", headers=other).json() == []


def test_paypal_failure_is_recorded_not_retried(client, synced):
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    demo(synced, client).fail_next = "remind_invoice"
    r = client.post(f"/api/v1/actions/{a['id']}/approve", headers=synced).json()
    assert r["status"] == "FAILED" and "Simulated" in r["error"]
    assert client.post(f"/api/v1/actions/{a['id']}/approve", headers=synced).status_code == 409


def test_revalidation_blocks_stale_proposal(client, synced):
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    with SessionLocal() as db:  # invoice gets paid between proposal and approval
        from app.models import Invoice
        i = db.get(Invoice, inv["id"]); i.status = "PAID"; db.commit()
    r = client.post(f"/api/v1/actions/{a['id']}/approve", headers=synced).json()
    assert r["status"] == "FAILED" and "PAID" in r["error"] and not [c for c in demo(synced, client).calls if c[0] == "remind_invoice"]


def test_invoice_create_then_send_needs_two_steps(client, synced):
    body = {"recipient_email": "new@customer.example", "recipient_name": "New Co", "currency": "USD", "due_in_days": 10,
            "items": [{"name": "Consulting", "quantity": 2, "unit_amount": 100, "tax_percent": 10}]}
    assert client.post("/api/v1/invoices/preview", json=body, headers=synced).json()["total"] == 220.0
    d = client.post("/api/v1/invoices", json=body, headers=synced).json()
    assert d["status"] == "COMPLETED" and d["result"]["status"] == "DRAFT" and d["result"]["total"] == 220.0
    assert not [c for c in demo(synced, client).calls if c[0] == "send_invoice"]  # draft != sent
    s = client.post(f"/api/v1/invoices/{d['result']['invoice_id']}/request-send", json={}, headers=synced).json()
    assert s["status"] == "PENDING"
    assert client.post(f"/api/v1/actions/{s['id']}/approve", headers=synced).json()["result"]["status"] == "SENT"
    assert client.post("/api/v1/invoices", json={**body, "recipient_email": "not-an-email"}, headers=synced).status_code == 422
    assert client.post("/api/v1/invoices", json={**body, "items": [{"name": "x", "unit_amount": -5}]}, headers=synced).status_code == 422


def test_identical_pending_proposals_are_deduplicated(client, synced):
    """Regression: the dedupe query used `json = json`, which works on SQLite but crashes on PostgreSQL."""
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    b = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=synced).json()
    assert a["id"] == b["id"] and len(client.get("/api/v1/actions?status=PENDING", headers=synced).json()) == 1


def test_custom_reminder_subject_and_note_are_kept(client, synced):
    """Used by the Studio agent tool and the scoreboard widget, which both queue a reminder with their own wording."""
    inv = overdue(client, synced)[0]
    a = client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={"subject": "Quick nudge", "note": "Hi! Just a heads-up about this one."}, headers=synced).json()
    assert a["status"] == "PENDING" and a["payload"]["subject"] == "Quick nudge" and a["payload"]["note"].startswith("Hi! Just")
    assert demo(synced, client).calls == []
