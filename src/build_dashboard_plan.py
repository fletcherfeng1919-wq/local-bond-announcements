"""Refresh the "最近一个月发行计划" section of the interactive HTML dashboard
(output/bond_analysis_dashboard.html) from the current data/state_plans.csv.

The dashboard is a single static HTML file with hand-authored JS chart data --
everywhere else in it is written once and edited by hand when the underlying
analysis changes. This section is different: it shows forward-looking
"发行安排" (issuance plan) data for the nearest upcoming month, which is
genuinely stale the day after it's written. So instead of hardcoding numbers,
the dashboard's drawPlan() function brackets its two data lines with
PLAN_DATA_START/PLAN_DATA_END marker comments, and this module's
refresh_plan_section() finds-and-replaces only the text between those markers
-- every other hand-written line in the file (including drawPlan()'s own
layout/rendering code) is left untouched.

Called from main.py after each pipeline run, so `python main.py` keeps this
section current without anyone hand-editing the dashboard HTML.
"""
import re

import pandas as pd

from . import config

DASHBOARD_PATH = config.OUTPUT_DIR / "bond_analysis_dashboard.html"

CAT_COLS = ["plan_general_amount_yi", "plan_special_amount_yi", "plan_refinancing_amount_yi"]

# A province publishing its plan many months ahead of the pack (e.g. one
# province alone announcing November while everyone else is still on August)
# is a one-off, not "the market's next-month plan" -- treating it as the
# latest period would make the section look like almost nothing has been
# published yet. Requiring a minimum number of provinces before a
# covered_period_start counts filters those isolated early announcements out.
MIN_PROVINCE_COVERAGE = 15

PLAN_BLOCK_RE = re.compile(
    r"(    // PLAN_DATA_START.*?\n)(.*?)(    // PLAN_DATA_END\n)",
    re.DOTALL,
)


def _latest_broad_period(df: pd.DataFrame):
    counts = df.groupby("covered_period_start")["province"].nunique()
    eligible = counts[counts >= MIN_PROVINCE_COVERAGE]
    if eligible.empty:
        return None
    return eligible.index.max()


def _build_plan_data(plan_df: pd.DataFrame):
    """Returns (meta_dict, rows_list) for the latest broadly-covered month, or
    None if there's no plan data with a usable covered_period_start yet."""
    df = plan_df.dropna(subset=["covered_period_start"]).copy()
    if df.empty:
        return None
    period = _latest_broad_period(df)
    if period is None:
        return None

    latest = df[df["covered_period_start"] == period].copy()
    for c in CAT_COLS:
        latest[c] = latest[c].fillna(0.0)
    # A province can legitimately have more than one 发行安排 announcement
    # covering the same month (e.g. an amendment); sum rather than dedupe by
    # province so partial/supplementary plans aren't silently dropped.
    agg = latest.groupby("province")[CAT_COLS].sum()
    agg["total"] = agg.sum(axis=1)
    agg = agg.sort_values("total", ascending=False)

    as_of = latest["pub_date"].dropna().max()
    meta = {
        "period": f"{period.year}年{period.month}月",
        "asOf": as_of.strftime("%Y-%m-%d") if pd.notna(as_of) else "",
        "covered": int(agg.shape[0]),
        "total": len(config.PROVINCES),
        "totalYi": round(float(agg["total"].sum()), 1),
    }
    rows = [
        {
            "province": prov,
            "general": round(float(row.plan_general_amount_yi), 2),
            "special": round(float(row.plan_special_amount_yi), 2),
            "refi": round(float(row.plan_refinancing_amount_yi), 2),
        }
        for prov, row in agg.iterrows()
    ]
    return meta, rows


def _js_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_js_block(meta: dict, rows: list[dict]) -> str:
    meta_js = (
        "{ period: %s, asOf: %s, covered: %d, total: %d, totalYi: %s }"
        % (_js_string(meta["period"]), _js_string(meta["asOf"]), meta["covered"], meta["total"], meta["totalYi"])
    )
    row_lines = ",\n      ".join(
        '{ province: %s, general: %.2f, special: %.2f, refi: %.2f }'
        % (_js_string(r["province"]), r["general"], r["special"], r["refi"])
        for r in rows
    )
    return (
        f"    const planMeta = {meta_js};\n"
        f"    const planData = [\n      {row_lines},\n    ];\n"
    )


def refresh_plan_section(plan_df: pd.DataFrame, dashboard_path=DASHBOARD_PATH) -> str | None:
    """Regenerate the embedded planMeta/planData block inside the dashboard
    HTML. Returns a short status string on success, None if there was nothing
    to do (no dashboard file, no usable plan data, or no marker block found)
    -- in every "nothing to do" case the dashboard file is left untouched
    rather than partially overwritten."""
    if not dashboard_path.exists():
        return None
    built = _build_plan_data(plan_df)
    if built is None:
        return None
    meta, rows = built

    html = dashboard_path.read_text(encoding="utf-8")
    if not PLAN_BLOCK_RE.search(html):
        return None

    new_block = _render_js_block(meta, rows)
    html = PLAN_BLOCK_RE.sub(lambda m: m.group(1) + new_block + m.group(3), html, count=1)
    dashboard_path.write_text(html, encoding="utf-8")
    return f"{meta['period']}发行计划 · {meta['covered']}/{meta['total']}省份 · 截至{meta['asOf']}"
