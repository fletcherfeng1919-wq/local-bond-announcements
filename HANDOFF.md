# 交接文档（写给零上下文的新会话）

最后更新：2026-08-11，最新 commit `e3fee4f`（已 push 到 `origin/main`，working tree 干净）。

## 1. 这是什么项目

`local_bond_announcements`：抓取 celma.org.cn（全国地方政府债券信息公开平台）的地方政府债券公告，结构化成表格，再做成一份交互式 HTML 分析看板。姊妹项目 `mof_bond_announcements`（国债公告）结构类似，其子项目 `wind_10y30y_spread_toolkit` 提供 Wind 口径的 10Y/30Y 国债活跃券每日中债估值收益率，用于计算"地方债 vs 国债利差"。

celma.org.cn 有三个抓取渠道（`channelId`）：
- **192 发行安排**（`dfzfxjh`，`doc_type="plan"`）→ `data/state_plans.csv`：月度/跨月的**计划**发行规模，按省份，无逐日拆分。
- **193 发行前公告**（`fxqgg`，`doc_type="announcement"`）→ `data/state_announcements.csv`：单期债券的招标前公告，含 `bid_date`（招标日，逐日精确）。
- **194 发行结果**（`fxjg`，`doc_type="result"`）→ `data/state_results.csv`：招标后的**已确认**结果，2020年起是标准化表格（含债券编码/简称/确认利率），2020年前是无编码的自由文本旧格式。这是主数据源，14,951行，覆盖 2018-10-26 ~ 2026-08-10。

代码结构：`src/pipeline.py`（抓取+落库主流程）、`src/extract_*.py`（三种文档类型的字段提取）、`src/config.py`（区域分组 `REGION_ORDER`/`PROVINCE_TO_REGION`、省份表 `PROVINCES`、期限表等常量）、`src/build_outputs.py`/`src/build_report.py`（生成 Excel/Markdown 报表）、`src/build_dashboard_plan.py`（见下）、`main.py`（CLI 入口，`python main.py` 跑全流程）。

## 2. 交付物：交互式 HTML 看板

**这是本次会话（以及最近好几轮会话）的主要工作对象。**

- 唯一权威文件：`/Users/sabacus/Projects/local_bond_announcements/output/bond_analysis_dashboard.html`（git 已跟踪，纯静态单文件，内嵌 CSS+JS+硬编码数据，无后端）。
- 已发布为 Claude Artifact：`https://claude.ai/code/artifact/86697346-81da-47bf-bc7c-438563254684`（每次用**同一个 `file_path`** 重新 `Artifact()` 发布即可保持同一个链接）。
- GitHub 仓库：`fletcherfeng1919-wq/local-bond-announcements`，分支 `main`。

### 当前看板结构（从上到下）

页头 → 数据源与方法说明卡 → 4个统计tile → **左侧滑动目录**（宽屏常驻/窄屏抽屉，滚动高亮当前章节）→ 背景知识（地方债定义/分类，含浙江省+宁波市的具体举例，说明只有省级政府和5个计划单列市（深圳/大连/宁波/厦门/青岛）能直接发债，普通地级市不能）→

**① 发行/公告状态**：发行前公告规律（提前期分布）、招标日时点规律、**本月/下月发行计划**（含时间图×区域堆叠柱、本月和下月各省规模横向条形图两张、以及**发行日历**网格组件）→

**② 发行量**：分期限发行规模、2022年以来发行规模、发行结构时间序列、发行规模趋势 →

**③ 利差**：收益率曲线演变、关键期限时间序列、**再融资债券研究**（原"券种利差"章节已改写，见下）、区域利差、地方债vs国债利差 →

**附录**：异常值逐条核实、数据校验说明（原来在页面靠前位置，已移到文末）。

已删除：原"结合市场研究框架的解读"整节（利差压缩与化债政策窗口相关性检验，相关系数只有0.12，判断意义不大，应用户要求删除）。

### 本次会话完成的工作（按时间顺序）

1. 目录从"页面内嵌网格卡片"改成**左侧滑动侧边栏**（`.side-toc` / `.toc-toggle` / `.toc-backdrop`）：≥1440px 宽屏常驻左侧、正文让出空间；窄屏收起为左上角"☰目录"按钮点击滑出，带遮罩层；`IntersectionObserver` 做滚动高亮当前章节。
2. 新增"本月/下月发行计划"章节，取代原来单月版本：
   - 数据来自 `state_plans.csv`（发行安排，月度口径，非逐日）。
   - "本月"/"下月"是**相对当前系统日期动态计算**的（`pd.Timestamp.now()`），不是写死某个月份，代码会自动滚动。
   - 一张时间图（本月 vs 下月，按 `config.REGION_ORDER` 五大区域堆叠着色）+ 两张各省规模横向条形图（本月/下月并排）。
