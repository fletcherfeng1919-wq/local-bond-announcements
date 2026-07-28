"""Title/text based classification: which province, and which of the three
bond categories (一般新增 / 专项新增 / 再融资) a piece of text describes."""
from . import config


def extract_province(text: str) -> tuple[str | None, str | None]:
    """Search (not anchor-match) for a known province/municipality name
    inside `text`. Longest names are tried first so '新疆生产建设兵团' isn't
    shadowed by the shorter '新疆维吾尔自治区' -- both start with '新疆'."""
    if not text:
        return None, None
    for name in config.PROVINCE_NAMES_BY_LEN_DESC:
        if name in text:
            return name, config.PROVINCES[name]
    return None, None


def classify_bond_category(name_text: str) -> tuple[str | None, str | None]:
    """Classify a single 债券名称-style string into one of the three
    top-level categories, plus an optional subtype ('一般'/'专项') that only
    applies within 再融资 (refinancing bonds are themselves issued as either
    general or special, but the user wants them kept in one 再融资 bucket at
    the top level)."""
    if not name_text:
        return None, None
    is_refinancing = "再融资" in name_text
    is_special = "专项" in name_text
    is_general = "一般" in name_text

    if is_refinancing:
        subtype = "专项" if is_special else ("一般" if is_general else None)
        return config.CATEGORY_REFINANCING, subtype
    if is_special:
        return config.CATEGORY_NEW_SPECIAL, None
    if is_general:
        return config.CATEGORY_NEW_GENERAL, None
    return None, None
