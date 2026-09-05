"""List YouGile projects / boards / columns to find YOUGILE_COLUMN_ID.

Usage:
  set YOUGILE_API_KEY=...
  python scripts/list_yougile.py
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.environ.get("YOUGILE_API_BASE", "https://yougile.com/api-v2").rstrip("/")


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
        projects = client.get(f"{BASE}/projects").json()
        print("=== PROJECTS ===")
        print(json.dumps(projects, ensure_ascii=False, indent=2)[:4000])

        content = projects.get("content") if isinstance(projects, dict) else projects
        if not isinstance(content, list):
            content = []

        for project in content:
            project_id = project.get("id")
            title = project.get("title")
            print(f"\n--- Boards for project {title} ({project_id}) ---")
            boards = client.get(f"{BASE}/boards", params={"projectId": project_id}).json()
            board_list = boards.get("content") if isinstance(boards, dict) else boards
            if not isinstance(board_list, list):
                board_list = []
            for board in board_list:
                board_id = board.get("id")
                print(f"  board: {board.get('title')} id={board_id}")
                columns = client.get(f"{BASE}/columns", params={"boardId": board_id}).json()
                col_list = columns.get("content") if isinstance(columns, dict) else columns
                if not isinstance(col_list, list):
                    col_list = []
                for col in col_list:
                    print(f"    COLUMN: {col.get('title')}  YOUGILE_COLUMN_ID={col.get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
