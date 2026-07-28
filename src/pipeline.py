"""End-to-end orchestration: crawl listings -> fetch detail pages -> download
PDF attachment(s) -> extract fields -> merge into two persistent state
tables (data/state_announcements.csv, data/state_plans.csv).

Re-running is incremental by default: URLs already present in a state file
are skipped entirely (no re-fetch, no re-parse, no re-download), and the
on-disk HTML/PDF caches mean even a from-scratch state rebuild doesn't
re-hit the network for pages/files already downloaded once.
"""
import sys

import pandas as pd

from . import config
from .article_parser import parse_article
from .extract_announcement import extract_announcement_fields
from .extract_plan import extract_plan_fields
from .http_client import fetch_pdf
from .listing_scraper import crawl_all_sources
from .pdf_extract import extract_pdf

ANNOUNCEMENT_COLUMNS = [
    "title", "pub_date", "url", "source_name", "doc_type", "province", "province_code",
    "category_code", "category_label", "category_subtype", "term", "batch_no",
    "issue_no", "issue_no_range", "total_amount_yi", "bid_date", "base_date_type",
    "payment_date", "listing_date", "natural_day_gap", "workday_gap", "doc_no",
    "bond_name", "extraction_method", "warnings",
]

PLAN_COLUMNS = [
    "title", "pub_date", "url", "source_name", "doc_type", "province", "province_code",
    "covered_year", "covered_month_start", "covered_month_end",
    "covered_period_start", "covered_period_end",
    "plan_general_amount_yi", "plan_special_amount_yi", "plan_refinancing_amount_yi",
    "extraction_method", "warnings",
]

DATE_COLS = {
    "announcements": ["pub_date", "bid_date", "payment_date", "listing_date"],
    "plans": ["pub_date", "covered_period_start", "covered_period_end"],
}
STATE_PATHS = {"announcements": config.STATE_ANNOUNCEMENTS_CSV, "plans": config.STATE_PLANS_CSV}
STATE_COLS = {"announcements": ANNOUNCEMENT_COLUMNS, "plans": PLAN_COLUMNS}


def load_state(kind: str) -> pd.DataFrame:
    path = STATE_PATHS[kind]
    if path.exists():
        df = pd.read_csv(path, dtype={"batch_no": "Int64", "issue_no": "Int64"} if kind == "announcements" else None)
        for col in DATE_COLS[kind]:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        return df
    return pd.DataFrame(columns=STATE_COLS[kind])


def save_state(kind: str, df: pd.DataFrame):
    df.to_csv(STATE_PATHS[kind], index=False)


def _pick_primary_pdf(attachments: list[dict], doc_type: str) -> dict | None:
    if not attachments:
        return None
    if doc_type == "announcement":
        for a in attachments:
            if "通知" in a["name"]:
                return a
        for a in attachments:
            if "发行公开" in a["name"]:
                return a
    else:
        for a in attachments:
            if "发行安排" in a["name"]:
                return a
    return attachments[0]


def process_listing_item(item: dict, use_cache: bool = True) -> tuple[list[dict], str]:
    """Returns (rows, status) where status in {"included", "no_attachment", "error"}."""
    try:
        article = parse_article(item["url"], use_cache=use_cache)
    except Exception as e:
        return [], f"error:fetch_failed:{e}"

    if not article["parse_ok"]:
        return [], "error:parse_incomplete"

    pdf_info = _pick_primary_pdf(article["attachments"], item["doc_type"])
    if pdf_info is None:
        return [], "no_attachment"

    try:
        pdf_path = fetch_pdf(pdf_info["url"], use_cache=use_cache)
        pdf_result = extract_pdf(pdf_path, use_cache=use_cache)
    except Exception as e:
        return [], f"error:pdf_failed:{e}"

    try:
        if item["doc_type"] == "announcement":
            rows = extract_announcement_fields(
                article["title"], article["pub_date"], item["url"], item["source_name"],
                item["doc_type"], pdf_result,
            )
        else:
            rows = [extract_plan_fields(
                article["title"], article["pub_date"], item["url"], item["source_name"],
                item["doc_type"], pdf_result,
            )]
    except Exception as e:
        return [], f"error:extract_failed:{e}"

    return rows, "included"


FLUSH_EVERY = 15  # persist to the state CSV every N processed items, not just
                   # at the very end -- a long batch (hundreds of items, some
                   # needing slow OCR) that gets interrupted would otherwise
                   # lose every row of work done since the run started.


def _merge_and_save(kind: str, state: pd.DataFrame, new_rows: list[dict]) -> pd.DataFrame:
    if not new_rows:
        return state
    new_df = pd.DataFrame(new_rows)
    for col in STATE_COLS[kind]:
        if col not in new_df.columns:
            new_df[col] = None
    new_df = new_df[STATE_COLS[kind]]
    state = pd.concat([state, new_df], ignore_index=True)
    dedup_keys = ["url", "issue_no", "term"] if kind == "announcements" else ["url"]
    state = state.drop_duplicates(subset=dedup_keys, keep="last")
    state = state.sort_values("pub_date").reset_index(drop=True)
    save_state(kind, state)
    return state


def _run_one_source(kind: str, items: list[dict], use_cache: bool, limit: int | None,
                     verbose: bool) -> pd.DataFrame:
    state = load_state(kind)
    seen_urls = set(state["url"]) if not state.empty else set()
    new_items = [it for it in items if it["url"] not in seen_urls]
    if limit is not None:
        new_items = new_items[:limit]

    if verbose:
        print(f"[pipeline:{kind}] {len(items)} listing items found, "
              f"{len(new_items)} not yet in state.", file=sys.stderr)

    pending_rows = []
    total_new_rows = 0
    counts = {"included": 0, "no_attachment": 0, "error": 0}
    for i, item in enumerate(new_items, 1):
        rows, status = process_listing_item(item, use_cache=use_cache)
        bucket = status.split(":")[0]
        counts[bucket] = counts.get(bucket, 0) + 1
        pending_rows.extend(rows)
        total_new_rows += len(rows)
        if i % FLUSH_EVERY == 0 or i == len(new_items):
            state = _merge_and_save(kind, state, pending_rows)
            pending_rows = []
        if verbose and (i % 20 == 0 or i == len(new_items)):
            print(f"[pipeline:{kind}] processed {i}/{len(new_items)} "
                  f"(included={counts['included']} no_attachment={counts['no_attachment']} "
                  f"error={counts['error']})", file=sys.stderr)

    if verbose:
        print(f"[pipeline:{kind}] done. status counts: {counts}. new rows: {total_new_rows}", file=sys.stderr)

    return state


def run(use_cache: bool = True, max_pages: int | None = None, limit: int | None = None,
        verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Crawl+process everything not already in state, append, save, return
    {"announcements": df, "plans": df}."""
    seen_urls_by_source = {
        "fxqgg": set(load_state("announcements")["url"]),
        "dfzfxjh": set(load_state("plans")["url"]),
    }
    listings = crawl_all_sources(use_cache=use_cache, max_pages=max_pages,
                                  seen_urls_by_source=seen_urls_by_source, new_item_target=limit)
    result = {}
    result["announcements"] = _run_one_source("announcements", listings["fxqgg"], use_cache, limit, verbose)
    result["plans"] = _run_one_source("plans", listings["dfzfxjh"], use_cache, limit, verbose)
    return result
