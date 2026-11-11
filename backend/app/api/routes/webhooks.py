from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from app.core.config import settings
from app.db import SessionLocal
from app.models import AuditLog, Invoice
from app.services.paypal import PayPalClient, PayPalError
from app.services.sync import upsert_invoice

router = APIRouter(tags=["Webhooks"])
STATUS = {"INVOICING.INVOICE.PAID": "PAID", "INVOICING.INVOICE.CANCELLED": "CANCELLED", "INVOICING.INVOICE.REFUNDED": "REFUNDED"}

@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    if not (settings.paypal_env_configured and settings.paypal_webhook_id):
        raise HTTPException(503, "Webhook verification not configured (PAYPAL_CLIENT_ID/SECRET/WEBHOOK_ID)")
    event = await request.json()
    client = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url)
    try: ok = client.verify_webhook(dict(request.headers), event, settings.paypal_webhook_id)
    except PayPalError: ok = False
    if not ok: raise HTTPException(400, "Invalid webhook signature")  # never act on unverified events
    res = event.get("resource", {}); pp_id = (res.get("invoice") or {}).get("id") or res.get("id")
    et = event.get("event_type", "")
    if pp_id and et.startswith("INVOICING."):
        with SessionLocal() as db:
            for inv in db.scalars(select(Invoice).where(Invoice.paypal_id == pp_id)):
                try: upsert_invoice(db, type("U", (), {"id": inv.user_id})(), client.get_invoice(pp_id))
                except PayPalError: inv.status = STATUS.get(et, inv.status)
                db.add(AuditLog(user_id=inv.user_id, event="webhook", detail={"event_type": et, "invoice": pp_id})); db.commit()
    return {"received": True}
