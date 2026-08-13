"""Automatic discovery layer on top of src/provincial_verify.py.

provincial_verify.py can only parse an ALREADY-KNOWN announcement URL --
it has no way to find fresh ones on its own, because every one of these
provincial listing/column pages either renders its article list via
client-side JS (plain `requests`/`http_client.fetch()` gets an empty or
unrelated page) or, in one case (上海), the "obvious" listing route is a
genuinely broken server-side template that no amount of JS execution can
fix. This module solves the discovery half using Playwright (a real
headless Chromium instance), confirmed 2026-08-11/12 to render all 14
currently-registered listing pages correctly (10 confirmed 2026-08-11,
西藏/山东/青岛/河南 added 2026-08-12 in a second research pass -- see
provincial_verify.py's module docstring and HANDOFF.md for the other ~14
provinces investigated and confirmed to be genuine dead ends or still
unresolved, not worth re-guessing at).

## Design notes / why it's built this way

- **No disk caching of the listing page itself.** Every other list-page
  fetch in this project (celma.org.cn) uses http_client.fetch()'s on-disk
  cache, and that caused a real, repeatedly-rediscovered bug (HANDOFF.md
  坑1: a cached stale listing page permanently hides new announcements
  unless the caller remembers `use_cache=False`). Playwright here does a
  live browser render on every call with no cache layer at all, so that
  entire bug class can't happen -- the cost is a live browser launch each
  time, which is fine at the cadence this runs (monthly/manual, not a
  tight loop).
- **Discovered announcement URLs ARE still cached** -- once
  provincial_verify.verify_announcement() fetches and parses one, that
  goes through the normal http_client/pdf caching, since individual
  announcement content genuinely is immutable once published (same
  reasoning as celma's own detail-page caching).
- **Date filtering by URL path, not by rendered "发布日期" text.** Every
  one of these sites' CMS embeds the publish date in the URL itself
  (`/YYYYMM/`, `/art/YYYY/M/D/`, etc.) -- parsed via _extract_url_date().
  Deliberately NOT relying on scraping a nearby "发布时间：" text node next
  to each link, since that requires a per-site DOM-position assumption
  this module's generic <a>-tag-only extraction doesn't have; the URL
  itself is more robust and is present on 100% of the confirmed sources.
"""
import re
from datetime import date, timedelta

from playwright.sync_api import sync_playwright

from . import provincial_verify as pv

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Verified 2026-08-11 via live Playwright render (see HANDOFF.md) -- each
# entry is the listing/column page that actually returns real bond-related
# <a> links, NOT the guessed "obvious" URL (several of those are dead/broken
# server routes, e.g. 上海's zys_8908/.../dfzwfxjg/index.html, or a 200-status
# stub page with no real content, e.g. 河北's root17/zfxx/ -- its real listing
# turned out to be loaded via an <iframe>, only spottable by reading raw HTML
# source since Playwright's rendered <a> selector on the PARENT page doesn't
# reach into iframe content).
LISTING_URLS: dict[str, str] = {
    "上海市": "https://czj.sh.gov.cn/zss/zt/dfzfx/zxxx/index.html",
    "新疆维吾尔自治区": "https://czt.xinjiang.gov.cn/",
    "河北省": "https://czt.hebei.gov.cn/root17/3007/3058/list_292.htm",
    "贵州省": "https://czt.guizhou.gov.cn/zwgk/zdlyxx/zfzw/",
    "江苏省": "https://czt.jiangsu.gov.cn/col/col77314/index.html",
    "宁夏回族自治区": "https://czt.nx.gov.cn/xwzx/tzgg/",
    "宁波市": "http://czj.ningbo.gov.cn/col/col1229029201/index.html",
    "天津市": "https://cz.tj.gov.cn/zwgk_53713/zfzq/",
    "湖南省": "https://czt.hunan.gov.cn/czt/dzqzfzjxx/list.html",
    "重庆市": "https://czj.cq.gov.cn/zwgk_268/zfxxgkml/dfzfzw/",
    # Added 2026-08-12, second research pass (see provincial_verify.py's
    # PROVINCE_SOURCES for structure/quirk notes on each):
    "西藏自治区": "https://www.xizang.gov.cn/zwgk/xxfb/gsgg_428/",
    "山东省": "http://czt.shandong.gov.cn/col/col10559/index.html",
    "青岛市": "http://qdcz.qingdao.gov.cn/zfxxgk/fdzdgknr/zdly/zwgl/index.shtml",
    "河南省": "https://czt.henan.gov.cn/xwdt/tzgg/",
    # Added 2026-08-13: 大连市 previously had no dedicated source at all in
    # this project (see provincial_verify.py's PROVINCE_SOURCES entry --
    # clean inline HTML, no OCR, verified 9/9 bonds against celma).
    "大连市": "https://czj.dl.gov.cn/col/col5025/index.html",
}

