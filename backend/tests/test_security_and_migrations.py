import os, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone
import jwt
from sqlalchemy import select
from app.core import security
from app.core.config import settings
from app.db import SessionLocal
from app.models import PayPalAccount
from conftest import signup

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_password_and_encryption_roundtrip():
    h = security.hash_password("correct horse"); assert h != "correct horse" and security.verify_password("correct horse", h) and not security.verify_password("wrong", h)
    assert security.verify_password("x", "not-a-hash") is False
    enc = security.encrypt("s3cret"); assert "s3cret" not in enc and security.decrypt(enc) == "s3cret"


def test_expired_and_forged_tokens_rejected():
    old = jwt.encode({"sub": "u", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, settings.jwt_secret, algorithm="HS256")
    forged = jwt.encode({"sub": "u", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "other-secret", algorithm="HS256")
    assert security.decode_token(old) is None and security.decode_token(forged) is None
    assert security.decode_token(security.create_token("abc")) == "abc"


def test_paypal_secret_is_encrypted_and_never_returned(client, auth, monkeypatch):
    monkeypatch.setattr("app.api.routes.paypal.PayPalClient.check_credentials", lambda self: None)
    r = client.post("/api/v1/paypal/connect", json={"client_id": "ID1234567890", "client_secret": "SUPERSECRET123"}, headers=auth)
    assert r.status_code == 200 and "SUPERSECRET" not in r.text
    with SessionLocal() as db:
        a = db.scalar(select(PayPalAccount)); assert "SUPERSECRET123" not in a.secret_encrypted and security.decrypt(a.secret_encrypted) == "SUPERSECRET123"
    assert "SUPERSECRET" not in client.get("/api/v1/paypal/status", headers=auth).text


def test_invalid_paypal_credentials_are_not_saved(client, auth):
    from app.services.paypal import PayPalError
    def boom(self): raise PayPalError(401, "rejected")
    import app.api.routes.paypal as r; r.PayPalClient.check_credentials = boom
    try:
        assert client.post("/api/v1/paypal/connect", json={"client_id": "ID1234567890", "client_secret": "SECRET1234567"}, headers=auth).status_code == 401
    finally:
        r.PayPalClient.check_credentials = lambda self: None
    with SessionLocal() as db: assert db.scalar(select(PayPalAccount)) is None


def test_login_is_rate_limited(client):
    signup(client)
    codes = [client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "bad-password"}).status_code for _ in range(12)]
    assert 429 in codes


def test_webhook_refuses_when_unconfigured_and_cors_is_scoped(client):
    assert client.post("/api/v1/webhooks/paypal", json={}).status_code == 503
    r = client.options("/api/v1/transactions", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


def _alembic(*args, db):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}"}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)


def test_migrations_apply_and_match_models():
    db = os.path.join(tempfile.mkdtemp(), "m.db")
    up = _alembic("upgrade", "head", db=db); assert up.returncode == 0, up.stderr
    chk = _alembic("check", db=db); assert chk.returncode == 0, "models changed without a migration:\n" + chk.stdout + chk.stderr
