"""Settings, read from environment variables only (a local .env at the repo root is a dev convenience)."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ENV_FILE, extra="ignore")

    database_url: str
    supabase_url: str
    supabase_service_role_key: str = ""
    redis_url: str = "redis://localhost:6379/0"
    sentry_dsn: str = ""
    daily_question_limit: int = 15
    per_ip_requests_per_minute: int = 10
    daily_token_budget: int | None = None  # None: no global budget (open decision)
    cors_allowed_origins: str = "http://localhost:3000"  # comma-separated web app origins

    @field_validator("daily_token_budget", mode="before")
    @classmethod
    def _blank_budget_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def auth_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.auth_issuer}/.well-known/jwks.json"
