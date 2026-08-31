"""One-time setup: brand @MegaPromptBot for syntora.space."""

from __future__ import annotations

import httpx

from config import settings

BOT_NAME = "Syntora · заявки"
BOT_DESCRIPTION = (
    "Демо Syntora: оставьте заявку в боте — менеджер получит её мгновенно в Telegram. "
    "ИИ-менеджеры и AI-лендинги для вашего бизнеса. syntora.space"
)
BOT_SHORT_DESCRIPTION = "Демо сбора заявок Syntora · syntora.space"
BOT_COMMANDS = [
    {"command": "start", "description": "Главное меню Syntora"},
    {"command": "cancel", "description": "Отменить заявку"},
]


def _post(method: str, payload: dict) -> dict:
    """Call Telegram Bot API method and return JSON body."""
    url = f"https://api.telegram.org/bot{settings.bot_token}/{method}"
    response = httpx.post(url, json=payload, timeout=15.0)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method} failed: {data}")
    return data


def main() -> None:
    """Apply Syntora branding to the site notification bot."""
    me = _post("getMe", {})
    username = me["result"]["username"]
    print(f"Bot: @{username}")

    _post("setMyName", {"name": BOT_NAME})
    _post("setMyDescription", {"description": BOT_DESCRIPTION})
    _post("setMyShortDescription", {"short_description": BOT_SHORT_DESCRIPTION})
    _post("setMyCommands", {"commands": BOT_COMMANDS})
    print("Profile updated for syntora.space")


if __name__ == "__main__":
    main()
