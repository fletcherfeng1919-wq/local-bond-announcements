"""Crawl the two celma.org.cn listing channels (发行安排 / 发行前公告) and
collect (url, title, pub_date) triples.

Both channels share one simple, server-rendered pagination scheme: page 1
lives at zqsclb.jhtml?ad_code=87&channelId=<id>, subsequent pages at
zqsclb_<n>.jhtml?ad_code=87&channelId=<id>, with a visible '共 N 条 / 共 M 页'
footer we read the total page count from. ad_code=87 (全国) returns every
province's items in one merged, newest-first feed.
"""
import datetime
import re
import sys

from bs4 import BeautifulSoup

from . import config
from .http_client import fetch

TOTAL_PAGES_RE = re.compile(r"共\s*(\d+)\s*页")
DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _parse_listing_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    container = soup.find(id="to-print1")
    if not container:
        return items
    for li in container.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        span = li.find("span")
        date_text = span.get_text(strip=True) if span else ""
        m = DATE_RE.search(date_text)
        pub_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
        items.append({
            "url": a["href"].strip(),
            "title": a.get("title", a.get_text(strip=True)).strip(),
            "listing_pub_date": pub_date,
        })
    return items


def _total_pages(html: str) -> int:
    m = TOTAL_PAGES_RE.search(html)
    return int(m.group(1)) if m else 1


CONSECUTIVE_SEEN_PAGES_STOP = 5  # ~50 items of nothing-but-already-seen in a
                                  # row is a safe signal the rest of history
                                  # (older, newest-first) is already in state.


def crawl_source(source: dict, use_cache: bool = True, max_pages: int | None = None,
                  seen_urls: set[str] | None = None, new_item_target: int | None = None) -> list[dict]:
    """Crawl one listing channel across its pages, return list of
    {url, title, listing_pub_date, source_name, source_label, doc_type} dicts.

    Listings are newest-first, so an incremental run doesn't need to walk all
    (up to ~850) pages every time: pagination stops early once either (a)
    `new_item_target` not-yet-seen items have been collected, or (b)
    `CONSECUTIVE_SEEN_PAGES_STOP` pages in a row contain nothing but items
    already in `seen_urls` -- a strong signal everything older is old news
    too. Neither condition applies (so the full site history gets walked) on
    a from-scratch backfill where `seen_urls` is empty/None."""
    seen_urls = seen_urls or set()
    channel_id = source["channel_id"]
    first_url = config.FIRST_PAGE_TPL.format(channel_id=channel_id)
    first_html = fetch(first_url, use_cache=use_cache)
    total_pages = _total_pages(first_html)
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)

    all_items = _parse_listing_page(first_html)

    def _new_count():
        return sum(1 for it in all_items if it["url"] not in seen_urls)

    def _target_met():
        return new_item_target is not None and _new_count() >= new_item_target

    failed_pages = []
    consecutive_seen_pages = 0
    stop_reason = None
    for n in range(2, total_pages + 1):
        if _target_met():
            stop_reason = f"reached new_item_target={new_item_target}"
            break
        page_url = config.PAGE_TPL.format(n=n, channel_id=channel_id)
        try:
            html = fetch(page_url, use_cache=use_cache)
        except RuntimeError:
            failed_pages.append(n)
            continue
        items = _parse_listing_page(html)
        if not items:
            failed_pages.append(n)
            continue
        all_items.extend(items)

        if items and all(it["url"] in seen_urls for it in items):
            consecutive_seen_pages += 1
            if consecutive_seen_pages >= CONSECUTIVE_SEEN_PAGES_STOP:
                stop_reason = f"{consecutive_seen_pages} consecutive fully-seen pages"
                break
        else:
            consecutive_seen_pages = 0

    if failed_pages:
        print(f"[listing_scraper:{source['name']}] {len(failed_pages)} page(s) failed/empty "
              f"and were skipped: {failed_pages[:20]}{'...' if len(failed_pages) > 20 else ''}",
              file=sys.stderr)
    if stop_reason:
        print(f"[listing_scraper:{source['name']}] stopped pagination early ({stop_reason}), "
              f"{_new_count()} new item(s) collected so far.", file=sys.stderr)

    for item in all_items:
        item["source_name"] = source["name"]
        item["source_label"] = source["label"]
        item["doc_type"] = source["doc_type"]
    return all_items


def crawl_all_sources(use_cache: bool = True, max_pages: int | None = None,
                       seen_urls_by_source: dict[str, set[str]] | None = None,
                       new_item_target: int | None = None) -> dict[str, list[dict]]:
    """Crawl every configured listing channel. Returns {source_name: [items]},
    kept separate (not merged) since 发行安排 and 发行前公告 are structurally
    different document types with different downstream field extraction."""
    seen_urls_by_source = seen_urls_by_source or {}
    result = {}
    for source in config.LISTING_SOURCES:
        result[source["name"]] = crawl_source(
            source, use_cache=use_cache, max_pages=max_pages,
            seen_urls=seen_urls_by_source.get(source["name"]), new_item_target=new_item_target,
        )
    return result
