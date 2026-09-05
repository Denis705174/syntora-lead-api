"""Gemini chat + CRM function calling for Kitchen AI."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Final

from openai import AsyncOpenAI, BadRequestError
from openai.types.chat import ChatCompletion

from kitchen.config import kitchen_settings
from kitchen.sheets import save_lead_to_sheet
from notifications import notify_kitchen_lead
from yougile import create_kitchen_lead_task

logger = logging.getLogger(__name__)

SYSTEM_PROMPT: Final[str] = (
    "Ты — профессиональный, уверенный в себе менеджер по продажам кухонь на заказ. "
    "Твоя задача — квалифицировать клиента (аккуратно узнать размеры помещения, "
    "примерный бюджет, сроки) и закрыть его на бесплатный выезд замерщика или "
    "создание 3D-проекта. Отвечай кратко (1-3 предложения), задавай наводящие "
    "вопросы, отрабатывай возражения. Никакой воды. Строго отказывайся отвечать "
    "на вопросы, не связанные с мебелью.\n\n"
    "Когда клиент оставляет номер телефона или соглашается на расчёт/замер и "
    "даёт контакт, обязательно вызови функцию save_lead. Извлеки из контекста "
    "диалога телефон, примерный бюджет и размеры кухни. Если бюджет или размеры "
    "ещё не названы — передай 'не указан'. Не выдумывай номер телефона."
)

SAVE_LEAD_TOOL: Final[dict[str, Any]] = {
    "type": "function",
    "function": {
        "name": "save_lead",
        "description": (
            "Сохраняет лид в CRM (YouGile), когда клиент оставил телефон "
            "или согласился на расчёт/выезд замерщика и передал контакт."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Номер телефона клиента"},
                "budget": {
                    "type": "string",
                    "description": "Примерный бюджет клиента или 'не указан'",
                },
                "dimensions": {
                    "type": "string",
                    "description": "Размеры кухни/помещения или 'не указан'",
                },
            },
            "required": ["phone", "budget", "dimensions"],
        },
    },
}

LEAD_SAVED_FALLBACK: Final[str] = (
    "Отлично, ваши данные сохранены! Менеджер свяжется с вами для "
    "бесплатного замера или 3D-проекта."
)

MAX_HISTORY_MESSAGES: Final[int] = 12

_client: AsyncOpenAI | None = None
_conversation_history: dict[int, list[dict[str, Any]]] = defaultdict(list)


def _get_client() -> AsyncOpenAI:
    """Return a lazily initialized AsyncOpenAI client pointed at Gemini."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=kitchen_settings.openai_api_key,
            base_url=kitchen_settings.openai_base_url,
        )
    return _client


def _trim_history(user_id: int) -> None:
    """Keep only the last N user/assistant text messages for a user."""
    history = _conversation_history[user_id]
    if len(history) > MAX_HISTORY_MESSAGES:
        _conversation_history[user_id] = history[-MAX_HISTORY_MESSAGES:]


