from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Invoice, Transaction, User
from app.services.paypal import normalize_invoice, normalize_transaction


def sync_transactions(db: Session, user: User, client, days: int = 90) -> dict:
    end = datetime.now(timezone.utc); start = end - timedelta(days=days)
    raw = [normalize_transaction(x) for x in client.fetch_transactions(start, end)]
    existing = {t.paypal_id: t for t in db.scalars(select(Transaction).where(Transaction.user_id == user.id))}
    added = updated = 0
    for r in raw:
        if not r["paypal_id"]: continue
        t = existing.get(r["paypal_id"])
        if t:
            for k, v in r.items(): setattr(t, k, v)
            updated += 1
        else:
            db.add(Transaction(user_id=user.id, **r)); added += 1
    db.commit()
    return {"added": added, "updated": updated, "fetched": len(raw)}


def upsert_invoice(db: Session, user: User, raw_invoice: dict) -> Invoice:
    n = normalize_invoice(raw_invoice)
    inv = db.scalar(select(Invoice).where(Invoice.user_id == user.id, Invoice.paypal_id == n["paypal_id"]))
    if inv:
        for k, v in n.items(): setattr(inv, k, v)
    else:
        inv = Invoice(user_id=user.id, **n); db.add(inv)
    db.commit()
    return inv


def sync_invoices(db: Session, user: User, client) -> dict:
    raws = client.list_invoices()
    for r in raws: upsert_invoice(db, user, r)
    return {"fetched": len(raws)}


def tx_rows(db: Session, user: User, days: int | None = None) -> list[dict]:
    """DB rows -> plain dicts for analytics/agent. Always scoped to the user."""
    q = select(Transaction).where(Transaction.user_id == user.id)
    if days: q = q.where(Transaction.date >= datetime.now(timezone.utc) - timedelta(days=days))
    return [{"id": t.paypal_id, "date": t.date, "status": t.status, "amount": float(t.amount), "currency": t.currency,
             "payer": t.payer_name, "email": t.payer_email, "subject": t.subject} for t in db.scalars(q.order_by(Transaction.date.desc()))]
