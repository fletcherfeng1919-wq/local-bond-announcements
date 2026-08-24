# 复刻指南：local_bond_announcements（写给另一台机器上、无法访问本仓库的 Claude Code agent）

## 0. 这份指南是什么 / 怎么用

你即将从零重建一个真实存在、已经跑通并验证过的项目：抓取"中国地方政府债券信息公开平台"(celma.org.cn) 的地方政府债券公告，结构化成三张状态表，并用另外四个独立来源（SSE交易所、Wind终端导出、15个省级财政厅官网、chinabond.com.cn全国门户）交叉校验数据质量。

**你没有这个仓库的 git 历史，只有这份文档**——所以这份文档尽量把每个模块的输入/输出契约、关键正则、真实验证过的URL、以及踩过的坑都写清楚，而不是只给一个模糊的架构图。按第17节的顺序实现，每完成一个模块就跑一遍第16节对应的验证方法，不要囤积到最后才测试。

**关于"完全复刻"的诚实说明**：这个项目除了数据抓取/校验流水线之外，还有一个另外用几十轮会话手工搭建起来的57个章节的交互式HTML分析看板（`output/bond_analysis_dashboard.html`，几千行内联CSS+JS+硬编码数据），这部分**不在本指南复刻范围内**——它的具体内容依赖于抓下来的真实数据和大量迭代设计决策，不是能从规格说明书还原的东西。本指南聚焦在**数据流水线本身**（抓取+提取+四路交叉校验），这是完全可规格化、可复刻的部分；看板部分在第15节只做简要说明（它读什么数据、大致怎么刷新），如果需要看板，那是一个独立的、需要多轮迭代的前端项目。

---

## 1. 项目目标

用户是一名固定收益分析师，需要一份可信、可增量更新的地方政府债券发行数据库，覆盖：
- **发行计划**（月度/季度，省级财政厅提前公布的发行规模）
- **发行前公告**（单期债券招标前的正式公告，含招标日）
- **发行结果**（招标后确认的结果，含债券编码/简称/票面利率——这是最重要的"主字典"）

celma.org.cn 是官方主数据源，但存在**已知的、系统性的**数据质量问题（后述），所以项目额外接入了四个独立来源做交叉验证和补漏，而不是盲信celma。

---

## 2. 环境搭建

```bash
mkdir local_bond_announcements && cd local_bond_announcements
python3 -m venv .venv
.venv/bin/pip install beautifulsoup4 chinese_calendar cn2an lxml matplotlib openpyxl \
    "pandas" pdfplumber playwright pytesseract Pillow python-dateutil python-docx \
    requests soupsieve
.venv/bin/playwright install chromium
```

另外需要系统级安装 **Tesseract OCR + 简体中文语言包**（scanned PDF /图片公告需要）：
- macOS: `brew install tesseract tesseract-lang`（确认 `chi_sim` 语言包已装：`tesseract --list-langs` 应包含 `chi_sim`）
- Linux: `apt install tesseract-ocr tesseract-ocr-chi-sim`

**不需要 PyMuPDF/fitz**——虽然你可能在别的项目里见过用 fitz 渲染PDF做OCR，这个项目实测发现 fitz 渲染在这类"表格边框+红色公章"的文档上OCR效果明显更差，改用 pdfplumber 自带的 `page.to_image()` 渲染（细节见第7节）。不要装/不要用 fitz。

目录结构（运行时自动创建，见 `config.py`）：
```
data/raw_html/     # HTML详情页缓存（按URL的sha1文件名）
data/raw_pdf/      # PDF附件缓存 + 每个PDF旁边的 .extract.json 提取结果缓存
data/state_announcements.csv
data/state_plans.csv
data/state_results.csv
output/            # 生成的Excel/Markdown/看板
charts/            # matplotlib图表
src/
main.py
```

---

## 3. 数据模型：三张状态表的精确 schema

这是整个项目的核心契约，所有后续模块都要产出/消费这个schema。

### 3.1 `state_results.csv`（发行结果，主字典，最重要）

```
title, pub_date, url, source_name, doc_type, province, province_code,
bond_name, bond_code, bond_short_name, bond_market_type,
category_code, category_label, term, total_amount_yi,
new_amount_yi, swap_amount_yi, refi_amount_yi, batch_label,
coupon_rate_pct, issue_date, value_date, payment_freq,
redemption_structure, extraction_method, warnings
```
- `bond_code`：celma官方6-7位数字债券编码（约2605xxx-2606xxx区间，**不是**交易所/托管的其它编码体系，见第13节的教训）。
- `bond_short_name`：市场简称，如"26江苏债33"（年份2位+省份简称[可能含"债"字]+序号）。**这是跨数据源匹配最可靠的字段**，一定要重视它的一致性。
- `category_code` ∈ `{new_general, new_special, refinancing}`，对应 `category_label` ∈ `{一般新增债券, 专项新增债券, 再融资债券}`。
- `term`：形如 `"10Y"` 的字符串（不是纯数字）。
- `extraction_method` ∈ `{text, ocr, wind_reconcile, chinabond_manual_verify, unsupported_legacy_format, failed}`——**每一行都要标注数据来源的可信等级**，OCR来源的行永远要在warnings里提示人工核对，不能和文本原生提取的行同等对待。

### 3.2 `state_plans.csv`（发行计划）

```
title, pub_date, url, source_name, doc_type, province, province_code,
covered_year, covered_month_start, covered_month_end,
covered_period_start, covered_period_end,
plan_general_amount_yi, plan_special_amount_yi, plan_refinancing_amount_yi,
extraction_method, warnings
```
- 月度计划：`covered_month_start == covered_month_end`；季度计划：跨3个月。
- **只有月度/季度粒度，没有逐日拆分**——千万不要为了做日历图就把月度总额除以工作日数摊成"每日计划"，那是编造数据（这是本项目踩过的坑，见第16节坑3）。

### 3.3 `state_announcements.csv`（发行前公告）

```
title, pub_date, url, source_name, doc_type, province, province_code,
category_code, category_label, category_subtype, term, batch_no,
issue_no, issue_no_range, total_amount_yi, bid_date, base_date_type,
payment_date, listing_date, natural_day_gap, workday_gap, doc_no,
bond_name, extraction_method, warnings
```
- `bid_date`：招标日，**这是三张表里唯一有意义的"逐日"精度来源之一**（另一个是`state_results.csv`的`issue_date`）。
- `natural_day_gap`/`workday_gap`：公告发布日到招标日之间的自然日/工作日差——法定最低提前期是5个工作日（财库〔2020〕43号），用`chinese_calendar`包算准确的工作日数，不要用自然日近似。

---

## 4. 核心工具模块（先写这些，其它模块都依赖它们）

### 4.1 `config.py`

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR / RAW_HTML_DIR / RAW_PDF_DIR / STATE_*_CSV / OUTPUT_DIR / CHARTS_DIR  # 见第2节目录结构，启动时 mkdir(parents=True, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
REQUEST_DELAY_RANGE = (1.5, 3.0)   # 礼貌爬虫：每次请求间随机延迟
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0

