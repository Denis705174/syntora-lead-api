# Переустановка Telegram webhooks на рабочий Render-сервис
# Запуск из папки lead-api (нужны токены в .env файлах):
#   python scripts/set_webhooks.py

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

BASE = "https://syntora-lead-api-1.onrender.com"
LEAD_ENV = Path(__file__).resolve().parents[1] / ".env"
KITCHEN_ENV = Path(__file__).resolve().parents[2] / "kitchen-ai-bot" / ".env"


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def api(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode())


def main() -> None:
    lead = load_env(LEAD_ENV)
    kit = load_env(KITCHEN_ENV)
    lead_token = lead.get("BOT_TOKEN", "")
    kit_token = kit.get("BOT_TOKEN", "") or kit.get("KITCHEN_BOT_TOKEN", "")

    if not lead_token:
        raise SystemExit(f"Missing BOT_TOKEN in {LEAD_ENV}")
    if not kit_token:
        raise SystemExit(f"Missing BOT_TOKEN in {KITCHEN_ENV}")

    pairs = [
        ("MegaPromptBot", lead_token, f"{BASE}/telegram/webhook"),
        ("iogram3x_bot", kit_token, f"{BASE}/telegram/kitchen-webhook"),
    ]
    for name, token, webhook in pairs:
        result = api(
            token,
            "setWebhook",
            {
                "url": webhook,
                "drop_pending_updates": False,
                "allowed_updates": ["message", "callback_query"],
            },
        )
        info = api(token, "getWebhookInfo")["result"]
        print(f"{name}: set={result.get('ok')} url={info.get('url')} err={info.get('last_error_message')}")


if __name__ == "__main__":
    main()
