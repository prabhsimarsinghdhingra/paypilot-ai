from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db import Base, engine
from app.api.routes import actions, ai, auth, insights, invoices, paypal, sweep, webhooks


@asynccontextmanager
async def lifespan(app):
    settings.validate_for_runtime()
    if settings.app_env != "production":
        Base.metadata.create_all(engine)  # dev convenience; production runs `alembic upgrade head`
    yield


app = FastAPI(title=settings.app_name, version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"])
for r in (auth, paypal, invoices, ai, actions, insights, sweep):
    app.include_router(r.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}
