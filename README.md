# PayPilot AI

**An AI copilot for PayPal merchants. It finds what needs attention, drafts the follow-up, and waits for your approval before anything is sent.**

Built for the PayPal AI Hackathon 2026 (PayPal + Gemini + AG Grid). Sandbox only: no real money moves.

## What it does
- **Syncs PayPal Sandbox** transactions (Transaction Search) and invoices (Invoicing v2) into your own database.
- **Overview and AG Grid transactions:** per-currency KPIs, monthly revenue, status mix; a grid with server-side paging, sorting, search, date/status/currency filters, column visibility, detail panel and CSV export.
- **Gemini assistant with tool calling:** 9 read-only tools (transactions, revenue, failed/pending payments, customers, overdue invoices, forecast, anomalies) and 3 *propose-only* tools (invoice draft, send invoice, payment reminder).
- **Human-in-the-loop execution:** proposals become approval slips. Approving re-validates and then calls PayPal (create draft, send, or remind). Every step is audited, and nothing runs twice.
- **Invoices:** compose with live totals, save as a PayPal draft, request send/reminder.
- **Analytics Studio (AG Studio):** an editable, drag-and-drop dashboard over your PayPal data, one currency at a time, with Studio's built-in AI assistant running on Gemini through our backend.
- **Overnight sweep (Render Workflows):** syncs PayPal and prepares a friendly reminder for each overdue invoice, fanned out per account on Render Workflows. It only prepares them; you approve each one.
- **Forecast and alerts:** weekly-trend forecast with uncertainty ranges, explainable anomaly flags.

## Try it (judges)
Hosted demo: _add URL_ · Register any email/password. Without PayPal keys the backend shows a clearly labeled **demo simulator**; add Sandbox credentials in **Settings** for real PayPal data. Test credentials: _add after deploy_.

## Run locally
See [docs/DEPLOY.md](docs/DEPLOY.md). **Verify everything locally:** `python scripts/check.py` (fast) or `python scripts/check.py --full` (adds build + browser tests) or `--live` (tests your real PayPal Sandbox and Gemini keys). Details in [docs/TESTING.md](docs/TESTING.md).

## How PayPal and AI are used
| | |
|---|---|
| PayPal REST | OAuth, `GET /v1/reporting/transactions`, `POST /v2/invoicing/invoices`, `…/send`, `…/remind`, `GET …/invoices`, webhook signature verification |
| Gemini | Function calling with a strict tool registry; writes personalised reminder copy and explains findings |
| AG Grid Community 36 | Infinite row model driving server-side paging/sort/filter |
| AG Studio 3 (commercial, trial licence) | Embedded self-serve dashboard; runs unlicensed with a watermark, see [docs/SPONSORS.md](docs/SPONSORS.md) |
| Next.js, Recharts, FastAPI, SQLAlchemy, Alembic, PostgreSQL | Product, charts, API, persistence |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The PayPal Agent Toolkit (TypeScript, MCP) exposes the same invoice operations; we call the REST endpoints directly from Python and put our own approval gate in front of them.

## Honest limits
Sandbox only · forecasts are estimates · anomalies are flags, not fraud findings · rate limiting is per-process · demo-simulator state resets on restart.

License: MIT
