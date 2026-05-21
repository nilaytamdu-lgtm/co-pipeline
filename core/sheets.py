"""Google Sheets connector for the outreach pipeline.

Design notes:
- One cached gspread client per Streamlit session, built from the
  service-account block in secrets.toml.
- `ensure_headers` is non-destructive: it preserves the team's existing
  column order and appends any missing schema columns to the right.
- All reads return pandas DataFrames so the UI can filter/sort easily.
- Append helpers auto-fill Sr No., Date of Entry, 180DC POC (from sector).
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from core.config import OWNERS, sheet_id

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@st.cache_resource(show_spinner=False)
def _client() -> gspread.Client:
    sa = dict(st.secrets.get("google_service_account", {}))
    if not sa.get("client_email"):
        raise RuntimeError(
            "Service account not configured. Fill [google_service_account] in secrets.toml."
        )
    creds = Credentials.from_service_account_info(sa, scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def _spreadsheet() -> gspread.Spreadsheet:
    sid = sheet_id()
    if not sid:
        raise RuntimeError("Sheet ID not configured. Set [sheets].spreadsheet_id in secrets.toml.")
    return _client().open_by_key(sid)


def list_tabs() -> list[str]:
    return [ws.title for ws in _spreadsheet().worksheets()]


def get_worksheet(name: str, create_if_missing: bool = True) -> gspread.Worksheet:
    sh = _spreadsheet()
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        if not create_if_missing:
            raise
        return sh.add_worksheet(title=name, rows=200, cols=30)


def ensure_headers(tab: str, schema: list[str]) -> list[str]:
    """Return the effective header order on the sheet.

    If the tab is empty, writes `schema` as row 1. If the tab already has
    headers, appends any missing schema columns to the right (preserves
    existing order). Returns the post-merge header list.
    """
    ws = get_worksheet(tab)
    existing = ws.row_values(1)
    if not existing:
        ws.update("A1", [schema])
        return list(schema)

    missing = [c for c in schema if c not in existing]
    if missing:
        merged = existing + missing
        ws.update("A1", [merged])
        return merged
    return existing


def read_df(tab: str) -> pd.DataFrame:
    ws = get_worksheet(tab, create_if_missing=False)
    records = ws.get_all_records()
    return pd.DataFrame(records)


def next_sr_no(tab: str) -> int:
    try:
        df = read_df(tab)
    except gspread.WorksheetNotFound:
        return 1
    if df.empty or "Sr No." not in df.columns:
        return 1
    try:
        return int(pd.to_numeric(df["Sr No."], errors="coerce").max() or 0) + 1
    except Exception:
        return len(df) + 1


def _autofill(row: dict, sector: Optional[str] = None) -> dict:
    out = dict(row)
    out.setdefault("Date of Entry", _dt.date.today().isoformat())
    if sector:
        out.setdefault("Organisation Sector", sector)
        out.setdefault("Sector", sector)
        out.setdefault("180DC POC", OWNERS.get(sector, ""))
    return out


def append_row(tab: str, row: dict, schema: list[str], sector: Optional[str] = None) -> int:
    """Append a row aligned to the sheet's actual header order. Returns 1-based row index."""
    headers = ensure_headers(tab, schema)
    enriched = _autofill(row, sector=sector)
    if "Sr No." in headers and "Sr No." not in enriched:
        enriched["Sr No."] = next_sr_no(tab)
    ordered = [str(enriched.get(h, "")) for h in headers]
    ws = get_worksheet(tab)
    ws.append_row(ordered, value_input_option="USER_ENTERED")
    return len(ws.col_values(1))


def update_cells(tab: str, row_index: int, updates: dict) -> None:
    """Update specific cells in a 1-based row index."""
    ws = get_worksheet(tab, create_if_missing=False)
    headers = ws.row_values(1)
    payload = []
    for col_name, val in updates.items():
        if col_name not in headers:
            continue
        col_idx = headers.index(col_name) + 1
        payload.append({"range": gspread.utils.rowcol_to_a1(row_index, col_idx), "values": [[str(val)]]})
    if payload:
        ws.batch_update(payload)


def find_row(tab: str, column: str, value: str) -> Optional[int]:
    """Return 1-based row index for the first row where `column` == `value` (case-insensitive, trimmed)."""
    df = read_df(tab)
    if df.empty or column not in df.columns:
        return None
    target = (value or "").strip().lower()
    matches = df.index[df[column].astype(str).str.strip().str.lower() == target].tolist()
    return matches[0] + 2 if matches else None  # +2 for 1-based + header row


def dedupe_against(tab: str, candidate: dict, keys: tuple[str, ...] = ("POC LinkedIn", "POC Email")) -> Optional[int]:
    """Return existing row index if `candidate` collides on any of the given key columns."""
    for k in keys:
        v = candidate.get(k)
        if v:
            hit = find_row(tab, k, v)
            if hit:
                return hit
    return None


def sheet_status() -> dict:
    """Quick health-check used by Settings page. Never raises."""
    out = {"ok": False, "sheet_title": None, "tabs": [], "error": None}
    try:
        sh = _spreadsheet()
        out["sheet_title"] = sh.title
        out["tabs"] = [ws.title for ws in sh.worksheets()]
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)
    return out
