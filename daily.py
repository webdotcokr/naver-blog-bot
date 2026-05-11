"""
Daily batch job.

Process the next N unprocessed keywords from keywords.csv (top-down).
- Skips keywords that already have processed_at filled (non-FAILED).
- Updates processed_at + result_path on success.
- Marks processed_at as 'FAILED <iso>' on exception (won't auto-retry; user
  must clear the field manually to retry).
- Regenerates status.md at the end.

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
import status as status_mod

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
KEYWORDS_CSV = ROOT / "keywords.csv"
OUTPUT_ROOT = ROOT / "output"
FIELDS = ["keyword", "added_at", "note", "processed_at", "result_path"]

DEFAULT_BATCH = 3


def needs_processing(row: dict) -> bool:
    """A row needs processing only if processed_at is empty (FAILED stays put)."""
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
            # Only keep known fields, fill missing keys with empty
            w.writerow({k: (r.get(k) or "") for k in FIELDS})


async def process_one(keyword: str) -> Path:
    return await scraper.run(keyword, OUTPUT_ROOT)


def main(batch: int = DEFAULT_BATCH):
    rows = load_rows()
    targets = [r for r in rows if needs_processing(r)][:batch]
    if not targets:
        print("[daily] no pending keywords — nothing to do")
        status_mod.regenerate()
        return

    print(f"[daily] processing {len(targets)} keyword(s): {[r['keyword'] for r in targets]}")

    for row in targets:
        kw = row["keyword"]
        started_iso = datetime.now(KST).isoformat(timespec="seconds")
        print(f"\n[daily] --- {kw} (started {started_iso}) ---")
        try:
            keyword_dir = asyncio.run(process_one(kw))
            row["processed_at"] = datetime.now(KST).isoformat(timespec="seconds")
            # Store result_path as repo-relative for portability
            try:
                row["result_path"] = str(keyword_dir.relative_to(ROOT))
            except ValueError:
                row["result_path"] = str(keyword_dir)
            print(f"[daily] OK: {kw} -> {row['result_path']}")
        except Exception as e:
            row["processed_at"] = f"FAILED {datetime.now(KST).isoformat(timespec='seconds')}"
            row["result_path"] = ""
            print(f"[daily] FAILED: {kw}: {e}", file=sys.stderr)
            traceback.print_exc()
        finally:
            # Save after each keyword so crashes mid-batch don't lose progress
            save_rows(rows)

    status_mod.regenerate()
    print("\n[daily] done — status.md regenerated")


if __name__ == "__main__":
    batch = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BATCH
    main(batch)
