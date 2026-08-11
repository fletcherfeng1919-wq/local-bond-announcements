"""Reconcile data/state_results.csv against a manually-exported Wind "地方
政府债" 一级市场 report.

Why this exists: celma.org.cn's own PDF extraction has real, systemic
failure modes that plain re-scraping can't fix --
  1. Multi-tranche bonds: a single bond_code sometimes appears as 2-3 rows
     within one PDF table (e.g. a 专项债券 split across 项目收益/棚改/土地
     储备 sub-purposes under one combined bond code). pipeline.py's merge
     dedupes on bond_code and keeps the *last* row, silently discarding
     the other tranches' amounts instead of summing them -- understating
     total_amount_yi.
  2. Bundled notices: when one "通知" PDF covers several separate batches
     that each get their own celma listing page, _pick_primary_pdf's
     "通知"-first heuristic pulls the document-level combined total onto
     every one of those separate listings instead of each batch's own
     amount.
  3. OCR failures on scanned PDFs sometimes can't find bid_date/issue_date
     at all, silently dropping the row from every date-filtered view even
     though it's sitting right there in the CSV.
Comparing against a Wind export (verified empirically to use the exact
same 债券简称/短称 convention as celma) surfaces exactly which rows are
wrong or missing without having to re-engineer every PDF edge case.

This is NOT a live/automated source. There's no public API here -- it's
whatever *.xlsx the user has manually exported from Wind and dropped in
the project root. Re-run reconcile_from_wind_file() by hand whenever a
fresher export shows up; it's idempotent (a second run against the same
file and an already-reconciled CSV reports zero diffs).
"""
import re

import pandas as pd

from . import config

RESULT_COLUMNS = [
    "title", "pub_date", "url", "source_name", "doc_type", "province", "province_code",
    "bond_name", "bond_code", "bond_short_name", "bond_market_type",
    "category_code", "category_label", "term", "total_amount_yi",
    "new_amount_yi", "swap_amount_yi", "refi_amount_yi", "batch_label",
    "coupon_rate_pct", "issue_date", "value_date", "payment_freq",
    "redemption_structure", "extraction_method", "warnings",
]

AMOUNT_TOLERANCE_YI = 0.05
RATE_TOLERANCE_PCT = 0.011

# 债券简称 (e.g. "26河北债44") drops the standard "XX省/XX市/XX自治区" suffix
# down to a bare province name -- build the reverse lookup once from
# config.PROVINCES rather than hardcoding a second province list to keep
# in sync by hand.
_SUFFIXES = ["维吾尔自治区", "回族自治区", "壮族自治区", "自治区", "省", "市"]


def _build_abbrev_map() -> dict[str, str]:
    m = {}
    for full in config.PROVINCES:
        ab = full
        for suf in _SUFFIXES:
            if full.endswith(suf):
                ab = full[: -len(suf)]
                break
        m[ab] = full
    m["兵团"] = "新疆生产建设兵团"  # short name uses "兵团", not "新疆生产建设兵团"
    return m


_ABBREV_TO_FULL = _build_abbrev_map()
_ABBREV_BY_LEN_DESC = sorted(_ABBREV_TO_FULL.keys(), key=len, reverse=True)


def _province_from_shortname(shortname) -> str | None:
    if not isinstance(shortname, str):
        return None
    body = shortname[2:] if shortname[:2].isdigit() else shortname  # strip "26"/"25" year prefix
    for ab in _ABBREV_BY_LEN_DESC:
        if body.startswith(ab):
            return _ABBREV_TO_FULL[ab]
    return None


def _clean_term(term) -> str | None:
    if pd.isna(term):
        return None
    return re.split(r"[(（]", str(term))[0].strip()


def _category(nature, kind) -> tuple[str, str]:
    if "再融资" in str(nature):
        code = config.CATEGORY_REFINANCING
    elif str(kind) == "专项债券":
        code = config.CATEGORY_NEW_SPECIAL
    else:
        code = config.CATEGORY_NEW_GENERAL
    return code, config.CATEGORY_LABELS[code]


