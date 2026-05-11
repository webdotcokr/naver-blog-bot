"""
Regenerate status.md from keywords.csv.

Usage:
    python status.py
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
KEYWORDS_CSV = ROOT / "keywords.csv"
STATUS_MD = ROOT / "status.md"


def load_rows() -> list[dict]:
    with KEYWORDS_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def is_processed(row: dict) -> bool:
    """A row counts as processed only if processed_at is a non-empty success marker."""
    val = (row.get("processed_at") or "").strip()
    return bool(val) and "FAILED" not in val


def is_failed(row: dict) -> bool:
    val = (row.get("processed_at") or "").strip()
    return "FAILED" in val


def render(rows: list[dict]) -> str:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    total = len(rows)
    done = [r for r in rows if is_processed(r)]
    failed = [r for r in rows if is_failed(r)]
    pending = [r for r in rows if not is_processed(r) and not is_failed(r)]

    today_kst = datetime.now(KST).strftime("%Y-%m-%d")
    today_done = [r for r in done if r["processed_at"].startswith(today_kst)]

    # Group history by date
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in done:
        date = r["processed_at"][:10]
        by_date[date].append(r)

    lines: list[str] = []
    lines.append("# 진행 상태")
    lines.append("")
    lines.append(f"> 마지막 갱신: {now}")
    lines.append("")

    # Summary
    pct = (len(done) / total * 100) if total else 0
    lines.append("## 요약")
    lines.append("")
    lines.append(f"- 총 키워드: **{total}개**")
    lines.append(f"- 처리 완료: **{len(done)}개** ({pct:.0f}%)")
    if failed:
        lines.append(f"- 실패: **{len(failed)}개** (재시도하려면 keywords.csv에서 processed_at 비우기)")
    lines.append(f"- 남은 키워드: **{len(pending)}개**")
    if pending:
        # Rough estimate: 3/day, weekdays only ≈ 15/week
        days_needed = -(-len(pending) // 3)
        lines.append(f"- 평일 3건 기준 예상 완료: 약 **{days_needed}영업일**")
    lines.append("")

    # Today's runs
    if today_done:
        lines.append(f"## 오늘 처리 ({today_kst})")
        lines.append("")
        lines.append("| 키워드 | 처리 시각 | 결과 |")
        lines.append("|---|---|---|")
        for r in today_done:
            ts = r["processed_at"][11:19] if len(r["processed_at"]) > 11 else r["processed_at"]
            lines.append(f"| {r['keyword']} | {ts} | `{r['result_path']}` |")
        lines.append("")

    # Pending preview
    if pending:
        lines.append("## 다음 처리 예정 (앞 10개)")
        lines.append("")
        for i, r in enumerate(pending[:10], start=1):
            note = f" — {r['note']}" if (r.get("note") or "").strip() else ""
            lines.append(f"{i}. {r['keyword']}{note}")
        lines.append("")

    # Full history
    if by_date:
        lines.append("## 처리 이력")
        lines.append("")
        lines.append("| 날짜 | 키워드 | 결과 경로 |")
        lines.append("|---|---|---|")
        for date in sorted(by_date.keys(), reverse=True):
            for r in by_date[date]:
                lines.append(f"| {date} | {r['keyword']} | `{r['result_path']}` |")
        lines.append("")

    # Failed list
    if failed:
        lines.append("## 실패 키워드")
        lines.append("")
        lines.append("| 키워드 | 마지막 시도 |")
        lines.append("|---|---|")
        for r in failed:
            lines.append(f"| {r['keyword']} | {r['processed_at']} |")
        lines.append("")

    return "\n".join(lines)


def regenerate():
    rows = load_rows()
    md = render(rows)
    STATUS_MD.write_text(md, encoding="utf-8")
    return STATUS_MD


if __name__ == "__main__":
    out = regenerate()
    print(f"[status] wrote {out}")
