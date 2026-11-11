import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db import get_db
from app.deps import current_user, get_paypal, rate_limit
from app.models import User
from app.services.sweep import sweep_user

router = APIRouter(tags=["Sweep"])
_RUNS: dict[str, str] = {}  # run id -> owner (in memory: a restart forgets in-flight runs)


class RenderSweepRunner:
    """Starts one Render Workflows task for this account. Needs RENDER_API_KEY and the workflow deployed (see docs/DEPLOY.md)."""
    def _client(self):
        from render import Render
        return Render(token=settings.render_api_key)

    def start(self, user_id: str) -> str:
        run = self._client().workflows.start_task(f"{settings.render_workflow_slug}/sweep_account", [user_id], idempotency_key=f"sweep-{user_id}-{int(time.time() // 60)}")
        return run.id

    def status(self, run_id: str) -> dict:
        d = self._client().workflows.get_task_run(run_id)
        status = getattr(d.status, "value", str(d.status))
        err = getattr(d, "error", None)
        return {"status": status, "result": (d.results[0] if status == "completed" and d.results else None), "error": err if isinstance(err, str) and err else None}


def get_sweep_runner():
    return RenderSweepRunner() if settings.render_api_key and settings.render_workflow_slug else None


@router.post("/sweep", dependencies=[Depends(rate_limit("sweep", 6))])
def start(u: User = Depends(current_user), db: Session = Depends(get_db), client=Depends(get_paypal), runner=Depends(get_sweep_runner)):
    """Prepare reminders for overdue invoices. On Render this starts a Workflows task; otherwise (local, or the demo simulator) it runs inline."""
    if runner is not None and client.mode != "demo":
        try: run_id = runner.start(u.id)
        except Exception as e:
            raise HTTPException(502, f"Could not start the Render workflow ({type(e).__name__}). Check RENDER_API_KEY and RENDER_WORKFLOW_SLUG.")
        _RUNS[run_id] = u.id
        return {"mode": "render", "run_id": run_id, "status": "pending"}
    try: result = sweep_user(db, u, client)
    except Exception as e:
        from app.services.paypal import PayPalError
        if isinstance(e, PayPalError): raise HTTPException(e.status if e.status in (401, 403, 404, 422, 429) else 502, e.detail)
        raise
    return {"mode": "inline", "run_id": None, "status": "completed", "result": result}


@router.get("/sweep/runs/{run_id}")
def run_status(run_id: str, u: User = Depends(current_user), runner=Depends(get_sweep_runner)):
    if _RUNS.get(run_id) != u.id or runner is None: raise HTTPException(404, "Run not found")
    try: return runner.status(run_id)
    except Exception as e: raise HTTPException(502, f"Could not read the workflow run ({type(e).__name__}).")
