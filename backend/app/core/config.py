from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PayPilot AI"
    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"  # comma-separated list allowed
    database_url: str = "sqlite:///./paypilot.db"  # use postgresql+psycopg://... in production
    jwt_secret: str = "dev-insecure-change-me"
    jwt_expire_minutes: int = 720
    encryption_key: str = ""  # Fernet key for stored PayPal secrets; derived from jwt_secret if empty
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    force_demo_paypal: bool = False  # use the built-in labeled PayPal simulator even if credentials exist
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_models: str = "gemini-flash-latest"  # comma-separated; tried if the main model is overloaded (503/429)
    render_api_key: str = ""  # lets the API start Render Workflows runs; empty = run sweeps inline
    render_workflow_slug: str = "paypilot-workflow"
    gemini_timeout_s: int = 40  # fail fast instead of hanging the chat
    gemini_thinking_level: str = ""  # optional "low" for faster answers on Gemini 3.x; empty = model default
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def _pg_driver(cls, v: str) -> str:  # Render/Heroku hand out postgres:// or postgresql:// URLs
        for old in ("postgres://", "postgresql://"):
            if v.startswith(old): return "postgresql+psycopg://" + v[len(old):]
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_url.split(",") if o.strip()]

    @property
    def paypal_env_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret) and not self.force_demo_paypal

    def validate_for_runtime(self) -> None:
        if self.app_env == "production" and self.jwt_secret == "dev-insecure-change-me":
            raise RuntimeError("Set a strong JWT_SECRET in production")
        if self.app_env == "production" and "sandbox" not in self.paypal_base_url:
            raise RuntimeError("This project is sandbox-only; refusing to start against a live PayPal URL")


settings = Settings()
