"""Labeled PayPal *simulator*. Same interface and raw response shapes as PayPalClient, so the normalisation,
sync, analytics, agent and approval code paths are identical. Used for automated tests and for judges who have no
sandbox credentials. It is NOT PayPal: the UI shows a 'DEMO SIMULATOR' badge whenever it is active."""
import random
from datetime import datetime, timedelta, timezone
from app.services.paypal import PayPalError, parse_pp_date

PAYERS = [("Acme Studio", "billing@acme.example"), ("Globex Design", "ap@globex.example"), ("Initech Labs", "pay@initech.example"),
          ("Hooli Media", "finance@hooli.example"), ("Umbrella Co", "accounts@umbrella.example"), ("Stark Retail", "ar@stark.example")]


def _ts(d): return d.strftime("%Y-%m-%dT%H:%M:%S+0000")


class DemoPayPal:
    mode = "demo"

    def __init__(self, seed: int = 7, now: datetime | None = None):
        self.now = now or datetime.now(timezone.utc)
        self.calls: list[tuple] = []  # every side-effecting call is recorded (tests assert on this)
        self.fail_next: str | None = None
        self.tx, self.invoices = [], {}
        rnd = random.Random(seed)
        n = 0
        for back in range(88, 0, -1):
            d = self.now - timedelta(days=back)
            thin = back <= 14  # a deterministic recent slowdown (not random) so the revenue-drop alert fires on every weekday
            if thin:
                if back % 4 == 0:
                    n += 1; self._add(n, d.replace(hour=11), "S", 70.0, "USD", PAYERS[0][0], PAYERS[0][1], "Small retainer")
                continue
            for _ in range(rnd.choice([0, 1, 1, 2])):
                n += 1
                name, email = rnd.choice(PAYERS)
                cur = "EUR" if name == "Globex Design" else "USD"
                amt = round(rnd.uniform(60, 420), 2)
                st = "S" if rnd.random() > .08 else rnd.choice(["P", "D"])
                self._add(n, d.replace(hour=rnd.randint(8, 20)), st, amt, cur, name, email, "Design retainer")
        n += 1; self._add(n, self.now - timedelta(days=30), "S", 4800.0, "USD", "Initech Labs", "pay@initech.example", "Annual license")
        for i in range(5):  # failed-payment spike in the last two weeks
            n += 1; self._add(n, self.now - timedelta(days=2 + i), "D", 150.0, "USD", PAYERS[i % 3][0], PAYERS[i % 3][1], "Card declined")
        today = self.now.date()
        seed_inv = [("Acme Studio", "billing@acme.example", 1200, -12, "SENT"), ("Globex Design", "ap@globex.example", 860, -5, "SENT"),
                    ("Hooli Media", "finance@hooli.example", 2300, -21, "UNPAID"), ("Umbrella Co", "accounts@umbrella.example", 450, 9, "SENT"),
                    ("Stark Retail", "ar@stark.example", 980, -30, "PAID"), ("Initech Labs", "pay@initech.example", 300, 14, "DRAFT")]
        for i, (nm, em, tot, due, st) in enumerate(seed_inv):
            self._add_invoice(f"INV2-DEMO-{i+1:04d}", nm, em, tot, today + timedelta(days=due), st)

    def _add(self, n, d, st, amt, cur, name, email, subj):
        self.tx.append({"transaction_info": {"transaction_id": f"DEMO{n:06d}", "transaction_initiation_date": _ts(d),
                        "transaction_status": st, "transaction_amount": {"currency_code": cur, "value": f"{amt:.2f}"},
                        "fee_amount": {"currency_code": cur, "value": f"-{amt*0.029+0.3:.2f}"}, "transaction_subject": subj,
                        "transaction_event_code": "T0006"}, "payer_info": {"email_address": email, "payer_name": {"alternate_full_name": name}}})

    def _add_invoice(self, inv_id, name, email, total, due, status, items=None, currency="USD", number=None, note=""):
        self.invoices[inv_id] = {"id": inv_id, "status": status, "detail": {"invoice_number": number or inv_id, "currency_code": currency,
            "note": note, "payment_term": {"term_type": "DUE_ON_DATE_SPECIFIED", "due_date": due.isoformat()}},
            "primary_recipients": [{"billing_info": {"email_address": email, "name": {"full_name": name}}}],
            "items": items or [{"name": "Services", "quantity": "1", "unit_amount": {"currency_code": currency, "value": f"{total:.2f}"}}],
            "amount": {"currency_code": currency, "value": f"{total:.2f}"}}

    def _maybe_fail(self, op):
        if self.fail_next == op:
            self.fail_next = None
            raise PayPalError(422, f"Simulated PayPal failure on {op}")

    def check_credentials(self): pass

    def fetch_transactions(self, start, end, max_pages=20):
        return [t for t in self.tx if start <= parse_pp_date(t["transaction_info"]["transaction_initiation_date"]) <= end]

    def next_invoice_number(self): return f"INV2-DEMO-{len(self.invoices)+1:04d}"

    def create_invoice(self, body):
        self._maybe_fail("create_invoice")
        d = body["detail"]; rec = body["primary_recipients"][0]["billing_info"]
        inv_id = f"INV2-DEMO-{len(self.invoices)+1:04d}"
        total = sum(float(i["quantity"]) * float(i["unit_amount"]["value"]) * (1 + float((i.get("tax") or {}).get("percent", 0)) / 100) for i in body["items"])
        self._add_invoice(inv_id, rec.get("name", {}).get("full_name", ""), rec["email_address"], round(total, 2),
                          datetime.strptime(d["payment_term"]["due_date"], "%Y-%m-%d").date(), "DRAFT", body["items"], d["currency_code"], d.get("invoice_number"), d.get("note", ""))
        self.calls.append(("create_invoice", inv_id))
        return self.invoices[inv_id]

    def get_invoice(self, inv_id):
        if inv_id not in self.invoices: raise PayPalError(404, "Invoice not found")
        return self.invoices[inv_id]

    def list_invoices(self): return list(self.invoices.values())

    def send_invoice(self, inv_id, subject=None, note=None):
        self._maybe_fail("send_invoice")
        inv = self.get_invoice(inv_id)
        if inv["status"] not in ("DRAFT", "SCHEDULED"): raise PayPalError(422, "Invoice is not in a sendable state")
        inv["status"] = "SENT"; self.calls.append(("send_invoice", inv_id)); return {}

    def remind_invoice(self, inv_id, subject, note):
        self._maybe_fail("remind_invoice")
        inv = self.get_invoice(inv_id)
        if inv["status"] not in ("SENT", "UNPAID", "PARTIALLY_PAID"): raise PayPalError(422, "Invoice cannot be reminded in its current state")
        self.calls.append(("remind_invoice", inv_id, subject)); return {}

    def verify_webhook(self, headers, event, webhook_id): return False
