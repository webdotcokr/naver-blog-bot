"""
Naver cafe scraper.

For a given query, extract the top 3 organic (non-ad) cafe articles from the
Naver cafe tab. For each article, scrape title, writer, posted_at, body, and
all comments (including replies). Save as `{rank}.json` under the keyword
directory.

Output layout:
  output/YYYY-MM-DD/cafe/{query}/{rank}.json

Private / member-only articles are saved with accessible=False and whatever
metadata could be collected from the search result.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from playwright.async_api import async_playwright, Frame, Page

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
KST = timezone(timedelta(hours=9))

ARTICLE_PAT = re.compile(r"^https?://cafe\.naver\.com/([a-zA-Z0-9_-]+)/(\d+)(?:\?.*)?$")
DATE_RE = re.compile(
    r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*(\d{1,2}):(\d{2}))?"
)


@dataclass
class Comment:
    nickname: str
    content: str
    posted_at: Optional[str]
    is_reply: bool = False


@dataclass
class CafeArticle:
    rank: int
    url: str
    cafe_url_id: str
    article_id: str
    board_name: Optional[str]
    title: str
    writer: str
    body: str
    posted_at: Optional[str]
    comments: list[Comment] = field(default_factory=list)
    accessible: bool = True
    error: Optional[str] = None
    collected_at: str = ""


def parse_date(raw: str) -> Optional[str]:
    """Parse '2026. 3. 30. 8:52' style into ISO KST string. Return None if no match."""
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


async def _new_page(pw):
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(
        user_agent=UA,
        viewport={"width": 1440, "height": 900},
        locale="ko-KR",
    )
    page = await ctx.new_page()
    return browser, ctx, page


async def _human_wait(page: Page, lo: float = 1.0, hi: float = 2.5):
    await page.wait_for_timeout(int(random.uniform(lo, hi) * 1000))


async def find_top_cafe_articles(
    page: Page, query: str, want: int = 3
) -> list[tuple[str, str, str]]:
    """Return list of (url, cafe_url_id, article_id), ads excluded, in rank order."""
    search_url = (
        f"https://search.naver.com/search.naver"
        f"?ssc=tab.cafe.all&query={quote(query)}"
    )
    print(f"[cafe] search: {search_url}")
    await page.goto(search_url, wait_until="networkidle", timeout=30000)
    await _human_wait(page)

    all_links = await page.locator("a[href*='cafe.naver.com']").evaluate_all(
        """els => els.map(a => {
            let host = a.parentElement;
            for (let i = 0; i < 14 && host; i++) {
                const cls = (host.className || '').toString();
                if (/layout|bx|total_wrap/.test(cls)) break;
                host = host.parentElement;
            }
            const txt = host ? host.innerText.slice(0, 300) : '';
            return { href: a.href, ctx: txt };
        })"""
    )

    selected: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in all_links:
        href = item["href"]
        m = ARTICLE_PAT.match(href)
        if not m:
            continue
        key = (m.group(1), m.group(2))
        if key in seen:
            continue
        seen.add(key)
        if "광고" in item.get("ctx", ""):
            print(f"[cafe] skip (ad): cafe={m.group(1)} art={m.group(2)}")
            continue
        selected.append((href, m.group(1), m.group(2)))
        if len(selected) >= want:
            break

    print(f"[cafe] selected {len(selected)} non-ad articles")
    return selected


async def _get_main_frame(page: Page, timeout: float = 15.0) -> Optional[Frame]:
    """Wait until the cafe_main iframe has loaded the article DOM."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for f in page.frames:
            if f.name == "cafe_main" and not f.url.startswith("about:"):
                try:
                    cnt = await f.locator(".article_container, .ArticleTitle").count()
                    if cnt > 0:
                        return f
                except Exception:
                    pass
        await page.wait_for_timeout(500)
    return None


async def _expand_comments(frame: Frame, max_clicks: int = 30):
    """Click 'more' button(s) inside the comment area until they disappear."""
    for _ in range(max_clicks):
        candidates = frame.locator(
            ".CommentBox .button_more, .CommentBox .more_area button, "
            ".CommentBox .more_area a"
        )
        n = await candidates.count()
        clicked = False
        for i in range(n):
            btn = candidates.nth(i)
            try:
                if await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    await frame.wait_for_timeout(700)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            break


