"""Field extraction for 发行安排 (monthly/quarterly issuance-plan disclosures).

These follow a nationally standardized two-table template (表2-1 再融资债券
计划发行规模, 表2-2 新增一般/专项债券计划发行规模) mandated across all
provinces, so -- unlike the free-form 发行前公告 notices -- this extraction
is regex-driven against the whole-document text rather than per-tranche
table parsing (pdfplumber's table-geometry detection proved unreliable on
this particular borderless template; the text layer is not).
"""
import calendar
import datetime
import re

from .classify import extract_province

TITLE_MONTH_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
TITLE_QUARTER_RE = re.compile(r"(\d{4})\s*年第?([一二三四1234])\s*季度")
QUARTER_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}

REFI_BLOCK_RE = re.compile(r"时间\s*再融资债券计划发行规模\s*\n([^\n]+)")
NEW_BLOCK_RE = re.compile(r"时间\s*新增一般债券\s*新增专项债券\s*\n([^\n]+)")
# The period-label token (e.g. '8月', '三季度') must be stripped before
# hunting for amounts in the same line -- otherwise a blank/zero-suppressed
# row like '8月' (no amount printed at all) has its own '8' misread as the
# amount. Only digits *after* this leading label are real data.
PERIOD_LABEL_RE = re.compile(r"^\s*(?:\d{1,2}\s*月|第?[一二三四]\s*季度)\s*")
NUM_RE = re.compile(r"[\d,]+\.?\d*")


def _covered_period(title: str, text: str) -> tuple[int | None, int | None, int | None]:
    """Returns (year, month_start, month_end) covering the disclosed period.
    Monthly plans have month_start == month_end; quarterly plans span 3 months."""
    m = TITLE_QUARTER_RE.search(title) or TITLE_QUARTER_RE.search(text[:200])
    if m:
        year = int(m.group(1))
        q = QUARTER_CN.get(m.group(2))
        if q:
            return year, (q - 1) * 3 + 1, q * 3
    m = TITLE_MONTH_RE.search(title) or TITLE_MONTH_RE.search(text[:200])
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        return year, month, month
    return None, None, None


def _strip_period_label(line: str) -> str:
    return PERIOD_LABEL_RE.sub("", line, count=1)


def _last_amount(line: str) -> float | None:
    nums = NUM_RE.findall(_strip_period_label(line).replace(",", ""))
    return float(nums[-1]) if nums else None


def _line_amounts(line: str, n: int) -> list[float | None]:
    nums = NUM_RE.findall(_strip_period_label(line).replace(",", ""))
    if len(nums) < n:
        return [None] * n
    tail = nums[-n:]
    return [float(x) for x in tail]


def extract_plan_fields(title, pub_date, url, source_name, doc_type, pdf_result: dict) -> dict:
    text = pdf_result["text"]
    method = pdf_result["method"]
    province, province_code = extract_province(title)
    if province is None:
        province, province_code = extract_province(text[:2000])

    row = {
        "title": title, "pub_date": pub_date, "url": url, "source_name": source_name,
        "doc_type": doc_type, "province": province, "province_code": province_code,
        "covered_year": None, "covered_month_start": None, "covered_month_end": None,
        "covered_period_start": None, "covered_period_end": None,
        "plan_general_amount_yi": None, "plan_special_amount_yi": None,
        "plan_refinancing_amount_yi": None, "extraction_method": method,
        "warnings": [],
    }

    if method == "failed":
        row["warnings"].append("PDF无文本层且OCR不可用/失败，疑似扫描件，字段留空需人工核对")
        row["warnings"] = "; ".join(row["warnings"])
        return row

    year, mstart, mend = _covered_period(title, text)
    row["covered_year"] = year
    row["covered_month_start"] = mstart
    row["covered_month_end"] = mend
    if year and mstart:
        row["covered_period_start"] = datetime.date(year, mstart, 1)
        last_day = calendar.monthrange(year, mend)[1]
        row["covered_period_end"] = datetime.date(year, mend, last_day)
    else:
        row["warnings"].append("未能从标题识别计划覆盖的月份/季度")

    refi_m = REFI_BLOCK_RE.search(text)
    if refi_m:
        row["plan_refinancing_amount_yi"] = _last_amount(refi_m.group(1))
    else:
        row["warnings"].append("未找到再融资债券计划发行规模(表2-1)")

    new_m = NEW_BLOCK_RE.search(text)
    if new_m:
        general, special = _line_amounts(new_m.group(1), 2)
        row["plan_general_amount_yi"] = general
        row["plan_special_amount_yi"] = special
    else:
        row["warnings"].append("未找到新增一般/专项债券计划发行规模(表2-2)")

    if method == "ocr":
        row["warnings"].append("本行来自OCR识别，数值型字段准确性需人工核对")

    row["warnings"] = "; ".join(row["warnings"])
    return row
