# 交接文档（写给零上下文的新会话）

最后更新：2026-08-10，最新 commit `faf725c`（已 push 到 `origin/main`，working tree 干净）。

## 1. 这是什么项目

`local_bond_announcements`：抓取 celma.org.cn（全国地方政府债券信息公开平台）的地方政府债券公告，结构化成表格，再做成一份交互式 HTML 分析看板。姊妹项目 `mof_bond_announcements`（国债公告）结构类似，其子项目 `wind_10y30y_spread_toolkit` 提供 Wind 口径的 10Y/30Y 国债活跃券每日中债估值收益率，用于计算"地方债 vs 国债利差"。

celma.org.cn 有三个抓取渠道（`channelId`）：
- **192 发行安排**（`dfzfxjh`，`doc_type="plan"`）→ `data/state_plans.csv`：月度/跨月的**计划**发行规模，按省份，无逐日拆分。
- **193 发行前公告**（`fxqgg`，`doc_type="announcement"`）→ `data/state_announcements.csv`：单期债券的招标前公告，含 `bid_date`（招标日，逐日精确）。
- **194 发行结果**（`fxjg`，`doc_type="result"`）→ `data/state_results.csv`：招标后的**已确认**结果，2020年起是标准化表格（含债券编码/简称/确认利率），2020年前是无编码的自由文本旧格式。这是主数据源，14,833行，覆盖 2018-10-26 ~ 2026-07-27。

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

## 3. 当前卡在哪 / 已知缺口

**没有任何本次会话交办的任务处于阻塞状态**——用户要求的所有修改都已完成、验证、发布、提交、推送。`git status` 干净，`HEAD` 和 `origin/main` 一致（`faf725c`）。

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

3. **"发行安排"（计划）数据只有月度粒度，没有逐日拆分**——**不要为了做日历/时间图就把月度总额除以工作日数摊出"每日计划"**，那是编造数据。真正有逐日精度的是：`state_results.csv` 的 `issue_date`（已确认结果，但发布有滞后，通常滞后约一周）和 `state_announcements.csv` 的 `bid_date`（招标前公告，通常只提前约5个工作日才有，见下方坑9）。**2026-08-10 更新**：发行日历组件现在两个都用——`issue_date` 填"已确认"的日子，`bid_date` 接着填"已公告未开标"的日子（补上确认结果滞后的那段空档），两者在 UI 上用实线/虚线+颜色明确区分，且"已公告"的债券 `couponPct` 永远是 `null`（利率还没定），千万不要因为"数据能凑出来"就给它编一个利率。这两个口径都不能覆盖到的日期（超出已公告范围的未来）就应该留空，不能再拿月度计划硬拆日去填——那还是编造数据。

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
| GitHub 仓库 | `fletcherfeng1919-wq/local-bond-announcements`，分支 `main`，最新 commit `faf725c` |
| Python 环境 | `.venv/bin/python3`（不要用系统 `python3`） |
