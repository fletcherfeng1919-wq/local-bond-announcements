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
