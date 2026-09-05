"""Aiogram handlers for @MegaPromptBot (Syntora lead demo)."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from bot_storage import save_bot_lead
from config import settings
from notifications import notify_bot_lead
from yougile import create_bot_lead_task

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 <b>Syntora Space</b> — студия ИИ-менеджеров и AI-лендингов.\n\n"
    "Это <b>демо</b> бота сбора заявок: вы заполняете короткую анкету — "
    "заявка мгновенно приходит менеджеру в Telegram.\n\n"
    "Так же работает форма на сайте Syntora Space.\n\n"
    "Нажмите «📝 Оставить заявку»."
)

ABOUT = (
    "<b>Syntora Space</b> внедряет ИИ-менеджеров и собирает AI-лендинги.\n\n"
    "• AI-сотрудник в Telegram — от 45 000 ₽\n"
    "• AI-лендинг + автоматизация — от 80 000 ₽\n"
    "• Локальное хранение заявки + алерт в Telegram\n\n"
    "Напишите «📝 Оставить заявку», чтобы протестировать контур."
)


class LeadForm(StatesGroup):
    """Multi-step lead collection inside the bot."""

    name = State()
    phone = State()
    service = State()
    message = State()


def main_keyboard() -> ReplyKeyboardMarkup:
    """Persistent menu for the Syntora demo bot."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Оставить заявку")],
            [KeyboardButton(text="🌐 Сайт Syntora Space"), KeyboardButton(text="ℹ️ Услуги")],
        ],
        resize_keyboard=True,
    )


def service_keyboard() -> InlineKeyboardMarkup:
    """Inline choices for the requested service."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Разбор воронки", callback_data="svc:consult")],
            [InlineKeyboardButton(text="AI-сотрудник", callback_data="svc:ai-employee")],
            [InlineKeyboardButton(text="AI-лендинг", callback_data="svc:landing")],
            [InlineKeyboardButton(text="Другое", callback_data="svc:other")],
        ]
    )


async def cmd_start(message: Message, state: FSMContext) -> None:
    """Show Syntora welcome and main menu."""
    await state.clear()
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=main_keyboard())


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Cancel the in-progress lead form."""
    await state.clear()
    await message.answer(
        "❌ Заявка отменена.\n\nНажмите «📝 Оставить заявку», когда будете готовы.",
        reply_markup=main_keyboard(),
    )


async def start_lead(message: Message, state: FSMContext) -> None:
    """Begin the lead questionnaire."""
    await state.set_state(LeadForm.name)
    await message.answer(
        "📝 <b>Заявка в Syntora Space</b>\n\nШаг 1 из 4: как вас зовут?",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


async def show_about(message: Message) -> None:
    """Send pricing and services summary."""
    await message.answer(ABOUT, parse_mode="HTML", disable_web_page_preview=False)


async def show_site(message: Message) -> None:
    """Link to the main website."""
    await message.answer(
        "🌐 Сайт Syntora Space пока на syntora.space "
        "(новый домен — после покупки).\n\n"
        "Форма на сайте работает так же — заявка сразу в Telegram.",
        disable_web_page_preview=True,
    )


async def form_name(message: Message, state: FSMContext) -> None:
    """Save name and ask for phone."""
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Укажите имя хотя бы из 2 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(LeadForm.phone)
    await message.answer(f"Отлично, {name}! ✍️\n\nШаг 2 из 4: телефон или @username в Telegram.")


async def form_phone(message: Message, state: FSMContext) -> None:
    """Save phone and ask for service."""
    phone = (message.text or "").strip()
    if len(phone) < 3:
        await message.answer("Укажите телефон или @username.")
        return
    await state.update_data(phone=phone)
    await state.set_state(LeadForm.service)
    await message.answer("Шаг 3 из 4: что вас интересует?", reply_markup=service_keyboard())


async def form_service_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Save selected service from inline keyboard."""
    if callback.data is None or not callback.data.startswith("svc:"):
        return
    service = callback.data.removeprefix("svc:")
    await state.update_data(service=service)
    await state.set_state(LeadForm.message)
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Шаг 4 из 4: кратко опишите задачу\n(или отправьте «—», если пока нечего добавить)."
        )


async def form_message(message: Message, state: FSMContext) -> None:
    """Finalize lead, save locally, and notify operator."""
    if message.from_user is None:
        return

    note = (message.text or "").strip()
    if note in {"—", "-"}:
        note = ""

    data = await state.get_data()
    name = str(data.get("name", ""))
    phone = str(data.get("phone", ""))
    service = str(data.get("service", "other"))

    lead_id = save_bot_lead(
        settings.bot_db_path,
        name=name,
        phone=phone,
        service=service,
        message=note or None,
        user_id=message.from_user.id,
        username=message.from_user.username,
    )

    try:
        await notify_bot_lead(
            lead_id=lead_id,
            name=name,
            phone=phone,
            service=service,
            message=note or None,
            user_id=message.from_user.id,
            username=message.from_user.username,
        )
    except Exception:
        logger.exception("Failed to notify operator for lead_id=%s", lead_id)

    try:
        await create_bot_lead_task(
            lead_id=lead_id,
            name=name,
            phone=phone,
            service=service,
            message=note or None,
            username=message.from_user.username,
        )
    except Exception:
        logger.exception("YouGile sync failed for bot lead_id=%s", lead_id)

    await state.clear()
    await message.answer(
        "✅ <b>Заявка отправлена!</b>\n\n"
        f"Имя: {name}\n"
        f"Контакт: {phone}\n\n"
        "Менеджер Syntora Space свяжется с вами в ближайшее время.\n"
        "Именно так работает контур, который мы настраиваем клиентам.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def fallback_text(message: Message, state: FSMContext) -> None:
    """Guide users who type outside the active form."""
    current = await state.get_state()
    if current is not None:
        await message.answer("Используйте /cancel для отмены или ответьте на текущий вопрос.")
        return
    await message.answer(
        "Выберите действие на клавиатуре ниже 👇",
        reply_markup=main_keyboard(),
    )


def build_dispatcher(storage: BaseStorage | None = None) -> Dispatcher:
    """Register all bot handlers."""
    dp = Dispatcher(storage=storage or MemoryStorage())

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_cancel, Command("cancel"))
    dp.message.register(start_lead, F.text == "📝 Оставить заявку")
    dp.message.register(show_about, F.text == "ℹ️ Услуги")
    dp.message.register(show_site, F.text == "🌐 Сайт Syntora Space")
    dp.message.register(form_name, StateFilter(LeadForm.name), F.text)
    dp.message.register(form_phone, StateFilter(LeadForm.phone), F.text)
    dp.message.register(form_message, StateFilter(LeadForm.message), F.text)
    dp.callback_query.register(form_service_callback, StateFilter(LeadForm.service))
    dp.message.register(fallback_text, F.text)

    return dp
