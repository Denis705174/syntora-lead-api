"""Runtime settings for the Syntora lead API."""

from __future__ import annotations

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load secrets and limits from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(min_length=1, description="Telegram Bot API token for notifications")
    chat_id: str = Field(min_length=1, description="Telegram chat/channel ID for lead alerts")
    allowed_origins: str = Field(
        default="https://syntora.space,http://localhost:8080",
        description="Comma-separated CORS origins",
    )
    db_path: str = Field(default="data/leads.db", description="SQLite database path")
    bot_db_path: str = Field(default="data/bot_leads.db", description="SQLite for Telegram bot leads")
    webhook_base_url: str = Field(
        default="",
        description="Public HTTPS URL for Telegram webhook, e.g. https://syntora-lead-api-1.onrender.com",
    )
    rate_limit_seconds: int = Field(default=30, description="Min seconds between submissions per IP")

    def resolved_webhook_base(self) -> str:
        """Prefer explicit WEBHOOK_BASE_URL, else Render's auto URL."""
        explicit = (self.webhook_base_url or "").strip().rstrip("/")
        if explicit:
            return explicit
        return (os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")


settings = Settings()
