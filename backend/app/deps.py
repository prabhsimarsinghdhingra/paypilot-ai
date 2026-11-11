import time
from collections import defaultdict, deque
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import decode_token, decrypt
from app.db import get_db
from app.models import PayPalAccount, User
from app.services.demo_paypal import DemoPayPal
from app.services.paypal import PayPalClient

bearer = HTTPBearer(auto_error=False)
_clients: dict = {}


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    uid = decode_token(cred.credentials) if cred else None
    user = db.get(User, uid) if uid else None
    if not user: raise HTTPException(401, "Not authenticated")
    return user


def resolve_paypal(user: User, db: Session):
    """Per-user connected sandbox app > server env sandbox app > labeled demo simulator. Also used by the Render workflow (no request)."""
    acct = db.scalar(select(PayPalAccount).where(PayPalAccount.user_id == user.id))
    if acct:
        key = ("acct", acct.id, acct.client_id)
        if key not in _clients: _clients[key] = PayPalClient(acct.client_id, decrypt(acct.secret_encrypted), settings.paypal_base_url)
        return _clients[key]
    if settings.paypal_env_configured:
        key = ("env", settings.paypal_client_id)
        if key not in _clients: _clients[key] = PayPalClient(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_base_url)
        return _clients[key]
    key = ("demo", user.id)
    if key not in _clients: _clients[key] = DemoPayPal()
    return _clients[key]


def get_paypal(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return resolve_paypal(user, db)


def get_llm():
    from app.services.agent import GeminiLLM
    if not settings.gemini_api_key: raise HTTPException(503, "GEMINI_API_KEY is not configured on the server")
    return GeminiLLM()


_hits: dict = defaultdict(deque)
def rate_limit(name: str, limit: int, per: int = 60):
    def dep(request: Request):
        k, now = (name, request.client.host if request.client else "?"), time.time(); q = _hits[k]
        while q and q[0] < now - per: q.popleft()
        if len(q) >= limit: raise HTTPException(429, "Too many requests, slow down")
        q.append(now)
    return dep


def get_studio_model():
    from app.services.studio_bridge import GeminiStudioModel
    if not settings.gemini_api_key: raise HTTPException(503, "GEMINI_API_KEY is not configured on the server")
    return GeminiStudioModel()
