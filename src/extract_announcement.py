"""Field extraction for 发行前公告 (single-issuance pre-bidding announcements),
from the PDF text/tables produced by pdf_extract.extract_pdf().

One announcement PDF typically bundles several tranches (e.g. a 10Y general
bond + two special-bond maturities in one batch, all bid on the same day) --
each tranche becomes its own output row, matching how MOF's savings-bond
announcements split into per-period rows. The shared 时间安排 bid date is
read once from the whole-document text and copied onto every tranche row
extracted from that document.
"""
import datetime
import re

from . import config
from .classify import classify_bond_category, extract_province
from .numerals import cn_to_int, parse_issue_range
from .workdays import workday_diff

FULL_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
DATE_TOKEN = r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
DOC_NO_RE = re.compile(r"[一-龥]{2,8}〔\d{4}〕\d+\s*号")
BATCH_NO_RE = re.compile(r"第([一二三四五六七八九十百0-9]+)批")
ISSUE_LABEL_RE = re.compile(r"[（(]([^）)]{1,12}?期)[）)]")
TERM_RE = re.compile(r"(\d{1,2})\s*年(?:期)?")
AMOUNT_RE = re.compile(r"([\d,]+\.?\d*)")


class AnchorYearResolver:
    """Resolve a date token missing its year to the most recent *preceding*
    full-year date in the document -- PDFs state the year in full once per
    section, then drop it for nearby dates ('7 月 27 日开始计息' right after
    '2026 年 7 月 24 日...招标')."""

    def __init__(self, text: str, fallback_year: int | None):
        self.full_dates = [(m.start(), int(m.group(1))) for m in FULL_DATE_RE.finditer(text)]
        self.fallback_year = fallback_year

    def year_at(self, pos: int) -> int | None:
        candidates = [y for (p, y) in self.full_dates if p <= pos]
        return candidates[-1] if candidates else self.fallback_year


def _to_date(y, mo, d):
    try:
        return datetime.date(int(y), int(mo), int(d))
    except (ValueError, TypeError):
        return None


def _find_date(text: str, pattern: str, resolver: AnchorYearResolver):
    m = re.search(pattern, text)
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    if y is None:
        y = resolver.year_at(m.start())
        if y is None:
            return None
    return _to_date(y, mo, d)


def _term_bucket(text: str) -> str | None:
    m = TERM_RE.search(text)
    if not m:
        return None
    term = f"{int(m.group(1))}Y"
    return term if term in config.VALID_TERMS else term


def _find_table_columns(header_row: list) -> dict | None:
    idx = {}
    for i, cell in enumerate(header_row):
        c = (cell or "").replace("\n", "")
        if "债券名称" in c:
            idx["name"] = i
        elif "期限" in c:
            idx["term"] = i
        elif "面值" in c or ("亿元" in c and "费率" not in c):
            idx.setdefault("amount", i)
    if "term" in idx and "amount" in idx:
        return idx
    return None


def _extract_tranches_from_tables(tables: list[list[list]]) -> list[dict]:
    tranches = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        cols = _find_table_columns(table[0])
        if not cols:
            continue
        for row in table[1:]:
            if not row or all(c is None for c in row):
                continue
            name_cell = (row[cols["name"]] or "").replace("\n", "") if "name" in cols else ""
            term_cell = (row[cols["term"]] or "").replace("\n", "")
            amount_cell = (row[cols["amount"]] or "").replace("\n", "")
            if not term_cell and not amount_cell:
                continue
            term = _term_bucket(term_cell)
            am = AMOUNT_RE.search(amount_cell.replace(",", ""))
            amount = float(am.group(1)) if am else None
            category, subtype = classify_bond_category(name_cell)
            issue_label_m = ISSUE_LABEL_RE.search(name_cell)
            issue_nos = parse_issue_range(issue_label_m.group(1)) if issue_label_m else []
            tranches.append({
                "bond_name": name_cell or None,
                "term": term,
                "total_amount_yi": amount,
                "category_code": category,
                "category_subtype": subtype,
                "issue_no": issue_nos[0] if len(issue_nos) == 1 else None,
                "issue_no_range": ",".join(str(n) for n in issue_nos) if len(issue_nos) > 1 else None,
            })
    return tranches


def _base_row(title, pub_date, url, source_name, doc_type, province, province_code):
    return {
        "title": title, "pub_date": pub_date, "url": url, "source_name": source_name,
        "doc_type": doc_type, "province": province, "province_code": province_code,
        "category_code": None, "category_label": None, "category_subtype": None,
        "term": None, "batch_no": None, "issue_no": None, "issue_no_range": None,
        "total_amount_yi": None, "bid_date": None, "base_date_type": None,
        "payment_date": None, "listing_date": None, "doc_no": None,
        "bond_name": None, "extraction_method": None, "warnings": [],
    }


