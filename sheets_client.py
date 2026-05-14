"""
Google Sheets client for naver-blog-bot.

Reads keywords from the `keywords` tab, appends results to the `results` tab,
and marks processed rows in `keywords`. Configured via .env:

    GOOGLE_SHEET_ID=<spreadsheet id>
    GOOGLE_CREDENTIALS_PATH=./credentials.json

If GOOGLE_SHEET_ID is missing/empty, the client is disabled and all calls
become no-ops — the rest of the pipeline keeps working with CSV + local JSON.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
    from dotenv import load_dotenv
except ImportError:  # graceful fallback so the rest of the project still imports
    gspread = None
    Credentials = None
    load_dotenv = None

KST = timezone(timedelta(hours=9))
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

RESULTS_HEADER = [
    "collected_at",
    "type",          # "blog" or "cafe"
    "keyword",
    "rank",
    "title",
    "url",
    "writer",
    "posted_at",
    "image_count",
    "comment_count",
    "accessible",
    "local_path",
]


def _project_root() -> Path:
    return Path(__file__).parent


def _load_env():
    if load_dotenv is None:
        return
    env_path = _project_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path)


class SheetsClient:
    def __init__(
        self,
        sheet_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
    ):
        _load_env()
        self.sheet_id = (sheet_id or os.environ.get("GOOGLE_SHEET_ID", "")).strip()
        self.credentials_path = (
            credentials_path
            or os.environ.get("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
        ).strip()
        self._sh = None
        self.enabled = bool(self.sheet_id) and gspread is not None

    # ---------- internal ----------
    def _open(self):
        if self._sh is not None:
            return self._sh
        if not self.enabled:
            return None
        cred_path = Path(self.credentials_path)
        if not cred_path.is_absolute():
            cred_path = _project_root() / cred_path
        if not cred_path.exists():
            raise FileNotFoundError(
                f"credentials file not found: {cred_path}. "
                f"Set GOOGLE_CREDENTIALS_PATH in .env or place credentials.json in the project root."
            )
        creds = Credentials.from_service_account_file(str(cred_path), scopes=SCOPES)
        gc = gspread.authorize(creds)
        self._sh = gc.open_by_key(self.sheet_id)
        return self._sh

    # ---------- keywords tab ----------
    def read_pending_keywords(self, limit: int = 3) -> list[dict]:
        """Return up to `limit` rows where processed_at is empty.

        Each item: {row, keyword, added_at, note}. `row` is the 1-based sheet row index.
        """
        if not self.enabled:
            return []
        sh = self._open()
        ws = sh.worksheet("keywords")
        rows = ws.get_all_values()
        if not rows:
            return []
        header = [h.strip() for h in rows[0]]
        try:
            col_keyword = header.index("keyword")
            col_processed = header.index("processed_at")
        except ValueError:
            raise RuntimeError(
                f"keywords tab missing required columns "
                f"(need 'keyword' and 'processed_at'). got: {header}"
            )
        col_added = header.index("added_at") if "added_at" in header else None
        col_note = header.index("note") if "note" in header else None

        out: list[dict] = []
        for i, row in enumerate(rows[1:], start=2):
            if col_keyword >= len(row):
                continue
            kw = row[col_keyword].strip()
            if not kw:
                continue
            processed = row[col_processed].strip() if col_processed < len(row) else ""
            if processed:
                continue
            out.append({
                "row": i,
                "keyword": kw,
                "added_at": (
                    row[col_added].strip()
                    if col_added is not None and col_added < len(row)
                    else ""
                ),
                "note": (
                    row[col_note].strip()
                    if col_note is not None and col_note < len(row)
                    else ""
                ),
            })
            if len(out) >= limit:
                break
        return out

    def mark_processed(self, row: int, result_path: str = ""):
        if not self.enabled:
            return
        sh = self._open()
        ws = sh.worksheet("keywords")
        header = ws.row_values(1)
        try:
            col_p = header.index("processed_at") + 1
        except ValueError:
            return
        col_r = header.index("result_path") + 1 if "result_path" in header else None
        now = datetime.now(KST).isoformat(timespec="seconds")
        ws.update_cell(row, col_p, now)
        if col_r and result_path:
            ws.update_cell(row, col_r, result_path)

    # ---------- results tab ----------
    def _ensure_results_header(self, ws) -> list[str]:
        rows = ws.get_all_values()
        if not rows or not any(c.strip() for c in rows[0]):
            ws.update(values=[RESULTS_HEADER], range_name="A1")
            return RESULTS_HEADER
        return [h.strip() for h in rows[0]]

    def append_results(self, results: list[dict]):
        """Append rows to the results tab.

        Each dict can contain any subset of RESULTS_HEADER keys; missing keys
        become empty strings. The existing sheet header is respected, so users
        who customized it still get a consistent column ordering.
        """
        if not self.enabled or not results:
            return
        sh = self._open()
        try:
            ws = sh.worksheet("results")
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(
                title="results", rows=1000, cols=len(RESULTS_HEADER)
            )
        header = self._ensure_results_header(ws)
        rows = [[str(r.get(col, "")) for col in header] for r in results]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
