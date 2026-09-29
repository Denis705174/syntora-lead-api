"""Telegram notifications for website and bot leads."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from config import settings

SERVICE_LABELS = {
    "consult": "Разбор воронки",
    "ai-employee": "AI-сотрудник под ключ",
    "landing": "AI-лендинг + автоматизация",
    "website": "Создание сайтов и лендингов",
    "other": "Другое",
}


class LeadPayload(BaseModel):
    """Validated contact form payload from syntora.space."""

    model_config = {"populate_by_name": True}

    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=3, max_length=80)
    email: str | None = Field(default=None, max_length=120)
    service: str = Field(min_length=1, max_length=40)
    message: str | None = Field(default=None, max_length=2000)
    consent: str = Field(min_length=1)
    gotcha: str | None = Field(default=None, alias="_gotcha")


async def _send_html(text: str) -> None:
    """Send an HTML message to the operator chat."""
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            url,
            json={
                "chat_id": settings.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    body = response.json()
    if response.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {response.status_code} {response.text}")


async def notify_website_lead(payload: LeadPayload, lead_id: int) -> None:
    """Alert operator without sending personal data over Telegram."""
    del payload  # payload is validated upstream; PII stays in SQLite / YouGile.
    await _send_html(f"🆕 <b>Новая заявка №{lead_id}</b>. Откройте CRM YouGile.")


async def notify_bot_lead(
    *,
    lead_id: int,
    name: str,
    phone: str,
    service: str,
    message: str | None,
    user_id: int,
    username: str | None,
) -> None:
    """Alert operator without sending personal data over Telegram."""
    del name, phone, service, message, user_id, username
    await _send_html(f"🆕 <b>Новая заявка №{lead_id} из Telegram-бота</b>. Откройте CRM YouGile.")


async def notify_kitchen_lead(*, phone: str, budget: str, dimensions: str) -> None:
    """Alert operator without sending personal data over Telegram."""
    del phone, budget, dimensions
    await _send_html("🆕 <b>Новый лид Kitchen AI</b>. Откройте CRM YouGile.")
