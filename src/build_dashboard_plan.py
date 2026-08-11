"""Refresh the "本月/下月发行计划" section of the interactive HTML dashboard
(output/bond_analysis_dashboard.html) from the current data/state_plans.csv.

The dashboard is a single static HTML file with hand-authored JS chart data --
everywhere else in it is written once and edited by hand when the underlying
analysis changes. This section is different: it shows forward-looking
"发行安排" (issuance plan) data for the current and next calendar month, which
is genuinely stale the day after it's written and shifts every month (this
month's plan becomes irrelevant history, next month's becomes current). So
instead of hardcoding numbers, the dashboard's drawPlan() function brackets
its data lines with PLAN_DATA_START/PLAN_DATA_END marker comments, and this
module's refresh_plan_section() finds-and-replaces only the text between
those markers -- every other hand-written line in the file (including
drawPlan()'s own layout/rendering code) is left untouched.

Called from main.py after each pipeline run, so `python main.py` keeps this
section current -- both in the sense of pulling fresh state_plans.csv rows
and in the sense of "current/next month" rolling forward on its own as real
time passes -- without anyone hand-editing the dashboard HTML.
"""
import re

import pandas as pd

from . import config
from .sse_listing import fetch_recent_listing_notices

DASHBOARD_PATH = config.OUTPUT_DIR / "bond_analysis_dashboard.html"

CAT_COLS = ["plan_general_amount_yi", "plan_special_amount_yi", "plan_refinancing_amount_yi"]

PLAN_BLOCK_RE = re.compile(
    r"(    // PLAN_DATA_START.*?\n)(.*?)(    // PLAN_DATA_END\n)",
    re.DOTALL,
)


def _current_and_next_month() -> tuple[pd.Timestamp, pd.Timestamp]:
    today = pd.Timestamp.now().normalize()
    this_month = pd.Timestamp(year=today.year, month=today.month, day=1)
    next_month = this_month + pd.DateOffset(months=1)
    return this_month, next_month


def _month_slice(df: pd.DataFrame, period: pd.Timestamp) -> dict | None:
    sub = df[df["covered_period_start"] == period]
    if sub.empty:
        return None
    prov = sub.groupby("province")[CAT_COLS].sum()
    prov["total"] = prov.sum(axis=1)
    prov = prov.sort_values("total", ascending=False)

    region = sub.assign(region=sub["province"].map(config.PROVINCE_TO_REGION))
    region_agg = region.groupby("region")[CAT_COLS].sum().reindex(config.REGION_ORDER).fillna(0.0)

    as_of = sub["pub_date"].dropna().max()
    return {
        "label": f"{period.year}年{period.month}月",
        "covered": int(prov.shape[0]),
        "total": len(config.PROVINCES),
        "totalYi": round(float(prov["total"].sum()), 1),
        "asOf": as_of.strftime("%Y-%m-%d") if pd.notna(as_of) else "",
        "provinces": [
            {
                "province": p,
                "general": round(float(r.plan_general_amount_yi), 2),
                "special": round(float(r.plan_special_amount_yi), 2),
                "refi": round(float(r.plan_refinancing_amount_yi), 2),
            }
            for p, r in prov.iterrows()
        ],
        "regions": [
            {
                "region": reg,
                "general": round(float(r.plan_general_amount_yi), 2),
                "special": round(float(r.plan_special_amount_yi), 2),
                "refi": round(float(r.plan_refinancing_amount_yi), 2),
            }
            for reg, r in region_agg.iterrows()
        ],
    }


def _build_plan_data(plan_df: pd.DataFrame):
    """Returns {"this": {...} | None, "next": {...} | None} for the current
    and next calendar month, or None overall if state_plans.csv has no usable
    covered_period_start values at all yet. A month with no announcements
    published so far is kept as None (not synthesized as a zero row) so the
    dashboard can render an explicit "尚未公布" state instead of a misleading
    empty chart."""
    df = plan_df.dropna(subset=["covered_period_start"]).copy()
    if df.empty:
        return None
    # load_state() parses this column via `.dt.date`, giving plain
    # datetime.date objects -- comparing those to a pd.Timestamp below is
    # silently always False (different types, not a raised error), so
    # normalize to Timestamp here rather than at every comparison site.
    df["covered_period_start"] = pd.to_datetime(df["covered_period_start"])
    for c in CAT_COLS:
        df[c] = df[c].fillna(0.0)
    this_month, next_month = _current_and_next_month()
    this_data = _month_slice(df, this_month)
    next_data = _month_slice(df, next_month)
    if this_data is None and next_data is None:
        return None
    return {"this": this_data, "next": next_data}


