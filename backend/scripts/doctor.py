"""Live setup check. Run from backend/ with your .env filled in:   python scripts/doctor.py
Tests your REAL PayPal Sandbox credentials and Gemini key end to end and tells you what to fix. Never prints secrets."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta, timezone

bad = 0
def line(ok, name, detail="", hint=""):
    global bad
    tag = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]; bad += ok is False
    print(f"[{tag}] {name}" + (f" - {detail}" if detail else "")); 
    if ok is False and hint: print(f"       fix: {hint}")

line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", hint="Use Python 3.10+ (3.12 recommended)")
from app.core.config import settings as s
line(os.path.exists(".env"), ".env file found", hint="copy .env.example to .env and fill it in")
line(s.jwt_secret != "dev-insecure-change-me", "JWT_SECRET changed from default", hint="set a long random JWT_SECRET (needed in production)") if s.app_env == "production" else None

try:  # database + migrations
    from sqlalchemy import text, inspect
    from app.db import engine
    with engine.connect() as c: c.execute(text("select 1"))
    tables = set(inspect(engine).get_table_names())
    line("alembic_version" in tables and "users" in tables, f"Database reachable ({engine.dialect.name}), migrations applied", hint="run: alembic upgrade head")
except Exception as e: line(False, "Database", type(e).__name__, "check DATABASE_URL")

from app.services.paypal import PayPalClient, PayPalError
if not (s.paypal_client_id and s.paypal_client_secret):
    line(None, "PayPal credentials", "not set in .env (the app will use the labeled demo simulator)")
else:
    pc = PayPalClient(s.paypal_client_id, s.paypal_client_secret, s.paypal_base_url)
    line("sandbox" in s.paypal_base_url, "PAYPAL_BASE_URL is the sandbox", s.paypal_base_url, "use https://api-m.sandbox.paypal.com")
    try: pc.check_credentials(); line(True, "PayPal OAuth token")
    except PayPalError as e: line(False, "PayPal OAuth token", e.detail, "re-copy Client ID/Secret from the SANDBOX tab (no spaces/quotes)")
    else:
        end = datetime.now(timezone.utc); 
        try: n = len(pc.fetch_transactions(end - timedelta(days=7), end)); line(True, "Transaction Search (last 7 days)", f"{n} transactions")
        except PayPalError as e: line(False, "Transaction Search", f"{e.status} {e.detail}", "enable 'Transaction Search' on the app; it can take hours to activate")
        try: n = len(pc.list_invoices()); line(True, "Invoicing: list invoices", f"{n} invoices")
        except PayPalError as e: line(False, "Invoicing: list invoices", f"{e.status} {e.detail}", "enable 'Invoicing' on the app; use a US sandbox business account")

if not s.gemini_api_key: line(False, "GEMINI_API_KEY", "not set", "add it to .env")
else:
    from app.services.agent import GeminiLLM, REGISTRY
    try:
        llm = GeminiLLM(); t = time.time()
        turn = llm.generate("You are a test.", [{"role": "user", "text": "How many failed payments do I have this month?"}], list(REGISTRY.values()))
        called = [c["name"] for c in turn.calls]
        line(bool(called), f"Gemini ({s.gemini_model}) chose a tool", f"{called} in {time.time() - t:.1f}s", "the model did not call a tool; try another GEMINI_MODEL")
        if called:  # second leg: send the tool result back (this is where Gemini 3 thought-signatures matter)
            t = time.time()
            follow = llm.generate("You are a test.", [{"role": "user", "text": "How many failed payments do I have this month?"},
                                  {"role": "model", "text": turn.text, "raw": turn.raw},
                                  {"role": "tool", "results": [{"name": c["name"], "response": {"count": 3, "failed": []}} for c in turn.calls]}], list(REGISTRY.values()))
            line(bool(follow.text or follow.calls), "Gemini accepted the tool result and replied", f"{time.time() - t:.1f}s")
    except Exception as e:
        code = getattr(e, "code", "")
        hint = {401: "key invalid: create a new key at aistudio.google.com/apikey and restart", 404: "model name retired: set GEMINI_MODEL (see the error text)", 429: "rate limited: wait a minute",
                503: "model overloaded: run python scripts/pick_model.py to find a model that is fast for your key right now", 504: "model too slow/overloaded: run python scripts/pick_model.py and use the model it recommends", 403: "enable the Generative Language API for the key's project"}.get(code, "see the message")
        line(False, "Gemini call", f"{type(e).__name__} {code} {str(getattr(e, 'message', e))[:160]}", hint)

print("\nAll good." if not bad else f"\n{bad} problem(s) found.")
sys.exit(1 if bad else 0)