# 新疆's own column-level listing pages (c115017/, c115008/) are WAF-blocked
# (403) even via Playwright -- the only reachable substitute is the site
# HOMEPAGE, which pulls a mixed feed from multiple columns. It also times
# out on "networkidle" (persistent background requests never settle), so it
# needs domcontentloaded + a fixed extra wait instead. Provinces not listed
# here use the default networkidle strategy in discover_links().
WAIT_STRATEGY_OVERRIDES: dict[str, dict] = {
    "新疆维吾尔自治区": {"wait_until": "domcontentloaded", "extra_wait_ms": 3000},
}

# Only these link-text keywords count as an issuance-RESULTS announcement
# (as opposed to a 发行安排/发行通知/信息披露/还本付息 sibling on the same
# listing page -- these general "通知公告"-style columns mix several
# announcement types together, confirmed on 宁夏/河北/新疆/重庆).
RESULT_KEYWORDS = ("发行结果", "招标结果", "发行结果公告")

_URL_DATE_PATTERNS = [
    re.compile(r"/(\d{4})/(\d{1,2})/(\d{1,2})/"),  # /art/2026/7/24/  (江苏)
    re.compile(r"/(\d{4})(\d{2})(\d{2})/"),  # /20260713/  (上海, 8-digit day-precision)
    re.compile(r"/(\d{4})(\d{2})/"),  # /202608/  (河北/贵州/宁夏/天津/重庆/湖南, month-only)
]
# Title-text fallback for sites whose URL carries no date at all (confirmed:
# 宁波, whose URLs are just ".../art/2026/art_<hash>.html" -- bare year, no
# month/day) -- the date is only recoverable from the title itself, e.g.
# "2026年6月26日宁波市政府债券发行结果公告". Also covers the "YYYY-MM-DD"
# form seen appended as a second line in some sites' <a> innerText (天津/
# 重庆's rendered date badge sitting inside the same anchor as the title).
_TITLE_DATE_PATTERNS = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
]


def _extract_url_date(url: str) -> date | None:
    for pat in _URL_DATE_PATTERNS:
        m = pat.search(url)
        if m:
            y = int(m.group(1))
            mo = int(m.group(2))
            d = int(m.group(3)) if m.lastindex >= 3 else 1
            try:
                return date(y, mo, d)
            except ValueError:
                continue
    return None