def extract_announcement_fields(title, pub_date, url, source_name, doc_type,
                                 pdf_result: dict) -> list[dict]:
    text = pdf_result["text"]
    tables = pdf_result["tables"]
    method = pdf_result["method"]

    province, province_code = extract_province(title)
    if province is None:
        province, province_code = extract_province(text[:2000])

    if method == "failed":
        row = _base_row(title, pub_date, url, source_name, doc_type, province, province_code)
        row["extraction_method"] = "failed"
        row["warnings"].append("PDF无文本层且OCR不可用/失败，疑似扫描件，字段留空需人工核对")
        row["warnings"] = "; ".join(row["warnings"])
        return [row]

    resolver = AnchorYearResolver(text, pub_date.year if pub_date else None)
    doc_no_m = DOC_NO_RE.search(text)
    doc_no = doc_no_m.group(0) if doc_no_m else None

    batch_m = BATCH_NO_RE.search(title)
    batch_no = cn_to_int(batch_m.group(1)) if batch_m else None

    bid_date = _find_date(text, DATE_TOKEN + r"[^\n]{0,25}?招标", resolver)
    payment_date = _find_date(text, DATE_TOKEN + r"[^\n]{0,15}?开始计息", resolver)
    listing_date = _find_date(text, DATE_TOKEN + r"[^\n]{0,20}?起[^\n]{0,20}?上市", resolver)

    batch_total_m = (
        re.search(r"计划发行总额\s*([\d,.]+)\s*亿元", text)
        or re.search(r"发行总额\s*([\d,.]+)\s*亿元", text)
        or re.search(r"招标总量\s*([\d,.]+)\s*亿元", text)
    )
    batch_total = float(batch_total_m.group(1).replace(",", "")) if batch_total_m else None

    tranches = _extract_tranches_from_tables(tables) if method == "text" else []

    rows = []
    if tranches:
        for t in tranches:
            row = _base_row(title, pub_date, url, source_name, doc_type, province, province_code)
            row.update({
                "category_code": t["category_code"],
                "category_label": config.CATEGORY_LABELS.get(t["category_code"]),
                "category_subtype": t["category_subtype"],
                "term": t["term"],
                "batch_no": batch_no,
                "issue_no": t["issue_no"],
                "issue_no_range": t["issue_no_range"],
                "total_amount_yi": t["total_amount_yi"],
                "bond_name": t["bond_name"],
                "bid_date": bid_date,
                "base_date_type": "招标日",
                "payment_date": payment_date,
                "listing_date": listing_date,
                "doc_no": doc_no,
                "extraction_method": method,
            })
            if row["category_code"] is None:
                row["warnings"].append("未能从债券名称识别品种(一般新增/专项新增/再融资)")
            if row["term"] is None:
                row["warnings"].append("未能识别发行期限")
            if bid_date is None:
                row["warnings"].append("未找到招标日期")
            if method == "ocr":
                row["warnings"].append("本行来自OCR识别，数值型字段准确性需人工核对")
            row["warnings"] = "; ".join(row["warnings"])
            rows.append(row)
    else:
        row = _base_row(title, pub_date, url, source_name, doc_type, province, province_code)
        category, subtype = classify_bond_category(title)
        row.update({
            "category_code": category,
            "category_label": config.CATEGORY_LABELS.get(category),
            "category_subtype": subtype,
            "batch_no": batch_no,
            "total_amount_yi": batch_total,
            "bid_date": bid_date,
            "base_date_type": "招标日" if bid_date else None,
            "payment_date": payment_date,
            "listing_date": listing_date,
            "doc_no": doc_no,
            "extraction_method": method,
        })
        row["warnings"].append("未能从表格解析分期明细，本行为整篇公告级别的合并记录")
        if category is None:
            row["warnings"].append("标题含多品种或无法识别品种，请查看PDF人工拆分")
        if bid_date is None:
            row["warnings"].append("未找到招标日期")
        if method == "ocr":
            row["warnings"].append("本行来自OCR识别，数值型字段准确性需人工核对")
        row["warnings"] = "; ".join(row["warnings"])
        rows.append(row)

    for row in rows:
        if row["bid_date"] and pub_date:
            gap = (row["bid_date"] - pub_date).days
            row["natural_day_gap"] = gap
            row["workday_gap"] = workday_diff(pub_date, row["bid_date"])
            if gap < 0:
                extra = ("公告发布日期晚于PDF内招标日期(负值)，可能是celma.org.cn平台镜像/上传延迟而非"
                         "真实违规，建议核对省级财政厅官网原始发布时间")
                row["warnings"] = (row["warnings"] + "; " + extra) if row["warnings"] else extra
        else:
            row["natural_day_gap"] = None
            row["workday_gap"] = None

    return rows