SITE_ROOT = "https://www.celma.org.cn"
```

**celma.org.cn 的三个抓取渠道**（`channelId`，全部走同一套分页URL模板，`ad_code=87` 是全国口径，一次抓全国比逐省抓36次更省事，省份从标题/正文里反查）：

```python
LISTING_SOURCES = [
    {"name": "dfzfxjh", "label": "发行安排（月度/季度发行计划）", "channel_id": "192", "doc_type": "plan", "detail_url_prefix": "/dfzfxjh/"},
    {"name": "fxqgg",   "label": "发行前公告（单期正式发行公告）", "channel_id": "193", "doc_type": "announcement", "detail_url_prefix": "/fxqgg/"},
    {"name": "fxjg",    "label": "发行结果（含债券编码/简称）",   "channel_id": "194", "doc_type": "result", "detail_url_prefix": "/fxjg/"},
]
FIRST_PAGE_TPL = SITE_ROOT + "/zqsclb.jhtml?ad_code=87&channelId={channel_id}"
PAGE_TPL = SITE_ROOT + "/zqsclb_{n}.jhtml?ad_code=87&channelId={channel_id}"
```

`RESULT_NEW_FORMAT_START = "2020-01-01"`：celma的"发行结果"文档在2019年5月~2020年5月之间的某个时间点，从无编码的自由文本切换成标准化的"表2-9/表2-10"含债券编码表格——本指南**只覆盖新格式**，2020年前的旧格式是已知未实现的缺口（见第16节）。

**省份表**（`PROVINCES: dict[省份全名, celma的ad_code]`，37个条目，含5个计划单列市：大连/宁波/厦门/青岛/深圳，各自有独立的ad_code而不是并入所属省份）：
```python
PROVINCES = {
    "北京市": "11", "天津市": "12", "河北省": "13", "山西省": "14",
    "内蒙古自治区": "15", "辽宁省": "21", "大连市": "2102", "吉林省": "22",
    "黑龙江省": "23", "上海市": "31", "江苏省": "32", "浙江省": "33",
    "宁波市": "3302", "安徽省": "34", "福建省": "35", "厦门市": "3502",
    "江西省": "36", "山东省": "37", "青岛市": "3702", "河南省": "41",
    "湖北省": "42", "湖南省": "43", "广东省": "44", "深圳市": "4403",
    "广西壮族自治区": "45", "海南省": "46", "重庆市": "50", "四川省": "51",
    "贵州省": "52", "云南省": "53", "西藏自治区": "54", "陕西省": "61",
    "甘肃省": "62", "青海省": "63", "宁夏回族自治区": "64",
    "新疆维吾尔自治区": "65", "新疆生产建设兵团": "66",
}
PROVINCE_NAMES_BY_LEN_DESC = sorted(PROVINCES.keys(), key=len, reverse=True)  # 长名字优先匹配，否则"新疆生产建设兵团"会被"新疆维吾尔自治区"的子串规则误伤
```

`VALID_TERMS = ["1Y","2Y","3Y","5Y","7Y","10Y","15Y","20Y","25Y","30Y"]`

`CATEGORY_NEW_GENERAL/NEW_SPECIAL/REFINANCING` 三个常量字符串 + `CATEGORY_LABELS` 中文映射（见3.1节）。

`STATUTORY_MIN_WORKDAYS = 5`（财库〔2020〕43号法定最低提前期）。

如果要做区域分组统计（看板用，非必需），有一个基于用户Wind终端自定义分组的 `REGION_GROUPS`/`PROVINCE_TO_REGION`/`REGION_ORDER` 五分组常量，不是官方地理分区，是本项目自己约定的市场惯例分组——除非你也要做同样的区域对比图表，否则可以跳过。

### 4.2 `http_client.py`：带磁盘缓存的礼貌请求

两个函数：`fetch(url) -> str`（HTML文本）、`fetch_pdf(url) -> Path`（PDF文件路径）。都按 `sha1(url)` 做磁盘缓存key，都有重试+退避。

**关键细节，容易漏**：
1. `fetch_pdf()` 必须做**PDF结构合法性检查**再信任缓存文件——网络中断可能在磁盘上留下一个"存在但损坏"的文件，requests不会报错（没有Content-Length或连接被读成干净EOF）。检查方法：`data.startswith(b"%PDF")` 且 `b"%%EOF" in data[-2048:]`。缓存文件没通过这个检查要当作"不存在"重新下载，不能永久信任。
2. `fetch()` 用 `resp.apparent_encoding` 而不是默认encoding，很多.gov.cn站点没有正确声明charset。

### 4.3 `classify.py`：省份/品种识别

```python
def extract_province(text: str) -> tuple[str|None, str|None]:
    # 按 PROVINCE_NAMES_BY_LEN_DESC 顺序做子串搜索（不是anchor匹配），命中第一个就返回 (省份全名, ad_code)

def classify_bond_category(name_text: str) -> tuple[str|None, str|None]:
    # 从"债券名称"文本里判断类别，优先级：含"再融资" -> refinancing（子类型再取"专项"/"一般"存进第二个返回值）
    #                                    含"专项" -> new_special
    #                                    含"一般" -> new_general
    #                                    否则 (None, None)
```

### 4.4 `numerals.py` + `workdays.py`

- `cn_to_int("十二")` -> `12`（用 `cn2an` 库，`cn2an.cn2an(text, "smart")`，纯数字字符串直接 `int()`）。
- `parse_issue_range("十二至十三期")` -> `[12, 13]`；单期 -> `[n]`；无法解析 -> `[]`。分隔符支持 `至`/`-`/`~`。
- `workday_diff(start, end)`：用 `chinese_calendar.is_workday()` 逐日累计，start不含end含，跨年超出该库支持范围时返回`None`而不是抛异常。

---

## 5. celma.org.cn 抓取层

### 5.1 `listing_scraper.py`：列表页翻页抓取

celma的列表页是服务端渲染的（不需要JS），结构：`<div id="to-print1"><li><a href=... title=...><span>日期</span></a></li>...</div>`，footer里有"共 N 页"文本用正则 `共\s*(\d+)\s*页` 抓总页数。

**增量抓取的提前停止逻辑**（重要，否则每次全量重跑850+页）：传入 `seen_urls` + `new_item_target`，翻页翻到「已收集够 `new_item_target` 条新item」或「连续5页全是已见过的URL」就停。**但这个提前停止只在 `new_item_target` 被显式设置时生效**——否则单纯"seen_urls非空"不能保证"连续几页已见"就代表后面全是旧数据（因为之前的抓取可能只拉了最新N条就停了，中间还有大段没抓过的历史页）。

### 5.2 `article_parser.py`：详情页解析

celma详情页本身**几乎没有正文内容**，真正的数据全在PDF附件里。这个模块只做三件事：
1. `<h1>` 取标题
2. `class="secondPage-content-inf"` 元素里用正则 `(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日` 取发布日期
3. `class="content-fj"`（附件区）里所有 `.pdf` 结尾的 `<a href>` 收集成附件列表

返回 `{"url","title","pub_date","body_text","attachments":[{url,name}],"parse_ok": bool(title and pub_date)}`。

### 5.3 `pdf_extract.py`：PDF -> 文本+表格（含OCR降级）

```python
def extract_pdf(pdf_path, use_cache=True) -> dict:
    # 返回 {"text": str, "tables": list[list[list]], "method": "text"|"ocr"|"failed"}
    # 结果缓存到 <pdf_path>.extract.json（OCR很慢，10-30秒一份，必须缓存）
```

流程：先用 `pdfplumber` 直接抽取每页的 `extract_text()`/`extract_tables()`；**如果拼起来的全文本是空的**（说明是扫描件，没有文本层），才降级到OCR；OCR也失败则 `method="failed"`，text/tables都是空。

**OCR渲染参数是这个项目实测调出来的，务必按这个来，不要凭直觉改**：
```python
def _ocr_pages(pdf_path, resolution: int = 150) -> list[str]:
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=resolution).original   # 用 pdfplumber 自带渲染器，不要用 PyMuPDF/fitz 的 get_pixmap()
            texts.append(pytesseract.image_to_string(img, lang="chi_sim", config="--psm 4"))  # PSM 4，不是默认的 PSM 3
    return texts
