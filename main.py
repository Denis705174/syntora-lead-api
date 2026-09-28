"""Syntora lead API + Telegram webhooks on Render."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from collections import OrderedDict, defaultdict
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
from yougile import create_website_lead_task, yougile_enabled

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

_SEEN_UPDATES_MAX = 2000
_seen_updates: dict[str, OrderedDict[int, None]] = defaultdict(OrderedDict)
# Enforced only after set_webhook succeeded in this process; otherwise Telegram
# may still deliver with an older (or no) secret and the bot would go silent.
_secret_enforced: dict[str, bool] = {"lead": False, "kitchen": False}
_background_tasks: set[asyncio.Task[None]] = set()


def _webhook_secret(token: str) -> str:
    """Stable per-bot secret derived from the token (Telegram allows [A-Za-z0-9_-], 1-256)."""
    explicit = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    seed = f"{explicit}:{token}" if explicit else token
    return hashlib.sha256(f"syntora-webhook:{seed}".encode()).hexdigest()


def _authorized(name: str, token: str, request: Request) -> bool:
    if not _secret_enforced[name]:
        return True
    received = request.headers.get("x-telegram-bot-api-secret-token", "")
    return hmac.compare_digest(received, _webhook_secret(token))


def _is_duplicate(name: str, update_id: int) -> bool:
    seen = _seen_updates[name]
    if update_id in seen:
        return True
    seen[update_id] = None
    if len(seen) > _SEEN_UPDATES_MAX:
        seen.popitem(last=False)
    return False


def _process_in_background(label: str, coro) -> None:
    """Answer Telegram immediately; slow AI/CRM work must not trigger redelivery."""

    async def runner() -> None:
        try:
            await coro
        except Exception:
            logger.exception("%s webhook handler failed", label)

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases and register Telegram webhooks."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    # httpx INFO lines contain full request URLs, i.e. bot tokens.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_db(settings.db_path)
    init_bot_db(settings.bot_db_path)
    logger.info("Lead API started, db=%s bot_db=%s", settings.db_path, settings.bot_db_path)

    webhook_base = settings.resolved_webhook_base()
    if webhook_base:
        # drop_pending_updates=False: on Render free cold-start the wake-up
        # message must not be discarded, or bots look "silent".
        try:
            lead_webhook = f"{webhook_base}/telegram/webhook"
            await bot.set_webhook(
                url=lead_webhook,
                drop_pending_updates=False,
                allowed_updates=["message", "callback_query"],
                secret_token=_webhook_secret(settings.bot_token),
            )
            _secret_enforced["lead"] = True
            logger.info("Lead bot webhook set: %s", lead_webhook)
        except Exception:
            logger.exception("Lead bot webhook registration failed")

        if kitchen_bot is not None and kitchen_dp is not None:
            try:
                kitchen_webhook = f"{webhook_base}/telegram/kitchen-webhook"
                await kitchen_bot.set_webhook(
                    url=kitchen_webhook,
                    drop_pending_updates=False,
                    allowed_updates=["message", "callback_query"],
                    secret_token=_webhook_secret(kitchen_settings.kitchen_bot_token),
                )
                _secret_enforced["kitchen"] = True
                logger.info("Kitchen bot webhook set: %s", kitchen_webhook)
            except Exception:
                logger.exception("Kitchen bot webhook registration failed")
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
    allow_headers=["Content-Type", "Accept"],
    expose_headers=["*"],
)


def _client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
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
        "yougile": yougile_enabled(),
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Receive Telegram updates for @MegaPromptBot (no polling needed)."""
    if not _authorized("lead", settings.bot_token, request):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        update = Update.model_validate(await request.json())
    except Exception:
        logger.exception("Lead webhook: invalid update payload")
        return {"ok": True}
    if _is_duplicate("lead", update.update_id):
        return {"ok": True}
    logger.info("Lead update id=%s", update.update_id)
    _process_in_background("Lead", dp.feed_update(bot, update))
    return {"ok": True}


@app.post("/telegram/kitchen-webhook")
async def kitchen_webhook(request: Request) -> dict[str, bool]:
    """Receive Telegram updates for @iogram3x_bot (Kitchen AI demo)."""
    if kitchen_bot is None or kitchen_dp is None:
        raise HTTPException(status_code=503, detail="Kitchen bot not configured")
    if not _authorized("kitchen", kitchen_settings.kitchen_bot_token, request):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        update = Update.model_validate(await request.json())
    except Exception:
        logger.exception("Kitchen webhook: invalid update payload")
        return {"ok": True}
    if _is_duplicate("kitchen", update.update_id):
        return {"ok": True}
    _process_in_background("Kitchen", kitchen_dp.feed_update(kitchen_bot, update))
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

    # Lead is already in SQLite — never fail the HTTP response solely on Telegram/CRM.
    telegram_notify = os.environ.get("TELEGRAM_NOTIFY", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if telegram_notify:
        try:
            await notify_website_lead(payload, lead_id)
        except Exception:
            logger.exception("Telegram notify failed for lead_id=%s (lead already saved)", lead_id)
    else:
        logger.info("Telegram notify skipped for lead_id=%s", lead_id)

    try:
        await create_website_lead_task(
            lead_id=lead_id,
            name=payload.name.strip(),
            phone=payload.phone.strip(),
            email=(payload.email or "").strip() or None,
            service=payload.service.strip(),
            message=(payload.message or "").strip() or None,
        )
    except Exception:
        logger.exception("YouGile sync failed for lead_id=%s", lead_id)

    logger.info("Lead #%s saved", lead_id)
    return {"status": "ok"}
