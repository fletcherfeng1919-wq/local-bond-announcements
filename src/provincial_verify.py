"""Cross-check data/state_results.csv against provincial finance-bureau
(财政厅/财政局) 发行结果公告 pages -- a THIRD independent source alongside
celma.org.cn (primary) and Wind (src/wind_reconcile.py), used specifically
for verifying the most recent 1-2 months, since that's the window where
celma's own publishing lag (see HANDOFF.md 2026-08-11 entries) matters most
and the user doesn't have a fresh Wind export on hand every time.

## Why there's no listing/crawl automation here

Every provincial site's own *listing* page for this column was either
JS-rendered (empty on a plain fetch, same failure mode as celma's list-page
caching pitfall) or blocked by a WAF/cert mismatch when probed with
WebFetch/requests. There is no reliable "give me this province's bonds for
month X" entrypoint the way celma.org.cn's channelId-based pagination gives
us. So this module's unit of work is **one already-known announcement URL**
(found via WebSearch, same way PROVINCE_SOURCES below was populated) --
verify_announcement() parses it, diff_against_state() cross-checks it. This
mirrors wind_reconcile.py's own shape (a manually-supplied input, not a
live crawl).

## Why matching is (province, issue_date, term, amount), not bond_short_name

Confirmed empirically (2026-08-11) against real announcements from 江苏省
and 宁夏回族自治区: provincial announcements follow a nationally standardized
disclosure template (财库〔2020〕43号/36号) built around 债券名称/计划发行
规模/实际发行规模/发行期限/票面利率/付息.../到期日 -- this is a DIFFERENT
template from celma's own 表2-9/表2-10 aggregation table, and critically it
never carries the market 债券编码/债券简称 that wind_reconcile.py's matching
relies on. The only reliable join key across sources is therefore the
tuple (province, issue_date, term, amount) -- same fallback approach
wind_reconcile.py used internally to catch celma/Wind naming-convention
mismatches.

## Structure types (confirmed 2026-08-11, see HANDOFF.md for full findings)

- "pdf": cover HTML page links to a PDF attachment with the actual
  key-value bond blocks. Text-native PDFs work well; some provinces
  (confirmed: 江苏) serve *scanned* PDFs that only extract_pdf()'s OCR
  fallback can read, and OCR quality is materially worse -- expect missing
  fields (esp. 票面利率/发行期限), never fabricate them.
- "html": the bond blocks are inline in the cover page's own HTML, no
  attachment at all. Cleanest and most reliable source (confirmed: 宁夏,
  宁波) -- no OCR risk.
- "docx" (湖南) / "image" (天津): confirmed to exist but NOT implemented --
  docx needs the `python-docx` package (not currently a project dependency)
  and 天津's announcements are JPG scans requiring the same OCR path as a
  scanned PDF. Calling verify_announcement() for these raises
  NotImplementedError rather than silently returning nothing.
- 重庆 (Chongqing): cover URL confirmed real but WebFetch couldn't extract
  a body during research -- structure genuinely unconfirmed, not just
  unimplemented. Don't assume "pdf" or "html" for it without checking.

Per explicit user instruction (2026-08-11): do NOT chase the remaining
~17 provinces where research only found partial leads or nothing at all
(甘肃/西藏/山西/陕西/山东/青岛/浙江/湖北/河南/江西/安徽/广东/吉林/黑龙江/
云南/四川/福建/内蒙古 -- 内蒙古 specifically confirmed to have NO
province-own results page at all, not just unfound). Only the provinces in
PROVINCE_SOURCES below are wired up; extend it when/if the user asks.
"""
import re
from dataclasses import dataclass, field

from . import http_client, pdf_extract

AMOUNT_TOLERANCE_YI = 0.05
RATE_TOLERANCE_PCT = 0.011


@dataclass
class ProvinceSource:
    province: str
    domain: str
    structure: str  # "pdf" | "html" | "docx" | "image" | "unknown"
    example_url: str
    notes: str = ""


