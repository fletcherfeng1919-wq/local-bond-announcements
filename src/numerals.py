"""Chinese numeral -> int helpers, used for batch/issue numbers like
'十二期' or ranges like '十二至十三期'."""
import re

import cn2an


def cn_to_int(text: str) -> int | None:
    """Convert a Chinese or Arabic numeral string to int. Returns None on failure."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return int(text)
    try:
        return int(cn2an.cn2an(text, "smart"))
    except Exception:
        return None


def parse_issue_range(text: str) -> list[int]:
    """'十二至十三期' / '十二期至十三期' / '十二期' / '12-13期' -> [12, 13] or [12].
    Returns [] if nothing parseable."""
    if not text:
        return []
    text = text.strip().rstrip("期")
    if "至" in text or "-" in text or "~" in text:
        parts = re.split(r"[至\-~]", text)
        lo = cn_to_int(parts[0].strip().rstrip("期"))
        hi = cn_to_int(parts[-1].strip().rstrip("期"))
        if lo is not None and hi is not None and hi >= lo:
            return list(range(lo, hi + 1))
        return [x for x in (lo, hi) if x is not None]
    n = cn_to_int(text)
    return [n] if n is not None else []
