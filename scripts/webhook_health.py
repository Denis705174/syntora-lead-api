"""Print webhook health without dumping secrets."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

env_path = Path(__file__).resolve().parents[1] / ".env"
vals: dict[str, str] = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    vals[key.strip()] = value.strip().strip('"').strip("'")

for name, key in (("lead", "BOT_TOKEN"), ("kitchen", "KITCHEN_BOT_TOKEN")):
    token = vals.get(key, "")
    if not token:
        print(f"{name}: TOKEN_MISSING")
        continue
    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)
    result = data.get("result", {})
    err = (result.get("last_error_message") or "")[:160]
    print(
        f"{name}: ok={data.get('ok')} url={result.get('url')} "
        f"pending={result.get('pending_update_count')} last_error={err!r}"
    )

print("CHAT_ID_SET=", bool(vals.get("CHAT_ID")))
print("YOUGILE_KEY_SET=", bool(vals.get("YOUGILE_API_KEY")))
print("YOUGILE_COL_SET=", bool(vals.get("YOUGILE_COLUMN_ID")))
print("ALLOWED_ORIGINS=", vals.get("ALLOWED_ORIGINS"))
print("SPREADSHEET_SET=", bool(vals.get("SPREADSHEET_ID")))
print("GOOGLE_CREDS_SET=", bool(vals.get("GOOGLE_CREDS_JSON")))
print("OPENAI_KEY_SET=", bool(vals.get("OPENAI_API_KEY")))
