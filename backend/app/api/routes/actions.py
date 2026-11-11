from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import current_user, get_paypal
from app.models import AIAction, AuditLog, User
from app.services import actions as act

router = APIRouter(tags=["Approvals"])

@router.get("/actions")
def list_actions(status: str | None = Query(None, max_length=12), u: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(AIAction).where(AIAction.user_id == u.id)
    if status: q = q.where(AIAction.status == status.upper())
    return [act.action_dict(a) for a in db.scalars(q.order_by(AIAction.created_at.desc()).limit(100))]

@router.post("/actions/{aid}/approve")
def approve(aid: str, u: User = Depends(current_user), db: Session = Depends(get_db), client=Depends(get_paypal)):
    return act.action_dict(act.approve_and_execute(db, u, aid, client))

@router.post("/actions/{aid}/reject")
def reject(aid: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    return act.action_dict(act.reject(db, u, aid))

@router.post("/actions/{aid}/cancel")
def cancel(aid: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    return act.action_dict(act.reject(db, u, aid, cancel=True))

@router.get("/audit")
def audit(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": l.id, "action_id": l.action_id, "event": l.event, "detail": l.detail, "at": l.created_at.isoformat()}
            for l in db.scalars(select(AuditLog).where(AuditLog.user_id == u.id).order_by(AuditLog.created_at.desc()).limit(200))]
