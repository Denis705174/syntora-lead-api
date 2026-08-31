"""Syntora lead API + @MegaPromptBot webhook on Fly.io."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from bot_handlers import build_dispatcher
from bot_storage import init_bot_db
from config import settings
from notifications import LeadPayload, notify_website_lead
from storage import init_db, save_lead

logger = logging.getLogger(__name__)

bot = Bot(token=settings.bot_token)
dp = build_dispatcher(MemoryStorage())
_recent_ips: dict[str, float] = defaultdict(float)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases and register Telegram webhook."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    init_db(settings.db_path)
    init_bot_db(settings.bot_db_path)
    logger.info("Lead API started, db=%s bot_db=%s", settings.db_path, settings.bot_db_path)

    if settings.webhook_base_url:
        webhook_url = f"{settings.webhook_base_url.rstrip('/')}/telegram/webhook"
        await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        logger.info("Telegram webhook set: %s", webhook_url)
    else:
        logger.warning("WEBHOOK_BASE_URL is empty — bot webhook not registered")

    yield

    if settings.webhook_base_url:
        await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()
    logger.info("Lead API stopped")


app = FastAPI(title="Syntora Lead API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    last = _recent_ips.get(ip, 0.0)
    if now - last < settings.rate_limit_seconds:
        raise HTTPException(status_code=429, detail="Too many requests")
    _recent_ips[ip] = now


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for Fly.io."""
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Receive Telegram updates for @MegaPromptBot (no polling needed)."""
    payload = await request.json()
    update = Update.model_validate(payload)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.post("/api/lead")
async def submit_lead(payload: LeadPayload, request: Request) -> dict[str, str]:
    """Accept a website lead, store locally, and notify via Telegram."""
    if payload.gotcha:
        return {"status": "ok"}

    if payload.consent.lower() not in {"yes", "true", "1", "on"}:
        raise HTTPException(status_code=400, detail="Consent required")

    ip = _client_ip(request)
    _check_rate_limit(ip)

    lead_id = save_lead(
        settings.db_path,
        name=payload.name.strip(),
        phone=payload.phone.strip(),
        email=(payload.email or "").strip() or None,
        service=payload.service.strip(),
        message=(payload.message or "").strip() or None,
        ip=ip,
    )

    try:
        await notify_website_lead(payload, lead_id)
    except Exception:
        logger.exception("Unexpected Telegram error for lead_id=%s", lead_id)
        raise HTTPException(status_code=502, detail="Telegram delivery failed") from None

    logger.info("Lead #%s saved and sent to Telegram", lead_id)
    return {"status": "ok"}
