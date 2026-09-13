"""Create the Syntora Space lead board in YouGile and print the target column id.

Idempotent: reuses the project / board / columns when they already exist.

Usage:
  set YOUGILE_API_KEY=...
  python scripts/setup_yougile_board.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

BASE = os.environ.get("YOUGILE_API_BASE", "https://ru.yougile.com/api-v2").rstrip("/")

PROJECT_TITLE = "Syntora Space"
BOARD_TITLE = "Заявки"
COLUMNS = [
    ("Новые заявки", 1),
    ("В работе", 5),
    ("Успешно", 3),
    ("Отказ", 12),
]
TARGET_COLUMN = COLUMNS[0][0]


def _items(payload: Any) -> list[dict[str, Any]]:
    content = payload.get("content") if isinstance(payload, dict) else payload
    return content if isinstance(content, list) else []


def _find(items: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("title", "")).strip().lower() == title.lower():
            return item
    return None


def main() -> int:
    key = (os.environ.get("YOUGILE_API_KEY") or "").strip()
    if not key:
        print("Set YOUGILE_API_KEY first", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    with httpx.Client(timeout=30.0, headers=headers) as client:
        projects = _items(client.get(f"{BASE}/projects").json())
        project = _find(projects, PROJECT_TITLE)
        if project is None:
            created = client.post(f"{BASE}/projects", json={"title": PROJECT_TITLE})
            created.raise_for_status()
            project_id = created.json().get("id")
            print(f"project created: {PROJECT_TITLE} id={project_id}")
        else:
            project_id = project.get("id")
            print(f"project exists: {PROJECT_TITLE} id={project_id}")

        boards = _items(client.get(f"{BASE}/boards", params={"projectId": project_id}).json())
        board = _find(boards, BOARD_TITLE)
        if board is None:
            created = client.post(f"{BASE}/boards", json={"title": BOARD_TITLE, "projectId": project_id})
            created.raise_for_status()
            board_id = created.json().get("id")
            print(f"board created: {BOARD_TITLE} id={board_id}")
        else:
            board_id = board.get("id")
            print(f"board exists: {BOARD_TITLE} id={board_id}")

        existing = _items(client.get(f"{BASE}/columns", params={"boardId": board_id}).json())
        target_id = None
        for title, color in COLUMNS:
            column = _find(existing, title)
            if column is None:
                created = client.post(
                    f"{BASE}/columns",
                    json={"title": title, "boardId": board_id, "color": color},
                )
                created.raise_for_status()
                column_id = created.json().get("id")
                print(f"column created: {title} id={column_id}")
            else:
                column_id = column.get("id")
                print(f"column exists: {title} id={column_id}")
            if title == TARGET_COLUMN:
                target_id = column_id

    print(f"\nYOUGILE_COLUMN_ID={target_id}")
    return 0 if target_id else 1


if __name__ == "__main__":
    raise SystemExit(main())
