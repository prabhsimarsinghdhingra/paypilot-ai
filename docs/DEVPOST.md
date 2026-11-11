# Devpost submission draft (edit the [brackets], delete this line)

## Project name
PayPilot AI

## Elevator pitch
An AI copilot for PayPal merchants. It reads your PayPal activity, finds who owes you money, drafts friendly reminders, and sends nothing until you approve it.

## Inspiration
Freelancers and small shops spend hours chasing late payments. Most AI tools either just answer questions or act without asking. We wanted an assistant that does the tedious preparation, and keeps the human in charge of anything that touches a customer.

## What it does
- Syncs **PayPal Sandbox** transactions (Transaction Search) and invoices (Invoicing v2) into your own database.
- **Transactions** in AG Grid with server-side paging, sorting, search, filters, column control, detail panel and CSV export.
- **Analytics Studio** (AG Studio): an editable dashboard with a custom "Who still owes you" scoreboard, a PayPilot theme, and Studio's built-in AI assistant running on Gemini.
- **Gemini assistant** with a strict tool registry: read-only tools run freely; anything that creates or sends (invoice drafts, sends, reminders) is only *proposed*.
- **Approvals:** every proposal waits for you. Approving re-validates against your current invoices, executes once through PayPal's API, and is written to an audit log.
- **Overnight sweep** on **Render Workflows:** one task per account, in parallel, prepares reminders for overdue invoices. Same approval gate.
- **Forecast and alerts:** weekly-trend forecast as a range (not a promise); explainable anomaly flags.

## How we built it
Next.js, TypeScript and Recharts on Vercel; FastAPI, SQLAlchemy and Alembic on Render with PostgreSQL; Gemini function calling; PayPal REST APIs (OAuth, Transaction Search with 31-day chunking, Invoicing create/send/remind, webhook verification); AG Grid Community and AG Studio; Render Workflows plus a cron trigger.
Safety by design: the model can't touch PayPal. The only code that causes side effects is the approval executor, which uses compare-and-swap state transitions so a double click or retry cannot send twice.

## Challenges
- PayPal Transaction Search has a 31-day window, no text search or sorting, so the grid reads a synced copy and the sync chunks and pages.
- A "duplicate proposal" check worked on SQLite and crashed on PostgreSQL (`json = json`). Running the suite on real Postgres in CI caught it.
- Gemini 3 tool calling needs thought signatures replayed between turns; Gemini models were also sometimes overloaded, so we added retries and model fallback.
- Free hosting tiers sleep and expire; we moved to paid plans on the Render credits.

## Accomplishments we're proud of
- 70 backend tests (also run on PostgreSQL 16), 12 browser end-to-end tests, CI, and a live "doctor" script. [confirm counts on your final run]
- Mutation-tested the approval and sweep logic: we broke the code on purpose and checked the tests failed.
- Nothing is ever sent without approval, and that is tested end to end.

## What we learned
Treat the model as a proposer, not an actor. Verify against real infrastructure (Postgres, real browsers) early.

## What was built during the hackathon
We started from a ~430-line starter with an in-memory approval demo, no auth, and no database. During the hackathon we rebuilt the backend (auth, database, migrations, PayPal client, agent, approval engine, forecasting), built the whole frontend, added AG Studio integration (custom widget, theme, agent bridge), the Render Workflows sweep, and the test and CI pipeline.

## Built with
PayPal REST APIs (Sandbox) · Google Gemini · AG Grid · AG Studio · Render (Web Service, PostgreSQL, Workflows, Cron) · Vercel · Next.js · React · TypeScript · FastAPI · Python · SQLAlchemy · Alembic · PostgreSQL · Recharts · Playwright · GitHub Actions

## Try it
- Live demo: [Vercel URL]  (register any email; judges get the labeled demo simulator, or connect a Sandbox in Settings)
- Test credentials for a pre-filled account: [email / password, optional]
- Code: [GitHub URL] (MIT license)
- Video: [YouTube URL]

## Sponsor tools to select on the form
PayPal, AG Grid, Render. Select Render only if the Workflow run succeeded in the Render dashboard. Do not select APIMatic unless you really used it (see docs/SPONSORS.md).
