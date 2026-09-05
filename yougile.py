"""YouGile CRM client — create tasks from website and bot leads."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)


def yougile_enabled() -> bool:
    """True when API key and target column are configured."""
    return bool(settings.yougile_api_key.strip() and settings.yougile_column_id.strip())


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.yougile_api_key.strip()}",
    }


def _tasks_url() -> str:
    base = settings.yougile_api_base.rstrip("/")
    return f"{base}/tasks"


async def create_task(*, title: str, description: str) -> str | None:
    """Create a YouGile task in the configured column. Returns task id or None."""
    if not yougile_enabled():
        logger.info("YouGile skipped: YOUGILE_API_KEY / YOUGILE_COLUMN_ID not set")
        return None

    payload: dict[str, Any] = {
        "title": title[:200],
        "columnId": settings.yougile_column_id.strip(),
        "description": description[:4000],
        "completed": False,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(_tasks_url(), headers=_headers(), json=payload)
            if response.status_code >= 400:
                logger.error(
                    "YouGile create task failed status=%s body=%s",
                    response.status_code,
                    response.text[:500],
                )
                return None
            data = response.json()
            task_id = None
            if isinstance(data, dict):
                task_id = data.get("id") or data.get("taskId")
            logger.info("YouGile task created id=%s", task_id)
            return str(task_id) if task_id else "ok"
    except Exception:
        logger.exception("YouGile create task raised")
        return None


async def create_website_lead_task(
    *,
    lead_id: int,
    name: str,
    phone: str,
    email: str | None,
    service: str,
    message: str | None,
) -> str | None:
    """Push a site form lead into YouGile."""
    title = f"Сайт #{lead_id}: {name} — {phone}"
    lines = [
        f"**Источник:** сайт syntora.space",
        f"**ID:** {lead_id}",
        f"**Имя:** {name}",
        f"**Контакт:** {phone}",
        f"**Email:** {email or '—'}",
        f"**Услуга:** {service}",
        f"**Сообщение:** {message or '—'}",
    ]
    return await create_task(title=title, description="\n".join(lines))


async def create_kitchen_lead_task(
    *,
    phone: str,
    budget: str,
    dimensions: str,
) -> str | None:
    """Push a Kitchen AI qualified lead into YouGile."""
    title = f"Kitchen AI: {phone}"
    lines = [
        "**Источник:** Telegram @iogram3x_bot (Kitchen AI)",
        f"**Телефон:** {phone}",
        f"**Бюджет:** {budget}",
        f"**Размеры:** {dimensions}",
    ]
    return await create_task(title=title, description="\n".join(lines))


async def create_bot_lead_task(
    *,
    lead_id: int,
    name: str,
    phone: str,
    service: str,
    message: str | None,
    username: str | None,
) -> str | None:
    """Push a Lead Bot form submission into YouGile."""
    title = f"Lead Bot #{lead_id}: {name} — {phone}"
    lines = [
        "**Источник:** Telegram Lead Bot",
        f"**ID:** {lead_id}",
        f"**Имя:** {name}",
        f"**Контакт:** {phone}",
        f"**Telegram:** @{username}" if username else "**Telegram:** —",
        f"**Услуга:** {service}",
        f"**Сообщение:** {message or '—'}",
    ]
    return await create_task(title=title, description="\n".join(lines))