async def _scrape_comments(frame: Frame) -> list[Comment]:
    items = frame.locator("li.CommentItem")
    n = await items.count()
    comments: list[Comment] = []
    for i in range(n):
        item = items.nth(i)
        try:
            cls = (await item.get_attribute("class")) or ""
            is_reply = False
            if "Reply" in cls or "reply" in cls:
                is_reply = True
            else:
                # check ancestor for ReplyBox
                try:
                    anc = item.locator(
                        "xpath=ancestor::*[contains(@class, 'ReplyBox')]"
                    )
                    if await anc.count() > 0:
                        is_reply = True
                except Exception:
                    pass

            nick_loc = item.locator(".comment_nickname")
            nickname = (
                (await nick_loc.first.inner_text()).strip()
                if await nick_loc.count() else ""
            )
            text_loc = item.locator(".comment_text_view")
            content = (
                (await text_loc.first.inner_text()).strip()
                if await text_loc.count() else ""
            )
            date_loc = item.locator(".comment_info_date")
            date_raw = (
                (await date_loc.first.inner_text()).strip()
                if await date_loc.count() else ""
            )
            posted = parse_date(date_raw) or (date_raw or None)
            comments.append(
                Comment(
                    nickname=nickname,
                    content=content,
                    posted_at=posted,
                    is_reply=is_reply,
                )
            )
        except Exception as e:
            print(f"[cafe] comment[{i}] parse error: {e}")
    return comments


async def scrape_article(page: Page, url: str, rank: int) -> CafeArticle:
    m = ARTICLE_PAT.match(url)
    cafe_url_id = m.group(1) if m else ""
    article_id = m.group(2) if m else ""

    article = CafeArticle(
        rank=rank,
        url=url,
        cafe_url_id=cafe_url_id,
        article_id=article_id,
        board_name=None,
        title="",
        writer="",
        body="",
        posted_at=None,
        comments=[],
        accessible=True,
        error=None,
        collected_at=datetime.now(KST).isoformat(timespec="seconds"),
    )

    print(f"[cafe] rank {rank} enter: cafe={cafe_url_id} art={article_id}")
    try:
        try:
            await page.goto(url, wait_until="networkidle", timeout=25000)
        except Exception:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await _human_wait(page, 2.0, 3.5)

        frame = await _get_main_frame(page)
        if frame is None:
            article.accessible = False
            article.error = "cafe_main frame did not load (private cafe or login required)"
            print(f"[cafe] rank {rank}: inaccessible — {article.error}")
            return article

        # title — .title_text holds just the headline; .link_board has the board name
        if await frame.locator(".ArticleTitle .title_text").count():
            article.title = (
                await frame.locator(".ArticleTitle .title_text").first.inner_text()
            ).strip()
        elif await frame.locator(".ArticleTitle").count():
            article.title = (
                await frame.locator(".ArticleTitle").first.inner_text()
            ).strip()

        if await frame.locator(".ArticleTitle .link_board").count():
            try:
                article.board_name = (
                    await frame.locator(".ArticleTitle .link_board").first.inner_text()
                ).strip()
            except Exception:
                pass

        # writer
        for sel in [".ArticleWriterProfile .nickname", ".nick_box .nickname", ".nickname"]:
            if await frame.locator(sel).count():
                try:
                    article.writer = (
                        await frame.locator(sel).first.inner_text()
                    ).strip()
                    if article.writer:
                        break
                except Exception:
                    pass

        # posted date
        for sel in [".article_info .date", ".date_area .date", ".date"]:
            if await frame.locator(sel).count():
                try:
                    raw = (await frame.locator(sel).first.inner_text()).strip()
                    article.posted_at = parse_date(raw) or raw or None
                    if article.posted_at:
                        break
                except Exception:
                    pass

        # body
        for sel in [".se-main-container", ".article_viewer", ".article_container"]:
            if await frame.locator(sel).count():
                try:
                    article.body = (
                        await frame.locator(sel).first.inner_text()
                    ).strip()
                    if article.body:
                        break
                except Exception:
                    pass

        # comments
        try:
            await _expand_comments(frame)
        except Exception as e:
            print(f"[cafe] rank {rank}: expand_comments error: {e}")
        article.comments = await _scrape_comments(frame)

        if not article.body and not article.title:
            article.accessible = False
            article.error = "title/body both empty"

        print(
            f"[cafe] rank {rank}: title={article.title[:30]!r} "
            f"body_chars={len(article.body)} comments={len(article.comments)} "
            f"accessible={article.accessible}"
        )
    except Exception as e:
        article.accessible = False
        article.error = f"{type(e).__name__}: {e}"
        print(f"[cafe] rank {rank} error: {article.error}")

    return article


async def run(query: str, output_root: Path, want: int = 3) -> Path:
    """Scrape and store. Returns the keyword output folder."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    out_dir = output_root / today / "cafe" / query
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser, ctx, page = await _new_page(pw)
        try:
            posts = await find_top_cafe_articles(page, query, want=want)
            if len(posts) < want:
                print(
                    f"[cafe] WARN: only {len(posts)} non-ad articles found (wanted {want})"
                )
            for rank, (url, _cid, _aid) in enumerate(posts, start=1):
                art = await scrape_article(page, url, rank)
                (out_dir / f"{rank}.json").write_text(
                    json.dumps(asdict(art), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"[cafe] saved {rank}.json")
        finally:
            await browser.close()

    return out_dir


if __name__ == "__main__":
    import sys

    query = sys.argv[1] if len(sys.argv) > 1 else "기업 홈페이지 제작"
    out_root = Path(__file__).parent / "output"
    asyncio.run(run(query, out_root))
