"""Nightly trigger (run by the Render cron job): starts the sweep_all workflow task. Workflows have no built-in schedule, so cron triggers it."""
import datetime, os, sys
from render import Render

slug = os.environ.get("RENDER_WORKFLOW_SLUG", "paypilot-workflow")
try:
    run = Render().workflows.start_task(f"{slug}/sweep_all", [], idempotency_key=f"nightly-{datetime.date.today().isoformat()}")
    print(f"Started {slug}/sweep_all run {run.id}")
except Exception as e:
    print(f"Could not start the sweep: {type(e).__name__}: {e}"); sys.exit(1)
