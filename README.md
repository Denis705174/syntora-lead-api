# Lead API + @MegaPromptBot webhook

Принимает:
- POST `/api/lead` — заявки с syntora.space
- POST `/telegram/webhook` — диалог @MegaPromptBot (без polling, без консоли PA)

## Деплой на Fly.io

```bash
flyctl auth login
flyctl launch --no-deploy --copy-config --name syntora-lead-api --region ams
flyctl volumes create syntora_leads_data --region ams --size 1
flyctl secrets set BOT_TOKEN=... CHAT_ID=815564766
flyctl deploy
```

После деплоя webhook: `https://syntora-lead-api.fly.dev/telegram/webhook`

## Переменные

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен @MegaPromptBot |
| `CHAT_ID` | `815564766` — ваш Telegram |
| `WEBHOOK_BASE_URL` | `https://syntora-lead-api.fly.dev` (в fly.toml) |
| `ALLOWED_ORIGINS` | CORS для syntora.space |

## Локально

```bash
pip install -r requirements.txt
# WEBHOOK_BASE_URL оставьте пустым — webhook не регистрируется
uvicorn main:app --reload --port 8080
```
