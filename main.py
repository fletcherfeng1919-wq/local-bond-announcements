"""CLI entrypoint.

Usage:
    python main.py                     # incremental crawl + rebuild all outputs
    python main.py --skip-crawl        # rebuild outputs only, from existing data/state_*.csv
    python main.py --no-cache          # force re-fetch every page/PDF (ignore disk cache)
    python main.py --max-pages 3       # debug: only look at the first N listing pages per channel
    python main.py --limit 30          # debug: only process the first N new items per channel
    python main.py --skip-provincial   # skip the celma/SSE/省级财政厅 three-way cross-check
                                        # (that step launches a real headless browser + OCR and
                                        # takes ~1-2 minutes; skip it for a fast dashboard-only
                                        # rebuild during iteration)
"""
import argparse

from src.build_dashboard_plan import refresh_calendar_section, refresh_plan_section
from src.build_outputs import (
    build_boxplot, build_raw_data_xlsx, build_summary_stat_xlsx, build_bond_dictionary_xlsx,
    _prep_announcements, _prep_plans, _prep_results,
)
from src.build_report import build_report
from src.pipeline import run
from src import config


def _run_provincial_check(months_back: int = 2) -> str:
    """celma vs SSE vs 省级财政厅公告 three-way cross-check (src/three_way_validate.py).
    Applies only high-confidence corrections to data/state_results.csv (see
    that module's docstring for exactly what qualifies) and writes the full
    validation report to output/provincial_validation_report.xlsx. Never
    raises past this function -- like sse_listing.py, this is a best-effort
    supplementary check and a failure here (e.g. a site went down, Playwright
    hit a new WAF) must never take down the rest of the pipeline."""
    from src import three_way_validate as tv
    try:
        validation = tv.run_validation(months_back=months_back)
        corrections = tv.apply_corrections(validation)
        tv.build_validation_report_xlsx(validation, corrections)
    except Exception as e:
        return f"省级财政厅交叉校验失败（不影响其余流程）：{e}"
    return (
        f"核对了 {validation['sse']['checked']} 条SSE上市公告、"
        f"{sum(len(d['matched']) + len(d['amount_mismatch']) + len(d['rate_mismatch']) + len(d['low_confidence']) for d in validation['provincial'].values())} "
        f"条省级财政厅公告债券；自动修正发行规模{corrections['amount_fixed']}处、票面利率{corrections['rate_fixed']}处；"
        f"报表见 output/provincial_validation_report.xlsx"
    )


def main():
    parser = argparse.ArgumentParser(description="全国地方政府债券发行公告抓取与统计分析")
    parser.add_argument("--no-cache", action="store_true", help="忽略本地HTML/PDF缓存，强制重新请求")
    parser.add_argument("--max-pages", type=int, default=None, help="限制每个栏目抓取的最大列表页数（调试用）")
    parser.add_argument("--limit", type=int, default=None, help="限制本次每个栏目新处理的条数（调试/抽样测试用）")
    parser.add_argument("--skip-crawl", action="store_true", help="跳过抓取，仅用已有 data/state_*.csv 重新生成输出文件")
    parser.add_argument("--skip-provincial", action="store_true", help="跳过celma/SSE/省级财政厅三方交叉校验（较慢，需启动浏览器+OCR）")
    parser.add_argument("--provincial-months-back", type=int, default=2, help="省级财政厅交叉校验回溯月数，默认2（本月+上月）")
    args = parser.parse_args()

    if not args.skip_crawl:
        run(use_cache=not args.no_cache, max_pages=args.max_pages, limit=args.limit)

    provincial_status = None
    if not args.skip_provincial:
        # Must run BEFORE _prep_results() below, so any corrections this
        # step applies to data/state_results.csv are reflected in result_df
        # and therefore in the dashboard calendar refresh further down --
        # running it after would silently leave the dashboard one step stale.
        provincial_status = _run_provincial_check(months_back=args.provincial_months_back)

    ann_df = _prep_announcements()
    plan_df = _prep_plans()
    result_df = _prep_results()
    if ann_df.empty and plan_df.empty and result_df.empty:
        print("data/state_*.csv 为空，没有可用数据，已退出。请先不加 --skip-crawl 运行一次。")
        return

    raw_path = build_raw_data_xlsx(ann_df, plan_df)
    summary_path, tables = build_summary_stat_xlsx(ann_df, plan_df)
    boxplot_path = build_boxplot(ann_df)
    dict_path = build_bond_dictionary_xlsx(result_df) if len(result_df) else None

    report_text = build_report(ann_df, plan_df, tables)
    report_path = config.OUTPUT_DIR / "local_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    plan_status = refresh_plan_section(plan_df)
    calendar_status = refresh_calendar_section(result_df, ann_df)

    print(
        f"完成。输出文件：\n"
        f"  {raw_path}\n"
        f"  {summary_path}\n"
        f"  {report_path}\n"
        f"  {boxplot_path}"
        + (f"\n  {dict_path}" if dict_path else "")
        + (f"\n  已刷新 bond_analysis_dashboard.html 中的最近发行计划栏目（{plan_status}）"
           if plan_status else "\n  未刷新 bond_analysis_dashboard.html 发行计划栏目（无dashboard文件或无可用计划数据）")
        + (f"\n  已刷新 bond_analysis_dashboard.html 中的发行日历栏目（{calendar_status}）"
           if calendar_status else "\n  未刷新 bond_analysis_dashboard.html 发行日历栏目（无dashboard文件或无可用发行结果数据）")
        + (f"\n  {provincial_status}" if provincial_status else "\n  已跳过省级财政厅三方交叉校验（--skip-provincial）")
    )


if __name__ == "__main__":
    main()
