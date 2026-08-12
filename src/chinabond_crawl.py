"""Crawl chinabond.com.cn's "地方政府债券信息披露门户" (Local Government Bond
Information Disclosure Portal) -- run by CCDC (中央国债登记结算有限责任公司,
the official bond registrar/clearing house), NOT a province's own site.

Discovered 2026-08-12 while investigating whether provincial finance-bureau
sites could fill celma/SSE coverage gaps. It turned out to matter far more
than any single province: this ONE source aggregates BOTH 发行结果
(issuance results) and 发行计划 (issuance plans) for effectively ALL
provinces in one consistent, JSON-driven interface -- including 内蒙古/
黑龙江/甘肃/山西/福建/浙江, every one of which was either WAF-blocked,
network-unreachable, or confirmed to publish nothing on its own site during
the 2026-08-12 provincial-site research pass (see provincial_verify.py /
HANDOFF.md). For those provinces specifically, chinabond.com.cn is the ONLY
working automated source found so far.

## Why this needed no Playwright at all

Unlike every provincial site in provincial_crawl.py, this portal's listing
is a plain JSON REST API (`requests.get()`, no browser, no JS execution) --
found by loading the portal once in Playwright and watching for XHR/fetch
calls (same technique used earlier for the SSE API), then confirmed the API
works standalone with a normal HTTP client and a Referer header.

## API shape

- `https://www.chinabond.com.cn/cbiw/lgb/infoListByPath` -- the listing
  endpoint. Params: `_tp_lgbInfo=1`, `pageSize=10` (other values return
  `{"code":"500","msg":"pageSize无效"}` -- 10 seems to be the only accepted
  value, not confirmed configurable), `channelName` (see CHANNELS below),
  `issuer` (**must be the SHORT province name, no 省/自治区/市 suffix** --
  e.g. "内蒙古" works, "内蒙古自治区" returns 0 results; confirmed this is
  what unlocks every "impossible" province), `depth=3`, `lan=` (empty).
  Response: `{"code","msg","lgbInfoList":[{...}]}`, each item has a
  `property0` field pointing to a per-item detail JSON URL.
- The detail JSON (fetched from `property0`) has `title`, `createTime`,
  `channelDesc`, and a `files` list -- each file has a direct PDF `url`.
  `content`/`htmlContent` are always empty in practice -- the actual bond
  data is NEVER structured JSON, always inside the attached PDF. Don't
  expect to skip PDF extraction for this source; it doesn't offer that.

## Structure of the documents themselves

For channelName="xxplwj_fxjg" (发行结果): same standardized key-value
template every provincial site's own 发行结果 announcements use (债券名称/
计划发行规模/实际发行规模/发行期限/票面利率/...) -- confirmed by parsing a
real 河南省 chinabond copy, which is close to (possibly literally) the same
PDF the province's own site published. This means results documents from
this source can reuse provincial_verify.parse_announcement_text() directly,
no new parser needed. OCR quality varies by document same as any scanned
PDF source -- confirmed one clean single-bond 内蒙古 document where OCR
still failed to read the actual data table (only got the intro paragraph;
the bordered table + red seal stamp overlapping it likely confuses
pytesseract's layout detection) despite the source PDF being visually
perfectly readable when rendered as an image and inspected directly. Not
tuned further -- flagged as a real, unresolved OCR limitation worth
revisiting (try alternate Tesseract PSM modes, or cropping out the seal
region) rather than a parser bug.

## Reading diff_against_state() results from this source correctly

Tested against 6 previously-impossible provinces (内蒙古/黑龙江/甘肃/山西/
福建/浙江, 139 rows total): **zero rows where both issue_date AND term were
successfully extracted still failed to match celma.** Every "not_found_in_state"
row was missing issue_date or term (i.e. the OCR/parser genuinely couldn't
read that document, not "celma doesn't have this bond") -- so a raw
not_found count from this source is NOT evidence of a celma coverage gap by
itself; only filter to rows with issue_date+term populated before treating
the count as meaningful. One single-bond, cleanly-photographed 内蒙古
document (内蒙古自治区政府再融资一般债券七期, 2026-08-10, 41.7053亿, 10Y,
1.76%) was manually read from its rendered page image and confirmed to be a
genuine celma gap matching an SSE-flagged missing bond (26内蒙18) -- proving
this source CAN fill real gaps, just not reliably through today's automated
OCR path for every document. Treat automated chinabond.com.cn extraction as
a "probably right, worth a human glance before trusting for edge cases"
signal for now, same caution as any other OCR'd source in this project, not
as authoritative as a text-native PDF (confirmed: 山东's own site) or clean
inline HTML (confirmed: 宁夏/西藏).

For channelName="xxplwj_fxjh" (发行计划): a DIFFERENT, much simpler
document -- a single small monthly summary table (province, total 亿元,
新增/再融资 breakdown), not per-bond blocks. **No parser exists for this
yet** -- parse_announcement_text() will not produce anything useful against
it (confirmed: tested against a real 上海市 2026年8月 plan PDF, got 0 usable
fields). This is exactly the kind of document that could fill the "10
provinces missing an August plan in state_plans.csv" gap identified
2026-08-12, but building that parser is separate follow-up work, not done
in this pass.

## Other channels available (not used by this module yet)

Discovered via the channel tree (`.../zdfzxxpl_xxplwj/channels.json`):
xxplwj_zdwj (制度文件), xxplwj_cxtgl (承销团管理), xxplwj_fxqpl (发行前披露).
Only xxplwj_fxjg (results) and xxplwj_fxjh (plans, unparsed) are wired up.
"""
import re