def _extract_title_date(title: str) -> date | None:
    for pat in _TITLE_DATE_PATTERNS:
        m = pat.search(title)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def discover_links(page, listing_url: str, since: date | None = None, province: str | None = None) -> list[dict]:
    """Render listing_url with an already-open Playwright page and return
    every link whose text matches RESULT_KEYWORDS, filtered to `since` (by
    URL-embedded date) when given. Returns [{"title", "url", "date"}, ...],
    most recent first. `date` is None when the URL carries no parseable
    date (kept, not dropped -- better to hand it to the caller than to
    silently lose an announcement over a date-parsing miss).

    `province`, when given, looks up WAIT_STRATEGY_OVERRIDES -- confirmed
    necessary for 新疆 (Xinjiang), whose homepage never reaches
    "networkidle" (persistent background requests keep the network busy)."""
    strategy = WAIT_STRATEGY_OVERRIDES.get(province, {})
    wait_until = strategy.get("wait_until", "networkidle")
    extra_wait_ms = strategy.get("extra_wait_ms", 1000)
    page.goto(listing_url, timeout=20000, wait_until=wait_until)
    page.wait_for_timeout(extra_wait_ms)
    raw_links = page.eval_on_selector_all(
        "a", "els => els.map(e => [e.innerText.trim(), e.href]).filter(x => x[0] && x[0].length > 4)"
    )
    seen_urls = set()
    out = []
    for raw_title, url in raw_links:
        if not any(kw in raw_title for kw in RESULT_KEYWORDS):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # innerText sometimes carries a second line (a rendered "发布日期"
        # badge sitting inside the same <a>, confirmed: 天津/重庆) -- keep
        # only the first line as the clean title, but still date-parse the
        # FULL raw text since that badge line is a good date source too.
        title = raw_title.splitlines()[0].strip()
        d = _extract_url_date(url) or _extract_title_date(raw_title)
        if since is not None and d is not None and d < since:
            continue
        out.append({"title": title, "url": url, "date": d})
    out.sort(key=lambda r: r["date"] or date.min, reverse=True)
    return out


def discover_all_provinces(months_back: int = 2, provinces: list[str] | None = None) -> dict[str, list[dict]]:
    """Discover recent issuance-results announcement links for every
    province in LISTING_URLS (or a subset via `provinces`). One browser
    instance is reused across all provinces to avoid the startup cost of
    launching Chromium once per province."""
    since = date.today().replace(day=1)
    for _ in range(months_back - 1):
        since = (since - timedelta(days=1)).replace(day=1)

    targets = provinces or list(LISTING_URLS.keys())
    results: dict[str, list[dict]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(ignore_https_errors=True, user_agent=USER_AGENT)
        page = ctx.new_page()
        for province in targets:
            listing_url = LISTING_URLS.get(province)
            if not listing_url:
                results[province] = []
                continue
            try:
                results[province] = discover_links(page, listing_url, since=since, province=province)
            except Exception as e:
                results[province] = [{"error": str(e)}]
        ctx.close()
        browser.close()
    return results


def crawl_province(province: str, months_back: int = 2, use_cache: bool = True) -> list[dict]:
    """Discover + parse every recent issuance-results announcement for one
    province. Returns the concatenation of provincial_verify.verify_announcement()
    over each discovered URL -- same bond-row shape, plus `source_url` and
    `announcement_title` so a caller can trace any row back to its origin."""
    discovered = discover_all_provinces(months_back=months_back, provinces=[province]).get(province, [])
    all_rows = []
    for item in discovered:
        if "error" in item:
            continue
        try:
            rows = pv.verify_announcement(province, item["url"], use_cache=use_cache)
        except NotImplementedError:
            raise
        except Exception as e:
            all_rows.append({
                "province": province, "bond_name": None, "bond_short_name": None,
                "total_amount_yi": None, "term": None, "coupon_rate_pct": None, "issue_date": None,
                "warnings": f"解析公告失败: {e}",
                "source_url": item["url"], "announcement_title": item["title"],
            })
            continue
        for r in rows:
            r["source_url"] = item["url"]
            r["announcement_title"] = item["title"]
        all_rows.extend(rows)
    return all_rows


def crawl_all(months_back: int = 2, use_cache: bool = True) -> dict[str, list[dict]]:
    """crawl_province() for every province in LISTING_URLS. Tianjin (image
    OCR) and any NotImplementedError-raising source are caught per-province
    so one broken source doesn't abort the whole run."""
    out = {}
    for province in LISTING_URLS:
        try:
            out[province] = crawl_province(province, months_back=months_back, use_cache=use_cache)
        except NotImplementedError as e:
            out[province] = []
            print(f"[provincial_crawl] {province} skipped: {e}")
    return out