# One verified real 2026 announcement URL per province, from the 2026-08-11
# research pass (6 parallel agents, 27 provinces). example_url is not meant
# to be re-fetched forever -- it's the calibration sample structure was
# confirmed against; pass a fresh URL to verify_announcement() for new
# months.
PROVINCE_SOURCES: dict[str, ProvinceSource] = {
    "上海市": ProvinceSource(
        "上海市", "czj.sh.gov.cn", "pdf",
        "https://czj.sh.gov.cn/zys_8908/gsgg_8929/czywgg_8930/dfzwfxjg/20260713/xxfboswf0000003751.html",
    ),
    "新疆维吾尔自治区": ProvinceSource(
        "新疆维吾尔自治区", "czt.xinjiang.gov.cn", "pdf",
        "https://czt.xinjiang.gov.cn/xjczt/c115017/202606/dca280a6218e4b54be9e3c1a5c53c1b0.shtml",
    ),
    "河北省": ProvinceSource(
        "河北省", "czt.hebei.gov.cn", "pdf",
        "http://czt.hebei.gov.cn/root17/zfxx/202608/t20260804_2407370.html",
    ),
    "贵州省": ProvinceSource(
        "贵州省", "czt.guizhou.gov.cn", "pdf",
        "https://czt.guizhou.gov.cn/zwgk/zdlyxx/zfzw/202607/t20260709_90604174.html",
        notes="Publishes on a regular near-monthly cadence (批次二~五 found for 2026 alone) -- "
              "good candidate for a recurring monthly check.",
    ),
    "江苏省": ProvinceSource(
        "江苏省", "czt.jiangsu.gov.cn", "pdf",
        "https://czt.jiangsu.gov.cn/art/2026/7/24/art_77314_11808314.html",
        notes="Confirmed scanned/OCR PDF -- expect missing coupon_rate_pct/term on some rows. "
              "Sibling announcements (e.g. a same-day refinancing-bond batch) may exist at "
              "neighboring art_77314_<id>.html URLs not covered by a single fetch.",
    ),
    "宁夏回族自治区": ProvinceSource(
        "宁夏回族自治区", "czt.nx.gov.cn", "html",
        "https://czt.nx.gov.cn/xwzx/tzgg/202606/t20260610_5261427.html",
        notes="Cleanest source of the batch -- inline HTML, no PDF/OCR step, verified byte-exact "
              "against celma on all 6 bonds in the calibration sample.",
    ),
    "宁波市": ProvinceSource(
        "宁波市", "czj.ningbo.gov.cn", "html",
        "http://czj.ningbo.gov.cn/art/2025/5/26/art_1229029201_58890796.html",
        notes="2026-dated example not yet located (search-index lag) -- URL pattern "
              "art/YYYY/M/D/art_1229029201_<id>.html confirmed stable since 2023.",
    ),
    "天津市": ProvinceSource(
        "天津市", "cz.tj.gov.cn", "image",
        "https://cz.tj.gov.cn/zwgk_53713/zfzq/202608/t20260804_7347170.html",
        notes="Bond data is embedded as JPG images, not PDF/HTML text. NOT IMPLEMENTED.",
    ),
    "湖南省": ProvinceSource(
        "湖南省", "czt.hunan.gov.cn", "docx",
        "https://czt.hunan.gov.cn/czt/dzqzfzjxx/202606/t20260625_34011506.html",
        notes="Attachment is .docx, not .pdf. NOT IMPLEMENTED -- needs `pip install python-docx`.",
    ),
    "重庆市": ProvinceSource(
        "重庆市", "czj.cq.gov.cn", "unknown",
        "https://czj.cq.gov.cn/zwgk_268/zfxxgkml/dfzfzw/202607/t20260729_15868828.html",
        notes="Cover URL real (6+ 2026 batches listed at this column) but WebFetch returned only "
              "metadata during research, not body/attachment -- structure genuinely unconfirmed.",
    ),
}

_BOND_BLOCK_RE = re.compile(r"债券名称")
_NAME_RE = re.compile(r"^(.+?)计划发行规模")
_AMOUNT_RE = re.compile(r"实际发行规模([\d.]+)亿元")
_PLANNED_AMOUNT_RE = re.compile(r"计划发行规模([\d.]+)亿元")
_TERM_RE = re.compile(r"发行期限(\d+)年")
_RATE_RE = re.compile(r"票面利率([\d.]+)%")
_ISSUE_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日已完成招标")
# Some provinces' templates (confirmed: 新疆) also carry 债券简称 -- when
# present it's a far more reliable join key than (province,date,term), so
# capture it opportunistically. OCR is confirmed (新疆 sample) to misread
# "债" as "贵" here, so match either. Short names look like "26新疆债26":
# 2-digit year, then arbitrary CJK, then a 1-3 digit trailing number.
_SHORTNAME_RE = re.compile(r"[债贵]券简称(\d{2}[^\d]{1,10}\d{1,3})")


