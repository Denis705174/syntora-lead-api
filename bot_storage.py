"""SQLite storage for leads collected in @MegaPromptBot."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def init_bot_db(db_path: str) -> None:
    """Create bot leads table if missing."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                service TEXT NOT NULL,
                message TEXT,
                user_id INTEGER NOT NULL,
                username TEXT
            )
            """
        )


def save_bot_lead(
    db_path: str,
    *,
    name: str,
    phone: str,
    service: str,
    message: str | None,
    user_id: int,
    username: str | None,
) -> int:
    """Persist a lead from the Telegram bot dialog."""
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO bot_leads (created_at, name, phone, service, message, user_id, username)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (created_at, name, phone, service, message or "", user_id, username or ""),
        )
        return int(cursor.lastrowid)
