"""Approval gate + executor. The ONLY code path that causes PayPal side effects.

Lifecycle: PENDING -> APPROVED -> EXECUTING -> COMPLETED | FAILED ;  PENDING -> REJECTED | CANCELLED.
Every transition is a compare-and-swap UPDATE ... WHERE status=<expected>, so double-clicks, retries and races cannot
execute an action twice. A FAILED action is never auto-retried (a retry could double-send); the user proposes a new one.
Everything is re-validated at execution time against the user's own records - never trust the proposal payload."""
from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.models import AIAction, AuditLog, Invoice, User, now
from app.services.paypal import PayPalError
from app.services.sync import upsert_invoice

REMINDABLE = {"SENT", "UNPAID", "PARTIALLY_PAID"}
ACTION_TYPES = {"create_invoice_draft", "send_invoice", "send_reminder"}


class LineItem(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    quantity: Decimal = Field(default=Decimal(1), gt=0, le=100000)
    unit_amount: Decimal = Field(gt=0, le=10_000_000)
    tax_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)


class InvoiceDraft(BaseModel):
    recipient_email: EmailStr
    recipient_name: str = Field(default="", max_length=100)
    items: list[LineItem] = Field(min_length=1, max_length=50)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    due_in_days: int = Field(default=14, ge=0, le=365)
    note: str = Field(default="Thank you for your business.", max_length=1000)


class SendInvoice(BaseModel):
    invoice_id: str  # local invoice id
    subject: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class SendReminder(BaseModel):
    invoice_id: str
    subject: str = Field(min_length=3, max_length=200)
    note: str = Field(min_length=3, max_length=2000)


def invoice_total(d: InvoiceDraft) -> Decimal:
    return sum((i.quantity * i.unit_amount * (1 + i.tax_percent / 100) for i in d.items), Decimal(0)).quantize(Decimal("0.01"))


def _audit(db, user_id, action_id, event, detail=None):
    db.add(AuditLog(user_id=user_id, action_id=action_id, event=event, detail=detail or {}))


def _own_invoice(db: Session, user_id: str, invoice_id: str) -> Invoice:
    inv = db.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.user_id == user_id))
    if not inv: raise ValueError("Invoice not found in your account")
    return inv


def validate_payload(db: Session, user_id: str, action_type: str, payload: dict) -> dict:
    """Used both when proposing and again right before executing. Raises ValueError with a human-readable reason."""
    if action_type == "create_invoice_draft":
        return InvoiceDraft(**payload).model_dump(mode="json")
    if action_type == "send_invoice":
        p = SendInvoice(**payload); inv = _own_invoice(db, user_id, p.invoice_id)
        if inv.status != "DRAFT": raise ValueError(f"Only DRAFT invoices can be sent (this one is {inv.status})")
        return p.model_dump()
    if action_type == "send_reminder":
        p = SendReminder(**payload); inv = _own_invoice(db, user_id, p.invoice_id)
        if inv.status not in REMINDABLE: raise ValueError(f"Cannot remind an invoice that is {inv.status}")
        return p.model_dump()
    raise ValueError("Unknown action type")


def propose(db: Session, user: User, action_type: str, title: str, payload: dict, source: str = "ai",
            conversation_id: str | None = None) -> AIAction:
    clean = validate_payload(db, user.id, action_type, payload)
    pending = db.scalars(select(AIAction).where(AIAction.user_id == user.id, AIAction.action_type == action_type, AIAction.status == "PENDING"))
    dup = next((a for a in pending if a.payload == clean), None)  # compared in Python: Postgres has no json = json operator
    if dup: return dup
    a = AIAction(user_id=user.id, action_type=action_type, title=title[:200], payload=clean, source=source, conversation_id=conversation_id)
    db.add(a); db.flush(); _audit(db, user.id, a.id, "proposed", {"source": source, "type": action_type}); db.commit()
    return a


def _cas(db, action_id, user_id, expected, new, **extra) -> bool:
    r = db.execute(update(AIAction).where(AIAction.id == action_id, AIAction.user_id == user_id, AIAction.status == expected)
                   .values(status=new, **extra))
    db.commit()
    return r.rowcount == 1