def _js_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _js_null_or(month: dict | None) -> str:
    if month is None:
        return "null"
    prov_lines = ",\n        ".join(
        '{ province: %s, general: %.2f, special: %.2f, refi: %.2f }'
        % (_js_string(r["province"]), r["general"], r["special"], r["refi"])
        for r in month["provinces"]
    )
    region_lines = ",\n        ".join(
        '{ region: %s, general: %.2f, special: %.2f, refi: %.2f }'
        % (_js_string(r["region"]), r["general"], r["special"], r["refi"])
        for r in month["regions"]
    )
    return (
        "{\n"
        f"      label: {_js_string(month['label'])}, asOf: {_js_string(month['asOf'])}, "
        f"covered: {month['covered']}, total: {month['total']}, totalYi: {month['totalYi']},\n"
        f"      provinces: [\n        {prov_lines},\n      ],\n"
        f"      regions: [\n        {region_lines},\n      ],\n"
        "    }"
    )


def _render_js_block(built: dict) -> str:
    return (
        f"    const planData = {{\n"
        f"      thisMonth: {_js_null_or(built['this'])},\n"
        f"      nextMonth: {_js_null_or(built['next'])},\n"
        f"    }};\n"
    )


CALENDAR_BLOCK_RE = re.compile(
    r"(    // CALENDAR_DATA_START.*?\n)(.*?)(    // CALENDAR_DATA_END\n)",
    re.DOTALL,
)


def _calendar_month_slice(result_df: pd.DataFrame, ann_df: pd.DataFrame, period: pd.Timestamp,
                           latest_confirmed: pd.Timestamp, sse_listed: list[dict] | None = None) -> dict | None:
    """Build one month's calendar (day -> {n, amountYi, bonds, status}) for
    [period, period+1month). Three source types, never blended within a day:
    - *confirmed* days come from 发行结果/state_results.csv (issue_date) --
      settled auctions with a final coupon rate. Always wins if a date has
      confirmed rows.
    - *listed* days come from SSE's 上市公告 feed (src/sse_listing.py),
      keyed by the listing notice's own publish date -- a DIFFERENT date
      concept than issue_date/bid_date (it's when the bond starts trading,
      typically a couple days after auction, not the auction day itself).
      Confirms the bond was successfully issued, but the notice itself
      carries no coupon rate, so couponPct stays null and status is
      "listed" ("已上市，利率待补"). Same-day-or-next-day faster than
      celma's confirmed results, so it's the second priority.
    - *scheduled* days come from 发行前公告/state_announcements.csv (bid_date)
      -- the auction date is real and already public, but the coupon isn't
      set until the auction happens, so couponPct stays null and the day is
      flagged status="scheduled". Lowest priority: only fills in dates with
      neither a confirmed nor a listed entry yet.
    Because "listed" and "scheduled" key off different date concepts for the
    same underlying bond, the same bond can legitimately appear on two
    different calendar days (once as "scheduled" on its bid_date, once as
    "listed" on its later listing-notice date) until celma's confirmed
    result supersedes both -- this is a known, accepted simplification, not
    deduplicated against each other; see build_dashboard_plan.py docstring.
    Returns None if the month has no rows in any of the three sources at
    all (true for any month far enough in the future that it hasn't been
    announced yet). 发行安排 (monthly-only plan totals, no day field) is
    deliberately never used here -- there's no date to place it on."""
    month_end = period + pd.offsets.MonthEnd(1)
    days = {}

    month_results = result_df[(result_df["issue_date"] >= period) & (result_df["issue_date"] <= month_end)]
    for day, day_df in month_results.groupby(month_results["issue_date"].dt.strftime("%Y-%m-%d")):
        bonds = [
            {
                "province": r.province,
                "bondShortName": r.bond_short_name if pd.notna(r.bond_short_name) else r.bond_name,
                "term": r.term,
                "amountYi": round(float(r.total_amount_yi), 2) if pd.notna(r.total_amount_yi) else None,
                "couponPct": round(float(r.coupon_rate_pct), 2) if pd.notna(r.coupon_rate_pct) else None,
            }
            for r in day_df.sort_values("total_amount_yi", ascending=False).itertuples()
        ]
        days[day] = {
            "n": len(day_df),
            "amountYi": round(float(day_df["total_amount_yi"].sum()), 1),
            "bonds": bonds,
            "status": "confirmed",
        }

    listed_through = None
    if sse_listed:
        by_day: dict[str, list[dict]] = {}
        for row in sse_listed:
            d = row["sseDate"]
            period_str_start = period.strftime("%Y-%m-%d")
            period_str_end = month_end.strftime("%Y-%m-%d")
            if not (period_str_start <= d <= period_str_end):
                continue
            by_day.setdefault(d, []).append(row)
        if by_day:
            listed_through = max(by_day.keys())
        for day, rows in by_day.items():
            if day in days:
                continue  # confirmed already covers this date
            bonds = [
                {
                    "province": r["province"] or "--",
                    "bondShortName": r["securityAbbr"] or "--",
                    "term": "--",
                    "amountYi": None,
                    "couponPct": None,
                }
                for r in rows
            ]
            days[day] = {
                "n": len(rows),
                "amountYi": 0.0,
                "bonds": bonds,
                "status": "listed",
            }

    scheduled_through = None
    if ann_df is not None and not ann_df.empty:
        month_ann = ann_df[(ann_df["bid_date"] >= period) & (ann_df["bid_date"] <= month_end)]
        if not month_ann.empty:
            scheduled_through = month_ann["bid_date"].max()
        for day, day_df in month_ann.groupby(month_ann["bid_date"].dt.strftime("%Y-%m-%d")):
            if day in days:
                continue  # confirmed already covers this date; don't duplicate/downgrade it
            bonds = [
                {
                    "province": r.province,
                    "bondShortName": r.bond_name if pd.notna(r.bond_name) else "(简称待公布)",
                    "term": r.term if pd.notna(r.term) else "--",
                    "amountYi": round(float(r.total_amount_yi), 2) if pd.notna(r.total_amount_yi) else None,
                    "couponPct": None,
                }
                for r in day_df.sort_values("total_amount_yi", ascending=False).itertuples()
            ]
            days[day] = {
                "n": len(day_df),
                "amountYi": round(float(day_df["total_amount_yi"].sum()), 1),
                "bonds": bonds,
                "status": "scheduled",
            }

    if not days:
        return None

    # asOf is the same "latest confirmed issue_date across all data" for both
    # months, not this month's own max -- a month that has zero confirmed
    # rows so far still needs a truthful "as of" date to explain *why*
    # (results haven't caught up to today yet), rather than reporting none.
    return {
        "monthLabel": f"{period.year}年{period.month}月",
        "asOf": latest_confirmed.strftime("%Y-%m-%d") if pd.notna(latest_confirmed) else None,
        "listedThrough": listed_through,
        "scheduledThrough": scheduled_through.strftime("%Y-%m-%d") if scheduled_through is not None and pd.notna(scheduled_through) else None,
        "days": days,
    }