def _assistant_message_from_raw(raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Build an assistant message dict from raw API JSON."""
    choice = (raw_payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    payload: dict[str, Any] = {
        "role": message.get("role", "assistant"),
        "content": message.get("content"),
    }
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        serialized_calls: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            item: dict[str, Any] = {
                "id": tool_call.get("id"),
                "type": tool_call.get("type", "function"),
                "function": {
                    "name": (tool_call.get("function") or {}).get("name"),
                    "arguments": (tool_call.get("function") or {}).get("arguments", "{}"),
                },
            }
            extra_content = tool_call.get("extra_content")
            if extra_content:
                item["extra_content"] = extra_content
            serialized_calls.append(item)
        payload["tool_calls"] = serialized_calls
    return payload


async def _create_completion(
    client: AsyncOpenAI,
    messages: list[dict[str, Any]],
    *,
    tool_choice: str,
) -> tuple[ChatCompletion, dict[str, Any]]:
    """Create a chat completion and return both parsed and raw JSON payloads."""
    raw_response = await client.chat.completions.with_raw_response.create(
        model=kitchen_settings.openai_model,
        messages=messages,
        tools=[SAVE_LEAD_TOOL],
        tool_choice=tool_choice,
    )
    completion = raw_response.parse()
    raw_payload = raw_response.http_response.json()
    if not isinstance(raw_payload, dict):
        raise RuntimeError("Gemini returned a non-object JSON payload")
    return completion, raw_payload


async def _handle_save_lead(arguments_json: str) -> str:
    """Execute save_lead tool and return a JSON status for the model."""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return json.dumps({"ok": False, "error": "invalid_json"}, ensure_ascii=False)

    phone = str(args.get("phone", "")).strip()
    budget = str(args.get("budget", "не указан")).strip() or "не указан"
    dimensions = str(args.get("dimensions", "не указан")).strip() or "не указан"

    if not phone:
        return json.dumps({"ok": False, "error": "phone_required"}, ensure_ascii=False)

    # Primary CRM: YouGile. Sheets optional and never blocks the chat.
    yougile_id = None
    try:
        yougile_id = await create_kitchen_lead_task(
            phone=phone, budget=budget, dimensions=dimensions
        )
    except Exception:
        logger.exception("YouGile kitchen lead failed")

    try:
        await notify_kitchen_lead(phone=phone, budget=budget, dimensions=dimensions)
    except Exception:
        logger.exception("Telegram kitchen lead notify failed")

    sheets_ok = False
    if kitchen_settings.spreadsheet_id.strip() and kitchen_settings.google_creds_json.strip():
        try:
            await save_lead_to_sheet(phone=phone, budget=budget, dimensions=dimensions)
            sheets_ok = True
        except Exception:
            logger.exception("Google Sheets kitchen lead failed (non-fatal)")

    logger.info(
        "Kitchen lead saved: phone=%s yougile=%s sheets=%s",
        phone,
        yougile_id,
        sheets_ok,
    )
    return json.dumps(
        {
            "ok": True,
            "phone": phone,
            "budget": budget,
            "dimensions": dimensions,
            "yougile": bool(yougile_id),
            "sheets": sheets_ok,
        },
        ensure_ascii=False,
    )


async def get_ai_response(user_id: int, user_text: str) -> str:
    """Send user text to Gemini and return the model reply."""
    client = _get_client()
    history = _conversation_history[user_id]

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_text},
    ]

    response, raw_payload = await _create_completion(client, messages, tool_choice="auto")

    if not response.choices:
        raise RuntimeError("Gemini returned an empty choices list")

    assistant_message = response.choices[0].message
    lead_saved = False

    if assistant_message.tool_calls:
        messages.append(_assistant_message_from_raw(raw_payload))

        for tool_call in assistant_message.tool_calls:
            function = tool_call.function
            if function is None or function.name != "save_lead":
                tool_result = json.dumps(
                    {"ok": False, "error": f"unknown_tool:{getattr(function, 'name', None)}"},
                    ensure_ascii=False,
                )
            else:
                tool_result = await _handle_save_lead(function.arguments or "{}")
                try:
                    if json.loads(tool_result).get("ok"):
                        lead_saved = True
                except json.JSONDecodeError:
                    pass

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )

        try:
            follow_up, _ = await _create_completion(client, messages, tool_choice="none")
            if not follow_up.choices or follow_up.choices[0].message is None:
                raise RuntimeError("Gemini follow-up returned empty choices")
            assistant_text = (follow_up.choices[0].message.content or "").strip()
        except (BadRequestError, RuntimeError) as exc:
            logger.warning("Follow-up after tool call failed (%s); using fallback", exc)
            assistant_text = LEAD_SAVED_FALLBACK if lead_saved else ""
    else:
        assistant_text = (assistant_message.content or "").strip()

    if not assistant_text:
        raise RuntimeError("Gemini returned an empty response")

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_text})
    _trim_history(user_id)

    return assistant_text
