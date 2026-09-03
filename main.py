"""Syntora lead API + Telegram webhooks on Render."""

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
from kitchen.config import kitchen_enabled, kitchen_settings
from notifications import LeadPayload, notify_website_lead
from storage import init_db, save_lead

logger = logging.getLogger(__name__)

bot = Bot(token=settings.bot_token)
dp = build_dispatcher(MemoryStorage())
_recent_ips: dict[str, float] = defaultdict(float)

kitchen_bot: Bot | None = None
kitchen_dp = None

if kitchen_enabled():
    from kitchen.handlers import build_kitchen_dispatcher

    kitchen_bot = Bot(token=kitchen_settings.kitchen_bot_token)
    kitchen_dp = build_kitchen_dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases and register Telegram webhooks."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    init_db(settings.db_path)
    init_bot_db(settings.bot_db_path)
    logger.info("Lead API started, db=%s bot_db=%s", settings.db_path, settings.bot_db_path)

    webhook_base = settings.resolved_webhook_base()
    if webhook_base:
        # drop_pending_updates=False: on Render free cold-start the wake-up
        # message must not be discarded, or bots look "silent".
        lead_webhook = f"{webhook_base}/telegram/webhook"
        await bot.set_webhook(
            url=lead_webhook,
            drop_pending_updates=False,
            allowed_updates=["message", "callback_query"],
        )
        logger.info("Lead bot webhook set: %s", lead_webhook)

        if kitchen_bot is not None and kitchen_dp is not None:
            kitchen_webhook = f"{webhook_base}/telegram/kitchen-webhook"
            await kitchen_bot.set_webhook(
                url=kitchen_webhook,
                drop_pending_updates=False,
                allowed_updates=["message", "callback_query"],
            )
            logger.info("Kitchen bot webhook set: %s", kitchen_webhook)
    else:
        logger.warning("WEBHOOK_BASE_URL / RENDER_EXTERNAL_URL empty — webhooks not registered")

    yield

    # Do NOT delete webhooks on shutdown — Render free tier sleeps often;
    # deleting them leaves bots silent until the next cold start.
    await bot.session.close()
    if kitchen_bot is not None:
        await kitchen_bot.session.close()
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


@app.get("/")
async def root() -> dict[str, str]:
    """Friendly root — Render health check uses /health."""
    return {
        "status": "ok",
        "health": "/health",
        "lead": "POST /api/lead",
        "kitchen_bot": "enabled" if kitchen_bot else "disabled",
    }


@app.get("/health")
async def health() -> dict[str, object]:
    """Health check for Render — includes bot readiness (no secrets)."""
    return {
        "status": "ok",
        "lead_bot": True,
        "kitchen_bot": kitchen_bot is not None,
        "webhook_base": bool(settings.resolved_webhook_base()),
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Receive Telegram updates for @MegaPromptBot (no polling needed)."""
    payload = await request.json()
    try:
        update = Update.model_validate(payload)
        logger.info("Lead update id=%s", update.update_id)
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Lead webhook handler failed")
    return {"ok": True}


@app.post("/telegram/kitchen-webhook")
async def kitchen_webhook(request: Request) -> dict[str, bool]:
    """Receive Telegram updates for @iogram3x_bot (Kitchen AI demo)."""
    if kitchen_bot is None or kitchen_dp is None:
        raise HTTPException(status_code=503, detail="Kitchen bot not configured")
    payload = await request.json()
    try:
        update = Update.model_validate(payload)
        await kitchen_dp.feed_update(kitchen_bot, update)
    except Exception:
        logger.exception("Kitchen webhook handler failed")
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