def _build_calendar_data(result_df: pd.DataFrame, announcement_df: pd.DataFrame | None = None):
    """Returns {"this": {...} | None, "next": {...} | None} for the current
    and next calendar month, mirroring _build_plan_data's this/next-month
    shape. Confirmed days (发行结果) always take priority; scheduled days
    (发行前公告 bid_date) fill in dates confirmed data hasn't reached yet.
    Returns None overall only if there's no usable date in either source."""
    df = result_df.dropna(subset=["issue_date"]).copy()
    ann = None
    if announcement_df is not None:
        ann = announcement_df.dropna(subset=["bid_date"]).copy()
        if not ann.empty:
            ann["bid_date"] = pd.to_datetime(ann["bid_date"])
            ann["total_amount_yi"] = ann["total_amount_yi"].fillna(0.0)

    if df.empty and (ann is None or ann.empty):
        return None
    if not df.empty:
        df["issue_date"] = pd.to_datetime(df["issue_date"])
        latest_confirmed = df["issue_date"].max()
    else:
        latest_confirmed = pd.NaT

    this_month, next_month = _current_and_next_month()
    next_month_end = next_month + pd.offsets.MonthEnd(1)
    sse_listed = fetch_recent_listing_notices(
        this_month.strftime("%Y-%m-%d"), next_month_end.strftime("%Y-%m-%d")
    )
    this_data = _calendar_month_slice(df, ann, this_month, latest_confirmed, sse_listed)
    next_data = _calendar_month_slice(df, ann, next_month, latest_confirmed, sse_listed)
    if this_data is None and next_data is None:
        return None
    return {"this": this_data, "next": next_data}