```
两个反直觉的实测结论：① pdfplumber自己的渲染器在"表格边框+红色公章遮挡"这类文档上明显比fitz的RGB渲染效果好（同分辨率对比过）；② 150 DPI 比 300 DPI 效果更好（配合上面的渲染器和PSM4，分辨率太高字符相对Tesseract预期尺寸变大反而更难识别）。PSM 4（"假设是单栏、多种字号文本"）比默认PSM 3（全自动版面分析）在这类文档上稳定得多，PSM 3会被公章+表格线搞乱整体版面分析。

`OCR_AVAILABLE = True` 只要能 `import pytesseract` 成功（不需要import fitz/PIL在模块顶层，pdfplumber内部已经用PIL）。

---

## 6. 字段提取器：三种文档类型各自的解析逻辑

三个模块结构相似：输入 `(title, pub_date, url, source_name, doc_type, pdf_result)`，输出一行或多行dict。**每个模块都要处理"OCR来源"和"解析失败"两种降级情况**，并在 `warnings` 字段里明确说明，不能静默吞掉。

### 6.1 `extract_result.py`：发行结果（最重要，是主字典来源）

先检查文本里有没有 `表2-\d+` 标记（`NEW_FORMAT_MARKER_RE`）——没有就是2020年前的旧格式，直接返回单行 `extraction_method="unsupported_legacy_format"`，不解析。

有标记的话，遍历 `pdf_result["tables"]`，对每张表找表头列（`_find_table_columns`，按关键词子串匹配：债券名称/债券编码/债券简称/债券类型/期限/发行规模/新增债券/置换债券/再融资债券/发行批次/利率/发行日期/起息日/付息方式/赎回模式），**必须同时命中"债券编码"和"期限"两列才算有效表头**，且这些关键词命中的列位置至少要有5个不同的index（防御一种真实发生过的bug：pdfplumber偶尔把整张表压成一行，所有文本堆在第0列，这时候朴素的关键词匹配会让所有字段都指向同一列）。

数值解析 `_to_float()` 要先 `re.sub(r"\s+", "", s.replace(",", ""))` 再转float——**已确认多个省份的PDF会在数字里插入杂散空格**（如"3. 28"读成两段），不处理会被正则 `[\d.]+` 截断成"3"丢掉小数部分。

字符串字段（`bond_short_name`等）也要去空格——已确认甘肃/青海/四川/海南/黑龙江的模板会把"25甘肃债28"渲染成"25 甘肃债 28"，不处理会导致后续精确匹配全部失败。

品类判断优先级：`refi_amt>0` -> refinancing；否则 `new_amt>0` -> 按`bond_market_type`含"专项"分new_special/new_general；否则 `swap_amt>0` -> 按置换债券归入refinancing（历史遗留品类，2019年前的债务置换，性质上最接近再融资）。

**列错位防御**（真实发生过，务必实现）：`bond_code`超过12字符或不是纯字母数字点号 -> 置空+警告；`coupon_rate_pct`不在0.1~8.0区间 -> 置空+警告；`total_amount_yi`不在0~1500区间 -> 置空+警告。这不是过度防御，是解析器真实会把票面利率读串到别的字段的实测教训。

### 6.2 `extract_announcement.py`：发行前公告

一份公告PDF通常打包多个tranche（比如一批同时发的10年一般债+两个期限的专项债），每个tranche变成一行输出，但招标日等"整份公告级别"的字段只解析一次、复制到每一行。

**日期锚定逻辑**（`AnchorYearResolver`）：PDF里日期经常第一次出现带完整年份，后面同一段落内就只写"7月27日"不再重复年份——用一个"往前找最近一个带完整年份的日期"的锚定策略去补全，不要假设所有日期都自带年份。

三个关键日期的匹配模式（必须要求锚定短语**紧邻**在日期后面，不能只是"附近N个字符内"——已确认宽松窗口会把到期日/兑付日误判成招标日，比如"...2050年2月25日偿还竞争性招标结束后..."里的2050是30年期债券的到期日，不是招标日）：
```
bid_date:     DATE_TOKEN + 可选时间段 + "招标"
payment_date: DATE_TOKEN + "(起)?开始计息"
listing_date: DATE_TOKEN + "起[^\n]{0,20}?上市"
```
其中 `DATE_TOKEN = r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"`。

**招标日合理性防御**：解析出的`bid_date`和公告`pub_date`相差超过400天就丢弃+警告（OCR会把"年"误读成别的字，导致年份锚定漂移到文档里完全不相关的年份，产生离谱的日期差而不报错）。

### 6.3 `extract_plan.py`：发行计划（月度/季度汇总表）

这是和上面两种完全不同的文档结构——不是逐笔债券明细，是一张"省份+总额+新增/再融资细分"的汇总表，全国统一遵循"表2-1 再融资债券计划发行规模 / 表2-2 新增一般/专项债券计划发行规模"两张表的模板。

```python
TITLE_QUARTER_RE = re.compile(r"(\d{4})\s*年[\s\S]{0,12}?第?([一二三四1234])\s*季度")  # 年份和季度标记之间要留出间隔容忍度，因为有些来源（如chinabond的广东文档）在两者之间插入了发行人名称文本，且PDF文本层有时候会在词组中间换行
TITLE_MONTH_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
QUARTER_CN = {"一":1,"二":2,"三":3,"四":4,"1":1,"2":2,"3":3,"4":4}
REFI_BLOCK_RE = re.compile(r"时间\s*再融资债券计划发行规模\s*\n([^\n]+)")
NEW_BLOCK_RE = re.compile(r"时间\s*新增一般债券\s*新增专项债券\s*\n([^\n]+)")
PERIOD_LABEL_RE = re.compile(r"^\s*(?:\d{1,2}\s*月|第?[一二三四]\s*季度)\s*")  # 抠数字前必须先去掉这个周期标签本身，否则"8月"这种空行会把自己的"8"误读成金额
```

`_covered_period(title, text)` 返回 `(year, month_start, month_end)`：优先试季度正则，命中就是 `((q-1)*3+1, q*3)`；否则试月度正则，`month_start==month_end`；都不中返回`(None,None,None)`。

---

## 7. 主流程编排：`pipeline.py` + `main.py`

