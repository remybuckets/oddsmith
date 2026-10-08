"""Orchestrator settings, from environment variables (a repo-root .env is a dev convenience)."""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _env(field: str, env_name: str) -> AliasChoices:
    return AliasChoices(field, env_name)


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ENV_FILE, extra="ignore", frozen=True)

    database_url: str = ""
    anthropic_api_key: str | None = None  # None: the SDK's own credential lookup
    model_fast: str = Field(
        "claude-sonnet-5-5", validation_alias=_env("model_fast", "CLAUDE_MODEL_FAST")
    )
    model_strong: str = Field(  # value questions (DECISIONS.md #3)
        "claude-opus-5-5", validation_alias=_env("model_strong", "CLAUDE_MODEL_STRONG")
    )
    news_enabled: bool = False
    value_edge_threshold: float = 0.05  # DECISIONS.md #9