def get_owned(db: Session, user: User, action_id: str) -> AIAction:
    a = db.scalar(select(AIAction).where(AIAction.id == action_id, AIAction.user_id == user.id))
    if not a: raise HTTPException(404, "Action not found")
    return a


def reject(db, user, action_id, cancel=False):
    get_owned(db, user, action_id)
    if not _cas(db, action_id, user.id, "PENDING", "CANCELLED" if cancel else "REJECTED", decided_at=now()):
        raise HTTPException(409, "Action is no longer pending")
    _audit(db, user.id, action_id, "cancelled" if cancel else "rejected"); db.commit()
    return db.get(AIAction, action_id)


def approve_and_execute(db: Session, user: User, action_id: str, client) -> AIAction:
    get_owned(db, user, action_id)
    if not _cas(db, action_id, user.id, "PENDING", "APPROVED", decided_at=now()):
        raise HTTPException(409, "Action is no longer pending (already approved, rejected or executed)")
    _audit(db, user.id, action_id, "approved"); db.commit()
    if not _cas(db, action_id, user.id, "APPROVED", "EXECUTING"):
        raise HTTPException(409, "Action is already executing")
    a = db.get(AIAction, action_id); db.refresh(a)
    try:
        result = _execute(db, user, a, client)
        a.status, a.result = "COMPLETED", result
        _audit(db, user.id, a.id, "executed", {"type": a.action_type, "result": result})
    except (ValueError, PayPalError) as e:
        a.status, a.error = "FAILED", (e.detail if isinstance(e, PayPalError) else str(e))[:500]
        _audit(db, user.id, a.id, "failed", {"type": a.action_type, "error": a.error})
    a.executed_at = datetime.now(timezone.utc)
    db.commit()
    return a


def _execute(db, user, a: AIAction, client) -> dict:
    p = validate_payload(db, user.id, a.action_type, a.payload)  # re-validate against current state
    if a.action_type == "create_invoice_draft":
        d = InvoiceDraft(**p)
        body = {"detail": {"invoice_number": client.next_invoice_number(), "invoice_date": date.today().isoformat(),
                           "currency_code": d.currency, "note": d.note,
                           "payment_term": {"term_type": "DUE_ON_DATE_SPECIFIED",
                                            "due_date": (date.today().fromordinal(date.today().toordinal() + d.due_in_days)).isoformat()}},
                "primary_recipients": [{"billing_info": {"email_address": d.recipient_email,
                                        **({"name": {"full_name": d.recipient_name}} if d.recipient_name else {})}}],
                "items": [{"name": i.name, "quantity": str(i.quantity), "unit_amount": {"currency_code": d.currency, "value": f"{i.unit_amount:.2f}"},
                           **({"tax": {"name": "Tax", "percent": str(i.tax_percent)}} if i.tax_percent else {})} for i in d.items]}
        inv = upsert_invoice(db, user, client.create_invoice(body))
        return {"invoice_id": inv.id, "paypal_invoice_id": inv.paypal_id, "status": inv.status, "total": float(inv.total), "currency": inv.currency}
    inv = _own_invoice(db, user.id, p["invoice_id"])
    if a.action_type == "send_invoice":
        client.send_invoice(inv.paypal_id, p.get("subject"), p.get("note"))
    else:
        client.remind_invoice(inv.paypal_id, p["subject"], p["note"]); inv.last_reminded_at = datetime.now(timezone.utc)
    fresh = upsert_invoice(db, user, client.get_invoice(inv.paypal_id))
    if a.action_type == "send_reminder": fresh.last_reminded_at = inv.last_reminded_at
    return {"invoice_id": inv.id, "paypal_invoice_id": inv.paypal_id, "status": fresh.status}


def action_dict(a: AIAction) -> dict:
    return {"id": a.id, "type": a.action_type, "title": a.title, "payload": a.payload, "status": a.status, "source": a.source,
            "result": a.result, "error": a.error, "created_at": a.created_at.isoformat(),
            "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            "executed_at": a.executed_at.isoformat() if a.executed_at else None}
