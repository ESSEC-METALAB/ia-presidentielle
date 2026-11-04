"""Environment settings, read from the process environment and .env (see .env.example)."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["fake", "mistral"] = "fake"
    mistral_api_key: SecretStr | None = None
    mistral_model: str | None = None
    # One annotation call. A reasoning model (mistral-large-4-0) thinks before it answers:
    # long passages took over 60 s on 2026-11-04 and were left pending.
    llm_timeout_seconds: float = Field(default=180, gt=0)
    database_path: Path = Path("data/observatoire.db")
    config_dir: Path = Path("config")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # `observatoire web`: the least time between two refreshes asked from the site.
    refresh_cooldown_minutes: int = Field(default=10, ge=0)