`pipeline.py::run()` 的完整流程：
```
crawl_all_sources() 拿到三个渠道的列表items
  → 对每个渠道调用 _run_one_source():
      过滤出 url 不在 state["url"] 里的新item
      对每个新item: parse_article() → 挑主PDF附件(_pick_primary_pdf) → fetch_pdf() → extract_pdf() → 对应的extract_*_fields()
      每处理15条就flush一次到state CSV（FLUSH_EVERY=15，防止长批次中途中断丢失已完成的工作）
      去重合并：announcements按(url,issue_no,term)去重，plans按url去重，results按bond_code去重（bond_code为空的行单独按url去重，因为pandas会把多个NaN当作相等，直接混在一起去重会把2020年前的旧格式行全部坍缩成一行）
```

`_pick_primary_pdf(attachments, doc_type)`：announcement优先选文件名含"通知"的附件，其次"发行公开"；plan选含"发行安排"的；result选含"发行结果"的；都没有就退而求其次用第一个附件。**这是一个已知的不完美启发式**——见第16节"已知限制"，一份"通知"PDF有时会打包多个独立批次，把文档级合计金额错误地套到每个单独批次的行上。

`main.py` 的CLI：`--no-cache` / `--max-pages N` / `--limit N`（调试抽样）/ `--skip-crawl`（只重建输出物）/ `--skip-provincial`（跳过下面第14节的三方校验，因为它要开浏览器+OCR，比较慢）/ `--provincial-months-back N`（默认2，本月+上月）。

**运行顺序有一个不能颠倒的依赖**：`_run_provincial_check()`（第14节）必须在准备输出数据（`_prep_results()`等）**之前**跑，因为它可能会修正`state_results.csv`，晚跑的话生成的报表/看板刷新就会用到修正前的旧数据。

---

## 8. 补充数据源 A：SSE上市公告（`sse_listing.py`）

**存在的意义**：celma的"发行结果"确认有大约1周的发布滞后，SSE（上交所）的"上市公告"在债券确认上市交易当天就发布，能补上celma覆盖不到的最近几天窗口。**代价**：SSE上市公告没有票面利率（PDF正文明确写"利率详见发行文件"），只能证明"这支债券确实发行成功且在交易"，不能当"已确认结果"用，UI/统计口径上要严格区分这两种状态，不能混为一谈。

API是通过Playwright打开 `https://bond.sse.com.cn/disclosure/announ/ltb` 抓包发现的XHR调用（如果这个接口以后失效，重新抓包的方法就是这样）：
```python
SSE_QUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
params = {
    "isPagination": "true", "pageHelp.pageSize": "200", "sqlId": "BS_ZQ_GGLL",
    "securityCode": "", "bondType": "LOCAL_GOVERNMENT_BOND_BULLETIN", "title": "",
    "orgBulletinType": "", "sseDate": f"{date_start} 00:00:00", "sseDateEnd": f"{date_end} 23:59:59",
    "order": "sseDate|desc,securityCode|asc,bulletinId|asc",
}
headers = {"User-Agent": "...", "Referer": "https://bond.sse.com.cn/disclosure/announ/ltb"}
```
只保留 `row["bulletinType"] == "上市公告"` 的记录，返回 `{securityAbbr, securityCode, province, sseDate, title}`。**任何异常都返回空列表**，这是一个辅助信号源，不能因为它挂了拖垮主流程。

**不落盘为state_*.csv**——这是"实时查询、用完即弃"的数据，不是要长期归档的历史。

---

## 9. 补充数据源 B：Wind终端人工核对（`wind_reconcile.py`）

用户会不定期从Wind终端手动导出一份"地方政府债一级市场"Excel（`sheet_name="一级市场"`），当作最权威的核对基准。**这不是自动化数据源**——是用户手动放到项目根目录的文件，`.gitignore` 里要排除掉（授权数据不能提交到公开仓库），只提交修复后的CSV和脚本本身。

这个模块存在的意义是**发现并修复三类celma自己PDF提取管线里的系统性bug**，不是孤立的某一天的问题：
1. **多子档合并求和bug**：同一个 `bond_code` 在celma的PDF表格里有时拆成2-3行（比如一支专项债同时对应"项目收益/棚改/土地储备"三个子用途），而 `pipeline.py` 按`bond_code`去重时用`keep="last"`只留最后一行，其余子档金额被静默丢弃而不是求和——**这是一个仍未在根源修复的已知限制**，Wind核对是下游补丁，不是根治。
2. **issue_date缺失bug**：有些行金额/利率都对，但`issue_date`提取失败是NaN，导致任何按日期筛选的视图都看不到它们。
3. 真正的celma未发布/提取彻底失败的缺口。

匹配键用 `bond_short_name`（验证过和celma格式完全一致），**全局匹配，不按日期窗口过滤**——如果按窗口过滤查找，issue_date=NaN的行永远匹配不到（因为它们的日期是空的，无法落入任何窗口），会被误判成"missing"然后重复插入一行新的，而不是patch已有行。

```python
def load_wind_export(xlsx_path) -> pd.DataFrame:
    raw = pd.read_excel(xlsx_path, sheet_name="一级市场").iloc[:, 1:]
    raw = raw.dropna(subset=["发行日","证券简称"])
    raw = raw[pd.to_numeric(raw["发行利率"], errors="coerce").notna()]  # 只保留已确认利率的行，未来的计划行不属于"结果"核对范围
    # 列名映射：发行日->issue_date, 证券简称->bond_short_name, 期限->term(去掉括号备注), 发行额(亿)->total_amount_yi,
    #          发行利率->coupon_rate_pct, 性质含"再融资"->refinancing, 类别=="专项债券"->new_special否则new_general
```

`_province_from_shortname(shortname)`：从"26河北债44"反推省份全名——先去掉开头2位年份数字，再从最长到最短匹配一份"简称->全名"反查表（由`config.PROVINCES`剥掉常见后缀`维吾尔自治区/回族自治区/壮族自治区/自治区/省/市`自动生成，注意"新疆生产建设兵团"的简称是特殊值`"兵团"`，要单独加进映射表）。

`diff_against_state()` 返回 `{missing, amount_mismatch, rate_mismatch, date_missing, duplicate_short_names}`，容差 `AMOUNT_TOLERANCE_YI=0.05`亿元 / `RATE_TOLERANCE_PCT=0.011`个百分点。`reconcile_from_wind_file(xlsx_path, dry_run=False)` 把diff结果实际patch进CSV，**是幂等的**（对同一份已核对过的CSV再跑一次，diff应该全为0）。

---

## 10. 补充数据源 C：省级财政厅官网（`provincial_verify.py` + `provincial_crawl.py`）

这是工作量最大的一块——15个省份各自的官网结构都不一样，`provincial_verify.py` 负责"给一个已知URL解析出结构化数据"，`provincial_crawl.py` 负责"自动发现最新公告的URL"（用Playwright，因为几乎所有列表页都是JS渲染的，纯requests拿到空页面）。

### 10.1 为什么匹配键是 `(province, issue_date, term)` 不是 `bond_short_name`

