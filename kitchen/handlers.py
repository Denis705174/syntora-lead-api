"""Aiogram handlers for @iogram3x_bot (Syntora Kitchen AI demo)."""

from __future__ import annotations

import logging

from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from openai import RateLimitError

from kitchen.ai import get_ai_response

logger = logging.getLogger(__name__)

DEMO_WELCOME = (
    "👋 <b>Syntora Kitchen AI</b> — демо-версия AI-менеджера для мебельного бизнеса.\n\n"
    "Напишите, как на обычной консультации: бюджет, сроки, пожелания по кухне. "
    "Покажу, как бот отрабатывает возражения и передаёт лид оператору."
)


async def handle_start(message: Message) -> None:
    """Send branded demo welcome on /start."""
    await message.answer(DEMO_WELCOME, parse_mode="HTML")


async def handle_message(message: Message) -> None:
    """Forward user text to Gemini; CRM leads are saved via function calling."""
    if message.from_user is None:
        return

    user_text = message.text or ""
    user_id = message.from_user.id

    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        reply = await get_ai_response(user_id=user_id, user_text=user_text)
        await message.answer(reply)
    except RateLimitError:
        logger.warning("Kitchen AI rate-limited for user_id=%s", user_id)
        await message.answer(
            "Сейчас высокая нагрузка на ИИ (лимит запросов). "
            "Напишите через 30–60 секунд — или оставьте заявку на syntora.space / в @MegaPromptBot."
        )
    except Exception as exc:
        logger.exception("Kitchen AI failed for user_id=%s err=%s", user_id, type(exc).__name__)
        await message.answer(
            "Сейчас не удалось получить ответ от ИИ. "
            "Напишите ещё раз через минуту или оставьте заявку на сайте syntora.space "
            "/ в @MegaPromptBot."
        )


def build_kitchen_dispatcher() -> Dispatcher:
    """Register Kitchen AI handlers."""
    dp = Dispatcher()
    dp.message.register(handle_start, CommandStart())
    # Exclude slash-commands; bare Command() raises in current aiogram.
    dp.message.register(handle_message, F.text, ~F.text.startswith("/"))
    return dp
