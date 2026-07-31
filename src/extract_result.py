"""Field extraction for 发行结果 (post-issuance results), the source of
truth for each bond's actual market code.

Since ~early 2020, celma.org.cn publishes these as a standardized table
(表2-9 一般债券信息 / 表2-10 专项债券信息) with 债券编码 (numeric bond code)
and 债券简称 (short ticker, e.g. '26江苏债33') columns -- this is the
"dictionary" this module builds. Before that cutover, results were free-text
announcements with no bond code field at all (see extract_result_legacy.py,
handled as a separate pass); this module only handles the new table format
and returns an empty list for anything else, so callers can tell the two
eras apart via extraction_method == "unsupported_legacy_format".
"""
import re

from . import config
from .classify import extract_province

TERM_RE = re.compile(r"(\d{1,2})\s*年")
NEW_FORMAT_MARKER_RE = re.compile(r"表2-\d+")


def _term_bucket(text: str) -> str | None:
    m = TERM_RE.search(text or "")
    if not m:
        return None
    term = f"{int(m.group(1))}Y"
    return term if term in config.VALID_TERMS else term


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace(",", "").replace("\n", "").strip()
    try:
        return float(s)
    except ValueError:
        m = re.search(r"[\d.]+", s)
        return float(m.group(0)) if m else None


def _find_table_columns(header_row: list) -> dict | None:
    idx = {}
    wanted = {
        "bond_name": "债券名称", "bond_code": "债券编码", "bond_short_name": "债券简称",
        "bond_market_type": "债券类型", "term": "期限", "total_amount_yi": "发行规模",
        "new_amount_yi": "新增债券", "swap_amount_yi": "置换债券",
        "refi_amount_yi": "再融资债券", "batch_label": "发行批次", "coupon_rate_pct": "利率",
        "issue_date": "发行日期", "value_date": "起息日", "payment_freq": "付息方式",
        "redemption_structure": "赎回模式",
    }
    for i, cell in enumerate(header_row):
        c = (cell or "").replace("\n", "").replace(" ", "")
        for key, needle in wanted.items():
            if needle in c and key not in idx:
                idx[key] = i
    if "bond_code" in idx and "term" in idx:
        return idx
    return None


def _row_get(row: list, idx: dict, key: str) -> str | None:
    i = idx.get(key)
    if i is None or i >= len(row):
        return None
    v = row[i]
    return v.replace("\n", "") if isinstance(v, str) else v


def extract_result_fields(title, pub_date, url, source_name, doc_type, pdf_result: dict) -> list[dict]:
    text = pdf_result["text"]
    tables = pdf_result["tables"]
    method = pdf_result["method"]

    province, province_code = extract_province(title)
    if province is None:
        province, province_code = extract_province(text[:2000])

    if not NEW_FORMAT_MARKER_RE.search(text):
        # Pre-~2020 free-text format, no bond code field exists in the
        # source document at all -- handled separately, not a failure of
        # this extractor.
        return [{
            "title": title, "pub_date": pub_date, "url": url, "source_name": source_name,
            "doc_type": doc_type, "province": province, "province_code": province_code,
            "bond_name": None, "bond_code": None, "bond_short_name": None,
            "bond_market_type": None, "category_code": None, "category_label": None,
            "term": None, "total_amount_yi": None, "new_amount_yi": None,
            "swap_amount_yi": None, "refi_amount_yi": None, "batch_label": None,
            "coupon_rate_pct": None, "issue_date": None, "value_date": None,
            "payment_freq": None, "redemption_structure": None,
            "extraction_method": "unsupported_legacy_format",
            "warnings": "2020年以前的旧版发行结果公告无债券编码字段，需另行处理",
        }]

    rows = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        idx = _find_table_columns(table[0])
        if not idx:
            continue
        for raw_row in table[1:]:
            if not raw_row or all(c is None for c in raw_row):
                continue
            bond_code = _row_get(raw_row, idx, "bond_code")
            if not bond_code or not re.search(r"\d", str(bond_code)):
                continue
            bond_market_type = _row_get(raw_row, idx, "bond_market_type") or ""
            new_amt = _to_float(_row_get(raw_row, idx, "new_amount_yi"))
            swap_amt = _to_float(_row_get(raw_row, idx, "swap_amount_yi"))
            refi_amt = _to_float(_row_get(raw_row, idx, "refi_amount_yi"))

            if refi_amt and refi_amt > 0:
                category_code = config.CATEGORY_REFINANCING
            elif new_amt and new_amt > 0:
                category_code = (config.CATEGORY_NEW_SPECIAL if "专项" in bond_market_type
                                  else config.CATEGORY_NEW_GENERAL)
            elif swap_amt and swap_amt > 0:
                category_code = config.CATEGORY_REFINANCING  # 置换债券: pre-2019-style debt swap, closest analog
            else:
                category_code = None

            row = {
                "title": title, "pub_date": pub_date, "url": url, "source_name": source_name,
                "doc_type": doc_type, "province": province, "province_code": province_code,
                "bond_name": _row_get(raw_row, idx, "bond_name"),
                "bond_code": str(bond_code).strip(),
                "bond_short_name": _row_get(raw_row, idx, "bond_short_name"),
                "bond_market_type": bond_market_type or None,
                "category_code": category_code,
                "category_label": config.CATEGORY_LABELS.get(category_code),
                "term": _term_bucket(_row_get(raw_row, idx, "term")),
                "total_amount_yi": _to_float(_row_get(raw_row, idx, "total_amount_yi")),
                "new_amount_yi": new_amt, "swap_amount_yi": swap_amt, "refi_amount_yi": refi_amt,
                "batch_label": _row_get(raw_row, idx, "batch_label"),
                "coupon_rate_pct": _to_float(_row_get(raw_row, idx, "coupon_rate_pct")),
                "issue_date": _row_get(raw_row, idx, "issue_date"),
                "value_date": _row_get(raw_row, idx, "value_date"),
                "payment_freq": _row_get(raw_row, idx, "payment_freq"),
                "redemption_structure": _row_get(raw_row, idx, "redemption_structure"),
                "extraction_method": method,
                "warnings": "本行来自OCR识别，数值型字段准确性需人工核对" if method == "ocr" else "",
            }
            rows.append(row)

    if not rows:
        rows.append({
            "title": title, "pub_date": pub_date, "url": url, "source_name": source_name,
            "doc_type": doc_type, "province": province, "province_code": province_code,
            "bond_name": None, "bond_code": None, "bond_short_name": None,
            "bond_market_type": None, "category_code": None, "category_label": None,
            "term": None, "total_amount_yi": None, "new_amount_yi": None,
            "swap_amount_yi": None, "refi_amount_yi": None, "batch_label": None,
            "coupon_rate_pct": None, "issue_date": None, "value_date": None,
            "payment_freq": None, "redemption_structure": None,
            "extraction_method": method,
            "warnings": "表格标记为新版格式，但未能解析出任何债券编码行，需人工核对",
        })

    return rows
