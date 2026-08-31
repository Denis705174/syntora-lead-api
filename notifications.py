"""Telegram notifications for website and bot leads."""

from __future__ import annotations

import html

import httpx
from pydantic import BaseModel, Field

from config import settings

SERVICE_LABELS = {
    "consult": "Разбор воронки",
    "ai-employee": "AI-сотрудник под ключ",
    "landing": "AI-лендинг + автоматизация",
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
    """Notify operator about a syntora.space form submission."""
    service_label = SERVICE_LABELS.get(payload.service, payload.service)
    lines = [
        f"🆕 <b>Заявка #{lead_id} с syntora.space</b>",
        "",
        f"<b>Имя:</b> {html.escape(payload.name)}",
        f"<b>Контакт:</b> {html.escape(payload.phone)}",
    ]
    if payload.email:
        lines.append(f"<b>Email:</b> {html.escape(payload.email)}")
    lines.extend(
        [
            f"<b>Услуга:</b> {html.escape(service_label)}",
            f"<b>Сообщение:</b> {html.escape(payload.message or '—')}",
        ]
    )
    await _send_html("\n".join(lines))


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
    """Notify operator about a lead collected inside @MegaPromptBot."""
    service_label = SERVICE_LABELS.get(service, service)
    user_ref = f"@{username}" if username else f"id {user_id}"
    lines = [
        f"🆕 <b>Заявка #{lead_id} из Telegram-бота</b>",
        "",
        f"<b>Имя:</b> {html.escape(name)}",
        f"<b>Контакт:</b> {html.escape(phone)}",
        f"<b>Услуга:</b> {html.escape(service_label)}",
        f"<b>Сообщение:</b> {html.escape(message or '—')}",
        f"<b>Telegram:</b> {html.escape(user_ref)}",
    ]
    await _send_html("\n".join(lines))