def load_wind_export(xlsx_path) -> pd.DataFrame:
    """Parse a Wind "地方政府债" 一级市场 export into a clean bond-level
    frame keyed by bond_short_name. Only rows with a confirmed rate
    (发行利率 not "--") are kept -- unpriced/future rows belong in the
    dashboard's forward-looking plan/calendar sections, not in the
    confirmed-results reconciliation."""
    raw = pd.read_excel(xlsx_path, sheet_name="一级市场").iloc[:, 1:]
    raw = raw.dropna(subset=["发行日", "证券简称"]).copy()
    raw = raw[pd.to_numeric(raw["发行利率"], errors="coerce").notna()]
    raw["发行日"] = pd.to_datetime(raw["发行日"])

    cat = raw.apply(lambda r: _category(r["性质"], r["类别"]), axis=1)
    df = pd.DataFrame({
        "bond_short_name": raw["证券简称"],
        "issue_date": raw["发行日"].dt.strftime("%Y-%m-%d"),
        "term": raw["期限"].map(_clean_term),
        "total_amount_yi": pd.to_numeric(raw["发行额(亿)"], errors="coerce").round(2),
        "coupon_rate_pct": pd.to_numeric(raw["发行利率"], errors="coerce"),
        "province": raw["证券简称"].map(_province_from_shortname),
        "category_code": [c[0] for c in cat],
        "category_label": [c[1] for c in cat],
    })
    return df.drop_duplicates(subset=["bond_short_name"], keep="last")


def diff_against_state(wind_df: pd.DataFrame, state_df: pd.DataFrame) -> dict:
    """Returns {"missing": [...], "amount_mismatch": [...], "rate_mismatch": [...],
    "date_missing": [...], "duplicate_short_names": [...]}, each a list of
    bond_short_name strings. The lookup against state_results.csv is
    deliberately GLOBAL (not scoped to wind_df's own date range) -- some
    existing rows have a correct amount/rate but a null issue_date (celma
    extraction failure, unrelated to Wind), and date-scoping the lookup
    would make those invisible and cause a duplicate row to be added
    instead of the existing one being patched."""
    lookup_all = state_df.dropna(subset=["bond_short_name"])
    duplicate_short_names = sorted(
        lookup_all[lookup_all.duplicated(subset=["bond_short_name"], keep=False)]["bond_short_name"].unique().tolist()
    )
    lookup = lookup_all.drop_duplicates(subset=["bond_short_name"], keep="last").set_index("bond_short_name")

    missing, amount_mismatch, rate_mismatch, date_missing = [], [], [], []
    for _, wrow in wind_df.iterrows():
        sn = wrow["bond_short_name"]
        if sn not in lookup.index:
            missing.append(sn)
            continue
        orow = lookup.loc[sn]
        if pd.isna(orow["total_amount_yi"]) or abs(wrow["total_amount_yi"] - orow["total_amount_yi"]) > AMOUNT_TOLERANCE_YI:
            amount_mismatch.append(sn)
        if pd.notna(wrow["coupon_rate_pct"]) and (
            pd.isna(orow["coupon_rate_pct"]) or abs(wrow["coupon_rate_pct"] - orow["coupon_rate_pct"]) > RATE_TOLERANCE_PCT
        ):
            rate_mismatch.append(sn)
        if pd.isna(orow["issue_date"]) or str(orow["issue_date"])[:10] != wrow["issue_date"]:
            date_missing.append(sn)
    return {
        "missing": missing, "amount_mismatch": amount_mismatch, "rate_mismatch": rate_mismatch,
        "date_missing": date_missing, "duplicate_short_names": duplicate_short_names,
    }


def _new_row_from_wind(wrow: pd.Series) -> dict:
    row = {c: None for c in RESULT_COLUMNS}
    row.update({
        "doc_type": "result",
        "source_name": "wind_reconcile",
        "province": wrow["province"],
        "bond_short_name": wrow.name,
        "category_code": wrow["category_code"],
        "category_label": wrow["category_label"],
        "term": wrow["term"],
        "total_amount_yi": wrow["total_amount_yi"],
        "coupon_rate_pct": wrow["coupon_rate_pct"],
        "issue_date": wrow["issue_date"],
        "pub_date": wrow["issue_date"],
        "extraction_method": "wind_reconcile",
        "warnings": "本行来自Wind一级市场导出人工核对补录，celma未能提取或未发布，无债券编码/发行人全称",
    })
    return row


