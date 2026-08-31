"""SQLite persistence for website lead submissions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def init_db(db_path: str) -> None:
    """Create the leads table if it does not exist."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                service TEXT NOT NULL,
                message TEXT,
                ip TEXT
            )
            """
        )


def save_lead(
    db_path: str,
    *,
    name: str,
    phone: str,
    email: str | None,
    service: str,
    message: str | None,
    ip: str | None,
) -> int:
    """Insert a lead row and return its ID."""
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO leads (created_at, name, phone, email, service, message, ip)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (created_at, name, phone, email or "", service, message or "", ip or ""),
        )
        return int(cursor.lastrowid)
