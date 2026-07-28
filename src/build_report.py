"""Generate local_report.md: the analysis writeup, lead-time ranges by term,
anomaly list, and known limitations."""
import datetime

import pandas as pd

from . import config

TERM_ORDER = config.VALID_TERMS


def _fmt(x, nd=1):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "N/A"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def build_report(ann_df: pd.DataFrame, plan_df: pd.DataFrame, tables: dict) -> str:
    valid = ann_df.dropna(subset=["category_code"])
    by_term_category = tables["by_term_category"]
    by_category = tables["by_category"]
    by_province = tables["by_province"]
    anomalies = tables["anomalies"]
    plan_lead = tables["plan_lead"]

    lines = []
    lines.append("# 全国地方政府债券发行公告结构化提取与公告间隔统计分析报告\n")
    lines.append(f"生成时间：{datetime.date.today().isoformat()}\n")

    lines.append("## 一、数据来源与口径说明\n")
    lines.append(
        "主数据源：中国地方政府债券信息公开平台（celma.org.cn）\"债券市场\"栏目下两个子栏目，"
        "均按 `ad_code=87`（全国）抓取合并后的全量列表，region 通过标题/正文匹配已知省份名单反查：\n\n"
        "1. **发行安排**（channelId=192，站内路径 `/dfzfxjh/`）— 省级财政部门于每月二十日前公开的"
        "下月度/下季度发行计划，采用全国统一模板（表2-1 再融资债券计划发行规模、表2-2 新增一般/专项"
        "债券计划发行规模），仅披露**月度加总金额**，不含具体招标日期。\n"
        "2. **发行前公告**（channelId=193，站内路径 `/fxqgg/`）— 单期/单批正式发行公告，含招标日期、"
        "期限、规模等完整要素，是本报告\"公告发布日→招投标日\"间隔统计的主要对象。\n\n"
        "两栏目的实际公告正文均以PDF附件形式提供（网页正文区为空），已按公告类型分表存储：\n"
        f"- 发行前公告累计抓取并结构化：{len(ann_df)} 行（含表格拆分出的多期/多品种分录）\n"
        f"- 发行安排（计划）累计抓取并结构化：{len(plan_df)} 行\n"
    )

    n_ocr = (ann_df["extraction_method"] == "ocr").sum()
    n_failed = (ann_df["extraction_method"] == "failed").sum()
    n_text = (ann_df["extraction_method"] == "text").sum()
    lines.append(
        f"\n**PDF提取方式分布**：文本层直接提取 {n_text} 行，OCR识别（tesseract + chi_sim，"
        f"用于无文本层的扫描件PDF）{n_ocr} 行，完全提取失败 {n_failed} 行。**OCR识别结果的数值型字段"
        "（金额、期限、日期）存在误识别风险，凡`提取方式`列标注为`ocr`的记录，交付前务必人工抽查核对**，"
        "该风险已在明细表\"提取备注/警告\"列同步标注。\n"
    )

    lines.append(
        "\n**重要口径提示（celma.org.cn平台公示日 vs 省级财政厅官网原始公示日）**：本报告\"公告发布"
        "日期\"取自celma.org.cn平台自身展示的公示日期，而非各省财政厅官网的原始发布时间。抽样发现存在"
        "平台公示日**晚于**PDF正文内招标日期的案例（即自然日间隔为负值），推测为平台镜像/上传存在滞后，"
        "而非真实的信息披露违规。**任何自然日间隔为负值或工作日间隔明显低于5天法定底线的样本，建议先按"
        "本项目设计的辅助核验源（各省财政厅官网公告页面）交叉核实原始发布时间，再判断是否为真实异常**，"
        "已在异常值清单中单独列出。\n"
    )

    lines.append("\n## 二、常规发行提前期规律（按期限 x 品种分组）\n")
    lines.append("| 品种 | 期限 | 样本数 | 平均提前工作日 | 中位数工作日 | 最大 | 最小 | 平均提前自然日 |\n")
    lines.append("|---|---|---|---|---|---|---|---|\n")
    for _, r in by_term_category.iterrows():
        lines.append(
            f"| {r['category_label']} | {r['term']} | {_fmt(r['样本数量'],0)} | "
            f"{_fmt(r['平均提前工作日'])} | {_fmt(r['中位数提前工作日'],0)} | "
            f"{_fmt(r['最大提前工作日'],0)} | {_fmt(r['最小提前工作日'],0)} | {_fmt(r['平均提前自然日'])} |\n"
        )

    lines.append(
        "\n**法定底线与市场实操常态区间**：《地方政府债券发行管理办法》（财库〔2020〕43号）要求发行"
        f"公告至少提前 **{config.STATUTORY_MIN_WORKDAYS} 个工作日**披露。上表中平均/中位数工作日间隔"
        f"明显高于 {config.STATUTORY_MIN_WORKDAYS} 天的期限，反映的是市场实操中普遍早于法定底线的"
        "提前量，可作为该期限品种的\"常规提前期\"参考区间；接近或低于法定底线的样本请结合下方异常值"
        "清单及平台公示日提示核实。\n"
    )

    lines.append("\n## 三、按品种分组（不分期限）\n")
    lines.append("| 品种 | 样本数 | 平均提前工作日 | 中位数工作日 | 平均提前自然日 |\n")
    lines.append("|---|---|---|---|---|\n")
    for _, r in by_category.iterrows():
        lines.append(
            f"| {r['category_label']} | {_fmt(r['样本数量'],0)} | {_fmt(r['平均提前工作日'])} | "
            f"{_fmt(r['中位数提前工作日'],0)} | {_fmt(r['平均提前自然日'])} |\n"
        )

    lines.append("\n## 四、分省份公告习惯差异（前15个样本量最大的省份/计划单列市）\n")
    lines.append("| 省份 | 样本数 | 平均提前工作日 | 中位数工作日 | 最大 | 最小 |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for _, r in by_province.head(15).iterrows():
        lines.append(
            f"| {r['province']} | {_fmt(r['样本数量'],0)} | {_fmt(r['平均提前工作日'])} | "
            f"{_fmt(r['中位数提前工作日'],0)} | {_fmt(r['最大提前工作日'],0)} | {_fmt(r['最小提前工作日'],0)} |\n"
        )
    lines.append("\n完整省份列表见 `local_summary.xlsx`『分组3_按省份』『分组4_按省份x品种』。\n")

    lines.append(f"\n## 五、异常样本清单（工作日间隔 < {config.STATUTORY_MIN_WORKDAYS} 天法定底线）\n")
    if len(anomalies):
        lines.append(f"共 {len(anomalies)} 条，占发行前公告有效样本的 "
                      f"{_fmt(100*len(anomalies)/max(len(valid),1))}%：\n\n")
        lines.append("| 公告标题 | 省份 | 品种 | 期限 | 公告发布日 | 招投标日 | 工作日间隔 |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for _, r in anomalies.head(50).iterrows():
            lines.append(
                f"| {r['title']} | {_fmt(r['province'])} | {_fmt(r['category_label'])} | {_fmt(r['term'])} | "
                f"{r['pub_date']} | {r['bid_date']} | {_fmt(r['workday_gap'],0)} |\n"
            )
        if len(anomalies) > 50:
            lines.append(f"\n（仅展示前50条，完整清单见 `local_summary.xlsx`『异常值_工作日间隔小于"
                          f"{config.STATUTORY_MIN_WORKDAYS}天』）\n")
    else:
        lines.append("本次抓取范围内未发现工作日间隔低于法定底线的样本。\n")

    lines.append("\n## 六、月度/季度发行计划 → 实际招投标日前置周期\n")
    lines.append(
        "发行安排（计划）PDF仅披露月度加总金额，不含具体招标日期，故\"计划公示日距离实际招投标日期\"的"
        "前置周期通过**关联匹配**得到：对每条计划记录，在同一省份、招投标日落在该计划覆盖月份/季度内的"
        "发行前公告中查找匹配样本，统计其提前工作日的最短/最长/平均值。\n\n"
    )
    if len(plan_lead):
        lines.append("| 省份 | 计划公示日 | 覆盖期间 | 匹配笔数 | 平均提前工作日 | 最短 | 最长 |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for _, r in plan_lead.head(30).iterrows():
            lines.append(
                f"| {r['省份']} | {r['计划公示日期']} | {r['覆盖期间']} | {r['匹配到的实际发行笔数']} | "
                f"{_fmt(r['平均提前工作日'])} | {_fmt(r['最短提前工作日'],0)} | {_fmt(r['最长提前工作日'],0)} |\n"
            )
        if len(plan_lead) > 30:
            lines.append(f"\n（仅展示前30条，完整表见 `local_summary.xlsx`『月度季度计划前置周期』）\n")
    else:
        lines.append("本次抓取范围内暂无可关联匹配的计划-实际发行样本对（可能是抓取的计划与公告"
                      "时间窗口未重叠，建议加大抓取范围后重新生成）。\n")

    lines.append("\n## 七、数据质量与已知局限\n")
    n_warn = (ann_df["warnings"].astype(str).str.len() > 0).sum()
    lines.append(
        f"- 共 {n_warn} / {len(ann_df)} 行发行前公告存在提取警告/备注（详见 local_raw_data.xlsx"
        "『提取备注/警告』列），请交付前人工抽查该列非空的记录。\n"
        "- **省级PDF模板差异**：发行前公告的国家层面要素（招标日期、期限、金额）遵循统一格式，"
        "但各省财政厅公文措辞、表格排版仍有差异；表格解析失败时会退化为\"整篇公告级别的合并记录\""
        "（不再拆分至每一期/每一品种），已在警告列标注。\n"
        "- **扫描件PDF**：约半数抽样省份使用无文本层的扫描版PDF，依赖OCR识别，准确率低于文本层"
        "PDF，务必人工核对`提取方式`为`ocr`的行，尤其是金额、期限等数值字段。\n"
        "- **celma.org.cn平台公示日与省级官网原始公示日可能不一致**：详见第一节口径提示，负值/"
        "过低的工作日间隔应优先怀疑平台镜像延迟，而非默认为真实违规。\n"
        "- 上市流通日（`listing_date`）在多数省份公告中仅表述为\"按规定上市流通\"而无具体日期，"
        "该字段大量留空为预期情况，非提取错误。\n"
        "- 工作日间隔的节假日判断使用 `chinese_calendar` 开源库，覆盖范围外的年份会返回空值。\n"
    )

    lines.append("\n## 八、图表\n")
    lines.append("见 `charts/boxplot_workday_gap_by_term.png`：各期限地方债提前工作日分布箱线图"
                  f"（红色虚线为{config.STATUTORY_MIN_WORKDAYS}个工作日法定底线）。\n")

    return "".join(lines)
