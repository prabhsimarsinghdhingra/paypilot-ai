from datetime import datetime, timedelta, timezone
from conftest import signup
from app.services import analytics as an


def test_auth_flow(client):
    assert client.get("/api/v1/transactions").status_code == 401
    h = signup(client)
    assert client.get("/api/v1/auth/me", headers=h).json()["email"] == "a@example.com"
    assert client.post("/api/v1/auth/register", json={"email": "A@example.com", "password": "supersecret1"}).status_code == 409
    assert client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "supersecret1"}).status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "short"}).status_code == 422


def test_sync_is_idempotent_and_server_side_grid(client, synced):
    assert client.get("/api/v1/paypal/status", headers=synced).json()["mode"] == "demo"
    n = client.get("/api/v1/transactions?page_size=5", headers=synced).json()
    assert n["total"] > 50 and len(n["rows"]) == 5
    again = client.post("/api/v1/paypal/sync", headers=synced).json()["transactions"]
    assert again["added"] == 0  # no duplicates on re-sync
    d = client.get("/api/v1/transactions?status=D&page_size=100", headers=synced).json()
    assert d["total"] >= 5 and all(r["status"] == "D" for r in d["rows"])
    asc = client.get("/api/v1/transactions?sort_by=amount&sort_dir=asc&currency=USD&page_size=3", headers=synced).json()["rows"]
    assert asc[0]["amount"] <= asc[1]["amount"] <= asc[2]["amount"]
    assert client.get("/api/v1/transactions?q=initech", headers=synced).json()["total"] >= 1
    assert client.get("/api/v1/transactions?sort_by=password", headers=synced).status_code == 422


def test_users_are_isolated(client, synced):
    other = signup(client, "b@example.com")
    assert client.get("/api/v1/transactions", headers=other).json()["total"] == 0
    assert client.get("/api/v1/invoices", headers=other).json() == []
    inv = client.get("/api/v1/invoices", headers=synced).json()[0]
    assert client.post(f"/api/v1/invoices/{inv['id']}/request-reminder", json={}, headers=other).status_code == 404


def test_summary_never_mixes_currencies(client, synced):
    s = client.get("/api/v1/dashboard/summary", headers=synced).json()
    cur = {c["currency"] for c in s["by_currency"]}
    assert cur == {"USD", "EUR"} and "total_revenue" not in s


def test_analytics_forecast_and_anomalies():
    now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)  # Friday; last completed week = Mon Oct 26 .. Sun Nov 1
    start = datetime(2026, 8, 24, 9, tzinfo=timezone.utc)  # a Monday, so every bucket is a full week
    mk = lambda i, d, amt: {"id": i, "date": d, "status": "S", "amount": amt, "currency": "USD", "payer": "x", "email": "x@x", "subject": ""}
    rows = [mk(f"t{n}", start + timedelta(days=n), 100.0) for n in range((now - start).days)]
    assert [x for x in an.anomalies(rows, now) if x["type"] == "revenue_drop"] == []
    f = an.forecast(rows, now)[0]
    p0 = f["projection"][0]
    assert f["status"] == "ok" and f["trend"] == "flat" and p0["low"] <= p0["expected"] <= p0["high"] and abs(p0["expected"] - 700) < 1
    lw = datetime(2026, 10, 26, tzinfo=timezone.utc)
    drop = [r for r in rows if not (lw <= r["date"] < lw + timedelta(days=7))] + [mk("tiny", lw + timedelta(days=2), 10.0)]
    a = [x for x in an.anomalies(drop, now) if x["type"] == "revenue_drop"]
    assert a and a[0]["severity"] == "high" and a[0]["why"] and a[0]["suggested_action"] and a[0]["evidence_transaction_ids"] == ["tiny"]
    assert an.forecast(rows[:3], now)[0]["status"] == "insufficient_data"
    assert an.forecast([], now) == []


def test_studio_dataset_is_single_currency_and_flat(client, synced):
    d = client.get("/api/v1/analytics/dataset", headers=synced).json()
    assert d["currency"] in d["currencies"] and len(d["currencies"]) == 2
    assert d["transactions"] and {r["currency"] for r in d["transactions"]} == {d["currency"]}
    r = d["transactions"][0]; assert set(r) >= {"paypal_id", "date", "month", "status", "payment", "failed", "customer"}
    assert all((x["payment"] is None) == (x["status"] != "Completed") for x in d["transactions"])
    other = [c for c in d["currencies"] if c != d["currency"]][0]
    assert {x["currency"] for x in client.get(f"/api/v1/analytics/dataset?currency={other}", headers=synced).json()["transactions"]} == {other}
    assert client.get("/api/v1/analytics/dataset?currency=JPY", headers=synced).status_code == 404
    assert client.get("/api/v1/analytics/dataset", headers=signup(client, "z@example.com")).json()["transactions"] == []


def test_demo_data_always_shows_a_revenue_drop_whatever_the_weekday():
    """Regression: the demo slowdown used to be random, so the headline alert vanished on some weekdays (it did on a Monday)."""
    from app.services.demo_paypal import DemoPayPal
    from app.services.paypal import normalize_transaction
    base = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    for i in range(21):  # three full weeks covers every weekday three times
        now = base + timedelta(days=i); d = DemoPayPal(now=now)
        rows = [{**normalize_transaction(t), "id": t["transaction_info"]["transaction_id"], "payer": "", "email": ""} for t in d.tx]
        kinds = {(a["type"], a["currency"]) for a in an.anomalies(rows, now)}
        assert ("revenue_drop", "USD") in kinds and ("failure_spike", "USD") in kinds, f"missing alert on {now:%a %Y-%m-%d}: {sorted(kinds)}"
