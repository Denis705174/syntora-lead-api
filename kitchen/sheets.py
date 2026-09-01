"""Google Sheets CRM for Kitchen AI demo bot."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from functools import lru_cache
from typing import Sequence

import gspread
from google.oauth2.service_account import Credentials

from kitchen.config import kitchen_settings

logger = logging.getLogger(__name__)

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)
_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def extract_spreadsheet_id(value: str) -> str:
    """Extract spreadsheet ID from a full URL or return the raw ID."""
    match = _SPREADSHEET_ID_RE.search(value)
    if match:
        return match.group(1)
    return value.strip()


def _load_credentials() -> Credentials:
    """Load Google service account credentials from env."""
    creds_json = kitchen_settings.google_creds_json.strip()
    if not creds_json:
        raise FileNotFoundError("GOOGLE_CREDS_JSON is not set on Render")
    info = json.loads(creds_json)
    return Credentials.from_service_account_info(info, scopes=list(SCOPES))


@lru_cache(maxsize=1)
def _get_worksheet() -> gspread.Worksheet:
    """Authorize and return the first worksheet of the CRM spreadsheet."""
    credentials = _load_credentials()
    client = gspread.authorize(credentials)
    spreadsheet_id = extract_spreadsheet_id(kitchen_settings.spreadsheet_id)
    spreadsheet = client.open_by_key(spreadsheet_id)
    return spreadsheet.sheet1


def _append_lead_sync(row: Sequence[str]) -> None:
    """Append a lead row to Google Sheets (blocking)."""
    worksheet = _get_worksheet()
    worksheet.append_row(list(row), value_input_option="USER_ENTERED")
    logger.info("Kitchen lead appended to Google Sheets: %s", row)


async def append_lead(row: Sequence[str]) -> None:
    """Append a lead row without blocking the event loop."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _append_lead_sync, row)


async def save_lead_to_sheet(phone: str, budget: str, dimensions: str) -> None:
    """Save a qualified lead with today's date."""
    today = datetime.now().strftime("%d.%m.%Y %H:%M")
    await append_lead([today, phone, budget, dimensions])
