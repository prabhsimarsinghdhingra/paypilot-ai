"""PayPal REST client (sandbox). Sync httpx; FastAPI runs sync routes in a threadpool.

Endpoints used (PayPal REST docs):
  POST /v1/oauth2/token                          client-credentials OAuth
  GET  /v1/reporting/transactions                Transaction Search (max 31-day window, page_size<=500)
  POST /v2/invoicing/generate-next-invoice-number
  POST /v2/invoicing/invoices                    create DRAFT (returns {href})
  GET  /v2/invoicing/invoices/{id}  and  GET /v2/invoicing/invoices
  POST /v2/invoicing/invoices/{id}/send          the ONLY call that emails the customer
  POST /v2/invoicing/invoices/{id}/remind
  POST /v1/notifications/verify-webhook-signature
"""
import base64
import threading
from datetime import datetime, timedelta, timezone
import httpx


class PayPalError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def parse_pp_date(s: str) -> datetime:
    s = (s or "").replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(s if ":" not in s[-6:] else s[:-3] + s[-2:], fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


def _fmt(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_transaction(item: dict) -> dict:
    info, payer = item.get("transaction_info", {}), item.get("payer_info", {})
    amt, fee = info.get("transaction_amount") or {}, info.get("fee_amount") or {}
    return {
        "paypal_id": info.get("transaction_id", ""),
        "date": parse_pp_date(info.get("transaction_initiation_date") or info.get("transaction_updated_date")),
        "status": info.get("transaction_status", "?"),
        "amount": float(amt.get("value", 0)), "currency": amt.get("currency_code", "USD"),
        "fee": float(fee.get("value", 0)),
        "payer_name": (payer.get("payer_name") or {}).get("alternate_full_name", ""),
        "payer_email": payer.get("email_address", ""),
        "subject": (info.get("transaction_subject") or info.get("transaction_note") or "")[:400],
        "event_code": info.get("transaction_event_code", ""),
    }


def normalize_invoice(inv: dict) -> dict:
    d = inv.get("detail") or {}
    rec = ((inv.get("primary_recipients") or [{}])[0]).get("billing_info") or {}
    nm = rec.get("name") or {}
    amt = inv.get("amount") or {}
    due = (d.get("payment_term") or {}).get("due_date")
    return {
        "paypal_id": inv.get("id", ""), "number": d.get("invoice_number", ""), "status": inv.get("status", "DRAFT"),
        "currency": amt.get("currency_code") or d.get("currency_code", "USD"), "total": float(amt.get("value", 0) or 0),
        "due_date": datetime.strptime(due, "%Y-%m-%d").date() if due else None,
        "recipient_email": rec.get("email_address", ""),
        "recipient_name": nm.get("full_name") or " ".join(x for x in (nm.get("given_name"), nm.get("surname")) if x),
        "items": inv.get("items") or [], "note": d.get("note", ""),
    }


class PayPalClient:
    mode = "sandbox"

    def __init__(self, client_id: str, client_secret: str, base_url: str):
        self.client_id, self.secret, self.base = client_id, client_secret, base_url.rstrip("/")
        self._tok: str | None = None
        self._exp = datetime.min.replace(tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def _token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._tok and datetime.now(timezone.utc) < self._exp:
                return self._tok
            auth = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
            try:
                r = httpx.post(f"{self.base}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                               headers={"Authorization": f"Basic {auth}"}, timeout=30)
            except httpx.HTTPError as e:
                raise PayPalError(502, f"Could not reach PayPal: {type(e).__name__}")
            if r.status_code in (401, 403):
                raise PayPalError(401, "PayPal rejected the Client ID/Secret (check they are Sandbox credentials)")
            if r.is_error:
                raise PayPalError(r.status_code, "PayPal OAuth failed")
            j = r.json()
            self._tok = j["access_token"]
            self._exp = datetime.now(timezone.utc) + timedelta(seconds=max(30, int(j.get("expires_in", 300)) - 60))
            return self._tok

    def check_credentials(self) -> None:
        self._token(force=True)

    def _req(self, method: str, path: str, params=None, body=None, _retry=True):
        try:
            r = httpx.request(method, self.base + path, params=params, json=body, timeout=40,
                              headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        except httpx.HTTPError as e:
            raise PayPalError(502, f"Could not reach PayPal: {type(e).__name__}")
        if r.status_code == 401 and _retry:  # expired/revoked token: refresh once
            self._token(force=True)
            return self._req(method, path, params, body, _retry=False)
        if r.is_error:
            try:
                j = r.json()
                msg = j.get("message") or j.get("error_description") or ""
                det = "; ".join(x.get("issue", "") + ((" – " + x["description"]) if x.get("description") else "")
                                for x in j.get("details", [])[:3])
            except ValueError:
                msg, det = r.text[:200], ""
            raise PayPalError(r.status_code, f"{msg} {det}".strip() or f"HTTP {r.status_code}")
        return r.json() if r.content else {}

    # ---- transactions ----
    def fetch_transactions(self, start: datetime, end: datetime, max_pages: int = 20) -> list[dict]:
        """Transaction Search allows <=31 days per call, so longer ranges are chunked and every page is followed."""
        out, cur = [], start
        while cur < end:
            nxt = min(cur + timedelta(days=31), end)
            page = 1
            while page <= max_pages:
                j = self._req("GET", "/v1/reporting/transactions", params={
                    "start_date": _fmt(cur), "end_date": _fmt(nxt), "fields": "transaction_info,payer_info",
                    "page_size": 100, "page": page})
                out += j.get("transaction_details", [])
                if page >= int(j.get("total_pages", 1)):
                    break
                page += 1
            cur = nxt
        return out

    # ---- invoicing ----
    def next_invoice_number(self) -> str:
        return self._req("POST", "/v2/invoicing/generate-next-invoice-number").get("invoice_number", "")

    def create_invoice(self, body: dict) -> dict:
        j = self._req("POST", "/v2/invoicing/invoices", body=body)
        inv_id = j["href"].rstrip("/").rsplit("/", 1)[-1]
        return self.get_invoice(inv_id)

    def get_invoice(self, inv_id: str) -> dict:
        return self._req("GET", f"/v2/invoicing/invoices/{inv_id}")

    def list_invoices(self) -> list[dict]:
        out, page = [], 1
        while page <= 20:
            j = self._req("GET", "/v2/invoicing/invoices", params={"page": page, "page_size": 100, "total_required": "true"})
            out += j.get("items", [])
            if page >= int(j.get("total_pages", 1)):
                break
            page += 1
        return out

    def send_invoice(self, inv_id: str, subject: str | None, note: str | None) -> dict:
        body = {"send_to_recipient": True, "send_to_invoicer": False}
        if subject: body["subject"] = subject
        if note: body["note"] = note
        return self._req("POST", f"/v2/invoicing/invoices/{inv_id}/send", body=body)

    def remind_invoice(self, inv_id: str, subject: str, note: str) -> dict:
        return self._req("POST", f"/v2/invoicing/invoices/{inv_id}/remind",
                         body={"subject": subject, "note": note, "send_to_invoicer": False})

    def verify_webhook(self, headers: dict, event: dict, webhook_id: str) -> bool:
        h = {k.lower(): v for k, v in headers.items()}
        j = self._req("POST", "/v1/notifications/verify-webhook-signature", body={
            "auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"), "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"), "webhook_id": webhook_id, "webhook_event": event})
        return j.get("verification_status") == "SUCCESS"