**这是一个反直觉但经过两个省份（江苏、宁夏）真实公告验证过的结论**：省级财政厅公告遵循的是财库〔2020〕43号/36号规定的另一套模板（债券名称/计划发行规模/实际发行规模/发行期限/票面利率/发行价格/付息频率/付息日/到期日的键值对列举），**和celma自己的表2-9/表2-10完全不同**，而且**大多数省份的这套模板压根不含债券编码/债券简称字段**（只有个别省份，如新疆，额外带了）。所以主匹配键退化成 `(province, issue_date, term)`，有简称时优先用简称（更可靠）。

### 10.2 共享解析器：`parse_announcement_text(raw_text, province)`

**四种文档结构里，PDF/HTML两种共用同一套正则解析器**（Word/图片分别有自己的解析函数但复用同样的正则常量）。核心思路：把文本按"债券名称"这个词切分成块，每块正则抠字段。

```python
_BOND_BLOCK_RE = re.compile(r"债券名称")
_NAME_RE = re.compile(r"^(.+?)计划发行规模")
_AMOUNT_RE = re.compile(r"实际发行规模([\d.]+)亿元")
_PLANNED_AMOUNT_RE = re.compile(r"计划发行规模([\d.]+)亿元")
_AMOUNT_WAN_RE = re.compile(r"实际发行规模([\d.]+)万元")       # 宁波用万元不用亿元，未命中亿元格式才试这个，/10000换算
_PLANNED_AMOUNT_WAN_RE = re.compile(r"计划发行规模([\d.]+)万元")
_TERM_RE = re.compile(r"发行期限(\d+)年")
_RATE_RE = re.compile(r"票面利率([\d.]+)%")
_ISSUE_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日已完成招标")
_ISSUE_DATE_RE2 = re.compile(r"于(\d{4})年(\d{1,2})月(\d{1,2})日.{0,20}招标发行")   # 西藏用的是"于XX年XX月XX日...招标发行"的语序，日期在"招标发行"前面而不是"已完成招标"后面
_TITLE_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\S{0,4}(?:政府债券|地方政府债)发行结果公告")  # 宁波正文里根本没有"已完成招标"这句话，招标日只出现在标题里，兜底用
_SHORTNAME_RE = re.compile(r"[债贵]券简称(\d{2}[^\d]{1,10}\d{1,3})")  # OCR常把"债"认成"贵"，两个都要匹配；新疆等少数省份模板带这个字段
```
先在**整篇文本**里按顺序试 `_ISSUE_DATE_RE` → `_ISSUE_DATE_RE2` → `_TITLE_DATE_RE` 拿到统一的 `issue_date`（同一份公告里所有tranche共用一个招标日），再按 `_BOND_BLOCK_RE` 切块逐块抠 `bond_name`/`total_amount_yi`/`term`/`coupon_rate_pct`/`bond_short_name`。

**OCR质量差导致的分块串块问题（真实踩过两次，必须实现这两层防御）**：
1. 统计文档里"债券简称"/"贵券简称"出现的次数 `expected_n`，如果 `expected_n > 0` 但和实际切出的块数不一致 -> 整份文档所有行标记为低置信度警告（OCR丢了"债券名称"标签导致相邻债券字段串块）。
2. 检查 `bond_name` 捕获组里有没有混进"债券代码/存续期/发行期限/票面利率/付息/到期日/计划发行/实际发行"这些字段标签词——正常的债券名称（哪怕是宁夏那种合法的连字符双名"A方案名-B方案名"）不会包含这些词，出现了就说明正则贪婪匹配跑过了缺失的块边界，吞掉了下一支债券的标题——同样标记低置信度。

**任何带这类warnings的行，下游 `diff_against_state()` 必须路由到 `low_confidence` 桶，绝不能当成真实的金额/利率差异去报告或自动修正。**

### 10.3 三种非共享解析路径

- **`parse_docx_table(docx_bytes, province)`**（湖南）：用 `python-docx` 读表格，按表头关键词（债券名称/实际发行规模/发行期限/票面利率）定位列，直接按行取值，不走正则分块（Word表格没有PDF/OCR那种版面坍缩问题，直接读cell）。招标日单独在段落文本里用同样的 `_ISSUE_DATE_RE`/`_ISSUE_DATE_RE2` 找。
- **`parse_image_sequence(cover_html, base_url, province)`**（天津）：公告内容是一串JPG扫描页图片，不是单个PDF/HTML。用正则 `src="([^"]*W\d{15,}_ORIGIN\.(?:jpg|jpeg|png))"` 找出所有"内容图片"（区别于站点logo等装饰性小图，命名规律是`W<18位以上数字>_ORIGIN.<扩展名>`），按文件名去重（同一张图常在页面里出现两次：缩略图+原图链接），逐张下载+`pytesseract.image_to_string(img, lang="chi_sim")`，拼接后复用 `parse_announcement_text()`。**这条路径实测产出率很低**（天津表格label和value跨行渲染，pytesseract逐行读取时永远拼不上"计划发行规模"这个完整标签），不必强求高产出，两层置信度防御能保证不产生假阳性就够了。
- **TLS握手失败的兜底**：确认过至少一个省份（湖南 `czt.hunan.gov.cn`）的服务器TLS配置会让本机OpenSSL握手报 `BAD_ECPOINT` 错误（`requests`/`urllib3`必现，但系统`curl`命令能正常连接同一个URL）——遇到这个特定错误时 fallback 到 `subprocess.run(["curl","-sL","-A",UA,url])`，并手动把结果写回 `http_client` 的磁盘缓存（否则每次调用都要重新shell出去，实测偶尔超过30秒，把curl超时调到45秒）。

### 10.4 `diff_against_state(rows, state_df)`：核对逻辑

对每一行：如果有 `warnings`（低置信度标记）-> 直接进 `low_confidence` 桶，不参与匹配。否则：有`bond_short_name`就先按`(province, bond_short_name)`精确查；查不到或没有简称就退化到`(province, issue_date, term)`，如果命中多条（同一天同期限有多支债券）且本行有`total_amount_yi`，用金额容差`0.05`亿元去消歧；消歧后还是多条 -> 进`low_confidence`（**绝不能矮子里拔将军选第0个当匹配**，那是编造匹配关系）。唯一匹配到之后比较金额/利率容差，超出的分别进`amount_mismatch`/`rate_mismatch`，否则进`matched`。

### 10.5 自动发现层：`provincial_crawl.py`

用Playwright渲染每个省份的公告列表页，提取所有 `innerText` 含 `RESULT_KEYWORDS = ("发行结果", "招标结果", "发行结果公告")` 的 `<a>` 标签。**日期从URL路径里解析**（不从"发布日期"文本节点解析，因为每个站点的DOM结构都不一样，URL里嵌日期是唯一跨站通用的信号）：
```python
_URL_DATE_PATTERNS = [
    r"/(\d{4})/(\d{1,2})/(\d{1,2})/",   # /art/2026/7/24/
    r"/(\d{4})(\d{2})(\d{2})/",          # /20260713/
    r"/(\d{4})(\d{2})/",                 # /202608/  (只到月份)
]
_TITLE_DATE_PATTERNS = [r"(\d{4})年(\d{1,2})月(\d{1,2})日", r"(\d{4})-(\d{1,2})-(\d{1,2})"]  # URL没日期时退回标题里找（确认宁波的URL模式是纯hash，没有日期）
```
**列表页本身不做磁盘缓存**（不同于celma那套——见第16节坑1，缓存列表页是一个反复踩过的坑，这里干脆不缓存，反正一个月/一次手动调用一次的频率，多花点浏览器渲染时间可以接受）；但发现的公告URL本身经过 `verify_announcement()` 解析后，走的是正常的 `http_client`/PDF缓存（内容不可变，可以放心复用）。

