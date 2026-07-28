# 全国地方政府债券发行公告抓取与统计分析

抓取中国地方政府债券信息公开平台（[celma.org.cn](https://www.celma.org.cn)）的
**发行安排**（月度/季度发行计划）与**发行前公告**（单期正式发行公告）两个栏目，
提取"公告发布日期 → 招投标日期"的间隔天数（自然日/工作日），区分一般新增债券、
专项新增债券、再融资债券三类分别统计，字段命名与 `mof_bond_announcements`（国债版）
对齐，便于国债+地方债整体对比分析。

## 环境准备（首次）

```bash
cd local_bond_announcements
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### OCR（扫描件PDF识别，可选但强烈建议）

抽样发现约半数省份发布的PDF公告是无文本层的扫描件，需要OCR才能提取字段：

```bash
brew install tesseract tesseract-lang   # 含中文简体语言包 chi_sim
```

不安装也能运行，扫描件行会被标记为 `提取方式=failed` 并留空，需人工从Wind或省财政厅
官网补录。

## 日常使用：一键增量更新

```bash
source .venv/bin/activate
python main.py
```

会自动：抓取"发行安排""发行前公告"两个栏目的全量列表页（全国口径，`ad_code=87`）
→ 跳过 `data/state_announcements.csv` / `data/state_plans.csv` 里已经处理过的
URL → 只对新公告下载PDF附件并解析、提取字段 → 追加进对应的 state csv → 重新生成
四个输出文件（`output/local_raw_data.xlsx`、`output/local_summary.xlsx`、
`output/local_report.md`、`charts/boxplot_workday_gap_by_term.png`）。

**注意：全量历史回溯耗时很长。** 截至本项目搭建时，"发行前公告"栏目全国口径约
8500+ 条、"发行安排"约 2200+ 条，每条需下载1个PDF附件（部分还需OCR，单份扫描PDF
OCR耗时可达10-30秒），叠加请求间隔延时，全量回溯预计需要数小时，建议：

```bash
# 后台运行，分批多次执行即可（增量去重，可随时中断/续跑）
nohup python main.py > crawl.log 2>&1 &
```

网页HTML与PDF会分别缓存在 `data/raw_html/`、`data/raw_pdf/`，同一URL/PDF不会被
重复下载；`data/state_announcements.csv` 与 `data/state_plans.csv` 是唯一的历史
数据存档，删除即清空对应的已抓取数据（谨慎操作，建议先备份）。

## 常用参数

```bash
python main.py --skip-crawl      # 不联网，只用现有 state csv 重新生成输出文件
python main.py --max-pages 3     # 调试用：每个栏目只看前3页列表
python main.py --limit 30        # 调试用：每个栏目本次最多新处理30条（小样本抽查）
python main.py --no-cache        # 忽略HTML/PDF缓存，强制重新请求
```

## 目录结构

```
src/
  config.py             # 抓取源、省份代码表、期限/品种标准化等全部可调参数
  http_client.py         # 带磁盘缓存+限速+重试的 HTML/PDF 下载
  listing_scraper.py      # 两个栏目的列表页翻页抓取（全国口径）
  article_parser.py        # 单篇公告详情页解析（标题/发布日期/PDF附件链接）
  pdf_extract.py             # PDF文本提取(pdfplumber)，无文本层时自动OCR(tesseract)
  classify.py                 # 省份名匹配、债券品种(一般新增/专项新增/再融资)分类
  extract_announcement.py      # 发行前公告字段提取（期限/规模/招标日/起息日等，按表格逐期拆分）
  extract_plan.py               # 发行安排(计划)字段提取（月度/季度计划发行规模）
  numerals.py                    # 中文数字/期数范围解析
  workdays.py                     # 基于 chinese_calendar 的工作日间隔计算
  pipeline.py                      # 抓取→解析→提取→合并入 state csv 的编排逻辑
  build_outputs.py                  # 生成 local_raw_data.xlsx / local_summary.xlsx / 箱线图
  build_report.py                    # 生成 local_report.md
data/
  raw_html/              # 详情页HTML缓存（按URL哈希命名）
  raw_pdf/                # PDF附件缓存（按URL哈希命名）
  state_announcements.csv  # 发行前公告全量结构化数据（增量运行的真实数据源）
  state_plans.csv            # 发行安排(计划)全量结构化数据
output/                  # 交付的Excel与报告
charts/                  # 交付的图表
```

## 字段设计与国债项目（mof_bond_announcements）的对齐

| 本项目字段 | 含义 | 对应国债项目字段 |
|---|---|---|
| `pub_date` | 公告发布日期 | `pub_date` |
| `bid_date` | 招投标日期(基准发行日) | `bid_date` |
| `natural_day_gap` / `workday_gap` | 自然日/工作日间隔 | 同名 |
| `term` | 标准化期限(2Y/3Y/.../30Y) | 同名 |
| `category_label` | 一般新增/专项新增/再融资 | `category_label`(国债品种) |
| `total_amount_yi` | 发行规模(亿元) | 同名 |
| `province` | 省份/计划单列市(地方债特有) | 无(国债无省份维度) |
| `warnings` | 提取备注/警告 | 同名 |

两个项目的 `local_raw_data.xlsx` / `raw_data.xlsx` 可直接按 `pub_date`/`term`/
`workday_gap` 等同名字段 concat 后做国债+地方债整体对比分析。

## 已知局限（详见 local_report.md 第七节）

- **celma.org.cn平台公示日可能滞后于省财政厅官网原始发布时间**：抽样发现存在
  平台展示的"公告发布日期"晚于PDF正文内招标日期的案例（自然日间隔为负）。这类
  样本已在 `warnings` 列标注，建议交叉核对省级财政厅官网（本项目设计中的辅助
  核验源）后再判定是否为真实的信息披露不合规。
- **扫描件PDF依赖OCR**：约半数抽样省份的公告PDF无文本层，OCR识别（tesseract +
  chi_sim）的数值字段（金额、期限、日期）准确率低于文本层PDF直接提取，`提取方式`
  列标注为 `ocr` 的记录务必人工复核。
- **省级PDF模板措辞差异**：国家层面要素（招标日期、期限、金额）遵循统一格式，
  但各省公文用词、表格排版不完全一致；表格解析失败时会退化为"整篇公告级别的
  合并记录"（不再拆分至每期/每品种），已在警告列标注。
- **上市流通日常年缺失**：多数省份公告仅表述"按规定上市流通"而无具体日期，
  该字段大量留空为预期情况，非提取错误。
- 若网站页面结构发生变化（列表页分页方式、详情页HTML的 class 名等），
  `src/listing_scraper.py` 和 `src/article_parser.py` 中依赖 HTML 结构的部分
  需要相应更新。
