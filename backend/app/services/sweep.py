"""The "overnight sweep": sync PayPal, scan for anomalies, and PREPARE friendly reminders for overdue invoices.
Everything it creates is a PENDING action. It never sends anything, so the human approval gate is unchanged.
Runs inline (local/demo) or as a Render Workflows task (one task per account, in parallel)."""
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import AIAction, Invoice, PayPalAccount, User
from app.services import actions as act, analytics as an
from app.services.sync import sync_invoices, sync_transactions, tx_rows

COOLDOWN_DAYS = 7  # don't nag: skip invoices reminded in the last week


def friendly_note(inv: Invoice, today: date) -> tuple[str, str]:
    late = (today - inv.due_date).days
    name = (inv.recipient_name or "there").split(" ")[0] if inv.recipient_name else "there"
    return (f"Friendly reminder: invoice {inv.number}",
            f"Hi {name}, just a friendly heads-up that invoice {inv.number} for {inv.currency} {float(inv.total):,.2f} was due on {inv.due_date.isoformat()} "
            f"({late} day{'s' if late != 1 else ''} ago). If it's already on its way, please ignore this note. Thank you!")


def _aware(d: datetime) -> datetime: return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def sweep_user(db: Session, user: User, client, today: date | None = None) -> dict:
    now = datetime.now(timezone.utc); today = today or now.date()
    tx = sync_transactions(db, user, client, 30); inv_sync = sync_invoices(db, user, client)
    anomalies = len(an.anomalies(tx_rows(db, user, 120), now))
    waiting = {a.payload.get("invoice_id") for a in db.scalars(select(AIAction).where(AIAction.user_id == user.id, AIAction.action_type == "send_reminder", AIAction.status == "PENDING"))}
    proposed = already = recent = 0; ids = []
    for inv in db.scalars(select(Invoice).where(Invoice.user_id == user.id, Invoice.status.in_(act.REMINDABLE)).order_by(Invoice.due_date)):
        if not inv.due_date or inv.due_date >= today: continue
        if inv.id in waiting: already += 1; continue
        if inv.last_reminded_at and now - _aware(inv.last_reminded_at) < timedelta(days=COOLDOWN_DAYS): recent += 1; continue
        subject, note = friendly_note(inv, today)
        a = act.propose(db, user, "send_reminder", f"Payment reminder to {inv.recipient_name or inv.recipient_email}", {"invoice_id": inv.id, "subject": subject, "note": note}, source="sweep")
        proposed += 1; ids.append(a.id)
    result = {"user_id": user.id, "transactions_fetched": tx["fetched"], "invoices_fetched": inv_sync["fetched"], "anomalies": anomalies,
              "proposed": proposed, "already_queued": already, "recently_reminded": recent}
    act._audit(db, user.id, None, "sweep", {k: v for k, v in result.items() if k != "user_id"}); db.commit()
    return result


def sweep_user_by_id(user_id: str) -> dict:
    """Entry point for the Render workflow task (separate process, no web request)."""
    from app.db import SessionLocal
    from app.deps import resolve_paypal
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user: return {"user_id": user_id, "skipped": "unknown user"}
        client = resolve_paypal(user, db)
        if client.mode == "demo": return {"user_id": user_id, "skipped": "demo simulator state lives in the web process, so it cannot be swept remotely"}
        return sweep_user(db, user, client)


def list_sweepable_user_ids() -> list[str]:
    from app.db import SessionLocal
    with SessionLocal() as db:
        if settings.paypal_env_configured: return list(db.scalars(select(User.id)))
        return list(db.scalars(select(PayPalAccount.user_id)))
