"""Smoke-check the Kitchen AI demo limit without touching Telegram or Gemini.

Usage:
  python scripts/check_kitchen_limit.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kitchen import handlers  # noqa: E402
from kitchen.config import kitchen_settings  # noqa: E402


class FakeBot:
    async def send_chat_action(self, **_: Any) -> None:
        return None


class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeChat:
    id = 1


class FakeMessage:
    """Minimal stand-in for aiogram Message capturing outgoing answers."""

    def __init__(self, text: str, user_id: int, sent: list[dict[str, Any]]) -> None:
        self.text = text
        self.from_user = FakeUser(user_id)
        self.chat = FakeChat()
        self.bot = FakeBot()
        self._sent = sent

    async def answer(self, text: str, **kwargs: Any) -> None:
        self._sent.append({"text": text, "has_buttons": kwargs.get("reply_markup") is not None})


async def main() -> int:
    limit = kitchen_settings.kitchen_message_limit
    user_id = 424242
    sent: list[dict[str, Any]] = []

    async def fake_ai(*, user_id: int, user_text: str) -> str:
        return f"ответ ИИ на «{user_text}»"

    handlers.get_ai_response = fake_ai  # type: ignore[assignment]

    for i in range(1, limit + 4):
        await handlers.handle_message(FakeMessage(f"сообщение {i}", user_id, sent))

    ai_replies = [m for m in sent if m["text"].startswith("ответ ИИ")]
    cta = [m for m in sent if "демо" in m["text"].lower()]

    print(f"limit={limit}")
    print(f"ai replies delivered: {len(ai_replies)} (expected {limit})")
    print(f"cta messages: {len(cta)}")
    print("--- last 4 messages ---")
    for m in sent[-4:]:
        print(f"[buttons={m['has_buttons']}] {m['text'][:90]}")

    await handlers.handle_start(FakeMessage("/start", user_id, sent))
    print("--- /start after limit ---")
    print(f"[buttons={sent[-1]['has_buttons']}] {sent[-1]['text'][:90]}")

    fresh: list[dict[str, Any]] = []
    await handlers.handle_start(FakeMessage("/start", 999999, fresh))
    print("--- /start for a new user ---")
    print(f"[buttons={fresh[-1]['has_buttons']}] {fresh[-1]['text'][:90]}")

    ok = len(ai_replies) == limit and len(cta) >= 1
    print("\nRESULT:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
