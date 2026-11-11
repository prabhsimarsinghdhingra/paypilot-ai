"""Render Workflows entry point. Deployed as its own `workflow` service (see render.yaml); start command: python workflow_main.py

  sweep_account(user_id)  one account: sync PayPal, scan anomalies, PREPARE reminders (pending approval, never sent)
  sweep_all()             fans sweep_account out across every account in parallel, each run on its own instance"""
import asyncio
from render import Retry, TaskContext, Workflows

app = Workflows(default_retry=Retry(max_retries=2, wait_duration_ms=2000, backoff_scaling=2), default_timeout=900)


@app.task
def sweep_account(ctx: TaskContext, user_id: str) -> dict:
    from app.services.sweep import sweep_user_by_id
    return sweep_user_by_id(user_id)


async def fan_out(run, task, user_ids: list[str]) -> dict:
    """One failing account must not stop the others."""
    results = await asyncio.gather(*[run(task, uid) for uid in user_ids], return_exceptions=True)
    done = [r for r in results if isinstance(r, dict) and "skipped" not in r]
    return {"accounts": len(user_ids), "swept": len(done), "skipped": sum(isinstance(r, dict) and "skipped" in r for r in results),
            "failed": sum(not isinstance(r, dict) for r in results), "reminders_proposed": sum(r.get("proposed", 0) for r in done)}


@app.task
async def sweep_all(ctx: TaskContext) -> dict:
    from app.services.sweep import list_sweepable_user_ids
    return await fan_out(ctx.run, sweep_account, list_sweepable_user_ids())


if __name__ == "__main__":
    app.start()
