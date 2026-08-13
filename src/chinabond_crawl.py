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
document -- a single small monthly/quarterly summary table (province, total
亿元, 新增/再融资 breakdown), not per-bond blocks. parse_announcement_text()
does not work against it (confirmed: 0 usable fields on a real 上海市
2026年8月 plan PDF). A dedicated parser was built 2026-08-12 (see
parse_plan_pdf() and its helpers below) using a 3-tier strategy, since at
least 4 distinct real-world table templates are in circulation across
provinces:
  1. Structured table-geometry parsing, in two orientations:
     _parse_plan_table_column_oriented() for 山东/辽宁-style tables
     (新增/再融资 as column-group headers, one data row per region), and
     _parse_plan_table_row_oriented() for 广东-style tables (新增/再融资
     as row-group labels, a dedicated "合计" column holds the period total).
  2. _parse_plan_text_fallback(): label-adjacent regex against the raw text
     layer, for text-native PDFs whose table geometry pdfplumber can't
     recover cleanly.
  3. _parse_plan_text_positional(): for OCR'd documents where even the
     category labels are lost, reads the 7 numbers off a "合计" line in
     fixed positional order and only trusts them if they arithmetically
     self-validate (新增一般+新增专项≈新增小计, etc.) -- returns nothing
     rather than a guess if validation fails.
Tested against exactly the 10 provinces state_plans.csv was missing an
August 2026 plan for: 6 filled cleanly (上海市, 吉林省, 广东省, 辽宁省,
山西省, 新疆生产建设兵团), while the other 4 (大连市, 河南省, 西藏自治区,
青岛市) were confirmed via direct API querying (both long and short
issuer-name forms) to simply have no recent 2026 plan document on
chinabond.com.cn for this channel -- a genuine source-side content gap,
not a parser or discovery failure.

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


# ---------------------------------------------------------------------------
# 发行计划 (issuance plan) parsing
# ---------------------------------------------------------------------------
#
# Confirmed 2026-08-12 across real documents from 上海/广东/山东: at least
# 3 distinct presentations exist for the SAME underlying data (province,
# 新增一般/新增专项/再融资一般/再融资专项 amounts for the covered period):
#   - 山东 (text-native PDF, clean pdfplumber table): column-oriented --
#     新增债券/再融资债券 are column-GROUP headers (each spanning 小计/一般
#     债券/专项债券 sub-columns), one data row per region.
#   - 广东 (text-native PDF, clean pdfplumber table): row-oriented, spans a
#     quarter with a monthly/旬 breakdown -- 新增债券/再融资债券 are ROW
#     group labels in an early column, 一般/专项债券 in the next column, and
#     a dedicated "合计" column holds each row's own period total (collapsing
#     the 旬/月 sub-breakdown, which is more granularity than state_plans.csv
#     tracks).
#   - 上海 (scanned/photographed PDF, OCR only, no table geometry survives):
#     falls back to a flat-text regex heuristic over the OCR'd text.
# parse_plan_pdf() tries both known table orientations first and only drops
# to the OCR text heuristic when no table structure was recovered at all.

from .extract_plan import _covered_period

_PLAN_AMOUNT_KEYS = ("new_general", "new_special", "refi_general", "refi_special")