3. 新增**发行日历**组件（对照用户提供的 Wind 终端日历截图做的月历网格）：周表头+每格显示当日"N只·X亿"和强度条，可点击展开当日债券明细表。**数据来自 `state_results.csv`（已确认发行结果，issue_date 逐日精确）**，因为"发行安排"渠道压根没有逐日数据（见坑3）。**2026-08-10 追加修改**：日历从"最新一个有完整确认数据的月份"（单月）改成了和上方"本月/下月发行计划"同款的**本月+下月两格并排**结构（`_calendar_month_slice()`，复用 `_current_and_next_month()`），"下月"绝大多数时候会是空的（确认结果不可能有未来数据），此时渲染明确的"暂无已确认的发行结果数据（该月尚未开始，或结果尚未公布）"空状态，不是bug。UI 文案里明确写了这是"已确认口径"、和上方"计划"口径不是一回事，不要在后续修改中把这条边界模糊掉。
4. 重新抓取刷新了 `data/state_plans.csv`（发现并绕开了坑1，见下）和 `data/state_announcements.csv`。
5. 把"券种利差"章节改写成**再融资债券专题研究**：定义（含"特殊再融资债券"）、发行时间（2019→2025规模增长4.9倍）、规模（七年累计25.7万亿，占比45.7%）、省份集中度（前10省份额51%，和全市场整体集中度相近，但具体是哪些省份进了前5发生了明显位移——贵州/湖南挤掉了广东/浙江，与"特殊再融资定向置换债务压力省份隐性债务"的政策设计吻合）。原因：老版本"再融资定价明显更紧"的结论，用国债利差法重新验证后站不住脚（见坑10），干脆把这节从"定价结论"改成"描述性研究"，避免继续用不稳健的结论。
6. 删除"结合市场研究框架的解读"整节。
7. 新建 `src/build_dashboard_plan.py`：**可重复运行的数据刷新脚本**，从 `state_plans.csv`/`state_results.csv` 重新计算"本月/下月计划"和"发行日历"两块数据，通过 marker 注释（`// PLAN_DATA_START` … `// PLAN_DATA_END`、`// CALENDAR_DATA_START` … `// CALENDAR_DATA_END`，均在 `output/bond_analysis_dashboard.html` 里）做正则替换，不动文件其他部分。已接入 `main.py`：正常运行 `python main.py`（或 `--skip-crawl`）就会自动刷新这两块，不需要手改 HTML。

**2026-08-10 追加的一轮修改**（commit `1fd0371`）：用户反馈发行日历一直停在7月，要求补上8月并且以后固定显示"本月+下月"。排查发现是坑1（列表页缓存）又犯了一次——`state_results.csv` 的确认结果实际已经更新到了 8-07，只是没重新抓取。处理过程：① 用 `use_cache=False` 重新抓取三个渠道里滞后的一个（`fxjg`/发行结果），拿到8月前7天的确认数据；② 把 `_build_calendar_data()` 从"取最新一个有数据的月份"改成了和 `_build_plan_data()` 完全一样的"本月/下月"结构（新增 `_calendar_month_slice()`，复用已有的 `_current_and_next_month()`）；③ 日历 HTML/JS 从单日历拆成本月/下月两个并排的 `chart-card`（`drawPlanCalendar()` 重构成 `renderCalendarMonth(month, ids)` 参数化调用两次，和 `renderProvinceMonth()`是同一个模式）。**这条修改印证了坑1不是一次性踩完就完事的——凡是"数据感觉滞后/停更"的报告，先怀疑列表页缓存，这次依然是同一个原因。**

**2026-08-11 追加的一轮修改**（commit `9c31bc9`）：用户拿 Wind 终端截图对比，指出即使补了8月数据，我们的"已确认"覆盖范围（当时到8-07）还是比 Wind 差一大截——Wind 对8-10的招标已经有确认利率了。查证后确认这**不是抓取问题**：直接绕过缓存重新抓 celma 的"发行结果"栏目，最新还是只到8-07——celma 平台自己的确认结果公告本身相对实际招标就有约1周的发布滞后，这是数据源结构性的，不是我们抓取的问题。

