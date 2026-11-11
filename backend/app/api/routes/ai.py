from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import current_user, get_llm, get_studio_model, rate_limit
from app.models import AIConversation, AIMessage, User
from app.services.agent import Ctx, run_agent
from app.services.studio_bridge import TurnIn, run_turn

router = APIRouter(prefix="/ai", tags=["AI"])

class Chat(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    conversation_id: str | None = None

@router.post("/chat", dependencies=[Depends(rate_limit("chat", 20))])
def chat(b: Chat, u: User = Depends(current_user), db: Session = Depends(get_db), llm=Depends(get_llm)):
    conv = db.scalar(select(AIConversation).where(AIConversation.id == b.conversation_id, AIConversation.user_id == u.id)) if b.conversation_id else None
    if b.conversation_id and not conv: raise HTTPException(404, "Conversation not found")
    if not conv:
        conv = AIConversation(user_id=u.id, title=b.message[:80]); db.add(conv); db.flush()
    history = [{"role": "user" if m.role == "user" else "model", "text": m.content} for m in conv.messages][-12:]
    db.add(AIMessage(conversation_id=conv.id, role="user", content=b.message)); db.commit()
    try:
        out = run_agent(Ctx(db, u, conv.id), llm, history, b.message)
    except HTTPException: raise
    except Exception as e:
        import logging
        logging.getLogger("uvicorn.error").exception("Gemini request failed")
        code = getattr(e, "code", None)
        if code in (429, 503): raise HTTPException(503, "Gemini is busy right now. Wait a few seconds and send it again.")
        msg = str(getattr(e, "message", None) or e)[:300]
        raise HTTPException(502, f"AI request failed ({type(e).__name__}{f' {code}' if code else ''}): {msg}")
    db.add(AIMessage(conversation_id=conv.id, role="assistant", content=out["reply"],
                     meta={"tool_calls": out["tool_calls"], "action_ids": [a["id"] for a in out["actions"]]})); db.commit()
    return {"conversation_id": conv.id, **out}

@router.get("/conversations")
def conversations(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in
            db.scalars(select(AIConversation).where(AIConversation.user_id == u.id).order_by(AIConversation.created_at.desc()).limit(30))]

@router.get("/conversations/{cid}")
def conversation(cid: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.scalar(select(AIConversation).where(AIConversation.id == cid, AIConversation.user_id == u.id))
    if not c: raise HTTPException(404, "Conversation not found")
    return {"id": c.id, "messages": [{"role": m.role, "content": m.content, "meta": m.meta} for m in c.messages]}


@router.post("/studio-turn", dependencies=[Depends(rate_limit("studio-turn", 60))])
def studio_turn(b: TurnIn, u: User = Depends(current_user), model=Depends(get_studio_model)):
    """One model turn for AG Studio's agent framework. Gemini runs here (key stays server-side); Studio executes the tool calls in the browser."""
    try:
        return run_turn(b, model)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except HTTPException: raise
    except Exception as e:
        import logging
        logging.getLogger("uvicorn.error").exception("Studio turn failed")
        code = getattr(e, "code", None)
        if code in (429, 503): raise HTTPException(503, "Gemini is busy right now. Wait a few seconds and send it again.")
        raise HTTPException(502, f"AI request failed ({type(e).__name__}{f' {code}' if code else ''}): {str(getattr(e, 'message', e))[:300]}")
