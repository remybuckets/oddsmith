"""Configuration from environment variables only (see the repo's .env.example)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# Free API-Football plans only serve seasons 2022-2024; switch to 2026 once on Pro.
DEFAULT_SEASON = 2024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ENV_FILE, extra="ignore")

    database_url: str
    api_football_key: str = ""
    odds_api_key: str = ""
    api_football_season: int = Field(default=DEFAULT_SEASON, ge=2000, le=2100)
    # Requests / credits always left untouched, so a runaway job can't drain the day.
    api_football_quota_reserve: int = Field(default=10, ge=0)
    odds_api_quota_reserve: int = Field(default=50, ge=0)
    # Free plan allows 10 requests a minute; Pro allows 300, so set to 0.2 there.
    api_football_min_interval: float = Field(default=6.5, ge=0)


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
