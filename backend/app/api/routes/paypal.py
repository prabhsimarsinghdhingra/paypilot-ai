from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import encrypt
from app.db import get_db
from app.deps import current_user, get_paypal
from app.models import PayPalAccount, Transaction, User
from app.services.paypal import PayPalClient, PayPalError
from app.services.sync import sync_invoices, sync_transactions

router = APIRouter(tags=["PayPal"])

def _wrap(fn):
    try: return fn()
    except PayPalError as e: raise HTTPException(e.status if e.status in (401, 403, 404, 422, 429) else 502, e.detail)

@router.get("/paypal/status")
def status(u: User = Depends(current_user), db: Session = Depends(get_db), client=Depends(get_paypal)):
    return {"mode": client.mode, "connected_account": bool(db.scalar(select(PayPalAccount).where(PayPalAccount.user_id == u.id))),
            "label": "DEMO SIMULATOR (not PayPal)" if client.mode == "demo" else "PayPal Sandbox",
            "transactions_stored": db.scalar(select(func.count()).select_from(Transaction).where(Transaction.user_id == u.id))}

class Connect(BaseModel):
    client_id: str = Field(min_length=10, max_length=200)
    client_secret: str = Field(min_length=10, max_length=300)

@router.post("/paypal/connect")
def connect(b: Connect, u: User = Depends(current_user), db: Session = Depends(get_db)):
    _wrap(lambda: PayPalClient(b.client_id, b.client_secret, settings.paypal_base_url).check_credentials())  # validate before storing
    acct = db.scalar(select(PayPalAccount).where(PayPalAccount.user_id == u.id))
    if acct: acct.client_id, acct.secret_encrypted = b.client_id, encrypt(b.client_secret)
    else: db.add(PayPalAccount(user_id=u.id, client_id=b.client_id, secret_encrypted=encrypt(b.client_secret)))
    db.commit(); return {"connected": True}

@router.delete("/paypal/connect")
def disconnect(u: User = Depends(current_user), db: Session = Depends(get_db)):
    acct = db.scalar(select(PayPalAccount).where(PayPalAccount.user_id == u.id))
    if acct: db.delete(acct); db.commit()
    return {"connected": False}

@router.post("/paypal/sync")
def sync(days: int = Query(90, ge=1, le=365), u: User = Depends(current_user), db: Session = Depends(get_db), client=Depends(get_paypal)):
    """Pulls Transaction Search (chunked into 31-day windows) and invoices from PayPal into the user's database."""
    return {"transactions": _wrap(lambda: sync_transactions(db, u, client, days)), "invoices": _wrap(lambda: sync_invoices(db, u, client)), "mode": client.mode}

SORTABLE = {"date": Transaction.date, "amount": Transaction.amount, "status": Transaction.status, "payer_name": Transaction.payer_name,
            "currency": Transaction.currency, "paypal_id": Transaction.paypal_id}

@router.get("/transactions")
def transactions(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), sort_by: str = "date", sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
                 status: str | None = Query(None, pattern="^(S|P|D|V)$"), currency: str | None = Query(None, pattern="^[A-Z]{3}$"), q: str | None = Query(None, max_length=100),
                 date_from: datetime | None = None, date_to: datetime | None = None,
                 u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Server-side paging/sorting/filtering over synced PayPal data. (PayPal's Transaction Search has no free-text search,
    no sorting and a 31-day window, so the grid queries our synced copy; /paypal/sync keeps it fresh.)"""
    if sort_by not in SORTABLE: raise HTTPException(422, f"sort_by must be one of {sorted(SORTABLE)}")
    f = [Transaction.user_id == u.id]
    if status: f.append(Transaction.status == status)
    if currency: f.append(Transaction.currency == currency)
    if date_from: f.append(Transaction.date >= date_from)
    if date_to: f.append(Transaction.date <= date_to)
    if q:
        like = f"%{q.lower()}%"
        f.append(or_(func.lower(Transaction.payer_name).like(like), func.lower(Transaction.payer_email).like(like),
                     func.lower(Transaction.subject).like(like), func.lower(Transaction.paypal_id).like(like)))
    total = db.scalar(select(func.count()).select_from(Transaction).where(*f))
    order = (asc if sort_dir == "asc" else desc)(SORTABLE[sort_by])
    rows = db.scalars(select(Transaction).where(*f).order_by(order, Transaction.id).offset((page - 1) * page_size).limit(page_size))
    return {"total": total, "page": page, "page_size": page_size, "rows": [
        {"id": t.id, "paypal_id": t.paypal_id, "date": t.date.isoformat(), "status": t.status, "amount": float(t.amount), "fee": float(t.fee),
         "currency": t.currency, "payer_name": t.payer_name, "payer_email": t.payer_email, "subject": t.subject} for t in rows]}