为了缩小这个滞后，找到并接入了一个新的数据源——**上交所（SSE）债券信息网的"上市公告"**：
- 真实接口是 `https://query.sse.com.cn/commonSoaQuery.do`，关键参数 `sqlId=BS_ZQ_GGLL&bondType=LOCAL_GOVERNMENT_BOND_BULLETIN`（不是网上能查到的 `commonQuery.do`，是猜不出来的，只能靠抓真实请求）。这个接口的数据是**当天**的（请求当天就能看到当天发布的上市公告）。
- **重要限制**：这个"上市公告"类型的PDF本身**不含票面利率**——原文明确写"本期债券其他具体要素内容见发行公告及相关发行文件"，把利率细节推给了另一份文件。所以这个数据源只能确认"债券已经成功发行、开始交易了"，确认不了利率是多少。**不要试图从这个PDF里解析利率，没有**。
- 因此日历现在是**三态**：已确认（`state_results.csv`，有利率）→ 已上市/利率待补（新的SSE数据源，没利率但比celma快）→ 已公告待开标（`state_announcements.csv` 的 bid_date，招标前）。三者按这个优先级填格子，同一天不会重复。
- 新建了 `src/sse_listing.py`：`fetch_recent_listing_notices(date_start, date_end)`，纯 `requests.get`（不需要登录/不需要浏览器，直接调这个URL就行），**不落盘存CSV**——因为这份数据只对"当下"有意义，不是要长期归档的历史数据，每次跑 `main.py` 现查现用。
- **接口是怎么找到的，供以后同类需求参考**：这类新式政府/交易所网站前端是JS单页应用，数据靠后台JSON接口异步加载，页面源码里看不到接口地址，纯靠 requests/curl 猜参数基本猜不中（试过 `commonQuery.do` 全部404/报错）。最后是装了 **Playwright**（`.venv/bin/pip install playwright && .venv/bin/playwright install chromium`，浏览器装在项目 venv 里，不影响系统），写了个脚本（`capture_sse_api.py`，未保留在仓库里，是临时脚本）跑一个真实的无头浏览器打开目标页面、监听所有 `response` 事件里 `content-type` 带 `json` 的请求，把真实调用的 URL 印出来——这样不到几分钟就找到了真接口，比瞎猜参数靠谱得多。**以后遇到类似"这个网站数据要API直连，但接口没文档"的需求，直接复用这个 Playwright 网络抓包思路**，不要再手动猜 sqlId 之类的参数。
- 顺带排除了两条走不通的路，别再浪费时间重复尝试：`chinamoney.org.cn`（中国货币网新域名）服务器的TLS配置太老，触发"unsafe legacy renegotiation disabled"，`curl`和Python `requests`（哪怕手动开`ssl.OP_LEGACY_SERVER_CONNECT`）都连不上，这是这台机器的OpenSSL版本（3.6.3）和对方服务器双方协议不兼容，不是请求方式的问题。`chinamoney.com.cn`（老域名）有一套"IP注册"反爬机制（跟着 AKShare 源码里 `bond_china_money.py` 的 `__bond_register_service()` 三步握手能注册成功），但注册后 AKShare 用的实际取数接口 `ags/ms/cm-u-bond-an/bnBondEmit` 现在返回 `404 Path not found`——网站后端已经改版，那个接口失效了。
- 期间用户还提过一个第三方工具 **OpenCLI**（`github.com/jackwener/OpenCLI`，号称能把网页/浏览器会话转成CLI命令），调研后发现要装 Node.js（这台机器没有）+ npm全局装第三方包，且它真正的"浏览器会话"能力依赖一个我装不进用户真实浏览器的Chrome扩展——用户权衡后选择了用 Playwright（不需要系统级新运行时，包在项目 venv 里）而不是 OpenCLI，**没有实际安装或使用 OpenCLI**，如果以后又提起这个工具，是没有装过的状态。

**同一天的后续修正**（commit `9c31bc9`）：用户拿实际 Wind 截图逐日核对，发现"已上市"那天的债券名单和 Wind 按"招标日"排的名单对不上。查证坐实：**SSE的"上市公告"发布日期比实际招标日晚约1个工作日（T+1），不是当天**——验证方法是核对2026-08-11发布的16条上市公告，对应的债券在Wind上全部显示是2026-08-10招标的，完全对得上但错一天。找过 SSE 有没有能查到真实起息日/招标日的接口（试了它的行情榜单接口 `yunhq.sse.com.cn:32042/v1/shb1/list/exchange/all`，那个只有实时价格/涨跌幅，没有票面利率或起息日字段），没找到，而且SSE的证券简称编号和我们自己`state_announcements.csv`里的批次编号对不上（不是同一套编号规则），没法可靠地跨源匹配拿到真实招标日。最终按用户选择保留"按上市公告发布日期占格子"的结构，但在三处地方（日历上方说明段落、点开某天后的详情面板提示、`_calendar_month_slice()`的docstring）都把"这是公告发布日，不是招标日，通常晚1个工作日"写得非常明确。**这条不是bug，是已知的口径限制，别当成新问题重新调查。**

