# 3-minute demo script (target 2:50, hard limit 3:00)

Record on the **hosted** app with **your connected PayPal Sandbox** (footer must say "PayPal Sandbox", not "DEMO SIMULATOR"). Before recording: sync, make sure 2-3 sandbox invoices are overdue and unpaid, clear old pending approvals, close extra tabs, 1080p, mic check. Do one full dry run.

| Time | Screen | Say (short!) |
|---|---|---|
| 0:00 | Overview | "Freelancers lose hours chasing late payments. PayPilot reads your PayPal activity, prepares the follow-up, and never sends anything without your approval." |
| 0:12 | Transactions (AG Grid) | "Real sandbox data. Filter failed payments, sort, open a row, export. All server-side." (filter + one click, 12 s) |
| 0:28 | Analytics Studio | "AG Studio dashboard, with a custom widget: who still owes me, worst first." |
| 0:40 | Edit dashboard, AI Assistant | Type: "Find overdue invoices and queue a friendly reminder for each one." "Studio's own agents run on Gemini through our backend, plus two PayPilot tools." Wait for it. |
| 1:15 | Approvals | "These are proposals. Nothing has been sent." Read one reminder aloud (5 s). |
| 1:30 | Approve one, reject one | "Approval is a real gate: re-validated, executed once, audited." Show COMPLETED. |
| 1:50 | PayPal sandbox | Show the reminder/invoice activity in the PayPal sandbox. "Executed through PayPal's Invoicing API." |
| 2:05 | Run sweep now | "Every night a Render Workflow fans out one task per account and prepares reminders. Same gate." Show the "Ran on Render Workflows" line, then 3 s of the Render dashboard run. |
| 2:25 | Forecast & alerts | "Forecasts are ranges, not promises. Every alert explains why." (5 s) |
| 2:35 | Repo / README | "Open source, 70 backend tests plus browser tests, CI on Postgres, Gemini key server-side." |
| 2:48 | Title card | "PayPilot AI. Link in the description." |

Rules: no dead air, no reading screens aloud, cut any step that fails twice (record again). Upload to YouTube as **Public**, title "PayPilot AI: an AI copilot for PayPal merchants", under 3:00.