def _strip_html_to_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "|", text)
    import html as htmlmod
    return htmlmod.unescape(text)


def parse_announcement_text(raw_text: str, province: str) -> list[dict]:
    """Shared parser for the standardized 财库〔2020〕43号/36号 disclosure
    template -- confirmed identical field vocabulary whether the source is
    clean HTML (宁夏) or OCR'd PDF text (江苏/新疆), just varying in how much
    noise corrupts individual fields. Returns rows with `bond_name`,
    `bond_short_name` (when the template carries one -- not all do, see
    module docstring), `total_amount_yi`, `term`, `coupon_rate_pct`,
    `issue_date`, `province`.

    Splits on "债券名称" to find bond block boundaries. This is confirmed
    FRAGILE against heavy OCR noise -- two distinct failure modes seen in
    the 2026-08-11 calibration sample:
      1. 新疆 (2026-06-11, 3-bond batch): OCR drops/garbles the "债券名称"
         label on 2 of 3 bonds, split finds only 1 boundary, one bond's
         票面利率 ends up attached to a different bond's total_amount_yi.
         Caught by comparing 债券简称/债券代码 occurrences (present in
         richer templates like 新疆's) against the number of blocks found.
      2. 河北 (2026-08-03, 4-bond batch mixing 一般/专项/再融资): OCR is bad
         enough that even 债券简称 mentions are mostly dropped too (only 1
         of 4 survived), so check #1 alone doesn't fire. Caught instead by
         checking whether other field-label keywords (债券代码/存续期/发行
         期限/票面利率/付息/到期日/计划发行/实际发行) leaked into the
         `bond_name` capture itself -- a clean bond name (even a legitimate
         hyphenated dual-name like 宁夏's "A方案名-B方案名" for one bond)
         never contains those labels; their presence means _NAME_RE's
         non-greedy match ran past a garbled/missing block boundary and
         swallowed a second bond's title plus stray label text.
    Either signal marks every row from the document as low-confidence.
    Rows this uncertain must never be treated as a clean amount/rate
    mismatch by diff_against_state -- always inspect `warnings` first."""
    text = re.sub(r"\s+", "", raw_text).replace("|", "")

    date_m = _ISSUE_DATE_RE.search(text)
    issue_date = f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}" if date_m else None

    blocks = _BOND_BLOCK_RE.split(text)[1:]
    expected_n = len(_SHORTNAME_RE.findall(text))
    shortname_count_mismatch = expected_n > 0 and expected_n != len(blocks)

    rows = []
    for b in blocks:
        name_m = _NAME_RE.match(b)
        amt_m = _AMOUNT_RE.search(b) or _PLANNED_AMOUNT_RE.search(b)
        term_m = _TERM_RE.search(b)
        rate_m = _RATE_RE.search(b)
        shortname_m = _SHORTNAME_RE.search(b)
        bond_name = name_m.group(1) if name_m else None
        leaked_labels = any(
            kw in (bond_name or "")
            for kw in ("债券代码", "存续期", "发行期限", "票面利率", "付息", "到期日", "计划发行", "实际发行")
        )
        row = {
            "province": province,
            "bond_name": bond_name,
            "bond_short_name": shortname_m.group(1) if shortname_m else None,
            "total_amount_yi": float(amt_m.group(1)) if amt_m else None,
            "term": f"{term_m.group(1)}Y" if term_m else None,
            "coupon_rate_pct": float(rate_m.group(1)) if rate_m else None,
            "issue_date": issue_date,
        }
        if shortname_count_mismatch:
            row["warnings"] = (
                f"文档内含{expected_n}处债券简称但只切分出{len(blocks)}个债券名称分块，"
                f"疑似OCR识别丢失部分'债券名称'标签导致相邻债券字段串块，"
                f"本行金额/期限/利率可能并非同一支债券，需人工核对原文"
            )
        elif leaked_labels:
            row["warnings"] = (
                f"债券名称字段内混入了'债券代码/存续期/票面利率'等字段标签文本，"
                f"疑似OCR丢失中间'债券名称'标签导致多支债券的标题和字段被合并进同一分块，"
                f"本行金额/期限/利率可能并非同一支债券，需人工核对原文"
            )
        rows.append(row)
    return rows


def _find_pdf_link(cover_html: str, base_url: str) -> str | None:
    m = re.search(r'href="([^"]+\.pdf)"', cover_html, re.I)
    if not m:
        return None
    href = m.group(1)
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin
    return urljoin(base_url, href)