def _to_float(s) -> float | None:
    if s is None:
        return None
    s = str(s).replace(",", "").replace("，", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        m = re.search(r"[\d.]+", s)
        return float(m.group(0)) if m else None


def _parse_plan_table_column_oriented(table: list) -> dict | None:
    """山东-style: 新增债券/再融资债券 as column-group headers spanning
    小计/一般债券/专项债券 sub-columns, one data row per region."""
    header_rows, data_row = [], None
    for row in table:
        first = (row[0] or "").strip() if row and row[0] else ""
        if first and first not in ("地区", "省", "市", "自治区") and any(k in first for k in ("省", "市", "自治区", "地区")):
            data_row = row
        else:
            header_rows.append(row)
    if data_row is None or not header_rows:
        return None

    filled_headers = []
    for hr in header_rows:
        filled, last = [], None
        for v in hr:
            v = (v or "").strip() or None
            if v:
                last = v
            filled.append(last)
        filled_headers.append(filled)

    result = {k: None for k in _PLAN_AMOUNT_KEYS}
    found_any = False
    for c in range(len(data_row)):
        supercat = subcat = None
        for hr in filled_headers:
            val = hr[c] if c < len(hr) else None
            if val in ("新增债券", "再融资债券"):
                supercat = val
            if val in ("一般债券", "专项债券"):
                subcat = val
        if supercat and subcat:
            key = ("new" if supercat == "新增债券" else "refi") + ("_general" if subcat == "一般债券" else "_special")
            result[key] = _to_float(data_row[c])
            found_any = True
    return result if found_any else None


def _parse_plan_table_row_oriented(table: list) -> dict | None:
    """广东-style: 新增债券/再融资债券 as row-group labels in an early
    column, 一般债券/专项债券 in the next column, a dedicated "合计" column
    holds each row's own period total."""
    total_col = None
    for row in table[:3]:
        for i, v in enumerate(row):
            if v and str(v).strip() == "合计":
                total_col = i
                break
        if total_col is not None:
            break
    if total_col is None:
        return None

    result = {k: None for k in _PLAN_AMOUNT_KEYS}
    current_supercat = None
    found_any = False
    for row in table:
        c0 = (row[0] or "").replace("\n", "").strip() if row and row[0] else ""
        if "新增" in c0:
            current_supercat = "新增债券"
        elif "再融资" in c0:
            current_supercat = "再融资债券"
        subcat = (row[1] or "").strip() if len(row) > 1 and row[1] else None
        if subcat in ("一般债券", "专项债券") and current_supercat and total_col < len(row):
            key = ("new" if current_supercat == "新增债券" else "refi") + ("_general" if subcat == "一般债券" else "_special")
            result[key] = _to_float(row[total_col])
            found_any = True
    return result if found_any else None


def _parse_plan_text_fallback(text: str) -> dict:
    """For OCR'd/scanned plan documents where no table geometry survived
    (confirmed: 上海/吉林's plan PDFs, both photographed/scanned originals).
    Every confirmed document of this kind lists 一般债券/专项债券 amounts in
    a fixed reading order -- 新增-一般, 新增-专项, 再融资-一般, 再融资-专项 --
    so the 1st "一般债券"-labeled number is new_general and the 2nd (if any)
    is refi_general, same pattern for 专项债券/new_special/refi_special. A
    blank cell (no number printed after the label) correctly produces no
    match for that occurrence rather than a wrong one.

    Originally this split the text at the "再融资债券" row-group label and
    looked for 一般/专项 before vs after that point, but real OCR output
    (confirmed: 吉林's 2026年8月 plan) can place a value BEFORE its own
    row-group label text appears in reading order (the 再融资-一般 number
    landed before the "再融资债券" label itself) -- silently dropping that
    field and, combined with the decimal-point-space OCR artifact below,
    truncating 21.3000/33.5400 to 21/33. The old code passed its own no-crash
    test (上海's refi cells are genuinely blank, so the bug was invisible)
    but produced 3 wrong numbers on 吉林 before this was caught by a manual
    visual check against the rendered PDF page. Don't revert to the
    split-based approach without re-verifying the reading-order assumption
    against a rendered image, not just the extracted text."""
    text = re.sub(r"(\d)\.\s+(\d)", r"\1.\2", text)
    result = {k: None for k in _PLAN_AMOUNT_KEYS}
    general_matches = re.findall(r"一般债券\s*[|｜]?\s*([\d,]+\.?\d*)", text)
    special_matches = re.findall(r"专项债券\s*[|｜]?\s*([\d,]+\.?\d*)", text)
    if general_matches:
        result["new_general"] = _to_float(general_matches[0])
        if len(general_matches) > 1:
            result["refi_general"] = _to_float(general_matches[1])
    if special_matches:
        result["new_special"] = _to_float(special_matches[0])
        if len(special_matches) > 1:
            result["refi_special"] = _to_float(special_matches[1])
    return result


def _parse_plan_text_positional(text: str) -> dict | None:
    """Second-tier OCR fallback for when even the category LABEL text
    (新增债券/一般债券/etc) was lost or scattered by OCR, not just the
    table borders (confirmed: 山西/新疆生产建设兵团 -- the label row and
    the numbers row land far enough apart in the OCR'd text that
    _parse_plan_text_fallback's label-adjacent-to-number assumption never
    matches). Every confirmed table template (山东/广东/辽宁, see above)
    puts a grand-total ("合计") row with exactly 7 numbers in the same
    fixed order: [总计, 新增小计, 新增一般, 新增专项, 再融资小计, 再融资
    一般, 再融资专项]. Find a "合计"-prefixed line with 7 numbers and
    SELF-VALIDATE the positional guess via arithmetic (一般+专项 should
    equal each 小计, and the two 小计 should sum to 总计) before trusting
    it -- confirmed exact (sub-1-unit rounding) on both 山西 and 新疆生产
    建设兵团's real documents. Returns None (never guesses) if the numbers
    don't add up, e.g. because this wasn't really the grand-total line."""
    for line in text.splitlines():
        if not re.match(r"^\s*合\s*计", line):
            continue
        # Confirmed (新疆生产建设兵团): OCR sometimes injects a stray space
        # right after a decimal point ("27. 0274" instead of "27.0274"),
        # splitting one number into two tokens -- same artifact already
        # documented in extract_result.py's _to_float() for province PDFs.
        # Must collapse this BEFORE extracting numbers, or a 7-number line
        # silently becomes 8 tokens and the whole positional mapping shifts.
        clean_line = re.sub(r"(\d)\.\s+(\d)", r"\1.\2", line)
        nums = [_to_float(x) for x in re.findall(r"[\d,]+\.?\d*", clean_line)]
        if len(nums) < 7 or any(n is None for n in nums[:7]):
            continue
        total, new_sub, new_g, new_s, refi_sub, refi_g, refi_s = nums[:7]
        tol = max(0.5, total * 0.01)
        if (abs(new_g + new_s - new_sub) < tol
                and abs(refi_g + refi_s - refi_sub) < tol
                and abs(new_sub + refi_sub - total) < tol):
            return {"new_general": new_g, "new_special": new_s, "refi_general": refi_g, "refi_special": refi_s}
    return None


def parse_plan_pdf(pdf_result: dict, province: str, title: str) -> dict:
    """Parse one chinabond.com.cn 发行计划 PDF (already run through
    pdf_extract.extract_pdf()) into the same field shape as
    state_plans.csv/extract_plan.py: plan_general_amount_yi (新增-一般),
    plan_special_amount_yi (新增-专项), plan_refinancing_amount_yi
    (再融资-一般 + 再融资-专项 summed, matching that schema's single
    combined refinancing field rather than splitting it further)."""
    text = pdf_result["text"]
    tables = pdf_result["tables"]
    method = pdf_result["method"]

    year, mstart, mend = _covered_period(title, text)
    row = {
        "province": province, "covered_year": year,
        "covered_month_start": mstart, "covered_month_end": mend,
        "plan_general_amount_yi": None, "plan_special_amount_yi": None,
        "plan_refinancing_amount_yi": None,
        "extraction_method": method, "warnings": [],
    }
    if year is None:
        row["warnings"].append("未能从标题识别计划覆盖的月份/季度")

    parsed = None
    for table in tables:
        parsed = _parse_plan_table_column_oriented(table) or _parse_plan_table_row_oriented(table)
        if parsed:
            break
    if parsed is None:
        parsed = _parse_plan_text_fallback(text)
        if not any(v is not None for v in parsed.values()):
            positional = _parse_plan_text_positional(text)
            if positional:
                parsed = positional
                row["warnings"].append("表格结构未能识别，字段标签也丢失，改用'合计'行7个数字的位置推断+算术自校验提取，建议人工核对")
            else:
                row["warnings"].append("表格结构未能识别（多为扫描件），改用OCR文本启发式规则提取，可靠性较低，需人工核对")
        else:
            row["warnings"].append("表格结构未能识别（多为扫描件），改用OCR文本启发式规则提取，可靠性较低，需人工核对")

    row["plan_general_amount_yi"] = parsed.get("new_general")
    row["plan_special_amount_yi"] = parsed.get("new_special")
    refi_g, refi_s = parsed.get("refi_general"), parsed.get("refi_special")
    if refi_g is not None or refi_s is not None:
        row["plan_refinancing_amount_yi"] = (refi_g or 0) + (refi_s or 0)

    if method == "ocr":
        row["warnings"].append("本行来自OCR识别，数值型字段准确性需人工核对")
    row["warnings"] = "; ".join(row["warnings"])
    return row


def crawl_plans(province: str, page_size: int = 10, use_cache: bool = True) -> list[dict]:
    """Fetch + parse the most recent 发行计划 items for one province from
    chinabond.com.cn. Returns rows in extract_plan.py's schema plus
    `source_url`/`announcement_title`, most recent first."""
    from . import http_client, pdf_extract

    items = fetch_channel_page(CHANNEL_PLANS, issuer=province, page_size=page_size)
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
                "province": province, "covered_year": None, "covered_month_start": None,
                "covered_month_end": None, "plan_general_amount_yi": None,
                "plan_special_amount_yi": None, "plan_refinancing_amount_yi": None,
                "extraction_method": "failed", "warnings": f"下载/解析PDF失败: {e}",
                "source_url": pdf_url, "announcement_title": item.get("title"),
            })
            continue
        row = parse_plan_pdf(result, province, item.get("title", ""))
        row["source_url"] = pdf_url
        row["announcement_title"] = item.get("title")
        all_rows.append(row)
    return all_rows


def crawl_all_plans(provinces: list[str], page_size: int = 10, use_cache: bool = True) -> dict[str, list[dict]]:
    """crawl_plans() for each province, resilient to one province's failure
    (see crawl_all_results()'s docstring for why)."""
    out = {}
    for p in provinces:
        try:
            out[p] = crawl_plans(p, page_size=page_size, use_cache=use_cache)
        except Exception as e:
            print(f"[chinabond_crawl] {p} (plans) failed: {e}")
            out[p] = []
    return out
