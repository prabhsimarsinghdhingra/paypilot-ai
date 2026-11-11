from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import current_user, get_paypal
from app.models import Invoice, User
from app.services import actions as act
from app.services.agent import _inv
from datetime import date

router = APIRouter(prefix="/invoices", tags=["Invoices"])

@router.get("")
def list_invoices(u: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    return [_inv(i, today) for i in db.scalars(select(Invoice).where(Invoice.user_id == u.id).order_by(Invoice.due_date.desc()))]

@router.post("/preview")
def preview(d: act.InvoiceDraft, u: User = Depends(current_user)):
    subtotal = sum(i.quantity * i.unit_amount for i in d.items)
    return {"subtotal": float(subtotal), "tax": float(act.invoice_total(d) - subtotal), "total": float(act.invoice_total(d)), "currency": d.currency}

@router.post("", status_code=201)
def create_draft(d: act.InvoiceDraft, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """User-authored draft: queued as a user-sourced action and executed immediately through the same engine (audited).
    Creating a DRAFT never emails the customer; sending needs a separate approval."""
    a = act.propose(db, u, "create_invoice_draft", f"Create invoice draft for {d.recipient_email}", d.model_dump(mode="json"), "user")
    return act.action_dict(act.approve_and_execute(db, u, a.id, get_paypal(u, db)))

class Req(BaseModel):
    subject: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)

@router.post("/{inv_id}/request-send", status_code=201)
def request_send(inv_id: str, r: Req, u: User = Depends(current_user), db: Session = Depends(get_db)):
    try: a = act.propose(db, u, "send_invoice", "Send invoice", {"invoice_id": inv_id, **r.model_dump()}, "user")
    except ValueError as e: raise HTTPException(422, str(e))
    return act.action_dict(a)

@router.post("/{inv_id}/request-reminder", status_code=201)
def request_reminder(inv_id: str, r: Req, u: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = db.scalar(select(Invoice).where(Invoice.id == inv_id, Invoice.user_id == u.id))
    if not inv: raise HTTPException(404, "Invoice not found")
    try:
        a = act.propose(db, u, "send_reminder", f"Payment reminder to {inv.recipient_name or inv.recipient_email}", {"invoice_id": inv_id,
                        "subject": r.subject or f"Reminder: invoice {inv.number} is overdue",
                        "note": r.note or f"Hi {inv.recipient_name or 'there'}, a friendly reminder that invoice {inv.number} ({inv.currency} {float(inv.total):,.2f}) is past due. Thank you!"}, "user")
    except ValueError as e: raise HTTPException(422, str(e))
    return act.action_dict(a)
