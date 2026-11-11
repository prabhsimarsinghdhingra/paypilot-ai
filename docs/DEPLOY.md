# Deploy

## 0. Claim the Render credits (do this first)
Hackathon sponsor credits: https://credits-portal-mmdm.onrender.com/claim/paypal-ai-hackathon, then apply them as described at https://render.com/docs/credits. Credits are deducted from your balance, which is billed at month end. Billing issues: Render Discord or the PayPal Discord.

## Why the blueprint uses paid plans (verified against Render's docs)
- **Free Postgres expires 30 days after creation** (then 14 days' grace before deletion). Winners are announced Dec 21, so a free database created now would die before judging ends.
- **Free web services sleep after 15 idle minutes** and take about a minute to wake. The login page shows a "waking up" message if that happens, but judges should not have to wait.
- Free web services also lose local files (SQLite) on restart. We use Postgres.
Check the prices on Render's pricing page; the credits should comfortably cover a Starter web service, a small Postgres, a cron job and workflow runs until Dec 21.

## 1. Backend on Render (Blueprint)
1. Push the repo to GitHub. In Render: **New > Blueprint**, pick the repo (`render.yaml`). Read the preview (plans, prices, any validation errors) before creating.
2. Generate **one** secret and paste the same value into `JWT_SECRET` on both the API and the workflow: `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
3. Fill the other variables: `FRONTEND_URL` (your Vercel URL, exact, no trailing slash), `GEMINI_API_KEY`, `GEMINI_MODEL` (from `python scripts/pick_model.py`).
   **Leave `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` EMPTY on the API and the workflow.** If they are set, every judge who registers is wired to YOUR sandbox merchant account, and one click on Approve would send reminders and change invoices in your account (sandbox only, but it would wreck your demo data). With them empty, judges get the clearly labeled demo simulator, and you connect your own sandbox per account in **Settings > Connect Sandbox** (stored encrypted, only for your user). Do that for your recording.
4. Create a Render API key (Account Settings > API Keys) and set it as `RENDER_API_KEY` on the API and on the cron job. In the Render dashboard open the workflow and check its slug; if it is not `paypilot-workflow`, set `RENDER_WORKFLOW_SLUG` to it on the API and the cron job.
5. Check `https://<service>.onrender.com/health`.

## 2. Render Workflows: what runs where
- `sweep_account(user_id)`: syncs PayPal, scans anomalies, and **prepares** friendly reminders for overdue invoices as pending approvals. It never sends anything.
- `sweep_all()`: fans `sweep_account` out across every connected account, each on its own instance, in parallel; one failing account does not stop the rest.
- The cron job triggers `sweep_all` nightly. In the app, **Approvals > Run sweep now** triggers `sweep_account` for the signed-in user.
- Demo-simulator users always run the sweep inline on the API (the simulator's state lives in the web process). To show a real Workflows run you need a **connected PayPal Sandbox account**.
- Do not claim Workflows on Devpost until you have seen a run succeed in the Render dashboard.
- If the blueprint rejects the `workflow` or `cron` entries, create them in the dashboard with the same build/start commands and env vars.

## 3. Frontend on Vercel
1. Import the repo, set **Root Directory** to `frontend`.
2. Environment variables: `NEXT_PUBLIC_API_URL = https://<service>.onrender.com/api/v1`, and `NEXT_PUBLIC_AG_LICENSE_KEY` (AG Studio trial key, https://www.ag-grid.com/studio/license-pricing/).
3. Put the Vercel URL into the API's `FRONTEND_URL` and redeploy the API.

## 4. PayPal webhook (optional)
Add a Sandbox webhook to `https://<service>.onrender.com/api/v1/webhooks/paypal`, subscribe to Invoicing events, set `PAYPAL_WEBHOOK_ID`.

## 5. Smoke test after deploying
Register, Settings > Connect Sandbox, Overview > Sync, Approvals > Run sweep now (it should say it ran on Render Workflows, with a run id), approve one reminder, check the invoice in the PayPal sandbox. Run `python backend/scripts/doctor.py` locally against the same keys first.

## Local, no Docker
```
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # add keys; blank PayPal keys = demo simulator
alembic upgrade head && uvicorn app.main:app --reload
cd ../frontend && cp .env.local.example .env.local && npm install && npm run dev
```
Local Postgres: `docker compose up -d`, then `DATABASE_URL=postgresql+psycopg://paypilot:paypilot_local_only@localhost:5432/paypilot`.
