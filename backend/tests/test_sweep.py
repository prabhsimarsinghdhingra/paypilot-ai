import asyncio
from datetime import datetime
from sqlalchemy import select
from app import deps
from app.core.security import encrypt
from app.db import SessionLocal
from app.main import app
from app.models import Invoice, PayPalAccount, User
from app.services import sweep as sw
from conftest import signup
from test_approvals import demo, overdue


def pending(client, h): return client.get("/api/v1/actions?status=PENDING", headers=h).json()


def test_sweep_prepares_reminders_for_overdue_invoices_and_sends_nothing(client, auth):
    r = client.post("/api/v1/sweep", headers=auth).json()
    assert r["mode"] == "inline" and r["status"] == "completed" and r["result"]["proposed"] == 3
    acts = pending(client, auth)
    assert len(acts) == 3 and {a["source"] for a in acts} == {"sweep"} and all(a["type"] == "send_reminder" for a in acts)
    late = {i["id"] for i in overdue(client, auth)}
    assert {a["payload"]["invoice_id"] for a in acts} == late                      # only overdue + unpaid invoices (not PAID, DRAFT or not-yet-due)
    assert all("friendly" in a["payload"]["subject"].lower() and "ignore" in a["payload"]["note"] for a in acts)
    assert demo(auth, client).calls == []                                           # prepared, never sent
    ev = client.get("/api/v1/audit", headers=auth).json(); assert "sweep" in {e["event"] for e in ev}


def test_sweep_is_idempotent_and_respects_the_cooldown(client, auth):
    client.post("/api/v1/sweep", headers=auth)
    again = client.post("/api/v1/sweep", headers=auth).json()["result"]
    assert again["proposed"] == 0 and again["already_queued"] == 3 and len(pending(client, auth)) == 3   # no duplicate nags
    first = pending(client, auth)[0]
    assert client.post(f"/api/v1/actions/{first['id']}/approve", headers=auth).json()["status"] == "COMPLETED"
    after = client.post("/api/v1/sweep", headers=auth).json()["result"]
    assert after["proposed"] == 0 and after["recently_reminded"] == 1 and after["already_queued"] == 2   # the one just reminded is left alone for a week


def test_sweep_only_touches_the_callers_account(client, auth):
    other = signup(client, "b@example.com")
    client.post("/api/v1/sweep", headers=other)
    assert len(pending(client, other)) == 3 and len(pending(client, auth)) == 0


def test_render_path_starts_a_workflow_run_and_only_the_owner_can_poll_it(client, auth, monkeypatch):
    class FakeRunner:
        started, polls = [], 0
        def start(self, user_id): self.started.append(user_id); return "trn-abc123"
        def status(self, run_id):
            FakeRunner.polls += 1
            return {"status": "running", "result": None, "error": None} if FakeRunner.polls == 1 else {"status": "completed", "result": {"proposed": 2}, "error": None}
    class SandboxClient: mode = "sandbox"
    import app.api.routes.sweep as route
    app.dependency_overrides[route.get_sweep_runner] = lambda: FakeRunner()
    app.dependency_overrides[deps.get_paypal] = lambda: SandboxClient()
    r = client.post("/api/v1/sweep", headers=auth).json()
    assert r == {"mode": "render", "run_id": "trn-abc123", "status": "pending"} and len(FakeRunner.started) == 1
    assert client.get("/api/v1/sweep/runs/trn-abc123", headers=auth).json()["status"] == "running"
    done = client.get("/api/v1/sweep/runs/trn-abc123", headers=auth).json(); assert done["status"] == "completed" and done["result"]["proposed"] == 2
    assert client.get("/api/v1/sweep/runs/trn-abc123", headers=signup(client, "b@example.com")).status_code == 404   # someone else's run
    assert client.get("/api/v1/sweep/runs/trn-unknown", headers=auth).status_code == 404


def test_demo_users_always_run_inline_even_when_render_is_configured(client, auth):
    import app.api.routes.sweep as route
    class Boom:
        def start(self, uid): raise AssertionError("must not call Render for a demo user")
    app.dependency_overrides[route.get_sweep_runner] = lambda: Boom()
    assert client.post("/api/v1/sweep", headers=auth).json()["mode"] == "inline"


def test_render_start_failure_is_reported_not_swallowed(client, auth):
    import app.api.routes.sweep as route
    class Down:
        def start(self, uid): raise RuntimeError("401 from Render")
    class SandboxClient: mode = "sandbox"
    app.dependency_overrides[route.get_sweep_runner] = lambda: Down(); app.dependency_overrides[deps.get_paypal] = lambda: SandboxClient()
    r = client.post("/api/v1/sweep", headers=auth); assert r.status_code == 502 and "RENDER_API_KEY" in r.json()["detail"]


def test_workflow_fan_out_isolates_failures_and_totals_results():
    import workflow_main as wf
    async def fake_run(task, uid):
        if uid == "bad": raise RuntimeError("task failed")
        return {"user_id": uid, "skipped": "demo"} if uid == "demo" else {"user_id": uid, "proposed": 2}
    out = asyncio.run(wf.fan_out(fake_run, object(), ["a", "bad", "demo", "b"]))
    assert out == {"accounts": 4, "swept": 2, "skipped": 1, "failed": 1, "reminders_proposed": 4}
    assert wf.sweep_account.name == "sweep_account" and wf.sweep_all.name == "sweep_all"


def test_worker_entry_point_skips_demo_accounts_and_lists_only_connected_ones(client, auth):
    with SessionLocal() as db:
        u = db.scalar(select(User)); uid = u.id
    assert sw.sweep_user_by_id(uid)["skipped"].startswith("demo simulator")      # simulator lives in the web process
    assert sw.sweep_user_by_id("nope")["skipped"] == "unknown user"
    assert sw.list_sweepable_user_ids() == []
    with SessionLocal() as db: db.add(PayPalAccount(user_id=uid, client_id="X" * 12, secret_encrypted=encrypt("s" * 12))); db.commit()
    assert sw.list_sweepable_user_ids() == [uid]


def test_reminder_wording_is_warm_and_specific():
    inv = Invoice(number="INV-7", recipient_name="Ada Lovelace", currency="USD", total=1200, due_date=datetime(2026, 11, 1).date())
    subject, note = sw.friendly_note(inv, datetime(2026, 11, 11).date())
    assert subject == "Friendly reminder: invoice INV-7" and note.startswith("Hi Ada,") and "USD 1,200.00" in note and "10 days ago" in note and "2026-11-01" in note
