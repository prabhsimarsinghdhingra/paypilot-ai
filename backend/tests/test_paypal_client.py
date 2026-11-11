"""The real PayPalClient exercised against a scripted fake of httpx (no network)."""
import json
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from app.services import paypal as pp
from app.services.paypal import PayPalClient, PayPalError


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body if body is not None else {}
        self.content = json.dumps(self._b).encode(); self.text = json.dumps(self._b)
    is_error = property(lambda s: s.status_code >= 400)
    def json(self): return self._b


@pytest.fixture
def net(monkeypatch):
    """net.script = list of Resp (or exceptions) consumed in order; net.calls records (method, path, params, body)."""
    class Net:
        script: list = []; calls: list = []
    n = Net(); n.script, n.calls = [], []
    def nxt(kind, method, url, **kw):
        n.calls.append((method, url.split("paypal.com")[-1], kw.get("params"), kw.get("json") or kw.get("data")))
        r = n.script.pop(0)
        if isinstance(r, Exception): raise r
        return r
    monkeypatch.setattr(pp.httpx, "post", lambda url, **kw: nxt("post", "POST", url, **kw))
    monkeypatch.setattr(pp.httpx, "request", lambda m, url, **kw: nxt("req", m, url, **kw))
    return n

TOKEN = Resp(200, {"access_token": "tok", "expires_in": 3600})
client = lambda: PayPalClient("id-1234567890", "secret-1234567890", "https://api-m.sandbox.paypal.com")


def test_token_is_cached(net):
    net.script = [TOKEN, Resp(200, {"a": 1}), Resp(200, {"a": 2})]
    c = client(); c._req("GET", "/x"); c._req("GET", "/y")
    assert [x[1] for x in net.calls].count("/v1/oauth2/token") == 1


def test_expired_token_refreshes_once_then_succeeds(net):
    net.script = [TOKEN, Resp(401, {"name": "AUTHENTICATION_FAILURE"}), Resp(200, {"access_token": "tok2", "expires_in": 3600}), Resp(200, {"ok": True})]
    assert client()._req("GET", "/x") == {"ok": True}


def test_persistent_401_gives_up(net):
    net.script = [TOKEN, Resp(401, {}), TOKEN, Resp(401, {"message": "nope"})]
    with pytest.raises(PayPalError) as e: client()._req("GET", "/x")
    assert e.value.status == 401


def test_bad_credentials_message(net):
    net.script = [Resp(401, {"error": "invalid_client"})]
    with pytest.raises(PayPalError) as e: client().check_credentials()
    assert "Sandbox" in e.value.detail and e.value.status == 401


def test_network_failure_is_502(net):
    net.script = [httpx.ConnectError("boom")]
    with pytest.raises(PayPalError) as e: client()._token()
    assert e.value.status == 502


def test_error_details_are_surfaced(net):
    net.script = [TOKEN, Resp(422, {"message": "Business validation error", "details": [{"issue": "INVALID_DATE", "description": "bad"}]})]
    with pytest.raises(PayPalError) as e: client()._req("POST", "/v2/invoicing/invoices", body={})
    assert e.value.status == 422 and "INVALID_DATE" in e.value.detail


def test_transaction_search_chunks_31_days_and_follows_pages(net):
    end = datetime(2026, 11, 6, tzinfo=timezone.utc); start = end - timedelta(days=70)
    page = lambda n, tp: Resp(200, {"transaction_details": [{"transaction_info": {"transaction_id": f"T{n}"}}], "total_pages": tp})
    net.script = [TOKEN, page(1, 2), page(2, 2), page(3, 1), page(4, 1)]  # window1 has 2 pages, windows 2-3 one each
    rows = client().fetch_transactions(start, end)
    assert len(rows) == 4
    searches = [c for c in net.calls if c[1] == "/v1/reporting/transactions"]
    assert len(searches) == 4
    for _, _, params, _ in searches:
        s = datetime.strptime(params["start_date"], "%Y-%m-%dT%H:%M:%SZ"); e = datetime.strptime(params["end_date"], "%Y-%m-%dT%H:%M:%SZ")
        assert e - s <= timedelta(days=31) and params["page_size"] <= 500


def test_create_invoice_parses_href_then_fetches_it(net):
    net.script = [TOKEN, Resp(201, {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-ABC", "method": "GET"}),
                  Resp(200, {"id": "INV2-ABC", "status": "DRAFT"})]
    assert client().create_invoice({"detail": {}})["id"] == "INV2-ABC"
    assert net.calls[-1][1] == "/v2/invoicing/invoices/INV2-ABC"


def test_send_and_remind_bodies(net):
    net.script = [TOKEN, Resp(200, {}), Resp(200, {})]
    c = client(); c.send_invoice("INV2-1", "Subj", "Note"); c.remind_invoice("INV2-1", "S", "N")
    send, rem = net.calls[1], net.calls[2]
    assert send[1] == "/v2/invoicing/invoices/INV2-1/send" and send[3]["send_to_recipient"] is True and send[3]["subject"] == "Subj"
    assert rem[1] == "/v2/invoicing/invoices/INV2-1/remind" and rem[3]["note"] == "N"


def test_list_invoices_paginates(net):
    net.script = [TOKEN, Resp(200, {"items": [{"id": "A"}], "total_pages": 2}), Resp(200, {"items": [{"id": "B"}], "total_pages": 2})]
    assert [i["id"] for i in client().list_invoices()] == ["A", "B"]


@pytest.mark.parametrize("status,expected", [("SUCCESS", True), ("FAILURE", False)])
def test_webhook_verification(net, status, expected):
    net.script = [TOKEN, Resp(200, {"verification_status": status})]
    ok = client().verify_webhook({"PayPal-Transmission-Id": "t", "paypal-auth-algo": "a", "PAYPAL-CERT-URL": "u", "paypal-transmission-sig": "s", "paypal-transmission-time": "x"},
                                 {"event_type": "INVOICING.INVOICE.PAID"}, "WH-1")
    body = net.calls[-1][3]
    assert ok is expected and body["webhook_id"] == "WH-1" and body["transmission_id"] == "t" and body["cert_url"] == "u"


def test_date_helpers():
    assert pp.parse_pp_date("2026-11-01T10:00:00+0000") == datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
    assert pp.parse_pp_date("2026-11-01T10:00:00Z") == datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
    assert pp._fmt(datetime(2026, 1, 2, 3, 4, 5, 999, tzinfo=timezone.utc)) == "2026-01-02T03:04:05Z"


def test_normalizers_handle_missing_fields():
    t = pp.normalize_transaction({"transaction_info": {"transaction_id": "X", "transaction_initiation_date": "2026-11-01T10:00:00+0000",
                                  "transaction_status": "S", "transaction_amount": {"currency_code": "USD", "value": "5.50"}}})
    assert t["amount"] == 5.5 and t["payer_email"] == "" and t["fee"] == 0
    i = pp.normalize_invoice({"id": "I", "status": "SENT", "detail": {"payment_term": {"due_date": "2026-12-01"}}, "amount": {"currency_code": "EUR", "value": "10"}})
    assert i["currency"] == "EUR" and i["due_date"].isoformat() == "2026-12-01" and i["recipient_email"] == ""