有个别省份需要非默认等待策略（`WAIT_STRATEGY_OVERRIDES`），比如新疆的首页有持续的后台请求导致永远不会到达"networkidle"状态，要改用 `wait_until="domcontentloaded"` + 固定 `extra_wait_ms=3000`。

### 10.6 15个已验证可用的省份清单（`PROVINCE_SOURCES`）

**这是最有价值的部分——每一条都是真实访问验证过的URL和结构，你不需要重新调研这些，直接照抄就能跑**（当然实际URL可能随时间失效，抓不到时先假设是链接过期，用同一个域名+关键词重新搜一次栏目页，不要假设整条渠道都死了）：

| 省份 | 域名 | 结构 | 关键坑 |
|---|---|---|---|
| 上海市 | czj.sh.gov.cn | pdf（文本原生） | "明显"的列表路由 `dfzwfxjg/index.html` 其实是服务端FreeMarker模板404（不是JS问题），真实可用列表在 `zss/zt/dfzfx/zxxx/index.html`（一个混合多种公告类型的"最新消息"页，靠关键词过滤） |
| 新疆维吾尔自治区 | czt.xinjiang.gov.cn | pdf（OCR） | 首页要用 `domcontentloaded` 等待策略（见上）；模板额外带债券简称字段 |
| 河北省 | czt.hebei.gov.cn | pdf（OCR） | "明显"列表页是200状态的空壳，真实列表在一个`<iframe>`里，只能读原始HTML源码找，Playwright渲染后的DOM选择器够不到iframe内容 |
| 贵州省 | czt.guizhou.gov.cn | pdf（文本原生） | 近月度发布节奏稳定 |
| 江苏省 | czt.jiangsu.gov.cn | pdf（扫描/OCR） | 同一天的多批公告可能分散在相邻的`art_77314_<id>.html`URL上，单次fetch可能覆盖不全 |
| 宁夏回族自治区 | czt.nx.gov.cn | html（内联，无OCR） | 最干净的来源之一 |
| 宁波市 | czj.ningbo.gov.cn | html（内联，无OCR） | 不用"已完成招标"措辞，招标日只在标题里（靠`_TITLE_DATE_RE`） |
| 天津市 | cz.tj.gov.cn | image（JPG序列OCR） | 见10.3节，低产出但安全 |
| 湖南省 | czt.hunan.gov.cn | docx | TLS的`BAD_ECPOINT`问题，需要curl兜底 |
| 重庆市 | czj.cq.gov.cn | pdf（扫描/OCR） | 版式是"先列一排字段标签，再列一排对应值"（不是标签紧跟值），当前共享解析器认不出，低产出但安全 |
| 西藏自治区 | www.xizang.gov.cn | html（内联，无OCR） | 走的是省级政府门户不是独立财政厅域名（`czt.xizang.gov.cn`不存在）；日期语序用`_ISSUE_DATE_RE2`；曾被WAF拦截WebFetch请求，Playwright真实浏览器能过 |
| 山东省 | czt.shandong.gov.cn | pdf（文本原生） | 部分公告不含票面利率字段（文档本身没写，不是解析失败） |
| 青岛市 | qdcz.qingdao.gov.cn | pdf（扫描/OCR） | **必须用`http://`不能用`https://`**（https直接403，不是证书问题是硬性协议屏蔽）；低产出 |
| 河南省 | czt.henan.gov.cn | pdf（扫描/OCR） | 列表栏目是`/xwdt/tzgg/`（不是带`index_7.html`分页后缀的旧URL）；PDF文件本体托管在另一个子域名`xcoss.henan.gov.cn` |
| 大连市 | czj.dl.gov.cn | html（内联，无OCR） | **整个项目里结构最干净的来源**，标准模板直接是页面正文HTML；列表栏目`/col/col5025/index.html`（"财政公告"）和"信息披露文件"混排，靠`RESULT_KEYWORDS`过滤 |

**已确认是真死胡同（官网压根不发布"发行结果"类内容，不用再调研）**：内蒙古/陕西/浙江/湖北/江西/安徽/广东/黑龙江/吉林/云南/四川/甘肃（甘肃是WAF拦截未能内容级确认，其余11个是读了全文内容后确认没有这类文档）。

**还没解决、值得留给你重新尝试**：山西（这台环境的网络层TLS屏蔽，站点本身是活的）、福建（服务端的分类筛选逻辑bug，Playwright能正常渲染页面但拿到的是错误分类的内容）。

**这15个省份+12个死胡同覆盖了37个省份中的27个，剩下10个（甘肃之外的分类信息不全）没有专门调研过**——如果要扩展覆盖率，方法是：`WebSearch` 搜 `site:域名 地方政府债券 发行结果`，找到一个真实2026年的公告URL，用Playwright打开确认能读到内容，再照着上面的模板加进`PROVINCE_SOURCES`/`LISTING_URLS`两个字典，解析逻辑大概率复用现成的`parse_announcement_text()`，不需要新写代码（除非又出现一种新的文档模板变体）。

---

## 11. 补充数据源 D：chinabond.com.cn 全国统一门户（`chinabond_crawl.py`）

**这是四个补充数据源里覆盖面最广的一个**——中央国债登记结算有限责任公司（中债登，官方债券登记托管机构）运营，网址 `https://www.chinabond.com.cn/dfz/`，背后是一个**纯JSON REST API，不需要Playwright**，同时覆盖发行结果和发行计划两类文档，理论上覆盖全部37个省份（包括上面确认"官网无此内容"的死胡同省份——这些省份的数据仍然会出现在这个中央门户上）。

### 11.1 API

```
GET https://www.chinabond.com.cn/cbiw/lgb/infoListByPath
参数: _tp_lgbInfo=1, pageSize=10（其它值直接返回{"code":"500","msg":"pageSize无效"}，翻页参数还没找到，只能拿到每个筛选条件下最新10条）,
      channelName（结果频道="xxplwj_fxjg"，计划频道="xxplwj_fxjh"）,
      issuer（**必须用省份短名，不带"省/自治区/市"后缀**——比如"内蒙古"而不是"内蒙古自治区"，长名会返回0条结果，这是解锁被墙/官网无内容省份数据的关键），
      depth=3, lan=""
Headers: Referer: https://www.chinabond.com.cn/dfz/ （必须带，否则可能被拒）
响应: {"code","msg","lgbInfoList":[{...,"title","createTime","property0"(详情JSON链接)}]}
```
详情JSON（从`property0`取）里有`files`列表，每个file带真实PDF直链，`content`/`htmlContent`字段在实践中永远是空的——**真实数据永远在附件PDF里，不要期望这个API直接给结构化字段**。