**2026-08-11 第二轮修改**：用户要求把上一节提到的"约30个硬编码图表"全部重新算一遍。做法：写了一个一次性脚本（未保留在仓库，跑在session scratchpad里）用 `pandas` 直接从修复后的 `state_results.csv` 按每个 `drawXXX()` JS函数的口径重新计算——**关键是先逐个读完 `output/bond_analysis_dashboard.html` 里所有 `drawXXX()` 函数源码，搞清楚每张图到底是中位数/求和/计数、按哪个字段分组、年份口径是不是"2026\*"（不完整年份）——不能凭图表标题猜口径，必须读JS里的聚合逻辑**。核对方法：把新算出的值和当前HTML里硬编码的旧值逐项diff，只有真正变化的值才动手改，没变的不碰（很多历史年份，如2020/2021，几乎没变化，因为Wind核对只覆盖了近1年窗口）。结果：
- **确认哪些图表不需要重算**：`drawHist`/`drawTermGap`/`drawRegionGap`/`drawWeekday`/`drawMonth`/`fillOutlierTable`（都来自 `state_announcements.csv` 的 `workday_gap`/`bid_date`）——用 `git diff --stat` 确认这两份文件本次会话完全没变，所以这几张图的口径没受Wind核对影响，直接跳过，不要浪费时间重算。
- **确认哪些图表继续BLOCKED**：`drawTspreadRegion`/`drawTspreadYear`/`drawTspreadRegionYear`（地方债vs国债利差三张图）——依赖 `mof_bond_announcements/wind_10y30y_spread_toolkit` 子项目导出的Wind国债收益率，那两个xlsx文件（`10Y30Y国债利差建模工具.xlsx`/`新老活跃券利差.xlsx`）用openpyxl读全是空值（依赖Excel里活的Wind插件公式，没有缓存静态值），本地没有能重新计算的数据源，这三张图和对应文字段落**原样保留，仍标注"仅至7月"**，没有跟着改成"8月10日"。
- **其余约20个图表全部重算并更新**：包括 `drawCurve`（收益率曲线）、`drawKeytermRate/Count`（关键期限）、`drawPremium`（期限溢价）、`drawMix`/`drawVolume`（券种结构/规模趋势）、`drawRefiTrend`/`drawRefiProvinceChart`（再融资研究两张图）、`drawRegion`（区域利差）、`drawTermVolume`/`drawTermVolumeYear`/`drawRecentTerm`/`drawRecentRegion`（分期限/分地区规模）、4个统计tile、浙江/宁波举例段落的样本数。同时把所有"2026仅至7月"字样（治理条数据以外的十几处）统一改成"2026仅至8月10日"，因为这次Wind核对把覆盖范围从7月底扩到了8月10日。
- **一个中途自查纠正的细节**：浙江省的记录数从452变成了看似460，但按类别分（专项328+再融资103+一般21=452）加总后其实还是452——多出的8条是2020年以前的无编码旧格式占位行（`extraction_method=="unsupported_legacy_format"`），`category_code`是空的，不应该计入"452条"这个按券种分类的统计。**原文案里"452条"本来就是三个子类别之和，不是`len(df)`，重算脚本一开始直接用了`len(df)`导致误判成"变了"，核对子类别加总后发现浙江省本级其实没变，只有宁波市是真变了（219→222）**——以后任何"总记录数 vs 按类别拆分之和不一致"的情况，优先怀疑是不是有 `category_code` 为空的行（大概率是2020年前旧格式占位行）被算漏或算重了。
- 附录"数据校验说明"新增了④⑤⑥⑦⑧四条（原来只有①②③④，现在④改名描述当前状态，新增⑤多批次未汇总、⑥合并通知误挂载、⑦简称内部空格、⑧Wind核实后确认），把之前 `wind_reconcile.py` 那一轮修复的三个bug也写进了看板正文（之前只写在HANDOFF.md和commit message里，看板本身没有体现）。
- 已按坑4的完整流程做（scratchpad改→cp到output→跑 `sips`/Chrome截图校验→cp回scratchpad→发布Artifact→git commit），结构校验（`<section>`/`<div>`/`<table>`标签配对、JS大括号配对）和headless Chrome截图视觉核对全部过了。

**同一天，用户中途插入了一个新方向**：不满足于只对比Wind，还想找**省级财政厅/财政局官网自己的"发行结果"专栏**作为第三方交叉验证源，且明确说优先级是"最近两个月+当前月+下月"这个滚动窗口（不是历史全量补全）。用6个并行research agent（每个5个省，共27个省+此前已验证的上海）分别去搜索确认，结果：
- **完全确认可用**（找到真实2026年URL，结构已看清）：上海（`czj.sh.gov.cn`，封面页+PDF）、新疆（`czt.xinjiang.gov.cn`，封面页+PDF）、天津（`cz.tj.gov.cn`，**图片格式**，需要OCR不是PDF）、河北（`czt.hebei.gov.cn`，封面页+PDF）、贵州（`czt.guizhou.gov.cn`，封面页+PDF，按月固定节奏发布）、宁夏（`czt.nx.gov.cn`，**直接内嵌HTML表格，不需要PDF提取**，最好解析）、湖南（`czt.hunan.gov.cn`，封面页+**.docx**不是PDF）、重庆（`czj.cq.gov.cn`，找到封面页但WebFetch没能取出正文，需要人工/换方式确认结构）、江苏（`czt.jiangsu.gov.cn`，封面页+PDF）、宁波（`czj.ningbo.gov.cn`，内嵌HTML表格，2025年例子确认，2026年大概率同结构但没搜到具体URL）。
- **部分线索但未确认**（域名/栏目找到了，具体2026年"发行结果"URL没锁定，或者被WAF/证书问题挡住了）：甘肃、西藏（WAF拦截WebFetch）、山西、陕西（栏目名不叫"发行结果"叫"信息披露文件"）、山东、青岛（SSL证书配错到别的局域名下，WebFetch连不上）、浙江（栏目找到但具体URL 404）、湖北、河南、江西（栏目疑似JS渲染，WebFetch拿不到列表）。
- **确认没有省本级独立发布**（查了多个角度，真没有，不是没搜到）：内蒙古（明确排查了三个可能栏目，全部只有发行通知没有发行结果，结论是这个省份只能靠celma/SSE）。
- **完全没找到**：安徽、广东、吉林（一次路径猜错没重试）、黑龙江、云南、四川、福建。
- 用户原话："you can start consolidate the provincial findings into a usable module after the current task, you don't need to refresh those data when the data is not complete"——**明确表态不需要把剩下没确认的省份都调查到完整**，先把已经确认能用的10个省份接入一个可用模块即可，这是下一步的任务，见第3节。

