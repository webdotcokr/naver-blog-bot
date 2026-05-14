"""
Daily batch job.

Process the next N unprocessed keywords (top-down).
- Source: Google Sheets `keywords` tab if GOOGLE_SHEET_ID is set in .env,
  otherwise keywords.csv.
- For each keyword runs BOTH blog and cafe scrapers (failures isolated).
- Updates processed_at + result_path on success.
- Marks processed_at as 'FAILED <iso>' if neither scraper produced output.
- Regenerates status.md at the end (CSV mode only).

Designed to be called by cron. Logs to stdout/stderr.
"""
from __future__ import annotations

import asyncio
import csv
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import scraper
import cafe_scraper
import status as status_mod

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
KEYWORDS_CSV = ROOT / "keywords.csv"
OUTPUT_ROOT = ROOT / "output"
FIELDS = ["keyword", "added_at", "note", "processed_at", "result_path"]

DEFAULT_BATCH = 3


def needs_processing(row: dict) -> bool:
    val = (row.get("processed_at") or "").strip()
    return not val


def load_rows() -> list[dict]:
    with KEYWORDS_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list[dict]):
    with KEYWORDS_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (r.get(k) or "") for k in FIELDS})


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def get_pending(batch: int):
    """Return (source, pending_list, sheets_client_or_none).

    source ∈ {'sheets', 'csv'}.
    pending_list items: {'keyword', 'row' (sheets only), 'added_at', 'note'}.
    """
    try:
        from sheets_client import SheetsClient
        sc = SheetsClient()
        if sc.enabled:
            pending = sc.read_pending_keywords(limit=batch)
            return ("sheets", pending, sc)
    except Exception as e:
        print(f"[daily] sheets keyword read failed, falling back to CSV: {e}",
              file=sys.stderr)

    rows = load_rows()
    targets = [r for r in rows if needs_processing(r)][:batch]
    pending = [{
        "keyword": r["keyword"],
        "added_at": r.get("added_at", ""),
        "note": r.get("note", ""),
    } for r in targets]
    return ("csv", pending, None)


def main(batch: int = DEFAULT_BATCH):
    source, pending, sc = get_pending(batch)
    if not pending:
        print("[daily] no pending keywords — nothing to do")
        if source == "csv":
            status_mod.regenerate()
        return

    print(
        f"[daily] source={source}, processing {len(pending)} keyword(s): "
        f"{[p['keyword'] for p in pending]}"
    )

    csv_rows = load_rows() if source == "csv" else None

    for entry in pending:
        kw = entry["keyword"]
        print(f"\n[daily] === {kw} ===")
        paths: list[str] = []

        # blog
        try:
            d = asyncio.run(scraper.run(kw, OUTPUT_ROOT))
            paths.append(_rel(d))
        except Exception as e:
            print(f"[daily] {kw} blog FAILED: {e}", file=sys.stderr)
            traceback.print_exc()

        # cafe
        try:
            d = asyncio.run(cafe_scraper.run(kw, OUTPUT_ROOT))
            paths.append(_rel(d))
        except Exception as e:
            print(f"[daily] {kw} cafe FAILED: {e}", file=sys.stderr)
            traceback.print_exc()

        now = datetime.now(KST).isoformat(timespec="seconds")
        result_path = "; ".join(paths)
        processed_val = now if paths else f"FAILED {now}"

        if source == "sheets":
            try:
                sc.mark_processed(entry["row"], result_path)
            except Exception as e:
                print(f"[daily] sheets mark_processed failed: {e}",
                      file=sys.stderr)
        else:
            for r in csv_rows:
                if r["keyword"] == kw:
                    r["processed_at"] = processed_val
                    r["result_path"] = result_path
                    break
            save_rows(csv_rows)

        print(f"[daily] {kw}: {processed_val} -> {result_path or '(no output)'}")

    if source == "csv":
        status_mod.regenerate()
        print("\n[daily] done — status.md regenerated")
    else:
        print("\n[daily] done — keywords tab updated")


if __name__ == "__main__":
    batch = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BATCH
    main(batch)
