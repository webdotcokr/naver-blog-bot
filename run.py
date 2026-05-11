"""
Orchestrator. Run with a single keyword.

Usage:
    python run.py "기업 홈페이지 제작"
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import scraper


def main():
    if len(sys.argv) < 2:
        print("usage: run.py <keyword>")
        sys.exit(1)
    query = sys.argv[1]
    out_root = Path(__file__).parent / "output"

    keyword_dir = asyncio.run(scraper.run(query, out_root))
    print(f"\n[done] {keyword_dir}")


if __name__ == "__main__":
    main()