## 3. 当前卡在哪 / 已知缺口

Wind核对+全量图表重算这两件事都已完成、验证、发布、提交、推送。`git status` 干净，`HEAD` 和 `origin/main` 一致（`d8bedd3`）。**唯一未完成的是省级财政厅交叉验证模块**（见上方"当前真正待办"小节）——已经做完调研（27省搜索结果），代码还没写，不算阻塞，只是还没开工。

**但有一件重要的、只完成了一半的事，下一个会话大概率会被继续问到**：用户提供了一份Wind终端导出的"地方政府债一级市场"报表（覆盖2025-08-11~2026-08-10，2487条已确认债券），说这是最准的数据源，让核对我们自己的 `state_results.csv` 有没有缺口。核对结果发现了**三个真实的、系统性的提取bug**（不是孤立的8月问题，全年都有）：
1. **多子档合并求和bug**：91支债券的 `total_amount_yi` 偏低——根因是同一 `bond_code` 在celma PDF表格里会拆成2-3行（比如一支专项债同时对应"项目收益/棚改/土地储备"三个子用途），`pipeline.py` 按 `bond_code` 去重时用 `keep="last"` 只留最后一行，其余子档金额被静默丢弃，而不是求和。
2. **issue_date缺失bug**：135支"缺失"的债券里，有41支其实不是真缺失，是已有记录的 `issue_date` 提取失败（NaN），导致任何按日期筛选的比对/图表都看不到它们——这条独立于Wind核对本身，是更早已经存在的数据质量问题，可能影响全库14833+行里的**394行**（不只是这41支）。
3. 剩下94支债券是celma确实还没发布或提取彻底失败，属于正常缺口。

已建 `src/wind_reconcile.py` 做了修复：按 `bond_short_name`（验证过和celma的短称格式完全一致）做全局匹配（不能按日期窗口过滤查找，第一版按窗口过滤就是因为这样才漏掉了issue_date=NaN的行，试错踩过一次坑，已改成全局查找），修正了91处金额、2处利率、50处issue_date，新增94行，合并/清理了4对（Wind覆盖范围内的）"同一债券在原数据里重复出现两次"的脏数据；跑了两遍确认幂等（第二遍diff全为0）。`state_results.csv` 从14889行变成14979行，`total_amount_yi` 总和增加了约6,158亿元（约占原先dashboard统计瓦片"累计发行规模57.6万亿元"的1.1%）。已刷新了看板的日历/计划两个**实时读取CSV**的板块（现在"已确认"正确覆盖到2026-08-10）。Wind的xlsx本身已经加进 `.gitignore`（授权数据不能提交），只提交了修复后的CSV和新脚本。

**"约30个硬编码图表重新计算"这件事已经在2026-08-11第二轮修改里做完了**（见上方对应小节），不再是待办事项。

**`src/provincial_verify.py` 已经建好并且用真实数据端到端验证过**（2026-08-11，同一轮会话）。关键发现和设计决策：