def reconcile_from_wind_file(xlsx_path, state_results_path=None, dry_run: bool = False) -> dict:
    """Applies the reconciliation to data/state_results.csv in place (unless
    dry_run=True). Returns a summary dict with before/after counts and the
    diff lists, so a caller can print a clear report either way."""
    state_results_path = state_results_path or config.STATE_RESULTS_CSV
    wind_df = load_wind_export(xlsx_path)
    state_df = pd.read_csv(state_results_path)

    diff = diff_against_state(wind_df, state_df)
    wind_lookup = wind_df.set_index("bond_short_name")

    # Pre-existing duplicate bond_short_names (celma reported the same bond
    # twice under different bond_codes -- unrelated to Wind, but Wind's
    # single record per short name lets us resolve them here too, since
    # they're exactly the rows that make "patch the matching row" ambiguous.
    # Keep the single row with the larger total_amount_yi (closer to Wind's
    # true total in every case checked) and drop the rest.
    dupes_in_wind = set(diff["duplicate_short_names"]) & set(wind_lookup.index)
    dropped_dupe_rows = 0
    for sn in dupes_in_wind:
        idx = state_df.index[state_df["bond_short_name"] == sn]
        if len(idx) < 2:
            continue
        keep = state_df.loc[idx, "total_amount_yi"].idxmax()
        drop = [i for i in idx if i != keep]
        state_df = state_df.drop(index=drop)
        dropped_dupe_rows += len(drop)

    fixed_amount = 0
    fixed_rate = 0
    fixed_date = 0
    touched = set(diff["amount_mismatch"]) | set(diff["rate_mismatch"]) | set(diff["date_missing"])
    for sn in touched:
        idx = state_df.index[state_df["bond_short_name"] == sn]
        if len(idx) == 0:
            continue
        i = idx[-1]
        wrow = wind_lookup.loc[sn]
        note = []
        if sn in diff["amount_mismatch"]:
            old = state_df.at[i, "total_amount_yi"]
            state_df.at[i, "total_amount_yi"] = wrow["total_amount_yi"]
            note.append(f"total_amount_yi由{old}订正为{wrow['total_amount_yi']}(Wind核对)")
            fixed_amount += 1
        if sn in diff["rate_mismatch"]:
            old = state_df.at[i, "coupon_rate_pct"]
            state_df.at[i, "coupon_rate_pct"] = wrow["coupon_rate_pct"]
            note.append(f"coupon_rate_pct由{old}订正为{wrow['coupon_rate_pct']}(Wind核对)")
            fixed_rate += 1
        if sn in diff["date_missing"]:
            old = state_df.at[i, "issue_date"]
            state_df.at[i, "issue_date"] = wrow["issue_date"]
            note.append(f"issue_date由{old}订正为{wrow['issue_date']}(Wind核对)")
            fixed_date += 1
        existing_warn = state_df.at[i, "warnings"]
        new_warn = "; ".join(note)
        state_df.at[i, "warnings"] = f"{existing_warn}; {new_warn}" if isinstance(existing_warn, str) and existing_warn else new_warn

    new_rows = [_new_row_from_wind(wind_lookup.loc[sn]) for sn in diff["missing"]]
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        for c in RESULT_COLUMNS:
            if c not in new_df.columns:
                new_df[c] = None
        state_df = pd.concat([state_df, new_df[RESULT_COLUMNS]], ignore_index=True)

    # Match pipeline.py's own merge convention (sorts by pub_date, not
    # issue_date) so this doesn't reorder rows in a way that looks like an
    # unrelated diff when the CSV is next committed.
    state_df = state_df.sort_values("pub_date").reset_index(drop=True)

    if not dry_run:
        state_df.to_csv(state_results_path, index=False)

    return {
        "wind_rows": len(wind_df),
        "missing_added": len(new_rows),
        "amount_fixed": fixed_amount,
        "rate_fixed": fixed_rate,
        "date_fixed": fixed_date,
        "duplicate_rows_dropped": dropped_dupe_rows,
        "diff": diff,
        "final_row_count": len(state_df),
    }