短名映射：`_SUFFIXES = ["维吾尔自治区","回族自治区","壮族自治区","自治区","省","市"]`，从省份全名右侧尝试剥离这些后缀之一，剩下的就是`issuer`参数。

**这台机器/这个环境如果配了系统代理，偶发瞬时503**——包一层3次重试+`2*(attempt+1)`秒退避即可，不是数据源本身不稳定。

### 11.2 发行结果解析：直接复用第10节的 `parse_announcement_text()`

同一份标准化模板，不需要新解析器。**读这个来源的结果时有一个重要方法论**：一份文档里"没能在state_results.csv找到匹配"这件事，**必须先看这一行有没有成功解析出`issue_date`和`term`**——本项目实测：凡是这两个字段都成功解析出来的行，100%能在celma里找到对应记录；所有"找不到匹配"的情况全部是这两个字段本身就解析失败（OCR问题），不是celma真的缺这条数据。缺任何一个字段的"未匹配"结论都是无效的。

### 11.3 发行计划解析：需要新解析器（`parse_plan_pdf`），三层降级策略

实测至少存在4种不同的发行计划表格模板，需要分层处理：

**第一层：结构化表格解析**（`pdf_result["tables"]` 非空时优先尝试），两种方向：
- **列组方向**（山东/辽宁式）：新增债券/再融资债券是跨列的列组表头（各自再分小计/一般债券/专项债券三个子列），一个省份一行数据。解析思路：先分离出"数据行"（第一列含省/市/自治区/地区关键词，但要排除表头单元格自己就是"地区"两个字的精确匹配这种假阳性）和"表头行"，表头行做**向右前向填充**（合并单元格只在第一格有文本，后续格是None，要复制上一个非空值），然后每列同时看两层表头，落在(新增债券,一般债券)交叉处的列就是new_general的值，以此类推。
  ```python
  def _parse_plan_table_column_oriented(table):
      header_rows, data_row = [], None
      for row in table:
          first = (row[0] or "").strip()
          if first and first not in ("地区","省","市","自治区") and any(k in first for k in ("省","市","自治区","地区")):
              data_row = row
          else:
              header_rows.append(row)
      # header_rows 做前向填充，再按 (新增债券/再融资债券, 一般债券/专项债券) 定位data_row对应列
  ```
- **行组方向**（广东式）：新增债券/再融资债券是行组标签（在前面某一列），一般/专项债券在下一列，有一个专门的"合计"列存这一行代表的周期总额（这种模板通常按季度发布，把月/旬的更细颗粒度收进这一个"合计"数，本项目schema只到月度精度，不需要更细）。解析思路：先在前3行里找到"合计"两个字所在的列index，然后遍历数据行，遇到含"新增"/"再融资"的单元格更新当前所属大类，遇到"一般债券"/"专项债券"就用当前大类+这个子类拼出字段名，取"合计"列的值。

**第二层：文本正则降级**（表格解析都失败，比如扫描件没有表格结构但文本层还在）：先归一化OCR的小数点空格artifact（`re.sub(r"(\d)\.\s+(\d)", r"\1.\2", text)` —— OCR常把"27.0274"识别成"27. 0274"两段，不归一化会让后续的数字提取截断到小数点），然后在全文里找所有"一般债券"/"专项债券"标签紧跟的数字（`re.findall(r"一般债券\s*[|｜]?\s*([\d,]+\.?\d*)", text)`），**按出现顺序取值，不要按标签文本相对位置做前后切分**——已确认真实文档的OCR阅读顺序有时会把"再融资-一般"这个数字排在"再融资债券"这个分组标签文字**之前**，如果用"找到'再融资债券'这个词的位置，之前的算新增、之后的算再融资"这种切分逻辑，会把这个数字错误地漏掉。正确做法：假定文档内所有"一般债券"数字按[新增-一般, 再融资-一般]的固定顺序出现，第1个是新增，第2个（如果存在）是再融资；"专项债券"同理。

**第三层：位置推断+算术自校验**（表格结构和分类标签文字都丢了，只剩纯数字）：找一行以"合计"开头（容忍"合\s*计"中间有空格）且能提取出恰好7个数字的行，固定顺序假定为 `[总计, 新增小计, 新增一般, 新增专项, 再融资小计, 再融资一般, 再融资专项]`，**必须验证算术自洽才采信**（新增一般+新增专项≈新增小计，再融资一般+再融资专项≈再融资小计，新增小计+再融资小计≈总计，容差`max(0.5, 总计*0.01)`），任何一条不满足就返回`None`，绝不能拿一个没验证过的位置猜测当真实数据用。

三层的调用顺序：`parse_plan_pdf()` 先试两种表格方向解析，都失败再试文本正则，文本正则如果全部字段都是None，再试位置推断兜底。每一层降级都要在`warnings`里注明用的是哪一层，方便后续人工判断可信度。

---

## 12. 三方交叉校验编排：`three_way_validate.py`

这是把第8/10节两个补充数据源组装成一套统一校验流程的模块，**三个来源可信度不对等，处理方式必须不同**：
- celma（`state_results.csv`）是基准，其它都是"diff against"它，不是平等合并。
- SSE只能证明"存在"，不能核对金额/利率——`check_sse_coverage()` 的唯一产出是"celma缺失哪些SSE已知的债券"。
- 省级财政厅数据字段最全但整体可信度最低（很多来源要走OCR）——`diff_against_state()`的`low_confidence`桶要被严格尊重，`apply_corrections()`只在**同时满足**"不在low_confidence桶""唯一匹配到state_results.csv里的一条记录（不是模糊匹配到多条里随便挑一条）""确实是数值差异不是提取失败的None"这三个条件时才自动patch，**且只patch已有行的字段，从不新增行**（省级模板大多没有bond_code/bond_short_name，新增行有和celma未来自己发布时产生重复的风险）。

**匹配上的连环坑，这个项目连续踩过两次，你要提前防住**：
1. **"债"字归一化**：SSE的`securityAbbr`不带"债"字（"26江苏31"），celma的`bond_short_name`带（"26江苏债31"）——两边都要 `.replace("债","")` 再比较，否则会产生大量假阳性"缺口"。
2. **省份根名称缩写**：SSE把"黑龙江省"简称成"龙江"、"内蒙古自治区"简称成"内蒙"（砍掉的不是常见的"省/自治区"后缀，是根名称本身的一个字），celma不会这样简称。这两个是`config.PROVINCES`里仅有的根名称≥3字的省份，是一个封闭、可枚举的集合：
   ```python
   _PROVINCE_ROOT_ALIASES = {"黑龙江": "龙江", "内蒙古": "内蒙"}
   def _normalize(s):
       s = s.replace("债", "")
       for full, short in _PROVINCE_ROOT_ALIASES.items():
           s = s.replace(full, short)
       return s
   ```
   两条归一化都要做，`_is_known(abbr)` 检查 `abbr in known_shortnames or _normalize(abbr) in known_normalized`。**每次做这类跨源字符串匹配，第一反应应该是怀疑命名约定不一致，不要假设一个"看起来很大"的缺口数字就是真的**——本项目两次"发现大量缺口"最后都证明是自己的匹配bug，不是真实数据问题。

