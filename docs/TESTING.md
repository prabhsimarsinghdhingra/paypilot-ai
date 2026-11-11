# Testing

```
python scripts/check.py          # secrets scan, lint, 70 backend tests, frontend typecheck   (~30 s)
python scripts/check.py --full   # + production build + 12 browser end-to-end tests            (~5 min)
python scripts/check.py --live   # + live doctor against your real PayPal Sandbox and Gemini keys
python backend/scripts/doctor.py # just the live check
```
Run from the repo root with the backend venv active (`pip install -r backend/requirements.txt -r backend/requirements-dev.txt ruff -r e2e/requirements.txt`, then `python -m playwright install chromium` once, and `npm install` in `frontend/`).

## What each layer covers
| Layer | Where | Covers |
|---|---|---|
| Unit/API | `backend/tests` | auth, per-user isolation, sync idempotency, server-side grid queries, multi-currency math, forecast + anomalies, the approval state machine (double approve, reject, cancel, stale proposals, PayPal failure), agent tool loop (malformed/unauthorised tool calls, step limit) |
| PayPal client | `test_paypal_client.py` | the real client against a scripted fake of HTTP: token cache and refresh, 31-day chunking, pagination, error mapping, invoice create/send/remind bodies, webhook verification |
| Gemini adapter | `test_gemini_adapter.py` | tool-call parsing, thought-signature preservation, retry + model fallback, fail-fast on auth/model errors |
| Security/migrations | `test_security_and_migrations.py` | encryption, token expiry, secrets never returned, rate limiting, CORS, `alembic upgrade` + drift check |
| Browser E2E | `e2e/` | register -> sync -> grid filter/sort/export -> overdue reminders -> approve/reject -> audit log -> invoice draft -> send; Studio numbers equal Overview numbers. Gemini is replaced by a deterministic stand-in (`e2e/fake_server.py`); PayPal is the labeled simulator |
| Studio bridge | `test_studio_bridge.py` | Studio conversation items -> Gemini contents (parallel calls, thought signatures, result-name lookup), payload limits, auth, error mapping |
| Sweep + workflow | `test_sweep.py` | reminder prep (idempotent, 7-day cooldown, overdue-only, nothing sent), inline vs Render path, run ownership, fan-out isolates failures |
| Live | `backend/scripts/doctor.py` | your real credentials, Transaction Search + Invoicing access, Gemini tool-calling round trip |

## What the automated tests cannot prove
They never call real PayPal or Gemini (CI has no secrets). Only `doctor.py` and your own sandbox run do. CI runs the backend suite on SQLite and on PostgreSQL 16.