- **省级公告和celma用的不是同一套模板**：一开始猜测省级PDF可能复用celma的"表2-9/表2-10"标准化表格（`extract_result.py` 已有的列名匹配逻辑或许能直接复用）——**这个猜测是错的**。实测发现省级公告统一遵循财库〔2020〕43/36号要求的另一套模板：按"债券名称/计划发行规模/实际发行规模/发行期限/票面利率/发行价格/付息频率/付息日/到期日"的键值对列举每支债券，**多数省份（江苏/宁夏都验证过）压根不含债券编码/债券简称字段**——只有个别省份（确认：新疆）的模板额外带了"债券代码/债券简称"。所以匹配 `state_results.csv` 不能像 `wind_reconcile.py` 那样按短称匹配，主匹配键改成了 `(province, issue_date, term)`，短称存在时才优先用（更可靠）。
- **单一个共享正则解析器就够了**（`parse_announcement_text()`），不需要每个省份单独写解析代码——因为不管数据来源是干净HTML（宁夏/宁波）还是PDF文本（含OCR，江苏/新疆/河北），字段词汇是同一套。真正需要区分的只是"怎么拿到这段文本"（HTML直接读 / PDF走 `pdf_extract.extract_pdf()`），不是"怎么从文本里抠字段"。
- **OCR质量问题比预想的更麻烦，已经踩过两次并修好**：解析器按"债券名称"这个词切分债券区块，但OCR质量差的PDF会漏掉部分"债券名称"标签，导致相邻债券的字段串块（比如新疆一支债券的票面利率被错误安到另一支债券的发行规模上）。**这不是假设性风险，是实测真实发生的**：新疆和河北两个例子都命中了。加了两层防护并都用真实案例验证过：① 数一下文档里"债券简称"出现的次数和切出的分块数是否一致（新疆案例靠这个抓到）；② 检查"债券名称"字段本身有没有混入"债券代码/存续期/票面利率"等字段标签词（河北案例靠这个抓到，因为河北的OCR连"债券简称"本身都大部分丢了，检查①测不出来）。**任何一层触发，该行就标记 `warnings` 进 `low_confidence` 桶，绝不能被当成真实的金额/利率差异报出去**——中途一度因为多加了一层"检测bond_name里有几个'20XX年'"的防护，把宁夏合法的"A方案名-B方案名"双名债券（同一支债券的两个官方名称用连字符连起来，不是两支债券拼在一起）也误判成了污染，已经改成检查字段标签词泄漏而不是数年份戳，重新验证过宁夏6支债券又变回全部干净匹配。
- **端到端真实测试结果**（6个省份，全部用研究阶段找到的真实2026年公告URL）：上海4/4匹配、宁夏6/6匹配、贵州1/1匹配、江苏2/3匹配（第3支因OCR漏字段无法解析，非真实差异）、新疆和河北各1行但都被正确标记成"低置信度/需人工核对"而不是报成假的利率/金额差异。**这一轮没有发现任何真实的celma数据错误**——这本身是有价值的信息（对已测试的这几个省份，celma数据得到了独立验证），不是"没做出结果"。
- **仍未接入的3个源**：湖南（.docx附件，需要 `pip install python-docx`，项目目前没装）、天津（发行结果直接嵌图片JPG，需要OCR，比PDF更麻烦）、重庆（封面URL是真的但研究阶段WebFetch没能取出正文/附件，结构本身还没确认）——调用 `verify_announcement()` 对这三个省份会抛 `NotImplementedError`，不是静默失败。

用户原话："you don't need to refresh those data when the data is not complete"——**没有主动去把"部分确认"和"完全没找到"的那17个省份（甘肃/西藏/山西/陕西/山东/青岛/浙江/湖北/河南/江西/安徽/广东/吉林/黑龙江/云南/四川/福建/内蒙古）继续调查**，`PROVINCE_SOURCES` 里只登记了这10个。如果用户以后要扩展覆盖范围，先重复2026-08-11用过的方法（WebSearch找`site:域名 地方政府债券 发行结果`+WebFetch验证一个真实URL），再把新省份加进 `PROVINCE_SOURCES` 字典，解析逻辑大概率不需要改（除非又出现新的文档模板变体）。

**当前真正待办**：还没有把这个模块接入 `main.py` 或做成自动化的"每月定期跑一遍"——目前是纯函数库，调用方式是手动 `from src import provincial_verify as pv; pv.verify_announcement(province, url)` 传入一个具体URL（因为省级列表页大多是JS渲染或有WAF挡着，找不到可靠的自动发现入口，见模块docstring）。如果用户要"每月自动跑"，需要先解决"怎么自动找到本月最新公告URL"这个问题——目前没有好方法，可能需要用 Playwright（本次会话早些时候找SSE接口时验证过的技术路径）对着这10个省份各自的列表页跑一遍网络抓包，或者干脆保持"用户看到新公告URL就手动传进来核对"这个更轻量的用法。

**另外，`地方政府债*.xlsx` 这个文件名模式现在是Wind核对的标准输入**——如果用户以后又存了一份更新/更大的同名（或类似命名）文件到项目根目录，说"再核对一下"，直接调用 `src.wind_reconcile.reconcile_from_wind_file('文件名.xlsx')` 就行，不需要重新设计。

**但过程中发现了一个未修复的数据质量问题**（不是本次任务范围内的活，只是顺带查出来的）：`state_announcements.csv` 里存在若干"不同URL/不同批次公告，但金额可疑地完全相同"的情况——例如湖南省2026-08-04的第23批和第24批再融资公告（两个不同URL），提取出的金额都是同一组数字（170.00/42.53/180.00）；广西壮族自治区2026年8月三个不同批次（一般再融资、专项再融资批次一、批次二）金额也都是244.42。**没有去调查根因、也没有去 dedupe**——因为不确定是提取环节真的把两份PDF的表格数据串了（类似此前"发行结果"里遇到过的列错位/跨公告重复类问题），还是这些批次凑巧金额一致；贸然dedupe可能反而把真实的重复批次错误合并掉。如果以后有人要用 `state_announcements.csv` 做严肃的金额统计（不只是日历展示），建议先查一下 `src/extract_announcement.py` 的表格提取逻辑，重点看同一省份同月多个批次公告是否共享了同一张表。

但这是一个跨很多轮会话的长期项目，历史上还遗留几个**从未闭环**的旧任务（来自更早期会话的 todo list，本次会话没有触碰，如果用户提起要记得）：

