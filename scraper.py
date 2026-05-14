"""
Naver blog scraper.

For a given search query, extract the top 3 organic (non-ad) blog posts from
the Naver blog tab and save each post's title, body, image count, and post date
as `{rank}.json` directly under the keyword directory.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

KST = timezone(timedelta(hours=9))

BLOG_URL_RE = re.compile(r"^https://blog\.naver\.com/([a-zA-Z0-9_-]+)/(\d+)")
# Matches strings like "2026. 3. 30. 8:52" or "2026. 3. 30."
DATE_RE = re.compile(
    r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(?:(\d{1,2}):(\d{2}))?"
)


@dataclass
class BlogRef:
    rank: int
    url: str
    blog_id: str
    log_no: str
    title: str
    body: str
    image_count: int
    posted_at: Optional[str]
    collected_at: str


def parse_publish_date(raw: str) -> Optional[str]:
    """Naver shows '2026. 3. 30. 8:52' (KST). Return ISO string or None."""
    if not raw:
        return None
    m = DATE_RE.search(raw)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h = int(m.group(4)) if m.group(4) else 0
    mi = int(m.group(5)) if m.group(5) else 0
    try:
        return datetime(y, mo, d, h, mi, tzinfo=KST).isoformat(timespec="seconds")
    except ValueError:
        return None


async def _new_page(pw) -> tuple:
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(
        user_agent=UA,
        viewport={"width": 1440, "height": 900},
        locale="ko-KR",
    )
    page = await ctx.new_page()
    return browser, ctx, page


async def _human_wait(page: Page, lo: float = 1.5, hi: float = 3.5):
    await page.wait_for_timeout(int(random.uniform(lo, hi) * 1000))


async def find_top_blog_posts(page: Page, query: str, want: int = 3) -> list[tuple[str, str, str]]:
    """Return list of (url, blog_id, log_no) in rank order, ads excluded."""
    search_url = (
        f"https://search.naver.com/search.naver"
        f"?ssc=tab.blog.all&sm=tab_jum&query={query}"
    )
    print(f"[scraper] search: {search_url}")
    await page.goto(search_url, wait_until="networkidle", timeout=30000)
    await _human_wait(page)

    all_links = await page.locator("a[href^='https://blog.naver.com/']").evaluate_all(
        """els => els.map(a => {
            let host = a.parentElement;
            for (let i = 0; i < 12 && host; i++) {
                const cls = (host.className || "").toString();
                if (/layout|bx/.test(cls)) break;
                host = host.parentElement;
            }
            const text = host ? host.innerText.slice(0, 300) : "";
            return { href: a.href, contextText: text };
        })"""
    )

    selected = []
    seen_urls = set()
    for item in all_links:
        href = item["href"]
        m = BLOG_URL_RE.match(href)
        if not m:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        if "광고" in item.get("contextText", ""):
            print(f"[scraper] skip (ad): {href}")
            continue
        selected.append((href, m.group(1), m.group(2)))
        if len(selected) >= want:
            break

    print(f"[scraper] selected {len(selected)} non-ad posts")
    return selected


async def scrape_post(page: Page, blog_id: str, log_no: str) -> tuple[str, str, int, Optional[str]]:
    """Return (title, body, image_count, posted_at_iso) for a single naver blog post."""
    url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
    print(f"[scraper] post: {url}")
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await _human_wait(page)

    title = ""
    if await page.locator(".se-title-text").count() > 0:
        title = (await page.locator(".se-title-text").first.inner_text()).strip()
    elif await page.locator(".pcol1").count() > 0:
        title = (await page.locator(".pcol1").first.inner_text()).strip()

    body = ""
    if await page.locator(".se-main-container").count() > 0:
        body = (await page.locator(".se-main-container").first.inner_text()).strip()
    elif await page.locator("#postViewArea").count() > 0:
        body = (await page.locator("#postViewArea").first.inner_text()).strip()

    img_count = 0
    if await page.locator(".se-main-container img").count() > 0:
        img_count = await page.locator(".se-main-container img").count()
    elif await page.locator("#postViewArea img").count() > 0:
        img_count = await page.locator("#postViewArea img").count()

    posted_at: Optional[str] = None
    if await page.locator(".se_publishDate").count() > 0:
        raw = await page.locator(".se_publishDate").first.inner_text()
        posted_at = parse_publish_date(raw)

    return title, body, img_count, posted_at


async def run(query: str, output_root: Path, want: int = 3) -> Path:
    """Scrape and store. Returns the keyword output folder."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    out_dir = output_root / today / query
    out_dir.mkdir(parents=True, exist_ok=True)

    saved_refs: list[BlogRef] = []
    async with async_playwright() as pw:
        browser, ctx, page = await _new_page(pw)
        try:
            posts = await find_top_blog_posts(page, query, want=want)
            if len(posts) < want:
                print(f"[scraper] WARN: only {len(posts)} non-ad posts found (wanted {want})")

            for rank, (url, blog_id, log_no) in enumerate(posts, start=1):
                title, body, img_count, posted_at = await scrape_post(page, blog_id, log_no)
                ref = BlogRef(
                    rank=rank,
                    url=url,
                    blog_id=blog_id,
                    log_no=log_no,
                    title=title,
                    body=body,
                    image_count=img_count,
                    posted_at=posted_at,
                    collected_at=datetime.now(KST).isoformat(timespec="seconds"),
                )
                (out_dir / f"{rank}.json").write_text(
                    json.dumps(asdict(ref), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                saved_refs.append(ref)
                print(
                    f"[scraper] saved {rank}.json: title={title[:30]!r} "
                    f"body_chars={len(body)} images={img_count} posted={posted_at}"
                )
        finally:
            await browser.close()

    _push_to_sheets(query, today, saved_refs)
    return out_dir


def _push_to_sheets(query: str, today: str, refs: list[BlogRef]):
    if not refs:
        return
    try:
        from sheets_client import SheetsClient
        sc = SheetsClient()
        if not sc.enabled:
            return
        rows = [{
            "collected_at": r.collected_at,
            "type": "blog",
            "keyword": query,
            "rank": r.rank,
            "title": r.title,
            "url": r.url,
            "writer": r.blog_id,
            "posted_at": r.posted_at or "",
            "image_count": r.image_count,
            "comment_count": "",
            "accessible": "TRUE",
            "local_path": f"{today}/{query}/{r.rank}.json",
        } for r in refs]
        sc.append_results(rows)
        print(f"[scraper] sheets: appended {len(rows)} rows")
    except Exception as e:
        print(f"[scraper] sheets push failed: {e}")


if __name__ == "__main__":
    import sys
    query = sys.argv[1] if len(sys.argv) > 1 else "기업 홈페이지 제작"
    out_root = Path(__file__).parent / "output"
    asyncio.run(run(query, out_root))
