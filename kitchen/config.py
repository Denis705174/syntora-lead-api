"""Kitchen AI bot settings (optional — enabled when KITCHEN_BOT_TOKEN is set)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KitchenSettings(BaseSettings):
    """Gemini + Google Sheets settings for @iogram3x_bot."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    kitchen_bot_token: str = Field(default="", description="Telegram token for @iogram3x_bot")
    openai_api_key: str = Field(default="", description="Gemini API key")
    openai_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    openai_model: str = Field(default="gemini-3.6-flash")
    openai_model_fallback: str = Field(
        default="gemini-3.1-flash-lite,gemini-flash-latest",
        description="Comma-separated models tried after the primary on 404/5xx/timeout",
    )
    backup_ai_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Second OpenAI-compatible provider used when every Gemini model fails",
    )
    backup_ai_api_key: str = Field(default="", description="Key for the backup provider (empty = off)")
    backup_ai_models: str = Field(
        default="qwen/qwen3.8-27b:free,google/gemma-4-31b-it:free",
        description="Comma-separated backup models",
    )
    spreadsheet_id: str = Field(default="", description="Google Sheets CRM ID or URL")
    google_creds_json: str = Field(default="", description="Service account JSON as string")
    kitchen_message_limit: int = Field(
        default=20,
        ge=1,
        description="Demo replies per user before the bot switches to the sales CTA",
    )


kitchen_settings = KitchenSettings()


def kitchen_enabled() -> bool:
    """Return True when Kitchen AI webhook should be registered.

    Sheets CRM is optional: /start and chat work with token + Gemini key only.
    """
    return bool(
        kitchen_settings.kitchen_bot_token.strip()
        and kitchen_settings.openai_api_key.strip()
    )