- **2020年以前的旧格式"发行结果"从未处理**：`state_results.csv` 里有 387 行 `extraction_method == "unsupported_legacy_format"`——这些是 2020 年前的自由文本发行结果公告，没有债券编码字段，代码里有意跳过（见 `src/extract_result.py` 顶部注释），从来没做过单独的旧格式解析器。如果用户要"补全2020年以前的债券字典"，这是要做的事。
- 更早期还有一条 todo 提到"re-run ~90 old announcement gap-fill items"（大意是有约90条发行前公告因为一个已修复的PDF缓存损坏bug需要重新抓取验证）——**当前会话没有去核实这条是否已经处理完**，如果用户提起，先去查证现状而不是直接假设它还没做或已经做了。
- 下月（当前是2026年9月）发行计划数据目前只有 2/37 个省份提前公布——**这是正常现象不是bug**，多数省份的月度发行安排会在月底前陆续发布，脚本会在下次刷新时自动捕捉更多。发行日历"下月"格子目前是空的同样正常——确认结果不可能有未来数据，等到了9月它自然会变成"本月"并开始有数据。

## 4. 下一步可能的计划（未经用户确认，仅供参考）

- 如果用户要继续扩展看板：目前 6 个"坑"里最容易被下一次修改重新踩中的是坑1（缓存导致数据显示滞后）和坑4（两份文件不同步）——动手前先复习第5节。
- 如果用户要处理 2020 年前旧格式结果数据，需要新写一个 `extract_result_legacy.py`（`extract_result.py` 里已经预留了这个文件名和判断逻辑的 TODO 位置）。
- 如果用户要给看板加更多"自动刷新"的章节，复用 `src/build_dashboard_plan.py` 的 marker-替换模式（单行注释、`re.DOTALL` 非贪婪匹配），不要发明新模式。

## 5. 踩过的坑 —— 绝对不要再踩

1. **列表页 HTML 会被缓存，导致"新帖子看不见"**：`src/http_client.py::fetch()` 按 URL 哈希缓存 HTML。celma.org.cn 的列表页第1页 URL 是固定的（`zqsclb.jhtml?...&channelId=X`），哪怕站点已经发了新公告，只要本地缓存过第1页，`use_cache=True` 的增量抓取会永远拿到旧缓存，看起来"没有新数据"。**本次会话在刷新 `state_plans.csv`/`state_announcements.csv` 时踩过这个坑**：第一次用 `use_cache=True` 抓取显示 0 条新增，改成 `use_cache=False`（只对列表页，不影响详情页/PDF的缓存）后立刻抓到了新条目。**以后任何"数据感觉滞后"的排查，第一步就是检查是不是列表页缓存的问题**，详情页/PDF 缓存本身没问题（内容不可变，可以放心复用）。

2. **`datetime.date` 和 `pd.Timestamp` 比较会静默返回 `False`，不报错**：`pipeline.py::load_state()` 用 `.dt.date` 解析日期列，得到的是 object dtype 的纯 Python `datetime.date`，不是 `datetime64`。用 `df['some_date_col'] == pd.Timestamp(...)` 这种比较**永远是 False**，不会抛异常，非常隐蔽。`build_dashboard_plan.py` 第一版就因为这个 bug 导致 `refresh_plan_section()` 悄悄返回 `None`（看起来"运行成功但什么也没做"）。**修复方式**：凡是要拿这些日期列去和 `pd.Timestamp`/字符串日期比较，先 `df[col] = pd.to_datetime(df[col])` 转换一遍。

3. **"发行安排"（计划）数据只有月度粒度，没有逐日拆分**——**不要为了做日历/时间图就把月度总额除以工作日数摊出"每日计划"**，那是编造数据。真正有逐日精度的是：`state_results.csv` 的 `issue_date`（已确认结果，但发布有滞后，通常滞后约一周）、`state_announcements.csv` 的 `bid_date`（招标前公告，通常只提前约5个工作日才有，见下方坑9）、以及新加入的 SSE"上市公告"（见上方2026-08-11条目，`src/sse_listing.py`，同日数据但没有利率）。**2026-08-11 更新**：发行日历组件现在是**三态**——`issue_date`填"已确认"，SSE上市公告填"已上市/利率待补"，`bid_date`填"已公告待开标"，按这个优先级覆盖同一天（`confirmed > listed > scheduled`）。三者在 UI 上用实线/点线/虚线+颜色明确区分，"已上市"和"已公告"两类的 `couponPct` 永远是 `null`（利率还没定），千万不要因为"数据能凑出来"就给它编一个利率或规模——SSE上市公告连规模都没有（`amountYi` 也是空）。**这三个口径都不能覆盖到的日期（超出已公告/已上市范围的未来）就应该留空，不能再拿月度计划硬拆日去填**——那还是编造数据。另外要注意："已上市"（SSE通知发布日）和"已公告"（原始bid_date）是两个不同的日期概念，同一支债券理论上可能在两个不同的日子里各出现一次（不去做跨源的债券身份匹配去重，这是已知的、接受的简化，见 `_calendar_month_slice` 里的说明）。

