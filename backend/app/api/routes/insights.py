from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import current_user
from app.models import User
from app.services import analytics as an
from app.services.sync import tx_rows

router = APIRouter(tags=["Insights"])
_now = lambda: datetime.now(timezone.utc)

@router.get("/dashboard/summary")
def summary(days: int = Query(90, ge=1, le=365), u: User = Depends(current_user), db: Session = Depends(get_db)):
    return an.revenue_summary(tx_rows(db, u, days), _now()) | {"window_days": days, "customers": an.customer_insights(tx_rows(db, u, days), 5)}

@router.get("/insights/forecast")
def forecast(u: User = Depends(current_user), db: Session = Depends(get_db)): return {"forecasts": an.forecast(tx_rows(db, u), _now())}

@router.get("/insights/anomalies")
def anomalies(u: User = Depends(current_user), db: Session = Depends(get_db)): return {"anomalies": an.anomalies(tx_rows(db, u), _now())}


STATUS_LABEL = {"S": "Completed", "P": "Pending", "D": "Failed", "V": "Reversed"}

@router.get("/analytics/dataset")
def dataset(currency: str | None = Query(None, pattern="^[A-Z]{3}$"), days: int = Query(365, ge=1, le=365),
            u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Flat, single-currency rows for the embedded AG Studio dashboard. One currency at a time, so no chart ever adds EUR to USD."""
    rows = tx_rows(db, u, days)
    currencies = sorted({r["currency"] for r in rows}, key=lambda c: -sum(r["amount"] for r in rows if r["currency"] == c and r["status"] == "S" and r["amount"] > 0))
    if not currencies: return {"currency": None, "currencies": [], "transactions": []}
    cur = currency or currencies[0]
    if cur not in currencies: raise HTTPException(404, "No transactions in that currency")
    out = []
    for r in rows:
        if r["currency"] != cur: continue
        d = r["date"] if r["date"].tzinfo else r["date"].replace(tzinfo=timezone.utc)
        paid = r["status"] == "S" and r["amount"] > 0
        out.append({"paypal_id": r["id"], "date": d.date().isoformat(), "month": d.strftime("%Y-%m"), "status": STATUS_LABEL.get(r["status"], r["status"]),
                    "amount": r["amount"], "payment": r["amount"] if paid else None, "failed": 1 if r["status"] == "D" else 0,
                    "customer": r["payer"] or r["email"] or "Unknown", "description": r["subject"], "currency": cur})
    return {"currency": cur, "currencies": currencies, "transactions": out}