def verify_announcement(province: str, url: str, use_cache: bool = True) -> list[dict]:
    """Fetch and parse one provincial 发行结果公告 URL. Returns a list of
    bond-row dicts (see parse_announcement_text). Raises NotImplementedError
    for structure types that aren't wired up yet (docx/image/unknown) --
    callers should catch this per-province rather than assuming every
    registered source is actually fetchable today."""
    src = PROVINCE_SOURCES.get(province)
    structure = src.structure if src else None

    if structure == "html":
        html = http_client.fetch(url, use_cache=use_cache)
        text = _strip_html_to_text(html)
        return parse_announcement_text(text, province)

    if structure == "pdf":
        cover_html = http_client.fetch(url, use_cache=use_cache)
        pdf_url = _find_pdf_link(cover_html, url)
        if not pdf_url:
            raise RuntimeError(f"no PDF link found on cover page {url}")
        pdf_path = http_client.fetch_pdf(pdf_url, use_cache=use_cache)
        result = pdf_extract.extract_pdf(pdf_path, use_cache=use_cache)
        rows = parse_announcement_text(result["text"], province)
        if result["method"] == "ocr":
            for r in rows:
                r["extraction_method"] = "ocr"
        return rows

    raise NotImplementedError(
        f"structure '{structure}' for {province} is not implemented "
        f"(see PROVINCE_SOURCES notes) -- docx needs python-docx, image needs OCR, "
        f"unknown needs a real structure check first"
    )


def diff_against_state(rows: list[dict], state_df) -> dict:
    """Cross-check parsed provincial rows against data/state_results.csv.
    Prefers matching on `bond_short_name` when the row has one (exact,
    reliable -- only some provincial templates carry it, see module
    docstring); falls back to (province, issue_date, term) otherwise, using
    amount to disambiguate same-day same-term multi-tranche bonds.

    Rows flagged `warnings` by parse_announcement_text (suspected
    OCR block-splitting cross-contamination) are routed to
    `low_confidence` instead of amount_mismatch/rate_mismatch -- a mismatch
    on a row whose fields might belong to two different bonds is not
    evidence of anything and must not be reported as a real discrepancy.

    Returns {"matched": [...], "amount_mismatch": [...], "rate_mismatch": [...],
    "not_found_in_state": [...], "low_confidence": [...]}, each a list of
    dicts with `row` (and `state_row` where matched), so a caller can print
    a clear report."""
    matched, amount_mismatch, rate_mismatch, not_found, low_confidence = [], [], [], [], []
    for row in rows:
        if row.get("warnings"):
            low_confidence.append({"row": row})
            continue

        candidates = None
        if row.get("bond_short_name"):
            hit = state_df[
                (state_df["province"] == row["province"])
                & (state_df["bond_short_name"] == row["bond_short_name"])
            ]
            if not hit.empty:
                candidates = hit

        if candidates is None:
            if row["issue_date"] is None or row["term"] is None:
                not_found.append({"row": row, "reason": "row itself missing issue_date/term, cannot match"})
                continue
            candidates = state_df[
                (state_df["province"] == row["province"])
                & (state_df["issue_date"] == row["issue_date"])
                & (state_df["term"] == row["term"])
            ]
            if candidates.empty:
                not_found.append({"row": row, "reason": "no state_results.csv row for this province/date/term"})
                continue
            if row["total_amount_yi"] is not None and len(candidates) > 1:
                close = candidates[(candidates["total_amount_yi"] - row["total_amount_yi"]).abs() <= AMOUNT_TOLERANCE_YI]
                if len(close) == 1:
                    candidates = close

        srow = candidates.iloc[0]
        entry = {"row": row, "state_row": srow.to_dict()}
        if row["total_amount_yi"] is not None and abs(row["total_amount_yi"] - srow["total_amount_yi"]) > AMOUNT_TOLERANCE_YI:
            amount_mismatch.append(entry)
        elif row["coupon_rate_pct"] is not None and abs(row["coupon_rate_pct"] - srow["coupon_rate_pct"]) > RATE_TOLERANCE_PCT:
            rate_mismatch.append(entry)
        else:
            matched.append(entry)
    return {"matched": matched, "amount_mismatch": amount_mismatch, "rate_mismatch": rate_mismatch,
            "not_found_in_state": not_found, "low_confidence": low_confidence}