4. **两份 dashboard 文件必须手动保持同步，且顺序不能错**：编辑用的是 session 临时目录下的 scratchpad 副本（`/private/tmp/claude-501/.../scratchpad/artifact/bond_analysis.html`，**每个新会话这个路径都会变**，不是固定路径），仓库里的权威副本是 `output/bond_analysis_dashboard.html`。`src/build_dashboard_plan.py` 的两个 `refresh_*_section()` 函数**只会改 `output/` 里那份**（硬编码 `config.OUTPUT_DIR`）。正确顺序永远是：① 在 scratchpad 副本上改 HTML/JS → ② `cp` scratchpad→output → ③ 跑 Python 刷新脚本（改的是 output 那份）→ **④ 再 `cp` output→scratchpad 一次，把刷新后的数据拷回去** → ⑤ 用 scratchpad 路径发布 Artifact → ⑥ git commit output 那份。**本次会话真实踩过一次**：忘了第④步，把还没刷新（日历数据是空 `{}` 桩）的 scratchpad 版本发布成了 Artifact，靠 `diff` 两份文件才发现，之后才补做第④步重新发布。**每次发布前务必 `diff` 一下两份文件确认完全一致。**

5. **改 HTML 之后必须做结构校验，发布前再做一次**：`<section>`/`</section>`、`<div>`/`</div>`、`<table>`/`</table>` 用 `grep -o ... | wc -l` 数量对比；JS 部分把 `<script>...</script>` 之间的内容单独抽出来，用 Python 数 `{}`/`()`/`[]` 是否配对；再用正则把 HTML 里所有 `id="X"` 和 JS 里所有 `getElementById('X')` 各自收集成集合，做差集，确认没有 JS 引用了不存在的 DOM id。这套校验流程在本次会话反复用来在发布前兜底，成本很低，务必每次编辑后都跑。

6. **这个项目的 Python 环境是 `.venv`，不是系统 `python3`**：系统 `python3`（`/opt/homebrew/bin/python3`）没装 pandas，任何跑数据分析的命令都要用 `cd /Users/sabacus/Projects/local_bond_announcements && .venv/bin/python3 ...`，不要直接裸调 `python3`。

7. **区域配色和券种配色有固定映射，不要发明新的**：区域五色固定用 `[colors.s1, colors.s3, colors.s2, colors.gold, colors.inkMuted]` 对应 `config.REGION_ORDER = ["北上广深","东部沿海","华北西南","中原西北","东北内蒙"]`；券种三色固定 `s1`=一般债券、`s2`=专项债券、`s3`=再融资债券。全篇所有图表都遵守这个映射，新加图表也要沿用，不要为了"好看"重新配色导致同一个区域/券种在不同图里颜色对不上。

8. **只有省级政府和5个计划单列市（深圳/大连/宁波/厦门/青岛）能独立发债，普通地级市不能**——这是用真实数据验证过的（浙江省452条记录全部以"浙江省"为发行人，无一条以具体地级市命名；宁波市219条记录完全独立于浙江省单独统计）。以后遇到类似"某某市发的地方债"的问题，先确认这个市是不是5个计划单列市之一。

9. 法定最低提前期是5个工作日（财库〔2020〕43号），86%的发行前公告精确卡在这条线上——这个统计结论已经在看板里，不要重新计算出不一致的数字而没意识到这是已知的、已验证过的规律。

10. **"再融资债券定价明显更紧"这个结论已被推翻，不要再用**：用原始票面利率算，再融资确实比专项/一般新增低30-60bp；但改用"地方债vs国债利差"法（控制了发行时点对应的整体利率水平后）重新算，再融资利差在全周期/全区域合并口径下并不是最紧的，2023-2024两年甚至是三类中最宽的。原因是再融资债券发行时点系统性偏向近年（低利率环境），原始利率对比被这个时间构成混淆了。这也是这节被改写成"再融资债券研究"（去掉定价结论、改成描述性研究）的原因。

11. **改动有风险的操作前先 `git status`**，尤其是任何可能丢弃未提交改动的命令（`checkout`/`reset`/`clean`）——这个仓库经常有本地未提交的 `data/state_*.csv` 增量抓取结果，不要在没检查的情况下用破坏性命令。

## 6. 关键路径速查

| 内容 | 路径/地址 |
|---|---|
| 项目根目录 | `/Users/sabacus/Projects/local_bond_announcements` |
| 看板权威文件（git 跟踪） | `output/bond_analysis_dashboard.html` |
| 数据刷新脚本 | `src/build_dashboard_plan.py`（`refresh_plan_section` / `refresh_calendar_section`，接入 `main.py`） |
| 区域/省份/期限常量 | `src/config.py` |
| 三张状态表 | `data/state_plans.csv` / `data/state_announcements.csv` / `data/state_results.csv` |
| Claude Artifact 链接 | `https://claude.ai/code/artifact/86697346-81da-47bf-bc7c-438563254684` |
| GitHub 仓库 | `fletcherfeng1919-wq/local-bond-announcements`，分支 `main`，最新 commit `e3fee4f` |
| 省级交叉验证模块 | `src/provincial_verify.py`（10个已确认省份，见第2节末尾说明） |
| Python 环境 | `.venv/bin/python3`（不要用系统 `python3`） |