import requests

from . import pdf_extract, provincial_verify as pv

API_BASE = "https://www.chinabond.com.cn/cbiw/lgb/infoListByPath"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.chinabond.com.cn/dfz/",
}
REQUEST_TIMEOUT = 20

CHANNEL_RESULTS = "xxplwj_fxjg"
CHANNEL_PLANS = "xxplwj_fxjh"

# issuer param MUST be the short form (no 省/自治区/市/兵团 suffix) -- confirmed
# 2026-08-12 this is what makes 内蒙古/黑龙江/甘肃/山西 (all unreachable via
# their own sites) return real results, while the long form returns nothing.
_SUFFIXES = ["维吾尔自治区", "回族自治区", "壮族自治区", "自治区", "省", "市"]


def _short_issuer(province: str) -> str:
    for suf in _SUFFIXES:
        if province.endswith(suf):
            return province[: -len(suf)]
    return province


def _get_with_retry(url: str, **kwargs) -> requests.Response:
    """Confirmed 2026-08-12: this machine's system HTTP proxy occasionally
    returns a transient 503 mid-batch (same issue found during the second
    provincial-site research pass, see HANDOFF.md) -- a couple of retries
    with a short backoff clears it without needing the proxy-bypass
    workaround provincial_crawl.py's Playwright calls sometimes need
    (chinabond.com.cn hasn't shown the harder ERR_TUNNEL_CONNECTION_FAILED
    failure mode those specific domains did, just this transient 503)."""
    import time
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err


def fetch_channel_page(channel_name: str, issuer: str | None = None, page_size: int = 10) -> list[dict]:
    """One page of listing items for a channel, optionally filtered to one
    province (short-name form, see module docstring). No pagination param
    confirmed working beyond pageSize -- this returns the most recent
    `page_size` items only; good enough for a recent-months gap-check, not
    for a full historical backfill (see module docstring's follow-up notes
    if that's ever needed)."""
    params = {
        "_tp_lgbInfo": 1, "pageSize": page_size, "channelName": channel_name,
        "issuer": _short_issuer(issuer) if issuer else "", "depth": 3, "lan": "",
    }
    resp = _get_with_retry(API_BASE, params=params)
    data = resp.json()
    if data.get("code") != "200":
        return []
    return data.get("lgbInfoList") or []


def fetch_detail(property0_url: str) -> dict:
    return _get_with_retry(property0_url).json()


def fetch_pdf_bytes(url: str) -> bytes:
    return _get_with_retry(url).content


def crawl_results(province: str, page_size: int = 10, use_cache: bool = True) -> list[dict]:
    """Fetch + parse the most recent 发行结果 items for one province from
    chinabond.com.cn. Returns bond-row dicts in the same shape
    provincial_verify.diff_against_state() expects, plus `source_url` and
    `announcement_title`. Downloaded PDFs go through http_client's normal
    disk cache via a local re-implementation (this module doesn't share
    http_client.fetch_pdf()'s cache keying since URLs here are already
    unique chinabond.com.cn paths, not needing the same hash scheme -- but
    still worth caching since re-downloading + re-OCRing is expensive)."""
    from . import http_client, config

    items = fetch_channel_page(CHANNEL_RESULTS, issuer=province, page_size=page_size)
    all_rows = []
    for item in items:
        detail_url = item.get("property0")
        if not detail_url:
            continue
        try:
            detail = fetch_detail(detail_url)
        except Exception:
            continue
        files = detail.get("files") or []
        if not files:
            continue
        pdf_url = files[0]["url"]
        try:
            pdf_path = http_client.fetch_pdf(pdf_url, use_cache=use_cache)
            result = pdf_extract.extract_pdf(pdf_path, use_cache=use_cache)
        except Exception as e:
            all_rows.append({
                "province": province, "bond_name": None, "bond_short_name": None,
                "total_amount_yi": None, "term": None, "coupon_rate_pct": None, "issue_date": None,
                "warnings": f"下载/解析PDF失败: {e}",
                "source_url": pdf_url, "announcement_title": item.get("title"),
            })
            continue
        rows = pv.parse_announcement_text(result["text"], province)
        for r in rows:
            r["source_url"] = pdf_url
            r["announcement_title"] = item.get("title")
            if result["method"] == "ocr":
                r["extraction_method"] = "ocr"
        all_rows.extend(rows)
    return all_rows


def crawl_all_results(provinces: list[str], page_size: int = 10, use_cache: bool = True) -> dict[str, list[dict]]:
    """crawl_results() for each province in `provinces` (pass a full
    province-name list, e.g. config.PROVINCES.keys() -- _short_issuer()
    handles the suffix stripping internally). Each province's fetch is
    wrapped so one transient failure (confirmed 2026-08-12: this machine's
    system HTTP proxy occasionally 503s mid-batch, same proxy issue found
    during the second provincial-site research pass) doesn't abort the
    whole run -- a failed province comes back as an empty list plus a
    printed warning, not a crashed process."""
    out = {}
    for p in provinces:
        try:
            out[p] = crawl_results(p, page_size=page_size, use_cache=use_cache)
        except Exception as e:
            print(f"[chinabond_crawl] {p} failed: {e}")
            out[p] = []
    return out