`run_validation(months_back=2)` 编排：SSE检查 + 遍历`provincial_crawl.crawl_all()`拿到的每省数据分别`diff_against_state()`，汇总成一个dict。`apply_corrections(validation)` 实际写回CSV（幂等）。`build_validation_report_xlsx()` 生成一份Excel报表（总览sheet + SSE缺口明细 + 省级核对明细 + 已自动修正列表），每个人工需要复核的行都要带上原始来源URL，不能只给汇总数字。

`check_chinabond_for_sse_gaps(sse_missing)`（第11节数据源的用法示例）：给定SSE标记的缺失债券列表，反查chinabond对应省份最近的发行结果条目，按`(chinabond文档日期 - SSE上市日期)`绝对差≤3天粗匹配，返回"文档层面找没找到"，**不做精确的字段级核对**——那一步需要真人渲染PDF页面看图核实（见第16节的教训）。**这整条链路故意不接入`main.py`默认流程**，是一个按需调用的诊断工具，不是自动化流水线的一部分——OCR不够可靠，写入主数据表之前必须有人看一眼渲染出来的PDF页面图片核对数字，不能盲信自动提取结果。

---

## 13. 输出层（简述，非本指南复刻重点）

- `build_outputs.py`：从三张state CSV生成 `output/local_raw_data.xlsx`（全量明细+公式校验版）、`output/local_summary.xlsx`（按期限/省份/品种分组统计）、`charts/boxplot_workday_gap_by_term.png`。
- `build_report.py`：生成 `output/local_report.md` 文字版摘要报告。
- `build_dashboard_plan.py`：**不生成新看板，是刷新一个已存在的大型静态HTML文件**（`output/bond_analysis_dashboard.html`）里两个用注释标记包起来的数据区块（发行计划、发行日历），用正则做marker-between替换，不重新生成整个文件。**这个HTML文件本身的内容不在本指南范围内**——它是几十轮会话手工设计+填充真实数据的产物，如果你的任务确实需要一个可视化前端，把它当成一个独立的、需要单独规划的项目来做，不要指望从这份指南直接生成。

---

## 14. 已知坑清单（预防性抄写自原项目 HANDOFF.md，全部是真实踩过的）

1. **列表页缓存导致"看不到新数据"**：celma列表页第1页URL是固定的（`zqsclb.jhtml?...&channelId=X`），只要本地缓存过就永远拿旧数据，哪怕站点已经更新。任何"数据感觉滞后"排查的第一步永远是先怀疑列表页缓存（`use_cache=False`），详情页/PDF缓存本身没问题（内容不可变）。
2. **`datetime.date` vs `pd.Timestamp` 比较静默返回False**：从CSV读出来经`.dt.date`处理的日期列是object dtype的纯Python `datetime.date`，不是`datetime64`，直接拿去和`pd.Timestamp`比较**永远是False，不报错**。用之前先`pd.to_datetime()`转换。
3. **不要把月度计划金额除以工作日数摊成"每日计划"**——那是编造数据。真正有逐日精度的只有`state_results.csv`的`issue_date`、`state_announcements.csv`的`bid_date`、SSE的`sseDate`，覆盖不到的日期就该留空。
4. **Python环境用`.venv`不用系统python3**——系统python3大概率没装pandas等依赖。
5. **多子档合并求和bug未在根源修复**：见第9节Wind核对部分的说明，`pipeline.py`的`keep="last"`去重策略会丢弃同一`bond_code`的其它子档金额，这是一个已知但还没修的限制，不是这份指南漏写了修复方法。
6. **跨数据源字符串匹配前，先假设命名约定不一致**：本项目至少两次把"命名约定差异"误判成"真实数据缺口"（"债"字有无、省份根名称缩写），每次都是因为直接做raw string比较。任何"发现一个很大的缺口/差异"的结论，落笔汇报前先抽样manual核对几条，不要直接相信程序第一次跑出来的数字。
7. **OCR来源的数据永远比文本原生来源低一个可信等级**：`extraction_method`要贯穿全流程标注清楚，任何自动patch/自动新增行的逻辑，都要把OCR来源排除在"高置信度可自动应用"的范围之外，改为人工核对后再写入（第11.3节和第16节的实际案例都是先渲染PDF成图片肉眼核对数字，再手写代码把验证过的值patch进CSV，不是让OCR自动写入）。
8. **改动前先`git status`**：这个仓库经常有本地未提交的`data/state_*.csv`增量抓取结果，任何可能丢弃未提交改动的命令（`checkout`/`reset`/`clean`）动手前先检查。

---

## 15. 建议实现顺序 / 里程碑

按这个顺序实现，每完成一步就用给出的验证方法测一下，不要囤积到最后一起测：

1. **第4节工具层**（config/http_client/classify/numerals/workdays）——单元测试几个正则/映射函数就够，不需要网络请求。
2. **第5节celma抓取**（listing_scraper → article_parser → pdf_extract）——跑一次`crawl_source()`确认能拿到真实的celma列表条目和详情页附件链接，人工挑1-2份PDF确认`extract_pdf()`输出合理的text/tables。
3. **第6节字段提取器**——针对每种`doc_type`各挑1-2份真实公告手动跑一遍`extract_*_fields()`，人工核对输出字段和PDF原文是否一致。**先做`extract_result.py`**，因为它是主字典，其它模块的验证都依赖有一个可信的`state_results.csv`做比对基准。
4. **第7节pipeline.py**——先用`--limit 20 --max-pages 3`这种小范围参数跑通端到端流程，确认state CSV能正确增量追加、去重逻辑不会误删数据。
5. **第8/9节SSE + Wind**——这两个不依赖大量调研，实现相对快，可以并行做，用来在早期就建立"celma数据有多准"的量化认知。
6. **第10节省级财政厅**——工作量最大，**直接照抄第10.6节的15个已验证URL开始**，不需要重新调研，先跑通这15个，再考虑是否扩展新省份。
7. **第11节chinabond.com.cn**——API发现的部分（issuer短名规则等）已经帮你踩完坑了，直接用；发行计划解析器的三层降级策略照着第11.3节的规格实现，用几份真实文档手动验证每一层。
8. **第12节三方校验编排**——把5/6/7的产出组装起来，第一次运行完一定要人工抽查几条"缺口"结论，确认不是命名约定bug（见第14节坑6）。

## 16. 怎么知道复刻成功了

不要只看"代码跑起来不报错"，用这几条**有真实数据基准**的检验标准：
- `state_results.csv`累计行数应该在1万+量级（celma从2018年至今的历史数据），2020年后的行`bond_code`覆盖率应该接近100%（覆盖不到就是`extract_result.py`的表头识别/分类判断有问题）。
- 用`wind_reconcile.py`或`three_way_validate.py`任何一个交叉校验模块跑一遍，**近2个月的窗口理论上应该趋近于0差异**——如果跑出来几十上百条"缺口"，先怀疑是不是又踩了第14节坑6（命名约定不一致），不要直接当成真实发现。
- 挑3-5份不同省份、不同结构类型（text-native/OCR/html/docx）的真实公告PDF，手动核对提取出的字段和肉眼读PDF的结果是否一致——这是唯一能真正验证提取正确性的方法，不能只看"有没有报错"。
