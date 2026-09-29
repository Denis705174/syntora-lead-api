"""Aiogram handlers for @iogram3x_bot (Syntora Kitchen AI demo)."""

from __future__ import annotations

import logging

from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from openai import RateLimitError

from kitchen.ai import get_ai_response
from kitchen.config import kitchen_settings

logger = logging.getLogger(__name__)

DEMO_WELCOME = (
    "👋 <b>Syntora Kitchen AI</b> — демо-версия AI-менеджера для мебельного бизнеса.\n\n"
    "Напишите, как на обычной консультации: бюджет, сроки, пожелания по кухне. "
    "Покажу, как бот отрабатывает возражения и передаёт лид оператору.\n\n"
    "В демо доступно {limit} ответов бота."
)

DEMO_LIMIT_REACHED = (
    "🔒 <b>Демо-лимит исчерпан</b> — это тестовая версия AI-менеджера, "
    "она отвечает на {limit} сообщений.\n\n"
    "Чтобы получить полную версию под ваш бизнес — без лимитов, со своим сценарием "
    "и передачей заявок в вашу CRM — оставьте заявку на сайте или напишите нам."
)

DEMO_LIMIT_NOTICE = (
    "🔒 Это был последний из {limit} ответов демо-версии.\n\n"
    "Полную версию под ваш бизнес собираем под задачу — оставьте заявку "
    "или напишите нам напрямую."
)

# In-memory counters: reset on restart, same lifetime as the dialogue history.
_reply_counts: dict[int, int] = {}
_pdn_ok: set[int] = set()


def replies_used(user_id: int) -> int:
    """How many demo replies the user has already received."""
    return _reply_counts.get(user_id, 0)


def demo_limit_reached(user_id: int) -> bool:
    """True when the user spent the whole demo quota."""
    return replies_used(user_id) >= kitchen_settings.kitchen_message_limit


def register_reply(user_id: int) -> int:
    """Count a delivered demo reply and return the new total."""
    total = replies_used(user_id) + 1
    _reply_counts[user_id] = total
    return total


def contact_keyboard() -> InlineKeyboardMarkup:
    """Buttons that turn a spent demo into a lead."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Оставить заявку", url="https://syntora.space/#contact")],
            [InlineKeyboardButton(text="💬 Написать нам", url="https://t.me/syntora_space")],
        ]
    )


def pdn_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Согласен", callback_data="kpdn:yes")],
            [InlineKeyboardButton(text="Отказаться", callback_data="kpdn:no")],
        ]
    )


async def ask_pdn(message: Message) -> None:
    await message.answer(
        "Перед началом работы нужно ваше согласие на обработку персональных данных:\n"
        "https://syntora.space/consent.html\n"
        "Политика: https://syntora.space/privacy.html\n\n"
        "Нажимая «Согласен», вы даёте его. Без согласия бот не продолжит диалог.\n"
        "Реальные заявки удобнее оставить на сайте: https://syntora.space/#contact",
        reply_markup=pdn_keyboard(),
        disable_web_page_preview=True,
    )


async def handle_start(message: Message) -> None:
    """Send branded demo welcome on /start."""
    limit = kitchen_settings.kitchen_message_limit
    if message.from_user is not None and demo_limit_reached(message.from_user.id):
        await message.answer(
            DEMO_LIMIT_REACHED.format(limit=limit),
            parse_mode="HTML",
            reply_markup=contact_keyboard(),
        )
        return
    if message.from_user is None or message.from_user.id not in _pdn_ok:
        await ask_pdn(message)
        return
    await message.answer(DEMO_WELCOME.format(limit=limit), parse_mode="HTML")


async def consent_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    if callback.data == "kpdn:no":
        _pdn_ok.discard(callback.from_user.id)
        await callback.message.answer(
            "Без согласия бот не продолжает диалог. Форма на сайте: https://syntora.space/#contact",
            disable_web_page_preview=True,
        )
        return
    _pdn_ok.add(callback.from_user.id)
    await callback.message.answer(
        DEMO_WELCOME.format(limit=kitchen_settings.kitchen_message_limit),
        parse_mode="HTML",
    )


async def handle_message(message: Message) -> None:
    """Forward user text to Gemini; CRM leads are saved via function calling."""
    if message.from_user is None:
        return

    user_text = message.text or ""
    user_id = message.from_user.id
    limit = kitchen_settings.kitchen_message_limit

    if user_id not in _pdn_ok:
        await ask_pdn(message)
        return

    if demo_limit_reached(user_id):
        logger.info("Kitchen AI demo limit hit for user_id=%s", user_id)
        await message.answer(
            DEMO_LIMIT_REACHED.format(limit=limit),
            parse_mode="HTML",
            reply_markup=contact_keyboard(),
        )
        return

    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        reply = await get_ai_response(user_id=user_id, user_text=user_text)
        await message.answer(reply)
        if register_reply(user_id) >= limit:
            await message.answer(
                DEMO_LIMIT_NOTICE.format(limit=limit),
                parse_mode="HTML",
                reply_markup=contact_keyboard(),
            )
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
    dp.callback_query.register(consent_callback, F.data.in_({"kpdn:yes", "kpdn:no"}))
    # Exclude slash-commands; bare Command() raises in current aiogram.
    dp.message.register(handle_message, F.text, ~F.text.startswith("/"))
    return dp