def _js_bond(b: dict) -> str:
    amt = "null" if b["amountYi"] is None else f'{b["amountYi"]:.2f}'
    cpn = "null" if b["couponPct"] is None else f'{b["couponPct"]:.2f}'
    return (
        "{ province: %s, bondShortName: %s, term: %s, amountYi: %s, couponPct: %s }"
        % (_js_string(b["province"]), _js_string(str(b["bondShortName"])), _js_string(str(b["term"])), amt, cpn)
    )


def _calendar_js_null_or(month: dict | None) -> str:
    if month is None:
        return "null"
    day_entries = []
    for day, d in sorted(month["days"].items()):
        bond_lines = ", ".join(_js_bond(b) for b in d["bonds"])
        day_entries.append(
            f'        {_js_string(day)}: {{ n: {d["n"]}, amountYi: {d["amountYi"]}, '
            f'status: {_js_string(d["status"])}, bonds: [{bond_lines}] }}'
        )
    days_js = ",\n".join(day_entries)
    as_of_js = _js_string(month["asOf"]) if month["asOf"] else "null"
    listed_js = _js_string(month["listedThrough"]) if month["listedThrough"] else "null"
    sched_js = _js_string(month["scheduledThrough"]) if month["scheduledThrough"] else "null"
    return (
        "{\n"
        f"      monthLabel: {_js_string(month['monthLabel'])}, asOf: {as_of_js}, "
        f"listedThrough: {listed_js}, scheduledThrough: {sched_js},\n"
        f"      days: {{\n{days_js}\n      }},\n"
        "    }"
    )


def _render_calendar_js_block(built: dict) -> str:
    return (
        f"    const calendarData = {{\n"
        f"      thisMonth: {_calendar_js_null_or(built['this'])},\n"
        f"      nextMonth: {_calendar_js_null_or(built['next'])},\n"
        f"    }};\n"
    )


def refresh_calendar_section(result_df: pd.DataFrame, announcement_df: pd.DataFrame | None = None,
                              dashboard_path=DASHBOARD_PATH) -> str | None:
    """Regenerate the embedded calendarData block (issuance calendar) inside
    the dashboard HTML. Confirmed days come from result_df; SSE's 上市公告
    feed (live-fetched, see sse_listing.py) fills in "listed, rate pending"
    days between the last confirmed date and today; announcement_df's bid_date
    fills in "scheduled, not yet auctioned" days beyond that. Same
    no-op-on-failure contract as refresh_plan_section."""
    if not dashboard_path.exists():
        return None
    built = _build_calendar_data(result_df, announcement_df)
    if built is None:
        return None

    html = dashboard_path.read_text(encoding="utf-8")
    if not CALENDAR_BLOCK_RE.search(html):
        return None

    new_block = _render_calendar_js_block(built)
    html = CALENDAR_BLOCK_RE.sub(lambda m: m.group(1) + new_block + m.group(3), html, count=1)
    dashboard_path.write_text(html, encoding="utf-8")

    parts = []
    for key in ("this", "next"):
        m = built[key]
        if not m:
            parts.append("无数据")
            continue
        n_confirmed = sum(1 for d in m["days"].values() if d["status"] == "confirmed")
        n_listed = sum(1 for d in m["days"].values() if d["status"] == "listed")
        n_scheduled = sum(1 for d in m["days"].values() if d["status"] == "scheduled")
        parts.append(f"{m['monthLabel']} 已确认{n_confirmed}天/已上市{n_listed}天/已公告{n_scheduled}天")
    return " | ".join(parts)


def refresh_plan_section(plan_df: pd.DataFrame, dashboard_path=DASHBOARD_PATH) -> str | None:
    """Regenerate the embedded planData block inside the dashboard HTML.
    Returns a short status string on success, None if there was nothing to do
    (no dashboard file, no usable plan data, or no marker block found) -- in
    every "nothing to do" case the dashboard file is left untouched rather
    than partially overwritten."""
    if not dashboard_path.exists():
        return None
    built = _build_plan_data(plan_df)
    if built is None:
        return None

    html = dashboard_path.read_text(encoding="utf-8")
    if not PLAN_BLOCK_RE.search(html):
        return None

    new_block = _render_js_block(built)
    html = PLAN_BLOCK_RE.sub(lambda m: m.group(1) + new_block + m.group(3), html, count=1)
    dashboard_path.write_text(html, encoding="utf-8")

    parts = []
    for key in ("this", "next"):
        m = built[key]
        parts.append(f"{m['label']} {m['covered']}/{m['total']}省 截至{m['asOf']}" if m else "无数据")
    return " | ".join(parts)
