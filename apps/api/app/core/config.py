from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the API service."""

    database_url: str = "sqlite:///./.data/mica.db"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    model_config = SettingsConfigDict(env_prefix="MICA_", env_file=".env", extra="ignore")
