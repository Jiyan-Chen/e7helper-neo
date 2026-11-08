# HANDOFF

> 新会话从这里读起。上次更新：2026-11-08（B14g2 已通过；发布 0.4.0-beta.2 测试版带上 3% 修正；下一块等用户定）

## 当前进度
- **B01 骨架 + 模块契约 + MuMu 设备层**：✅ 已通过，记录见 [reviews/B01.md](reviews/B01.md)。
- **B02 视觉层 + 模板工具**：✅ 已通过，记录见 [reviews/B02.md](reviews/B02.md)。
- **B03 运行时 + 事件总线 + 场景/弹窗**：✅ 已通过，记录见 [reviews/B03.md](reviews/B03.md)。
- **B04 刷神秘商店**：✅ 已通过，记录见 [reviews/B04.md](reviews/B04.md)。
- **B05 竞技场 NPC**：✅ 已通过，记录见 [reviews/B05.md](reviews/B05.md)。
- **B06 重复刷关（托管战斗 + 手动刷讨伐）**：✅ 已通过，记录见 [reviews/B06.md](reviews/B06.md)。
- **B07 日常收取（邮件 / 精灵之森 / 誓约免费召唤）**：✅ 已通过，记录见 [reviews/B07.md](reviews/B07.md)。
- **B08 API 层（REST + WebSocket + 定时调度）**：✅ 已通过，记录见 [reviews/B08.md](reviews/B08.md)。
- **B09 GUI（Tauri 2 + React，游戏风）**：✅ 已通过，记录见 [reviews/B09.md](reviews/B09.md)。
- **B10 打包发布（PyInstaller onedir + NSIS）**：✅ 已通过，记录见 [reviews/B10.md](reviews/B10.md)。
- **B10a 弹窗补漏：断线自动重进**：✅ 已通过，记录见 [reviews/B10a.md](reviews/B10a.md)。B10 真机验证时发现的「与服务器的连接中断」弹窗，单独立项、单独审核。
- **B11 自定义流程 + 玩家模板采集**：✅ 已通过，记录见 [reviews/B11.md](reviews/B11.md)。
- **B12 试用打磨（开发版）**：✅ 已通过，记录见 [reviews/B12.md](reviews/B12.md)。9 条反馈：竞技场并入日常收取、补旗做成附加选项、精简全部说明、「动态」红色 asyncio 报错、书签刷取（固定三种商品 + 没出就停 / 换世界频道）、标题栏做进应用、引擎关闭挂住（改用 Selector 事件循环）、左上角固定头像和应用名、界面过渡动画。
- **B12a 讨伐异界**：✅ 已通过，记录见 [reviews/B12a.md](reviews/B12a.md)。重复刷关加上「异界」难度和 阿吉玛纳克 / 卡戴斯 / 食人魔；异界消耗光谱核心，可用叶子 / 天空石补充；异界胜利后的宝珠画面；「托管最多几份」进表单；GUI 新增 `fieldLocks`（食人魔锁定异界）。全量 `890 passed, 7 skipped`，前端 16 个。
- **B12b 日常收取：商店日常购买**：✅ 已通过，记录见 [reviews/B12b.md](reviews/B12b.md)。日常收取加一项「商店」（排在竞技场前）：交易所 › 竞技场 → 商店 › 一般 → 商店 › 传承石，买用户圈定的 14 件每日 / 每周限购商品；按周记账；GUI 商品点选。实跑买了 13 次，天空石 0。
- **B12c 书签刷取：历史统计**：✅ 已通过，记录见 [reviews/B12c.md](reviews/B12c.md)。书签刷取页「设置」下面加「刷取历史」（代替通用「最近运行」）：近 7 天 / 近 30 天 / 全部，商品卡（几次、共几个、平均刷几次出一次）、刷新 / 天空石 / 金币 / 运行次数、每天刷新次数柱状图（标出书签 / 奖牌，「全部」超过 45 天按周）、每次运行列表；dry-run 不算。删掉原「统计」页和各模块 `statLabels`。全量 `973 passed, 7 skipped`，前端 22 个。
- **发布 0.2.0**（B12c 审核后用户要求）：五处版本号改成 0.2.0，重新冻结引擎、打 NSIS 安装包（见「打包」）。**这个安装包不含 B13**（B13 之后才合进 main），下次发版再带上。
- **B13 英雄数据库**：✅ 已通过，记录见 [reviews/B13.md](reviews/B13.md)。`core/data`：389 名英雄（Fribbels 数据 + e7.wiki 的国服中文名 / 昵称 / 技能 / 角色奉献 / 专属装备 / 发布日期），随包内置 + 联网更新；Fribbels 配装库实时汇总（中位数，速度套看前 10% / 前 25%，其他按速度分快中慢）；GUI「英雄图鉴」（按发布日期排、筛选、详情三个页签），属性 / 职业 / 套装 / 刻印 / 等级 / 属性类型图标都从游戏截图裁。审核改了 12 轮。全量 `1004 passed, 7 skipped`，前端 22 个。用户先开了 B13（在 B12c 之前的 main 上做），2026-10-21 合进 main。
- **B14a RTA：对局数据**：✅ 已通过，记录见 [reviews/B14a.md](reviews/B14a.md)。RTA BP 助手（对齐 e7rtabot.com/draft）按用户意见拆成 B14a–B14f，每块一个会话。本块：`core/rta`（选秀规则、国服 + 海外官方战绩站客户端、对局解析、sqlite 滚雪球采集、数据报告）+ CLI `rta probe / crawl / report`。审核通过时采集库国服 16.0 万场、海外 42.7 万场（本赛季 ss21 为主），解析通过率约 98.5%（失败的全是选秀阶段有人退出）。全量 `1060 passed, 7 skipped`，之后 RTA 测试 53 个。
- **B14b RTA：胜率 / 选人模型**：✅ 已通过，记录见 [reviews/B14b.md](reviews/B14b.md)。ss21 两服 91.1 万场快照 → 随包 Transformer + 因子分解机的混合结构（d = 128、3 层，66.5 万参数，ONNX 3 MB）：测试集后禁后 log loss 0.6166、AUC 0.717、ECE 0.005（最强基线因子分解机 0.6236 / 0.708），选人前 5 命中 0.601（热度 0.411）。AMD 显卡 + Windows ROCm 版 torch 训练（比 CPU 快约 16 倍）、训练曲线页、Platt 校准、终端模拟 BP（`rta sim`）。审核中发现模型对冷门英雄会外推出极端胜率，用户决定留给 B14c 的搜索挡住。全量 `1116 passed, 7 skipped`。
- **B14c RTA：选秀推荐**：✅ 已通过，记录见 [reviews/B14c.md](reviews/B14c.md)。
  - `core/rta/search.py` 三层搜索：我方这一轮 → 对手回应 → 我方再回应，最后几手搜到后禁。候选只从选人头先验里取，还有少见选择的高估修正。
  - 两手回合按对评估、保护位排顺序；后禁 4 × 4 矩阵 + 纳什；预禁只推荐数据里常见的组合。
  - 第二个模型（切分训练的）随包，两个模型差 ≥ 5 个百分点标「不确定」。
  - `priors.json`；接口 `/api/rta/model|advise|preban`；CLI `rta advise / preban / priors / audit`。
  - 验收：第一名里冷门英雄 0.0%，advise p95 3.43 s，预禁 p95 ≤ 2.30 s。自对弈 ≥ 90% 有 4 局（超过 2% 门槛，用户接受）。
  - 审核时追加：和 e7rtabot 对抗 8 局，两边都更看好自己选的阵容。发现官方 `energyGauge` 是开局行动条、采集漏存（留给 B14d）。
  - 全量 `1144 passed, 9 skipped`；`test_scheduler.py` 的退避测试偶尔失败（和 B14c 无关，没修）。
- **B14d1 RTA：开局行动条 / 先动概率 / 英雄池**：✅ 已通过，记录见 [reviews/B14d1.md](reviews/B14d1.md)。B14d 按用户意见拆成 B14d1 / B14d2。
  - 采集规范：存 `energyGauge`（开局行动条），解析成每名英雄的行动条和先动方；已有对局再采到时补上，`rta crawl --backfill` 国服整季重翻；报告、训练快照带上。
  - 官方「英雄分析」的能力值直方图其实是绝对值（速度 110–310、每档 20，按段位）；`rta herostats` 取快照。
  - 先动概率 `core/rta/speed.py`：官方分段位速度 + 290 以上用开局行动条反推 + 开局规则（智武 +30%、赫尔赛蒂限速）+ 英雄池速度，蒙特卡洛；`POST /api/rta/first`，advise 的推荐 / 后禁矩阵旁边显示，**不改胜率**（速度进模型留给 B14g，用户意见）。
  - 英雄池 `core/rta/pool.py`，`GET/PUT /api/rta/pool`，advise 不传 pool 时用它。
  - **采集没跑**（用户意见「采集以后再说」）：当时随包没有速度表。B14h 用国际服补上了。
  - 全量 `1173 passed, 9 skipped, 1 failed`（又是 `test_scheduler.py` 的退避测试，单独重跑 3 次都过）。
- **B14e1 RTA：选秀页（菜单「RTA 助手」）**：✅ 已通过，记录见 [reviews/B14e1.md](reviews/B14e1.md)。B14e 按用户意见拆成 B14e1（选秀页）/ B14e2（英雄池）。
  - GUI 五步手动模式（准备 / 预禁 / 选秀 / 后禁 / 结果），审核中布局改成参考 e7rtabot.com/draft；段位 5 个图标（挑战者及以下合一项，图标从游戏截图裁）、开战规则 / 先后手分段按钮（有规则时必须选，没有「不知道」）；正在选的格子里放前 3 名；后禁时信息条显示推荐行的预期。
  - 引擎：`GET /api/rta/priors`、`/api/rta/model` 的 `options.rules`；`engine/tools/cut_icons.py --grabcut`。
  - 审核改了 4 轮：改名和布局、后禁胜率和开战规则、卡片对齐、全页布局检查（1280×800 和 1100 宽）。
  - 全量 `1175 passed, 9 skipped`（第 1 轮审核前跑的，之后只改了前端和一个接口字段，RTA 接口测试 13 个每轮都跑）；前端 45 个。
- **B14h RTA：国际服重采 + 速度表 + 重训**：✅ 已通过，记录见 [reviews/B14h.md](reviews/B14h.md)。B14e2 开工时用户改为先做这块（B14e2 方案已定好，在这份记录末尾）。
  - 用户意见：国服已同步国际服、国服数据质量不行，**以后只用国际服数据**；新英雄侦探茉萝（c2187）还没养成，**不进训练**（采集照常存，快照里整场去掉）。
  - 国际服 ss21 采到 115 万场（带开局行动条）；快照 107.6 万场（截止 11-01，去掉含茉萝的 3.3 万场）；按 B14b / B14c 的流程重训主模型和第二个模型、重新生成 priors、重新量高估修正常数（还是 1.5%）、audit。
  - 测试集（10-26 ~ 11-01）切分模型 log loss 0.6125 / AUC 0.721；两个全量模型都没见过的 11-02 上新主模型 0.6099、原来的 0.6124（好 0.0025，区间不跨 0）。训练时 10% 换成「不知道」规则，页面不到优胜者时发 `null`。
  - **速度表第一次随包**（国际服）：官方速度直方图里大量「没算装备」的低档尖峰，先去掉再按开局行动条把真的慢速配装补回；验收 log loss 0.2814、先动英雄猜中 77.7%（官方原样 0.3218 / 73.8%）。
  - 随包英雄数据补上 Fribbels 还没有的新英雄（e7.wiki 数据）：391 名，新增茉萝、兔女郎黑手党优芬妮。
  - 开发版试用补的：后禁矩阵编号从局面取；信息条加上先动后收紧。审核第 1 轮（用户意见）：**模型没训练进的英雄不进 RTA 助手和英雄池**，只在图鉴里看。
  - 全量 `1182 passed, 9 skipped`（审核第 1 轮之前跑的；之后 RTA 测试 174 个、前端 46 个都跑过）。
- **B14e2 RTA：英雄池**：✅ 已通过，记录见 [reviews/B14e2.md](reviews/B14e2.md)。方案 11-03 定好（B14h.md 末尾），开工时没有新的试用反馈。
  - 开工时工作区停在 B14e1：**B14h 的提交 `c08469c` 在分支 `claude/b14e2-rta-hero-pool-390fbe` 上、没进 main**，先把 B14e2 的分支（`claude/b14e2-rta-hero-pool-6a846c`）快进到它再开工；所以 B14e2 的分支上是 B14h + B14e2。合进 main 时两块一起进。
  - 图鉴「英雄池」模式（`#/heroes?pool=1`）：只列模型里的英雄、按发布日期排，点头像勾选，右栏速度（50–400，不填 = 按段位的常见速度），改了 400ms 后自动保存。
  - RTA 助手：始终按英雄池推荐我方选人（预禁推荐不管英雄池）；顶栏「英雄池 N 名」+「编辑」；网格打勾 +「只看我的」；推荐卡「英雄池：名字」标记；池里能选的不够这一轮时这一轮推荐全部英雄（`pool_short`）。
  - 审核 2 轮（用户意见）：信息条始终用**我方的读数**（我方回合 = 推荐第 1 名的预期；对方回合 = 引擎新算的「对方常见选法 → 我方从英雄池里挑回应」的预期，p95 2.3 秒）；**去掉「只推荐我的英雄」开关**，没设置过时**默认用本赛季最常被选的 60 名**（占选人 93%，不写进文件），图鉴里「恢复默认」。
  - 全量 `1192 passed, 9 skipped`；前端 58 个。
- **发布 0.3.0（正式版）+ 0.4.0-beta.1（测试版）**（2026-11-07，B14e2 之后用户要求；见「打包」）：
  - 仓库推到 GitHub **`Jiyan-Chen/e7helper-neo`（私有）**，只推 main 和版本标签（`claude/…` 分支都已合进 main，不推）；remote `origin`。
  - 正式版不带 RTA（新加的 `build.py --no-rta`，标签 `v0.3.0`），测试版带 RTA、在 GitHub 上标预发布（标签 `v0.4.0-beta.1`）；两个版本号、可见性、推送范围都是用户选的。
  - 用户说「先不做画面识别」：B14f 什么时候开工等用户说。
- **B14g1 RTA：重训加入先动（模型）**：✅ 已通过，记录见 [reviews/B14g1.md](reviews/B14g1.md)。B14g 原定等 ss22，因为 0.4.0-beta.1 的 bug 提前做，用户要求一步到位修好（不先做临时修正）、用现有 ss21 快照、拆成 B14g1（模型）/ B14g2（搜索 / 接口 / 界面 + 换随包模型）。
  - 起因：准备选「挑战者及以下 vs 战神」时推荐的预期只有 3.1%（传说 vs 传说 63.1%）。**快照里的段位是赛后的**，把结果混进去了（差两档的对局先手方胜率 0.1% / 100%），旧模型学成「段位高的一定赢」。
  - **用户原则**：段位只影响「谁先动」的判断，胜率由英雄 BP 计算，再按先动概率混合。
  - 模型：胜率不看段位（ctx 格式不变、段位被忽略），保留开战规则；三个胜率头「先手方先动 / 后手方先动 / 不知道」（训练用快照的 `first_mover`，不知道的对局只训「不知道」头）；选人头不变。
  - 快速先动概率 `speed.FirstCalc`（按速度分布直接算，不再抽样）；混合用 `model.effective_first`（不是直接用速度表：直接用比「不知道」头还差）。
  - 结果：测试集 n11 混合 0.6231 / AUC 0.708；段位同档的对局 0.6236（B14h 0.6238，持平，B14h 全体更好的部分全是段位泄漏）；留出日 11-02 0.6222（= B14h 把段位换成不知道）。模型层面复现（已选 3 手）：挑战者 vs 战神 41.1%、传说 vs 传说 41.6%（旧 1.1% / 46.5%）。
  - 新模型当时暂存在 `F:\e7helper-data\rta\bundles\b14g1\`（主 + `second/`），B14g2 换进了随包。
  - 全量 `1199 passed, 9 skipped, 1 failed`（又是 `test_scheduler.py` 的退避测试，单独重跑 3 次都过）；训练 / 导出测试在 GPU 环境 32 个通过；前端没改。
- **B14g2 RTA：搜索 / 接口 / 界面接入先动混合**：✅ 已通过，记录见 [reviews/B14g2.md](reviews/B14g2.md)。**0.4.0-beta.1 的 3% 问题修好了**，0.4.0-beta.2 发版带上。
  - 随包换成 B14g1 的新模型（旧 B14h 模型备份在 `F:\e7helper-data\rta\bundles\b14h\`）；`priors.json` 加每一手的选取次数 `slots`。
  - 搜索每行按阵容算先动概率（双方段位 + 我方英雄池速度 → `effective_first`）混合三个头；推荐、最坏、对手回应、后禁矩阵、`opponent.win`、预禁一处改全改；每个值带「我方先动时 / 后动时」两种，页面鼠标提示显示（用户意见）。
  - 审核两轮（用户意见）：**页面上显示的先动概率只按双方已经选出的英雄、用速度表算**，不补还没选的几手、不把对方之后的回应合进去（推荐卡 = 加上这一组；一方还没有英雄时不显示）；后禁矩阵每格 / 结束时是 4 打 4 混合用的。算胜率时照旧按补全的阵容。
  - 复现用例（我方先手、挑战者 vs 战神 / 传说 vs 传说）：推荐第 1 名执行官维德瑞 + 奥芙，预期 59.9% / 61.5%（旧 3.1% / 63.1%）。
  - audit：推荐第一名冷门 0.0%；advise p95 4.00 s（B14h 3.60 s；同机交替计时 3.77 → 4.56 s）；自对弈 ≥ 90% 的 1 局（门槛第一次过）；高估修正常数不改（混合后最接近 1.25%，误差差得很少）。
  - 全量 `1209 passed, 9 skipped`；训练 / 导出 32 个；前端 60 个；`rta model --check` 通过。冻结引擎冒烟测试在发 0.4.0-beta.2 时跑了，全过。
- **发布 0.4.0-beta.2（测试版）**（2026-11-08，B14g2 之后用户要求；见「打包」）：B14g2 提交 `7a3947c`、版本号 `5b72391`、标签 `v0.4.0-beta.2`，GitHub 预发布（0.3.0 仍是 Latest）。正式版 0.3.x 不带 RTA，没动。
- 下一块：**等用户定**（见下面「下一块」）。B14f（画面识别）什么时候开工等用户说；B14d2（站位 / 快速分析 / 英雄统计）往后放，等 ss22 赛季更新、数据重采后再做（用户意见）。

## 已有能力
### 设备（B01）
- `from e7helper.device import connect; d = connect()`
  - `d.screenshot()`：返回 BGR 帧，IPC 约 10ms
  - `d.tap(x, y)` / `d.swipe(...)`：坐标是设备像素
  - `d.adb.shell(...)`
  - `d.input_text("70")`（B12）：往获得焦点的输入框打字，走 adb `input text`，只收字母和数字；`ctl.input_text(...)` 同名

### 视觉（B02，详见 architecture.md 的“视觉层”一节）
- 模块里用 `self.vision`：
  - `find` / `exists` / `best` / `find_all` / `find_any`
  - `self.vision.ocr.read_number(frame, Rect(...))`、`read_line`、`read_fraction`、`read`
- 坐标一律是 1600×900 基准。任务里点击用 `self.ctl`（B03），它负责换算到设备坐标。
- 模板：`engine/assets/<module_id>/cn/<name>.png` + `.json`。
  - 查找顺序：模块自己的 → `common`。
  - 已有模板：
    - `common`：`back`、`top/skystone`、`top/gold`、`dialog/cancel`、`dialog/confirm`、`lobby/secret_shop`（带 `tap`）、`lobby/shop`；B05 新增 `lobby/arena`、`top/flag`、`arena/mode_arena`；B06 新增 `lobby/battle`、`title/battle`、`title/prep`、`top/energy`（行动力）、`top/auto_clock`（托管图标表盘）；B03 新增 `title/secret_shop`、`title/shop`、`title/arena`、`title/sanctuary`、`popup/notice`、`popup/network_error`、`popup/network_retry`；B07 新增 `lobby/sanctuary`（带 `tap`）、`lobby/summon`、`top/mail`、`title/mail`、`title/forest`、`title/summon`；B10a 新增 `popup/disconnected`、`popup/tap_close`、`popup/announce_close`、`popup/announce_faq`、`title/start`（游戏标题画面「轻触画面开始」）；B12a 新增 `top/core`（光谱核心，阈值 0.75）
    - `secret_shop`：`title`、`refresh`、`buy`；B04 新增 `coin`、`dialog/buy_title`、`dialog/buy_ok`、`dialog/refresh_text`、`item/covenant`、`item/mystic`
    - `arena_npc`（B05）：`tab/npc`、`npc/*`、`prep/*`、`battle/*`、`result/*`、`record/*`、`buy/*`，共 21 个
    - `repeat_battle`（B06）：`menu/hunt`、`hunt/header`、`prep/*`、`auto/*`、`battle/*`、`clear`、`result/*`、`after/*`、`energy/*`，共 27 个；B12a 新增 `core/*`（购买光谱核心框）、`ow_reward`（异界宝珠画面），共 33 个
    - `daily`（B07）：`sanctuary/forest`、`forest/*`、`mail/*`、`summon/*`，共 18 个；B12b 新增 `shop/*` 29 个（左侧菜单、页签、卡片价格图标、顶栏图标、购买商品框、获得奖励框）
- fixtures：`engine/tests/fixtures/`（B07 后约 137MB；B12b 新增 16 张 `daily_shop_*`，约 18MB：更新精选、一般（买免费商品前 / 后）、传承石（开头 / 中间 / 末尾）、交易所 › 竞技场、7 种购买框、获得奖励）。B07 新增 35 张 `daily_*`（大厅、圣域白天 / 夜晚、精灵之森各状态和奖励框、邮件列表 / 详情框 / 领取后、召唤页、誓约页 21/21 · 11/21 · 1/21 · 用完 · 带光效、召唤动画、十连结果、单抽结果；期望结果在 `tests/test_daily.py`）。B06 新增 36 张 `rb_*`（讨伐导航、准备界面各状态、托管各框、战斗、CLEAR、结算、战后、行动力不足；期望结果在 `tests/test_repeat_battle.py`）。B12a 新增 15 张（约 14MB）：`rb_ow_*`（异界准备界面 有记录 / 无记录 / 卡戴斯、托管设置框、购买光谱核心框、宝珠画面、战后）、`rb_hunt_list_azimanak` / `_kades`、`rb_auto_setup_110`。此前的包括 `lobby`、`secret_shop`、`secret_shop_scrolled`、`secret_shop_refresh_confirm`；B05 新增 17 张 `arena_*`（模式选择外的竞技场各界面、战斗中、两种结算、补旗框三种状态）；B04 新增 `secret_shop_relist(_scrolled)`、`secret_shop_buy_confirm`、`secret_shop_sold`、`secret_shop_bought_toast`；B03 新增 `shop`、`arena`、`arena_notice`、`sanctuary`、`sanctuary_help`、`lobby_exit_confirm`、`lobby_network_error`；B10a 新增 `lobby_disconnected`、`summon_disconnected`、`title_announcement`、`title_connecting`、`title_start`、`title_start_forest`（约 5.9MB）。模板的期望结果在 `tests/test_vision_fixtures.py`，场景的期望结果在 `tests/test_scene.py`。
- CLI：
  - `capture <module> <name>`：弹窗框选，或用 `-f 文件 -r x,y,w,h` 指定
  - `match <module> [names] [-f] [-a]`
  - `ocr [-f] [-r] [--line|--number]`

### 运行时 / 场景 / 事件（B03，详见 architecture.md 对应三节）
- 任务模块里用 `self.ctl`（`Controller`），坐标一律 1600×900 基准：
  - 截图与识别：`screenshot` / `find` / `wait(ref)` / `wait_until(probe)` / `detect() → SceneState`
  - 点击：`tap(x, y)` / `tap_rect` / `tap_match(m)` / `tap_template(ref)` / `swipe` / `back()`。自带随机偏移、按压时长和点击后等待；模板 json 设了 `tap` 时点 tap 区域
  - 场景：`wait_scene("lobby")`（途中自动关弹窗，并等画面静止 0.5 秒）；导航用 `tap_until(target, scene)`（会补点，**不要用于刷新/购买**；目标界面一直有动画时传 `settle=False`，B06）
  - 弹窗：`dismiss_popups()`；`progress()` 清零卡死计数；`sleep()` 可被急停打断
- 场景判定：`state.is_("secret_shop")` 表示在该场景且没有弹窗。内置场景 `lobby` / `secret_shop` / `shop` / `arena`（B05 起只认模式选择）/ `sanctuary`；内置弹窗 `disconnected`（点「点击关闭」）/ `announcement`（登录公告，点 X）/ `title_start`（标题画面，点「轻触画面开始」）——这三个是 `reload=True`，组成**断线自动重进**（B10a：关闭后 `_wait_reload` 等游戏加载完，每段最多 120 秒；`wait_scene` / `tap_until` 遇到重进会重新计时，`ctl.reloads` 记次数），`network`（点重试）、`notice`（返回键）、`confirm`（**一律点取消**）、`obscured`（压暗且静止时按返回键兜底）
- 模块注册自己的场景：`self.ctl.scenes.add_scene(Scene(..., ("secret_shop:xxx",)), replace=True)`（限定引用 `module_id:name`）
- `Runtime(device)`：`run_task` / `start_task`（互斥、`timeout`、急停、卡死），失败时调试信息存到 `%LOCALAPPDATA%\e7helper\debug\`；`attach_assistant`（只读设备、帧订阅）
- 事件总线：`self.events`，主题 `frame` / `log` / `task` / `scene` / `assistant`
- 测试：`tests/game_sim.py` 用 fixtures 截图模拟游戏（点到「确认」会进入 DANGER），任务逻辑可以离线测；`tests/test_runtime_live.py` 是真机端到端测试

### 书签刷取 `secret_shop`（B04，B12 改版；详见 architecture.md「已有模块」、reviews/B04.md 和 reviews/B12.md 反馈 5）
- `python -m uv run e7helper run secret_shop`：默认 **dry-run**（只滑动、识别、决策）
- 实跑：`-c '{"dry_run": false, "max_refreshes": N}'`。B12 起表单只有：`items`（固定三种商品，玩家点选：誓约书签 184,000 / 神秘奖牌 280,000 / 友情点数 18,000，默认前两种；按名字或图标识别，并核对价格）、`max_refreshes`「刷新次数」、`stop_after_misses`「连续多少次没出就停止」、`channel_after_misses`「连续多少次没出就换世界频道」、演练；天空石预算（默认不限）/ 保底、金币下限、`targets` 是内部接口；`probe_channel` 演练时换一次频道再换回来
- 换世界频道（`chat.py`）：顶栏聊天图标 → 停在骑士团页签先点「频道」→ ⇆ →「变更频道」框输入当前频道号 +1 → 核对输入框数字 → 点框里的「输入」→ 标题变了才算 → 返回键一次关掉整个聊天。底部发消息的输入框绝不碰
- B12 之前保存的配置（旧 targets + 预算 30）读进来会被 `_migrate_b12` 去掉旧默认值
- 统计：`%LOCALAPPDATA%\e7helper\modules\secret_shop\history.jsonl`、`stats.json`；B12c：`GET /api/modules/secret_shop/report?runs=500`（`stats.report`：实跑按天汇总 + 每次运行明细），GUI 书签刷取页的「刷取历史」（`src/modules/secret_shop/ShopHistory.tsx` + `report.ts`）
- 实测：每页（扫两屏 + 刷新）约 3 秒，一次购买约 2 秒
- 可以复用的做法：
  - 有消耗的操作**按资源读数差确认**，不按点击次数计；
  - 有消耗的确认框注册成本模块弹窗，自动关闭时点取消；
  - 列表类界面用「列表区域停稳」代替整屏静止（`_settle_list`）；
  - 离线测试用 `tests/shop_sim.py` 式的模拟器（点到确认默认进入 DANGER）。

### 竞技场 NPC（B05；B12 起不是单独的模块，是日常收取的一项（B12b 起排第 5），代码在 `modules/daily/arena.py`，模板在 `assets/daily/cn/arena/`）
- 只跑竞技场：`python -m uv run e7helper run daily -c '{"mail": false, "forest": false, "covenant": false}'`（默认 dry-run：导航到准备界面、决定模式后回大厅）
- 实跑 `"dry_run": false` 打到旗帜用完；`"arena_buy_flags": true` 用完后用友情点数补一次（100 换 5 面，每天一次，成功后账本记 `arena_buy`）
- 内部字段 `arena_max_battles`、`arena_prefer_quick`、`arena_friendship_keep`、`arena_battle_timeout`、`arena_probe_dialogs`
- 统计并进日常收取的 `history.jsonl` / `stats.json`；旧的 `modules\arena_npc\` 数据不再使用
- 实测：快速对战一场约 7 秒（从点按钮到核对完成），普通战斗约 33 秒
- 可以复用的做法：
  - 普通战斗中的**自动战斗**：图标静止约 0.6 秒 = 没开（开启后一直旋转），点完再观察（`_ensure_auto`）；
  - 战斗中不按返回键（会打开暂停菜单），只有网络异常立即重试；战斗画面在动就 `progress()`；
  - 两个选项的购买框：点购买前核对**哪个选项被选中**（边框亮度），不能只看按钮；
  - 离线测试用 `tests/arena_sim.py` + `tests/test_daily_arena.py`（战斗、结算、自动图标旋转都能模拟）。

### 重复刷关 `repeat_battle`（B06，B12a 加讨伐异界；详见 architecture.md「已有模块」、reviews/B06.md 和 reviews/B12a.md）
- 游戏的「重复战斗」已重做成**托管战斗**：准备界面设份数（1 份 = 4 次，行动力或叶子付费），后台按最快通关记录自动打，完成后在托管框「结算」。无记录的关卡开不了。
- `python -m uv run e7helper run repeat_battle`：默认 **dry-run**（导航到 讨伐双足飞龙 地狱级，打开托管设置框核对后关闭，切普通战斗后停下）
- 实跑：`-c '{"dry_run": false, "manual_runs": N}'`。表单字段：`hunt`（飞龙 / 魔像 / 报丧妖 / 阿吉玛纳克 / 卡戴斯 / 食人魔）、`tier`（中级 / 上级 / 地狱级 / 异界；食人魔只有异界，GUI 锁定）、`start_here`、`auto_battle`、`auto_max_units`（「托管最多几份」，B12a 进表单）、`auto_leaves`、`manual`、`manual_runs`、`refill_leaf` / `max_leaf_refills`、`refill_skystone` / `max_skystone_refills`（B12a 起叫「用生命之叶补充 / 用天空石补充」，行动力和光谱核心通用）、`dry_run`；内部字段 `auto_prefer_energy`、`skystone_keep` 等
- 托管和手动是两个独立开关；只开托管时处理一次就退出（周期性结算重开由 B08 定时调度反复启动模块，用户确认）
- **讨伐异界**（B12a）：消耗**光谱核心**（顶栏行动力左边的红色图标，只在讨伐列表 / 准备界面显示，`page.read_core`）。准备界面没有快速战斗；托管 1 次 = 1 核心或 2 叶子（份数框按叶子数，+1 加 2）；补充点顶栏核心图标打开「购买光谱核心」框（叶子 2 换 1、天空石 80 换 1、数量保持 1）；胜利后是宝珠画面「请轻触屏幕领取奖励。」（`rb_ow_reward`）→ 战后，没有 CLEAR 和结算页。实测一场约 133 秒（食人魔）
- 统计新增 `cores_spent`（GUI「花费光谱核心」）；`history.jsonl` 每行有 `currency`
- 统计：`%LOCALAPPDATA%\e7helper\modules\repeat_battle\history.jsonl`、`stats.json`
- 实测：手动一场约 2 分钟（地狱级，自动战斗）；托管 1 份约 7 分钟
- 可以复用的做法：
  - 点了弹窗的确认 / 购买 / 关闭后，**等框自己淡出**（`_wait_popup_gone`），不要马上 `wait_scene`；
  - 位置会变的列表（讨伐列表、难度卡片）用 OCR `read` 找整行文字再点；
  - 状态图标的红点要按图标亮度归一化，并用多帧排除转动的光效（`auto_state` + `dots_match`）；
  - 离线测试用 `tests/rb_sim.py`（战后界面一直在动、弹窗淡出、点到「推荐配置」= DANGER；B12a 加异界：`tier="异界"` 时用 `rb_ow_*` 画面，点原切换钮位置 / 核心不够还点战斗开始 = DANGER）。

### 日常收取 `daily`（B07，详见 architecture.md「已有模块」和 reviews/B07.md）
- `python -m uv run e7helper run daily`：默认 **dry-run**（三项都进去识别，不点领取 / 照料 / 召唤 / 收信）
- 实跑：`-c '{"dry_run": false}'`；表单有 `mail`、`forest`、`covenant`、`shop` / `shop_items`（B12b）、`arena`（B12 并入，默认开）、`arena_buy_flags`（竞技场的附加选项）、`dry_run`；内部字段 `mail_max_hours`（默认 24）、`mail_max_claims`、`covenant_max`、`force`（忽略账本）、竞技场的 `arena_*`
- 顺序：邮件 → 精灵之森 → 誓约召唤 → 商店 → 竞技场；各项共用的异常在 `daily/errors.py`
- 按天记账：`%LOCALAPPDATA%\e7helper\modules\daily\ledger.json`（游戏日北京时间 3 点切换；誓约当天用完就不进去；精灵之森按最短倒计时记下次时间）；统计 `history.jsonl`、`stats.json`
- 实测：全部三项约 20–35 秒；免费十连约 7–10 秒，单抽约 15 秒（动画不能跳过）
- 可以复用的做法：
  - 「有没有花东西」对比**顶栏货币区域的画面**，前后各两帧、两两都变才算（排除背景光效；见 `page.changed_pixels_all`）；
  - 点了按钮后弹出的确认 / 详情框要核对内容再点（邮件详情框核对剩余时间）；认不出的静止画面就停，不乱点；
  - 一项失败不影响其他项（`ItemFailed`），核对异常立即停止整个任务（`DailyAnomaly`）。
- 离线测试用 `tests/daily_sim.py`（「全部领取」、非第一行领取、不免费的召唤、「再召唤一次」都是 DANGER）。

### 商店日常购买（B12b；日常收取的第 4 项，代码在 `modules/daily/shop.py` / `shop_page.py`，模板在 `assets/daily/cn/shop/`；详见 architecture.md「已有模块 / 商店」和 reviews/B12b.md）
- 只跑商店：`python -m uv run e7helper run daily -c '{"mail": false, "forest": false, "covenant": false, "arena": false}'`（默认 dry-run：三页都扫，记下会买什么）；实跑加 `"dry_run": false`
- 表单：`shop`（默认开）、`shop_items`（`ShopItem` 14 件，默认全选）；内部 `shop_affinity_weekly`（亲密度献礼选择箱每周次数，默认 5）、`shop_max_buys`（每次最多买几次）、`shop_probe_dialogs`（dry-run 时打开购买框核对后点取消）
- 商品清单在 `shop.CATALOG`（名字、页、货币、单价、限购、每日 / 每周）；货币只认 免费 / 友情点数 / 行动力 / 银光传承石 / 竞技场点数
- 账本：每日的记 `done["shop:<id>"]`，每周的记 `week_done`（游戏周 = 周一北京时间 3 点切换，`ledger.game_week`）；计时多了「每周重置」
- 实测：只看光谱核心约 15 秒；三页全扫约 75 秒；全部买约 100 秒（每次购买约 4 秒）
- 可以复用的做法：
  - 横向列表：按名字 OCR 找卡片（名字框中心 = 卡片中心），只处理完整显示的卡片；滑不动（卡片名和位置不变）= 到头；买完会重排就重扫；
  - 买完核对**只看读数差**（天空石不变 + 付款货币正好减少总价），不依赖「获得奖励」框；
  - 离线测试用 `tests/daily_shop_sim.py`：真实 fixtures 认场景 / 按钮，卡片和顶栏由模型给（测试把 `shop_page.scan_cards / read_top / read_dialog` 换成 `sim.fake_*`）。

### API 层（B08，详见 architecture.md「API 层」和 reviews/B08.md）
- `python -m uv run e7helper serve [--port 47800] [--index N] [--no-connect] [--paused] [--no-auth] [--token X] [--allow-host H]`
  - 默认只监听 127.0.0.1；`--port 0` 随机端口；
  - `{pid, url, port, token}` 写进 `<数据目录>/api.json`，正常退出（Ctrl+C / CTRL_BREAK）时删除；
  - 启动后在后台自动连接设备（`--no-connect` 关掉），调度器同时启动。
  - uvicorn 配置在 `cli.server_config()`：**Selector 事件循环**（B12 反馈 7：Windows 默认的 Proactor 在客户端断开太快时会关掉监听 socket、关服务时卡在 wait_closed），关服务最多等 5 秒。
- **鉴权**：除 `GET /api/health`、`/docs` 外都要 token（`Authorization: Bearer` 或 `?token=`），并校验 Host 头；日志里的 `token=` 自动打码。
- **核心路由**（`/api`）：
  - `status`、`logs`
  - `device`（`connect` / `disconnect` / `instances` / `screenshot`）、`scene`
  - `modules` / `modules/{id}`（含 `config_schema`）/ `config`（GET/PUT，存 `modules/<id>/config.json`）/ `stats` / `timers`
  - `tasks`（POST → 202，409 busy）/ `current` / `stop` / `history`
  - `assistants`
  - `schedules`（CRUD + `run`）、`PUT /scheduler {paused}`
  - 错误格式 `{"error":{"code","message","detail"}}`
- **模块子路由**：`routes()` 挂到 `/api/modules/<id>/`，不能占用 `config` / `stats` / `timers`。已有 `GET /api/modules/daily/ledger`。
- **契约新增**：`Module.timers(data_dir) -> list[ModuleTimer]`（GUI 倒计时）、`TaskModule.next_due(config, data_dir, last_success)`（「按模块时间」调度）。daily 都实现了。
- **WebSocket**：
  - `/ws?token=`：先推 `hello`；请求 `{"id","op"}`，每个都有 `reply`。操作有 subscribe / unsubscribe / start_task / stop_task / run_schedule / pause / resume / status / ping。事件 `{"type":"event","topic","time","data"}`，主题有 log / task / scene / assistant / device / schedule / stats。
  - `/ws/frames?token=&fps&scale&quality`：二进制 JPEG。
- **调度**（`<数据目录>/schedules.json`）：
  - 触发方式：`interval`（从上次结束算）、`daily`（北京时间 HH:MM）、`module`（`next_due` + 最短间隔，失败时退避）；
  - 规则：到点忙时排队（`max_wait_minutes` 默认 30），或按计划设置跳过；补跑一次；连续失败 3 次停用；
  - **计划的 config 是完整快照，调度器不改 dry_run**：要实跑必须在计划里写 `dry_run:false`。
- **daily 两种用法**（B08 用户意见）：单次 = `POST /tasks`；持续收菜 = `module` 触发的计划（重置后跑一次，精灵之森到时间再跑）。repeat_battle 托管 = `interval` 计划，config 写 `manual:false`。
- 实测：经 WS 急停 daily，0.1 秒内退出；daily dry-run 一次约 23 秒；空闲时帧频道 4fps、半尺寸 JPEG 约 64KB 一帧。
- 测试：`tests/test_api.py`、`tests/test_scheduler.py`；`tests/api_fakes.py` 提供只截图不点击的假模块和 `make_engine`（GameSim 当设备）。

### GUI `app/`（B09，详见 architecture.md「GUI」和 reviews/B09.md）
- 在 `app/` 下：`pnpm install`、`pnpm tauri dev`（桌面应用）、`pnpm dev`（只起网页，浏览器打开 `http://localhost:1420/?url=<引擎地址>&token=<token>`）、`pnpm test`、`pnpm typecheck`、`pnpm build`。
- **引擎连接**（`src-tauri/src/engine.rs`）：先读 `<数据目录>/api.json`，`/api/health` 正常就直接连；否则拉起 `engine/.venv/Scripts/python.exe -m e7helper.cli serve --port 0`，token 随机生成、经 `E7_API_TOKEN` 传入，按 token 认出自己的服务。
  - 拉起的进程放进 Windows 作业对象。应用退出时 `POST /api/shutdown`，8 秒后强制结束；外部起的服务不动。
  - 开发用环境变量：`E7_ENGINE_DIR`、`E7_ENGINE_ARGS`（例如 `--no-connect --paused`）、`E7_DATA_DIR`。引擎输出在 `<数据目录>/logs/engine-stdout.log`。
- **开发版 / 正式版**（`src/lib/env.ts`；用户意见：正式版面向玩家，按用户思维布局）：
  - 演练开关只在开发版显示（默认演练，切实跑要确认）；正式版启动任务、建计划一律 `dry_run:false`（`lib/run.ts`）。引擎里模块默认仍是演练。
  - 只在开发版出现：模板采集、示例模块、日志「全部」、设备后端、引擎地址；`VITE_E7_DEV=1` 可在打包版打开。
- **页面**：各模块页（通用：说明、计时胶囊、设置自动保存、最近运行、底部开始 / 停止）、计划（列表、新建 / 编辑、推荐计划、总开关）、运行记录、日志、设置（模拟器连接 / 切换实例）、模板采集（开发版）。外壳：顶栏（模拟器、当前画面、下个计划、停止）、左侧菜单、右侧「实时画面 + 动态」。
- **模块界面扩展**：`src/modules/<id>/index.tsx` 默认导出 `ModuleUI`，自动收集（图标、菜单名、字段图标 / 依赖 / 开发版字段、推荐计划、`RunExtra`、`Header`、`onConfigSaved`）。daily 的「持续收菜」是 `RunExtra`；repeat_battle 推荐「托管自动结算」计划。
- **样式**：游戏风（原型 `docs/prototypes/b09/d-epic.html`，用户选定），主题和组件类在 `src/index.css`；背景是压暗的圣域图 `src/assets/bg_sanctuary.jpg`。
- **引擎新增**：`POST /api/shutdown`；`/api/capture/*` 模板采集接口（`api/capture.py`）；各模块配置字段补了中文 `title`。
- 测试：前端 `src/lib/*.test.ts`（vitest）；引擎 `tests/test_capture_api.py`。全量 `705 passed, 7 skipped`。
- 实测：拉起引擎 2.8–5.8 秒；经 GUI 跑 daily 演练 12.4 秒，中途停止立即生效；关闭应用时引擎正常退出并删除 api.json。

- **B12 起**：
  - 没有系统标题栏（`decorations: false`）：顶栏就是标题栏（`data-tauri-drag-region`，拖动、双击最大化），左上固定索尔缇娅头像 +「第七史诗助手」，右上 `WindowControls`（最小化 / 最大化 / 关闭，只在 Tauri 里显示）；启动画面顶上有 `WindowDragStrip`；权限在 `src-tauri/capabilities/default.json`。
  - `ModuleUI` 新增 `subFields`（附加选项画在主开关那一行里）、`fieldRenderers`（模块自己画某个字段，例如书签刷取的 `ItemPicker`）。
  - B12a：`ModuleUI.fieldLocks(config)` 按当前设置锁定字段（显示锁定值、变灰，和设置不一致时自动写入）；计划编辑里的设置改成函数式更新。
  - 过渡动画：`index.css` 里的 `--ease-*` / `--dur-*` 和 `anim-page` / `anim-dialog` / `anim-overlay` / `anim-menu` / `anim-slide-right` / `toast`；页面区按路径加 key（流程编辑器的路径算一页）。系统「减少动画」时全部关掉。
  - 说明文字只写功能做什么（用户意见），不写运行逻辑和安全规则。
  - B12c：「统计」页删掉了；`ModuleUI.RunsPanel` 代替通用「最近运行」（书签刷取的刷取历史）；`api.moduleGet(id, path)` 调模块子路由。

### RTA 助手页（B14e1，详见 architecture.md「GUI / RTA 助手（B14e1）」和 reviews/B14e1.md）
- 左侧菜单「英雄图鉴」下面「RTA 助手」，`#/rta`，宽页面（不显示右侧栏）。文件：`src/pages/DraftPage.tsx`（页面框架、请求、右边英雄网格）、`src/components/rta/`（`Panels.tsx` 各步面板 + 信息条、`TeamColumn.tsx` 阵容栏、`bits.tsx` 小部件：头像 / 段位图标 / 分段按钮 / 胜率颜色 / 标记）、`src/lib/draft.ts`（局面：选人顺序、保护位、预禁 / 选人 / 后禁、段位 5 项、开战规则、转成引擎格式）、`draftStore.ts`（当前局面 + 撤销，放在页面外）、`rta.ts`（接口数据形状、`useLatest`、`banHeadline`）。
- 局面按「我方 / 对方」记、整局按顺序存 10 手；发给引擎时 `apiState` 换成先手 / 后手，后禁双方都填了才带上。段位「挑战者及以下」按 `challenger` 发；双方都在优胜者以上才有开战规则（必须选，每局清空），否则发 `null`（没有规则；B14h 前发 `unknown`）。
- 请求「只要最新的」：同一时间只发一个，在途时局面变了只记最新的；结果按局面缓存在页面外（撤销、切页面不用再算）。引擎在途的搜索取消不了。
- 胜率：推荐卡是「预期」（搜索值）；信息条 B14e2 起在选秀时也是「预期」= 我方的读数（我方回合推荐第 1 名的、对方回合 `opponent.win`，`lib/rta.ts` 的 `pickHeadline`；用户意见：不用不知道英雄池的模型读数，鼠标提示里还有）；后禁这一步信息条显示「禁 X 后」= 推荐行（或已选那一行）的预期（用户意见）；结果是「胜率」。先动概率引擎给了才显示（B14h 起随包有速度表：信息条、推荐卡、后禁矩阵每格、结果都有）；信息条 1440 宽以下去掉三个文字标签、1200 以下去掉手数，才放得下一行。
- 右边网格**只放主模型里有的英雄**（`/rta/model` 的 `codes`，`lib/rta.ts` 的 `inModel`；B14h 用户意见）。
- 英雄网格是共用组件 `src/components/heroes/HeroGrid.tsx`（图鉴也用）：`HeroIcon`、`FilterRow`（`iconOnly`）、`HeroFilters`（`compact`、`onEnter`）、`HeroGrid`（`decor`：变灰、角标）；`filterHeroes(heroes, filter, score?)` 按 score 排。
- 段位图标 `app/src/assets/game/rank_{challenger,champion,warlord,emperor,legend}.png`：世界竞技场 › 排名 › 赛季奖励截图，`python tools/cut_icons.py <截图> ../app/src/assets/game --grabcut --max 128 rank_legend:370,248,150,152 rank_emperor:370,400,150,150 rank_warlord:370,550,150,150 rank_champion:370,700,150,150 rank_challenger:60,195,220,195`（挑战者用左边「我的段位」大图标）。
- 测试：`src/lib/draft.test.ts`（14）、`rta.test.ts`（2）、`heroes.test.ts` 加 1；引擎 `tests/test_rta_api.py`（13）。

### 打包（B10，详见 architecture.md「打包发布」和 reviews/B10.md）
- `cd engine && python -m uv run --group build python packaging/build.py`：检查 5 处版本号 → PyInstaller onedir → 冒烟测试（不碰设备）。产物 `engine/dist/e7engine/` 约 272MB、352 个文件。
- `cd app && pnpm bundle`（= `tauri build --config src-tauri/tauri.bundle.conf.json`）：安装包 `app/src-tauri/target/release/bundle/nsis/第七史诗助手_<版本>_x64-setup.exe`，约 96MB。
- **当前发布 0.3.0（正式版）+ 0.4.0-beta.2（测试版）**（GitHub Releases）：
  - 测试版 0.4.0-beta.2（2026-11-08，B14g2 之后）：带 B14g1 / B14g2 的修正（段位只影响先动、胜率按先动概率混合）。引擎 290MB、2641 个文件，冒烟测试全过（advise 1013 ms、preban 1066 ms，RTA 模型 parity 通过）；安装包 111.09 MiB，SHA256 `f31c7f74bcc4da2c76b9624e914c103719b28cf15e4461674067520582b2753c`。直接跑 `target/release/e7helper.exe`（临时数据目录、`--no-connect --paused`）：4.0 秒拉起随包引擎，版本 0.4.0-beta.2、`features.rta = true`、模型 274 名、有速度表、默认英雄池 60 名。冻结引擎 `rta advise` 跑复现用例：执行官维德瑞 + 奥芙 59.9%（挑战者 vs 战神）/ 61.5%（传说 vs 传说），和开发环境一致。推送 4 秒、上传 23 秒。
  - `bump_version.py` 要用全局 Python 直接跑（`python packaging/bump_version.py …`），经 `uv run` 跑时 venv 里没有 uv，改完 5 处后在 `uv lock` 那步失败；失败后用全局 Python 重跑同一个版本号就行（5 处会「原样替换」，再更新两个锁文件）。
- 以前的发布（2026-11-07，B14e2 之后）：
  - 正式版 0.3.0：`build.py --no-rta`，引擎 282MB、2631 个文件（比 0.2.0 多的是 B13 的英雄头像和技能图标），冒烟测试全过；安装包 105.41 MiB。直接跑 `target/release/e7helper.exe`（临时数据目录）：9 秒拉起随包引擎，版本 0.3.0、`features.rta = false`、`/api/rta/model` 404；开发版前端连这个引擎：菜单没有 RTA 助手、`#/rta` 回首页、图鉴没有英雄池按钮。
  - 测试版 0.4.0-beta.1：引擎 290MB、2641 个文件，冒烟测试全过（advise 1218 ms、preban 1059 ms）；安装包 111.06 MiB。直接跑 `target/release/e7helper.exe`：6.7 秒拉起随包引擎，版本 0.4.0-beta.1、`features.rta = true`、模型 274 名、默认英雄池 60 名。NSIS 接受带预发布后缀的版本号。版本号带预发布后缀：`uv.lock` 里规范成 `0.4.0b1`，其他 5 处原样，`build.py` 比的是 5 处原文。
  - 发版步骤：`python packaging/bump_version.py <版本号>`（改 5 处版本号，再 `uv lock` + `cargo update --workspace --offline`）→ 提交、打标签 → `build.py [--no-rta]` → `pnpm bundle`（`CARGO_TARGET_DIR` 指到主工作区的 `app/src-tauri/target` 可以复用 Rust 编译缓存）→ 先把安装包复制出来再打下一种 → `git push origin main <标签>` → `gh release create <标签> "e7helper_<版本>_x64-setup.exe#第七史诗助手 <版本> 安装包" --notes-file … --verify-tag`（正式版加 `--latest`，测试版加 `--prerelease --latest=false`）。
  - GitHub 会把资源文件名里的中文换掉，所以安装包先复制成英文名 `e7helper_<版本>_x64-setup.exe` 再传，中文名放在 `#` 后面的标签里；说明里附 SHA256。
  - 推送直连 GitHub 就行，0.3.0 这次推 210MB 用了 37 秒。全局 `.gitconfig` 原来设的代理 `127.0.0.1:7897`（Clash Verge）没开时会让 `git push` 连不上，2026-11-08 已按用户要求删掉；以后 push 失败先看 `git config --global --get-regexp proxy` 是不是又被加上了。
- **上一次发布 0.2.0**（2026-10-20，B12c 之后）：引擎 `dist/e7engine/` 272MB、446 个文件，冒烟测试全过；安装包 `第七史诗助手_0.2.0_x64-setup.exe` 97.39 MiB（Rust release 编译 3 分 35 秒）。没装，直接跑 `target/release/e7helper.exe`（临时数据目录、`--no-connect --paused`）：5.1 秒拉起随包 `engine/e7engine.exe`，`/api/health` 版本 0.2.0；关窗口后引擎退出、api.json 删除。冻结版的 `GET /api/modules/secret_shop/report` 实测能用。这个包不含 B13（B13 之后才合进 main）。下次发版改 5 处版本号（`build.py` 会检查）。
- 引擎冻结：`engine/packaging/`（`entry.py`、`e7engine.spec`、`build.py`）；冻结后 `paths.FROZEN`，`ENGINE_ROOT = sys._MEIPASS`；解释器开 `-X utf8`。
- `engine.rs`：release 构建拉起 `<资源目录>/engine/e7engine.exe serve --port 0`；debug 构建照旧用 venv；`E7_ENGINE_DIR` / `E7_ENGINE_ARGS` / `E7_DATA_DIR` 两种构建都认。
- 应用名「第七史诗助手」，exe `e7helper.exe`；NSIS `installMode: both`、简体中文；当前用户默认装到 `%LOCALAPPDATA%\Programs\第七史诗助手`。
- 图标：「雪之国的索尔缇娅」头像（官方 `c2111_s.png`，112px）+ 金色头像框，`src-tauri/icons/source/make_icon.py` 合成，`pnpm tauri icon` 生成各尺寸。
- 实测：安装版在精简环境（PATH 只有 System32 / Windows，全新数据目录）里 2.4–2.7 秒拉起引擎；连 MuMu（IPC）正常；关闭后 1–1.5 秒引擎退出、api.json 删除。

### 自定义流程 + 玩家模板（B11，详见 architecture.md「已有模块 / custom_flow」「自定义流程和玩家模板接口」和 reviews/B11.md）
- 流程定义 / 存储：`e7helper/core/flows/`（`Flow`、12 种步骤、`FlowStore`）；流程 `<数据目录>/flows/<id>.json`，玩家模板 `<数据目录>/flows/templates/`（不写安装目录）。
- 结构是**嵌套积木**：如果（那么 / 否则）、重复（N 次 / 直到 / 当…时），条件 = 模板（任一）出现 / 不出现或在某个内置界面，最多等 X 秒。步骤编号：「如果」先编「那么」再接着编「否则」（2.1、2.2 | 2.3）。
- 执行：一个通用模块 `custom_flow`（config `{"flow": "<id>"}`），经 `POST /api/tasks` 运行、能进计划；`config_schema` 给 `enum` + `x-enum-labels`，计划编辑里是下拉框。每步发 `custom_flow.step` 事件。
- 安全（用户确认）：只自动处理断线重进、网络重试和守卫弹窗（确认框 / 各模块的购买框，**一律点取消**）；点击落在已知「确认 / 购买」按钮上直接拦下停止；流程有最多运行时间（默认 10 分钟）和最多点击次数（默认 200）；遮罩兜底的返回键在流程里不生效。
- 引擎新增的通用能力：`Module.make_vision()`（模块自定义识别器）、`TaskFailed`（预期内的失败，只记消息不带调用栈）、`ctl.dismiss_popups(only=...)`。
- API：`/api/flows`（CRUD、复制、被计划使用时删除要 `force`）、`/api/user-templates`（列表含只读的 common、图片、保存并回验 `quality`、删除保护、在画面上测试）；冻结画面和开发版采集共用 `/api/capture/frames`。
- GUI：菜单「我的流程」「我的模板」（正式版也有）；编辑器 `/flows/:id`（拖动排序、现场采集模板、坐标点选、「在当前画面上找」、未保存提醒）；开发版的采集页改叫「内置模板采集」。前端步骤树工具在 `src/lib/flow.ts`（有 vitest）。
- 测试：`tests/test_custom_flow.py`（41 个，GameSim 离线）、`tests/test_flows_api.py`（9 个）、`app/src/lib/flow.test.ts`（8 个）。全量 `780 passed, 7 skipped`；前端 16 个。
- 实测（真机，正式版）：采「圣域入口」模板 1.00；大厅 → 圣域 → 返回 10.6 秒，1 次点击。

### 英雄数据库（B13，详见 architecture.md「游戏数据 `e7helper.core.data`」和 reviews/B13.md）
- `from e7helper.core.data import heroes; db = heroes()`：`db.get("c2111")` / `db.find(名字或昵称)`（忽略空白、全半角、大小写、间隔号，OCR 结果能直接查）/ `db.search(词)` / `db.icon(编号)`（头像 BGR 112×112）/ `db.detail(编号)`（技能、角色奉献、群阵位置 `devotion_slot`、专属装备三选一效果）/ `db.artifacts()`（神器中文名 + e7.wiki 图标名）。不依赖设备，助手模块可以直接用。
- 数据：随包 `engine/assets/data/heroes/`（`heroes.json` 一名一行、`icons/`、`details/<编号>.json` + `details/icons/`、`artifacts.json`、`overrides.json` 名字修正表）；联网更新写 `<数据目录>/data/heroes/`，较新的优先。只收 `c` 开头的编号（`m` 开头是愚人节怪物英雄）。随包数据更新：`python -m uv run e7helper heroes --update --bundled`（首次约 3 分钟；详情按 e7.wiki 更新时间增量下载）。
- 来源：Fribbels 仓库（herodata / artifactdata / 简中翻译 / 头像，GitHub → jsDelivr）、e7.wiki（`admin.e7.wiki/api/open/epicseven/hero/card-list`、`.../artifact/artifact-list`、`assets2.e7.wiki/static/heroes/<slug>.json`）、Fribbels 配装库 `krivpfvxi0.execute-api.us-west-2.amazonaws.com/dev/getBuilds`（POST 英文名）、神器图标先官方指南站再 e7.wiki。都不是公开 API。
- 配装汇总（`hero_builds.py`）：中位数；带速度套的组合 前 10% / 前 25% / 中位三行，不带的按速度三等分快 / 中 / 慢；装备均分 = 装备分 ÷ 6；缓存一天（`builds/`，带格式版本）。
- API：`/api/heroes`、`/api/heroes/{code}`（`/icon`、`/detail`、`/builds?refresh=`）、`/api/hero-icons/{name}`、`/api/artifacts/{code}/icon`、`POST /api/heroes/update`。
- GUI：左侧菜单「英雄图鉴」（正式版也有，宽页面）；详情弹窗 `components/heroes/HeroDetailDialog.tsx`（860px，角色信息 / 技能详情 / 配装方案）。游戏图标 60 个在 `app/src/assets/game/`（`gameIcon(名字)`，没有时退回文字 / 色块）：`element_*`、`role_*`、`set_*`、`stat_*`、`grade_d…sss`、`devotion_self`、`devotion_team_<位置>`（1 右、2 下、3 上、4 左）。
- 测试：`tests/test_heroes.py` 36 个、`app/src/lib/heroes.test.ts`；冒烟测试检查随包英雄数据、头像、技能详情和图标。

### RTA 对局数据（B14a，详见 architecture.md「RTA 选秀 `e7helper.core.rta`」和 reviews/B14a.md）
- `from e7helper.core.rta import rules, parse_battle`：
  - `rules`：`PICK_ORDER`（F S S F F S S F F S，F = 先手方）、`mover(n)` / `left_in_turn(n)` / `side_counts(n)` / `interleave()`、保护位 = 每边第 3 手、`validate(prebans, picks, banned, complete=)`（中文问题列表）、段位和段位档（金牌及以下合一档）、开战规则对照表 `OPENING_RULES` + 类别兜底 `rule_label(tid, category)`；
  - `parse_battle(raw, "cn"|"global") → Match`（`first` / `second` 两个 `Side`：段位、预禁、按顺序的 5 个 `Pick`（被禁、站位、神器、套装、伤害）；`winner`、`rule`、`rule_category`、`sequence()`），不合格抛 `BadBattle(reason)`。
- `official.OfficialClient("cn"|"global")`：限速（默认 1 秒 + 抖动）、429 / 5xx 退避重试；`seasons / current_season / recommend / ranking（海外） / battles / popular_hero / hero_analysis`。
- 采集库 `F:\e7helper-data\rta\crawl.sqlite`（开发机上的固定位置，环境变量 `E7_RTA_DB` 可改；不进 git、不随包；不放 AppData 的原因见「坑」里 MSIX 那条）：`players`（队列，玩家编号只在这里）、`battles`（`key = 服务器:battle_seq`，`raw` 是去掉昵称 / 编号后的原始字段）、`meta`（每天请求数）。读法：`crawl.iter_battles(server=, season=)` → (服务器, raw)，再 `parse_battle`。
- CLI（开发用）：`e7helper rta probe -s cn|global`（采一页看字段）、`rta crawl [--server both] [--season …] [--min-grade champion] [--max-requests N]`（Ctrl+C / 关掉后接着采）、`rta report [--json]`。
- 实测：国服约 4000 场 / 分钟（一页 100 场约 80 场是新的），海外约 1400 场 / 分钟（接口一次 3–4 秒）。国服优胜者以上约 2000 名玩家，几个小时就采完；海外玩家多，滚雪球到近 1 万名。
- 测试：`tests/test_rta_*.py`（53 个），合成对局在 `tests/rta_fakes.py`（照官方格式手写，不含真实玩家数据），采集用假客户端。

### RTA 胜率 / 选人模型（B14b，详见 architecture.md「RTA 选秀」的「胜率 / 选人模型」和 reviews/B14b.md）
- 运行时（只要 onnxruntime）：`from e7helper.core.rta import model; m = model.load()` → `m.win(states)`（先手方赢的概率）/ `m.next_picks(state, k)`（下一手轮到的一方最可能选谁）/ `m.evaluate(states)`（一批局面一次前向：win [B] + picks [B, V]）/ `m.check()`（parity）。局面用 `encode.DraftState(prebans, picks, banned, grades, rule)`：F = 先手方，picks 按这一方的选人顺序，rule：None = 没有规则、`"unknown"` = 不知道（B14h 起是各条规则的平均）、其余是 `opening_rule_desc_tid`。
- 编码：一场 = 17 个 token（0 CTX、1–4 预禁、5–14 选秀、15–16 双方被禁的），一次前向读出 12 个局面（已选 n 手读位置 4 + n，后禁后读 16）。胜率一律是**先手方**的。
- 随包 `engine/assets/data/rta/`：`model.onnx`（输出每个位置的 win_logit / pick_logits）、`meta.json`（词表 265 名（B14h 起 274 名）、开战规则 4 条、每个局面一组 Platt 校准、训练数据、切分模型的测试指标）、`parity.json`。推理一批 256 场 33–45 ms（门槛 50 ms，用户同意放宽）。
- **冷门英雄外推**：带冷门英雄（训练集里被选 < 1000 次）的局面模型过度自信，一层贪心会专挑冷门英雄把胜率推到 100%。**用户决定留给 B14c 的搜索挡住**：候选和对手回应只从选人头先验里取（参考 `sim.suggest`：这一手常见度 ≥ 0.5% 或排前 40）。
- 开发用（要 torch：`python -m uv sync --group train`；GPU 用 `engine/.venv-rocm`，`tools/setup_rocm_venv.ps1`）：`rta dataset [--until]`（快照 `F:\e7helper-data\rta\datasets\ss21-2026-10-23.npz`）、`rta train -m lr0|lr|fm|transformer|hybrid`（默认跑满整个余弦周期、按验证集保存最好的一轮；`--patience` 可选早停）、`rta eval`、`rta export <run> --metrics-from <切分 run>`、`rta watch`（曲线页 `http://127.0.0.1:47900/`）、网格 `tools/rta_grid.ps1`。run 在 `F:\e7helper-data\rta\runs\`。
- 不要 torch 的：`rta model --check`（冻结引擎冒烟测试也跑它）、`rta predict --first 艾丝黛 ...`（中文名试算）、`rta sim [--side F|S] [--opponent ai|manual]`（终端模拟 BP：一层估算的推荐 + 后禁 4 × 4 矩阵）。
- 测试：`tests/test_rta_encode.py` / `dataset` / `metrics` / `train` / `export` / `model` / `sim` / `watch`（新增 61 个，`train` / `export` 要 torch；RTA 共 114 个）；合成快照 `rta_fakes.synthetic_dataset`。

### RTA 选秀推荐（B14c，详见 architecture.md「RTA 选秀 / 选秀推荐（B14c）」和 reviews/B14c.md）
- `from e7helper.core.rta import search; adv = search.load()`（随包主模型 + `assets/data/rta/second/` 第二个模型 + `priors.json`，进程内只读一次）：
  - `adv.advise(state, "F"|"S", pool=None, budget=5.0)`：按局面分三种情况。
    - 轮到我方：给 `recommend`（每项有 `heroes`、`protected`、`score` / `win` / `worst` / `now`、`common`、`rare`、`trust`、`second.spread`、`uncertain`、`close`、对手回应）；
    - 轮到对手：给 `opponent`（对手可能的选择 + 威胁）；
    - 选完：给 `ban`（4 × 4 矩阵、每行最坏 / 预期 / 分数、`recommend`、`nash`）。
  - `adv.preban(side|None, grades=(我方, 对方), rule=, rule_category=, fixed=)`：预禁推荐。
  - 返回的胜率一律是**我方**的。按局面缓存，同一时间只跑一个搜索（后到的请求要等）。
- 门槛都在 `SearchConfig`：
  - 冷门 = 训练时被选 < 1000 次；
  - 候选 = 这一手常见度 ≥ 0.5%，或前 40 且不冷门；
  - 分数 = ½ 预期 + ½ 最坏；截止 5 秒。
  - 高估修正 `correction`：可信度 = q / (q + 1.5%) × min(1, 次数 / 1000)，只扣对出手方有利的部分。**重训（新赛季）后常数要用新的切分模型重新量。**
- `priors.json`（`core/rta/priors.py`，`rta priors` 从训练快照生成）：每名英雄被选次数、双方 ≥ 优胜者的预禁组合频率（各前 300 组）、后禁率。
- 接口（`api/rta.py`）：`GET /api/rta/model`、`POST /api/rta/advise {side, state, pool?, top?, budget?}`（局面不合法 422 `invalid_state`）、`POST /api/rta/preban`；没有模型 503 `no_model`。
- CLI：`rta advise --side F --pre-mine … --pre-theirs … --mine … --theirs … [--pool] [--json]`、`rta preban`、`rta sim`（改用这里的搜索）、`rta priors`、`rta audit [--parts …]`（开发用，要训练快照；结果在 `F:\e7helper-data\rta\audit\`）。
- 实测：advise p50 2.56 s、p95 3.43 s、最长 5.39 s（截止时间不管第二个模型的重算）；预禁 p95 0.99 s（先后手已知）/ 2.30 s（不知道）；冻结引擎 290 MB，冒烟测试跑 advise / preban。
- 测试：`tests/test_rta_search.py`（30 个，27 个用 `rta_fakes.FakeModel` 能手算）、`test_rta_api.py`（8 个）、`test_rta_audit.py`（4 个）。
- e7rtabot 对抗对比的脚本只在 B14c 会话里跑过（没进仓库），原始记录在 `F:\e7helper-data\rta\crosscheck\`（不进 git）。

### RTA 开局行动条 / 先动概率 / 英雄池（B14d1，详见 architecture.md「RTA 选秀 / 先动概率 / 英雄池（B14d1）」和 reviews/B14d1.md）
- 对局：`Pick.energy`（开局行动条 0–100，没有是 None）、`Match.first_mover`（F / S）/ `first_hero`；行动条不合格只是没有，`battle.energy_issue(raw, m)` 给原因。旧对局全都是「缺行动条」。
- 采集：`rta crawl [--backfill]`（`--backfill` 开跑时把国服这些赛季的玩家重置到第 1 页）；已有、没有行动条的对局再采到时整行替换，算「补」（`ServerStats.battles_filled`），翻页时算新的。
- 官方能力值快照 `core/rta/herostats.py`：`snapshot(client, season, codes, grades=)` → 采集库 `hero_stats` 表（原样存 result_body，-10002 没数据存空串）；`speed_histograms(season)`；`energy_matches(season, servers=)`（有行动条的对局 → 每场 8 个 `EnergyUnit`，在 Python 里按时间排）；`SCALES` 是官方页面上 8 项属性的刻度。
- 速度 / 先动 `core/rta/speed.py`：`load()`（随包 `assets/data/rta/speed.json`，没有返回 None）、`first_mover(table, [Unit(side, code, grade, speed?)])`、`annotate(out, state, side, table, speeds)`、开局规则 `RULES`；开发用 `build` / `fit_tails` / `implied_speeds` / `residuals` / `evaluate` / `choose_jitter`。
- 英雄池 `core/rta/pool.py`：`<数据目录>/modules/rta_draft/pool.json`，`load()` / `save()`，`Pool.limit()`（空 = 不限制）、`Pool.speeds`。
- 接口：`POST /api/rta/first {mine, theirs, grades?, speeds?}`（没有速度表 503 `no_speed_data`）、`GET/PUT /api/rta/pool`；advise 加 `use_saved_pool`、`speeds`，结果加 `first` / 推荐的 `first` / `ban.first`（我方先动的概率）、`pool`；`/rta/model` 加 `speed`。
- CLI：`rta first --mine … --theirs … [--grades] [--speed 名字=速度] [--table]`、`rta herostats`、`rta speed`、`rta advise --speed`、`rta report`（多一行行动条）。
- 测试：`test_rta_speed.py`（9）、`test_rta_herostats.py`（3），以及 battle / crawl / dataset / report / api 里新加的；合成开局行动条 `rta_fakes.gauge()`。RTA 共 165 个（2 个要 torch 的跳过）。
- 方案阶段的临时脚本和取到的数据（93 名英雄的官方传说 / 冠军速度直方图、13 名的 Fribbels 速度）只在那个会话的临时目录里，没进仓库；样本 `F:\e7helper-data\rta\energy_probe.json` 还在。

### RTA 国际服重训（B14h，详见 architecture.md 的 RTA 几节和 reviews/B14h.md）
- 快照：`rta dataset --servers global --exclude c2187 --until <最后完整的一天>`（`--servers` 默认 global；`--exclude` 收编号或中文名，刚出、随包英雄数据里还没有的直接写编号）。B14h 的快照 `F:\e7helper-data\rta\datasets\ss21-2026-11-01.npz`（107.6 万场，建一次约 19 分钟）。
- 训练：`TrainConfig.rule_unknown_rate`（`rta train --rule-unknown`，默认 0.1）。B14h 的 run：`b14h-hy-d128-L3-lam1`（切分，随包 `second/`）、`b14h-hy-d128-L3-lam1-full`（全量，随包主模型）、`b14h-fm-k16`（对照）、`b14h-cmp-b14b-split` / `-full`（B14b 两个模型的副本，评估对比用）。
- 高估修正常数：`python -m uv run python tools/rta_trust.py <快照> assets/data/rta/second`（每次重训后跑，结果差得多才改 `SearchConfig.trust_c`）。
- 速度表：`rta herostats -s global` → `rta speed`（默认国际服、默认清理「没算装备」的低档：`speed.clean_hists` + `refit_low`，`--no-clean` 关掉）。打印去掉 / 补回的低档、四种验收（加尾部 / 不加 / 只去掉 / 官方原样）、核对表、残差。
- 英雄数据：`heroes --update [--bundled]` 会把 e7.wiki 有、Fribbels 还没有的新英雄补上（`Hero.source = "wiki"`），Fribbels 有了自动换掉。
- 只放模型里的英雄（用户意见）：`/api/rta/model` 的 `codes`；RTA 页网格、预禁组合（`_Preban.pairs`）只用它们；`PUT /api/rta/pool` 有别的 422 `not_in_model`，GET / advise 跳过以前存的。`advise` 的 `unknown` 也列局面里模型没见过的英雄（命令行 / 接口直接传时才有）。
- 测试：`test_rta_dataset.py`、`test_rta_speed.py`、`test_heroes.py`、`test_rta_search.py`、`test_rta_api.py` 里加的 9 个；前端 `rta.test.ts` 加 `inModel`。

### RTA 英雄池（B14e2，详见 architecture.md「先动概率 / 英雄池」「GUI / 英雄图鉴、RTA 助手」和 reviews/B14e2.md）
- 引擎：
  - `core/rta/pool.py`：`load_saved()`（没设置过 / 文件坏了 = None）、`default(picks, codes, n=60)`（主模型里训练时被选最多的 60 名，`Pool.default = True`，不写进文件，重训后跟着变）、`reset()`（删文件）；`load()` 还是「没有 = 空」（命令行用）。
  - 接口：`GET /api/rta/pool` 没设置过返回默认的；`DELETE /api/rta/pool` 恢复默认；advise 始终传存的英雄池（存成空的也传 → 每一轮 `pool_short`、推荐全部英雄）。
  - `search.py`：英雄池里能选的（先验 > 0）不到这一轮要选的名数时不限制（`limited` / `eligible(need)`，根上记 `pool_short`，第 3 层同样）；**轮到对手时**算我方的读数：最可能的 8 种 + 模型读数最差的 4 种选法，各自 `reply_value`（我方从池里先验前 16 名挑回应、分数 ½ 预期 + ½ 最坏、按对手再下一轮先验前 12 名），`opponent.win` 按先验加权，模型读数留在每项的 `now`。
  - 命令行 `rta advise` / `rta sim` 打印 `pool_short` 的提示，`rta sim` 在这种回合允许选池外的英雄。
- 前端：`lib/pool.ts`（勾选 / 速度 / `parseSpeed` / `autoSave`：400ms 防抖、同一时间一个请求、`RESET` 恢复默认也排队、离开页面 `flush`）、`components/heroes/PoolEditor.tsx`（图鉴英雄池模式；从 RTA 助手进来带 `&from=rta`，按钮「返回 RTA 助手」）、`HeroGrid.tsx` 的 `PoolMark` 和筛选 `shrink`（1200 以下属性 / 职业只画图标）、`DraftPage.tsx` 的 `PoolInfo` 和网格「只看我的」、`lib/rta.ts` 的 `adviceKey`（缓存键带英雄池 `updated`）/ `pickHeadline` / `rareTag`。
- 测试：`test_rta_search.py`（池不够 3 个、对方回合 2 个）、`test_rta_api.py`（池不够、默认英雄池 2 个）；前端 `pool.test.ts`（7）、`rta.test.ts`（加 5）。

### RTA 先动模型（B14g1，详见 architecture.md 的 RTA 几节和 reviews/B14g1.md）
- **三个胜率头**：`encode.FIRST_HEADS = ("F", "S", "U")`（`HEAD_F` 先手方先动、`HEAD_S` 后手方先动、`HEAD_U` 不知道）；`encode.first_heads(first_mover)`（1 → F、0 → S、其余 → U）。新模型 `meta.json` 有 `format: 2`、`first_heads`、`grades: false`，ONNX `win_logit` 是 [B, 17, 3]，校准按头存 `{"F": …, "S": …, "U": …}`；ctx 输入还是 [B, 3]，段位那两格被忽略。旧格式模型照样能读（一个头复制成三个）。
- 运行时 `model.py`：`m.first` / `m.grades`；`m.heads(states)` / `m.all_states(heroes, ctx)` → [B, 12, 3]；`m.win(states, first=None, ref=None)`、`m.evaluate(states, first=, ref=)`（`Evaluation.heads`）；`model.effective_first(heads, first, ref, tau=FIRST_TAU)`、`model.mix(heads, first, ref)`。不给 first 用「不知道」的头。
- **混合公式**（`effective_first`）：q = 模型隐含的先动概率 (pU − pS) / (pF − pS)，w = 差² / (差² + τ²)（τ = 0.1），π = σ(logit π速度 + w · (logit q − logit π参照))；π速度 = 按双方段位 + 英雄池速度的速度表，π参照 = 段位 None、不带英雄池速度的同一张表。胜率 = π · pF + (1 − π) · pS。没有速度表时用 pU。
- 先动概率 `speed.FirstCalc(table, weights=, slot_weights=)`：速度分布在网格上直接积分（抖动 8 点求积、赫尔赛蒂限速分 8 档），没选满 4 名的一方按每一手的选取次数（`speed.slot_counts`）补占位；`prob_batch` 一批算；`speed.first_pair(calc, states, speeds)` → (first, ref) [B, 12]；`speed.match_first_probs(calc, tokens, codes, grade_ids)`（评估用）。5 名都在、还没后禁的局面对 16 种被禁平均。
- 训练：`TrainConfig.grades = False`、`first = True` 是默认（`rta train --with-grades --no-first` 只做对比）；`load_run` 读旧 run 时补 `grades=True, first=False`。`rta eval` 三头模型多一张表（混合 / 只用速度表 / 不知道 / 知道谁先动 / 先动差 / 先动概率），结果存 `eval-<split>-first.npy` / `-first-ref.npy`；子集多「段位:同档 / 差1档 / 差≥2档」。
- CLI：`rta model` 打印胜率头和是否看段位；`rta predict --dir <模型目录> --first-prob …` 打印三种情况和混合值。
- 开发工具：`tools/rta_holdout.py <留出快照> --day <日期> --train <训练快照> --model <新> --model <旧>`（留出日新旧模型直接比较，旧模型另列「段位换成不知道」）、`tools/rta_first_gap.py`（先动 / 后动两种胜率按阵容差多少）。
- B14g1 的 run：`b14g-hy-d128-L3-lam1`（切分）、`-full`（全量，29 轮）、`b14g-fm-k16`（对照）、`b14g-cmp-b14h-split` / `-fm`（B14h 的副本）。暂存模型 `F:\e7helper-data\rta\bundles\b14g1\`（主）+ `second/`（切分），parity 通过，一批 256 场 34 ms。
- 测试：`test_rta_train.py` / `test_rta_export.py`（要 torch，27 + 5）、`test_rta_speed.py`（FirstCalc 5 个 + first_pair）、`test_rta_model.py`（`effective_first` / `mix`）、`test_rta_encode.py`（`first_heads`）、`test_rta_dataset.py`（`head`）；`rta_fakes.synthetic_dataset` 带 `first_mover`（25% 不知道）。

### RTA 先动混合接入（B14g2，详见 architecture.md「RTA 选秀 / 选秀推荐」「先动概率 / 英雄池」和 reviews/B14g2.md）
- 随包 `assets/data/rta/` = B14g1 的三头模型（主 = `b14g-hy-d128-L3-lam1-full`，`second/` = 切分 run）；`priors.json` 多 `slots`（一方第 1–5 手各英雄被选次数，`Priors.slots`，旧文件 = []）。
- `search.py`：`Advisor(model, priors, second, speed_table=)`（`search.load()` 带随包 `speed.json`）→ `adv.calc`（`FirstCalc(**speed.FAST)`，占位按 `priors.picks` / `slots`）；`adv.advise(state, side, pool, speeds=)`（我方速度进缓存键）；`adv.win(states)`（和搜索同一口径的胜率，sim / audit 用）；`adv.info()["mix"]`（`first`，没有速度表时 `unknown`）。
  - 一次搜索一个 `_FirstCtx`：`_Net.forward` 取三个头，每行按阵容算 first / ref（`speed.ids_first_probs`：一批按编号拼好的局面、同一阵容只算一次；5 名都在、没后禁的对 16 种被禁平均；UNK 英雄按自己的编号）→ `model.effective_first` → 混合。
  - 每个值带「我方先动时 / 后动时」（`_Vals` / `_Result` 的 `s_*`、`_Cand.s_win`），输出 `win_first` / `win_second` / `first`。**显示的 `first`**（审核意见）：选秀中 `_Search.shown_first`（只按双方已选英雄、`FirstCalc.prob(fill=False)`，一方没有英雄时 None）；后禁每格 / 结束 = 4 打 4 混合用的 π，每行 = 按对方后禁率平均。
- `speed.py`：`FirstCalc(step=, levels=, dtype=)`、`FAST`（每档 4 速、限速 4 档、float32；评估仍用默认）、`tables` 缓存（只读）、`prob(fill=)`、`ids_first_probs`；`annotate` 只在 `out["first"]` 上加速度表读数 `heroes`。
- 接口 / CLI：advise 把英雄池速度传进搜索；`rta advise` 推荐表多「先动时 / 后动时」、后禁每格「先动 x% · a/b」；`rta sim` 胜率曲线用混合胜率。前端：`lib/rta.ts` 的 `Split` / `splitTip`，`Panels.tsx` 的推荐卡 / 对方选法 / 后禁矩阵每格每行 / 信息条 / 结果页鼠标提示。
- 开发工具：`tools/rta_trust.py` 按先动混合（`--no-mix` 对照）。
- 测试：`test_rta_search.py` 加 8 个（`rta_fakes.FakeModel(gap=)` 三头假模型）、`test_rta_speed.py`（`ids_first_probs`、`annotate`）、`test_rta_api.py`（先动概率由带速度表的推荐器给）；前端 `rta.test.ts` 加 3 个。

### 模块与 CLI（B01，B03 / B08 更新）
- 模块：继承 `TaskModule` / `AssistantModule`，放到 `e7helper/modules/<id>/` 就会被自动发现。参考 `modules/hello/`。
- CLI：`doctor`、`bench`、`screenshot`、`tap`、`modules`、`run <id> [-c JSON] [-t 超时]`（经 runtime）、`scene [-f 图片] [--dismiss] [--watch]`、`capture`（新增 `--tap`）、`match`、`ocr`、`serve`（B08）、`heroes [词] [--update [--bundled]]`（B13）、`rta probe|crawl|report`（B14a，子命令组）、`rta dataset|train|eval|export|model|predict|sim|watch`（B14b）、`rta advise|preban|priors|audit`（B14c）、`rta first|herostats|speed`、`rta crawl --backfill`（B14d1）、`rta train --with-grades --no-first`、`rta predict --dir --first-prob`（B14g1）；`rta advise` / `sim` 按先动概率混合、打印先动时 / 后动时（B14g2）。

## 关键决策
- 基准分辨率 1600×900。本机 MuMu 已经是 1600×900（平板模式 tablet.2）。
- IPC 为主、adb 为后备。adb 用 MuMu 自带的 `nx_main\adb.exe`。
- 所有入口必须先调用 `isolate_native_stdout()`（原因见 architecture.md）。
- 依赖安装走华为云镜像。`pyproject.toml` 里已经写了 `[[tool.uv.index]]`，`uv.lock` 也保留镜像 URL（用户确认）。
- `[tool.uv] override-dependencies` 排除了 `opencv-python-headless`。它是 rapidocr 带进来的，会覆盖带 GUI 的 cv2。**不要删这条。**
- 共用模板放 `common`（这个 id 保留），刷商店模块的 id 定为 `secret_shop`。
- fixtures 截图直接进 git，不用 LFS（用户确认）。
- 代码由 git 管理；每块审核通过后由用户确认再提交。
- **登录公告 / 每日签到不做自动处理**（B03 用户确认）：由用户自己把游戏点到大厅，任务默认从大厅开始。
- 场景标题模板放在 `common/title/*`，弹窗模板放在 `common/popup/*`。
- 有消耗的任务 dry-run 默认开启；表单只放用户真正需要的开关，其余参数作为引擎内部接口（B05 用户意见）。
- 本仓库没有配置远程；「推送到 main」= 把本地 main 快进到块分支的提交（B05 用户确认合入 main）。
- B06：托管 + 手动放在同一个模块（任务互斥，拆开就不能同时跑）；不用快速战斗；异界（专用代币）和迷宫不做；开托管时勾选「优先使用持有的行动力」。
- B07：日常只做邮件（剩余一天以内）、精灵之森（领取 + 照料）、誓约免费召唤（方案 A：优先免费十连，用完为止）；派遣（轮换活动）、骑士团（将改版）、每日任务 / 通行券不做。每日重置 = GMT-7 中午 12 点 = 北京时间 3 点。顶栏货币核对保留（用户确认）。
- 实跑阶段的录屏可以由我自行录（B07 用户确认）；采 fixture 时仍按用户说「开始 / 好了」。
- B08：
  - 鉴权用随机 token + Host 校验；调度到点有任务时排队，带等待上限；模板采集 API 推迟到 B09（均为用户选择）。
  - daily 由用户选择单次或持续收菜，GUI 显示模块计时（用户意见）。
  - 默认端口 47800。
- B09：
  - 风格选原型 D「游戏风」（用户在 A / B / C 之外要求更贴近游戏），背景用圣域 UI 淡入前的一帧并压暗（用户指定）。
  - 引擎连接「先连，连不上再拉起」，token 用 `E7_API_TOKEN`（用户选）。
  - dry_run 开关只在开发版显示，正式版一律实跑；打包版面向玩家，不带开发者思维（用户意见）。
  - 时间格式后端不动，前端统一转换；模板采集接口在 B09 补，只在开发版使用。
- B10：
  - PyInstaller onedir，作为 Tauri `bundle.resources` 带上（不用 onefile / externalBin）；
  - 安装时让用户选当前用户 / 所有用户（管理员账户会弹 UAC）、应用名「第七史诗助手」、图标用索尔缇娅头像（均为用户选择）；
  - 保留 opencv 的 ffmpeg DLL，不做裁剪；干净环境用本机模拟验证（用户选）；
  - 版本号 0.1.0；不做自动更新；安装包不签名；
  - 打包版真机验证只看连接、实时画面、当前画面识别（用户同意的范围）。
  - 用户意见：缺「玩家自己采集模板、自己设定流程运行」的功能 → 新开 B11，流程做到「步骤 + 条件分支」，模板采集开放玩家版（存用户数据目录，不改内置模块模板）。
- B11：
  - 流程用嵌套积木（不用「跳到第 N 步」）；GUI 是「我的流程」页 + 一个通用模块 `custom_flow`（不是每个流程一个模块）；遇到确认框一律点取消、禁止点确认（均为用户选择）；
  - 编辑器界面由我决定：左步骤树 + 右属性面板 + 底部保存 / 运行，没做原型；
  - 流程可以只读引用 `common` 内置模板（不含 `popup/*`），其他内置模块的模板不开放；上限：单步 300 秒、循环 999 轮、嵌套 6 层、300 步（用户没有异议）。
- B12（均为用户意见 / 选择）：
  - 竞技场不单独做模块，并进日常收取；补旗是竞技场的附加选项，名字「用友情点数补充旗帜」，不带说明；
  - 全应用的说明只讲功能做什么，不讲运行逻辑和安全边界；
  - 神秘商店改名「书签刷取」：商品固定三种（誓约书签 / 神秘奖牌 / 友情点数），选中高亮、不能增删；设置只留刷新次数 / 连续没出就停 / 连续没出就换世界频道；换频道 = 当前频道号 +1；
  - 标题栏做进应用（自己画窗口按钮），左上固定头像 + 应用名；界面加过渡动画；
  - 讨伐异界和后三个地下城单独立项 B12a；日常收取的商店日常购买单独立项 B12b；都在 B12 之后做。
- B13（用户选择，2026-10-21 审核通过）：
  - 数据随包内置 + 联网更新；国服中文名用 Fribbels 简中 / e7.wiki 的（用户确认一致）；assassin 叫「盗贼」；技能等中文资料用 e7.wiki；配装用 Fribbels 配装库原始数据；立绘不做；不显示昵称（只用来搜索）；
  - GUI 图标一律用**游戏里的图标**，由用户把游戏点到对应界面、我只截图裁出来（不用网站上的图）；
  - 图鉴按发布日期新的在前；愚人节怪物英雄不要；专属装备只显示三选一的效果，不显示背景说明；
  - 配装统计不用平均值：中位数，带速度套的看前 10% / 前 25%，不带的按速度分快 / 中 / 慢；装备分显示成装备均分；
  - 头像先只存，识别留给 RTA BP 助手（到时看真实 BP 画面）。
- B12c（2026-10-20 审核通过）：
  - 统计只做书签刷取，不单独做页面，删掉原「统计」页（用户意见）；
  - 放在设置下面代替「最近运行」、范围按钮、商品卡 / 数字 / 柱状图 / 每次运行列表、dry-run 不算、数据全部从 `history.jsonl` 算（我的决定，审核没有异议）；
  - 书签一次 5 个、奖牌一次 50 个写在前端 `items.ts`。
- 发布：B12c 后打包 0.2.0（用户要求发 release，版本号是我的决定）。
- B12b（用户选择，2026-10-20 审核通过）：
  - 花金币 / 免费 / 友情点数 / 各类代币，不花天空石；每日 + 每周限购都买；商品按用户截图圈定（14 件），表单是开关 + 逐个点选；
  - 光谱核心（160 行动力）行动力够就买满、不留保底；亲密度献礼选择箱越买越贵，每周只买 5 次；5面旗帜不进清单，由竞技场的「用友情点数补充旗帜」负责；
  - 商店排在竞技场前；页的顺序 交易所 → 一般 → 传承石（先拿到行动力再买光谱核心，我的决定）；
  - 传承石页签的绿色货币叫「银光传承石」（用户告知）。
- B12a（用户选择，2026-10-20 审核通过）：
  - 光谱核心允许用叶子 / 天空石补充；实现上沿用原来两个补充开关并改成通用名字（我的决定，审核没有异议）；
  - 异界能托管、用代币付费，手动流程同普通难度（实测胜利后是宝珠画面，已处理）；
  - 只有食人魔只有异界（用户纠正），GUI 选食人魔时难度锁定成异界，引擎收到别的难度直接停止并提示；
  - 「托管最多几份」放进表单（默认 0 = 不限，持有多少就全部拿来开托管）。

- B14（RTA BP 助手，2026-10-22 / 23，均为用户意见 / 选择）：
  - 功能对齐 e7rtabot.com/draft（五步：准备 → 预禁 → 选秀 → 后禁 → 结果），附加功能全要：先手概率、站位建议、快速分析、英雄统计；
  - **拆成 B14a 数据 → B14b 模型 → B14c 选秀推荐 → B14d 分析功能 → B14e 页面 → B14f 画面识别，每块一个会话**（「引擎工程量比较大，不要尝试直接在一个会话里做完」）；
  - 训练数据**国服 + 海外一起用、直接合并**，不用考虑两服版本不同步（国服很快同步国际服）；
  - 开战规则（优胜者以上）作为模型输入；国服接口没有这个字段，记为「未知」；
  - 每个空位推荐 **5–8 名**（e7rtabot 是 1 + 2）；计算时间可以放宽（定为 advise p95 ≤ 2 秒、预禁 ≤ 5 秒）；
  - 不管游戏内的「禁用助手」，推荐全权按我们的模型；
  - 英雄池：在英雄图鉴里勾选「我有的英雄」（可填速度），勾了只推荐这些，没勾不限制；
  - 采集只存选秀数据，不存昵称，玩家编号只在本机队列表里（我的决定，审核没有异议）。
- B14b（2026-10-25 / 26 审核通过）：
  - 训练数据只用本赛季 ss21、两服合并、全段位（段位作为输入，主指标看双方 ≥ 优胜者）；随包模型用切分选好结构和轮数后全量数据重训（均为用户选择）；
  - 训练过程要能实时看（终端进度条 + 自己做的曲线页，用户选）；GPU 能用就用（用户要求；AMD 官方 Windows ROCm 版 torch，比 CPU 快约 16 倍）；
  - 纯 Transformer 打不过因子分解机、也用不上后禁信息 → 随包「Transformer + 因子分解机」混合结构；早停只看胜率；Platt 校准（都是我按数据改的，审核没有异议）；
  - 速度门槛从 30 ms 放宽到 50 ms，换取 d = 128（用户选）；
  - 默认跑满整个周期、按验证集保存最好一轮（用户问 grokking 后改；重跑没有更好，grokking 实验也没出现）；
  - 冷门英雄外推留给 B14c 的搜索用选人头先验挡住，不在模型里修（用户决定）；
  - 用户是高端 RTA 玩家，判断对局会结合技能机制（开战套开局冷却、任务 / 额外伤害 / 推条等）：用户按实战判断模型对那局全手动模拟的 67.3% 是准确的。
- B14c（2026-10-29 审核通过）：
  - 时间预算放宽：「游戏里每轮的 bp 时间都在 20s 往上」→ 搜三层，advise p95 ≤ 6 秒（原来 2 秒）、预禁 ≤ 5 秒（用户意见）；
  - 「开工并加第二个模型」：切分训练的模型随包，只用来标「不确定」（用户选）；
  - 冷门门槛、先验门槛、分数 = ½ 预期 + ½ 最坏、预禁只推荐数据里常见的组合、英雄池里的冷门英雄可以推荐但要压住，都按我的默认（用户同意）；
  - 少见选择的高估修正是开工后按数据加的；显示的胜率不做整体缩放（跟着推荐的实际兑现 0.86–1.19）；
  - 自对弈 ≥ 90% 的 4 局（超过我定的 2%）按现状接受（审核通过，没有另提意见）；
  - 和 e7rtabot 的对抗对比：站长在 Discord 同意小规模、限频（每 3–5 秒一次请求）。网站条款原本禁止自动访问，以后要再跑，先问用户；
  - 开局行动条（`energyGauge`）的采集和用法放到 B14d 开工时定（用户决定）。
- B14g2（2026-11-08 审核通过）：
  - 按 B14g1 的设计草案做、没有拆子块；鼠标提示给「我方先动时 / 后动时」两种胜率（B14g1 时用户提的）；
  - **页面上显示的先动概率只按双方已经选出的英雄算**（审核两轮，用户意见：「应该显示当前局面的先动概率，不要计算考虑了对方应对后的先动概率」「不用补全，就按对方现在已经选的角色来判断就行」）；胜率混合照旧按补全的阵容（我定的、用户没有异议）；
  - 我定的、审核没有异议：先动概率在搜索里用快速档（`speed.FAST`）；高估修正常数不改（1.5%）；advise p95 多约 0.4 秒可以接受；冻结引擎冒烟测试留到下次打包。
- B14g1（2026-11-08 审核通过）：
  - **段位只影响「谁先动」的判断，胜率由英雄 BP 计算，再按先动概率混合**（用户原则；快照段位是赛后的，进胜率模型会漏结果）；
  - 一步到位修好，不先做临时修正；用现有国际服 ss21 快照现在做、不等 ss22；拆成 B14g1（模型）/ B14g2（搜索 / 接口 / 界面，换随包模型）（均为用户选择）；
  - 鼠标提示里可以显示先动 / 后动两种胜率（用户意见，B14g2 做）；
  - 我定的、审核没有异议：先动概率用 `effective_first`（模型隐含的 + 速度表的变化量）而不是直接用速度表；τ = 0.1；没有速度表时用「不知道」的头；新模型先暂存、不换随包模型。
- B14e2（2026-11-07 审核通过，均为用户意见 / 选择）：
  - 方案（11-03）：图鉴英雄池模式按发布日期排；预禁推荐完全不管英雄池；英雄池只放模型里有的英雄（B14h）；
  - 第 1 / 2 轮审核：信息条**始终用我方的读数**（「始终使用自己这儿的读数」：不显示不知道英雄池的模型读数，对方回合也要按我方从英雄池里回应来算）；**去掉「只推荐我的英雄」开关、始终按英雄池推荐**，**默认配置热门英雄**（「以防止玩家没有配置而无法进行推荐」）；
  - 我定的、用户没有异议：默认 60 名、默认的不写进文件、「恢复默认」= 删文件、存成空的 = 每一轮推荐全部英雄并提示、池不够这一轮就这一轮不限制（以后几轮的搜索也一样）、推荐卡上只因为英雄池才推荐的冷门英雄标「英雄池」、信息条用推荐第 1 名的预期（不是卡片里预期最高的那张）。
- B14h（2026-11-04 审核通过，均为用户意见 / 选择）：
  - **RTA 数据以后只用国际服**（国服已同步国际服，国服数据质量不行）：快照、速度表都只用海外；
  - 还没养成的新英雄（B14h 是侦探茉萝）采集照常存，**不进训练**（快照 `--exclude`）；
  - 赛季还是 ss21，没有平衡性调整，不影响采集和重训；速度表这次一起做；
  - 随包英雄数据补上 Fribbels 还没有的新英雄；
  - **模型没训练进的英雄不进 RTA 助手和英雄池**，只在图鉴里看（对方选了这种英雄时页面录不进去，用户审核时按现状通过）；
  - B14e2 方案（2026-11-03 定的）：预禁推荐完全不管英雄池；图鉴英雄池模式按发布日期排；B14e1 试用没有要改的。
- B14e1（2026-10-30 审核通过，均为用户意见 / 选择）：
  - B14e 拆成 B14e1（选秀页）/ B14e2（英雄池 + 试用反馈）；
  - 菜单名「RTA 助手」；布局参考 e7rtabot.com/draft（方案阶段选的「仿游戏 BP 画面」在第 1 轮审核时改掉）；
  - 段位用游戏里的段位图标，「挑战者及以下」合成一项；开战规则、先后手用按钮不用下拉框；国服 RTA 有开战规则（战绩站接口没有这个字段），**有规则的局玩家一定知道规则**，所以没有「不知道」、没选不能开始；预禁前就知道先后手；
  - 后禁这一步显示推荐行的预期，不显示「后禁前」的读数（两种读法单局能差 ±12 个点，模型那边留给 B14g）；
  - 卡片要对齐（「前面对齐、后面突然不对齐，体验不好」）：一组卡片放进列宽固定的网格，同一面板里几组用同一个列模板，每张卡行数一样；页面按桌面版默认 1280×800 和最窄 1100 宽核对。
- B14d1（2026-10-29 审核通过）：
  - B14d 拆成 B14d1（行动条 / 先动 / 英雄池）和 B14d2（站位 / 快速分析 / 英雄统计）（按「大块拆开」的习惯，用户同意）；
  - 速度按段位取（用户提议「像配装推荐一样按段位用不同分位」）→ 查到官方英雄分析的速度直方图就是按段位的绝对值，直接用；Fribbels 不批量取（会 403）；
  - 开局效果要和速度分开算（用户：「即使有开局加行动条的智武，200 速也跑不过 320 速的普通角色」）；天秤之主开局不触发（用户纠正）；
  - 290 以上（「高段位经常有 320 速以上的一速」，用户）用开局行动条反推；
  - **速度 / 先动不在模型外修正胜率**（用户：有的阵容抢到一速胜率差几十个点，有的几乎不差）；推荐只在旁边显示先动概率；ss22 重训时把「谁先动」放进模型（新增 B14g）；
  - **采集以后再说**（用户）：国服补采、能力值快照、随包速度表都没跑，工具和步骤保留（B14h 用国际服做了，见「重训流程」）。
  - **B14d2 往后放**（用户，审核通过后）：站位 / 快速分析 / 英雄统计等 ss22 赛季更新、数据重采后和 B14g 一起做；B14e 先做五步 BP 页面和英雄池，快速分析、英雄统计页跟着 B14d2 往后放。

## 下一块：等用户定
B14g2 通过、0.4.0-beta.2 发版后，ROADMAP 里没有排定的下一块（2026-11-08）。可选：
1. **B14f 画面识别**：见下一节（用户说过「先不做画面识别」，什么时候开工等用户说）。
2. **B14d2**：往后放，等 ss22 赛季更新、数据重采后再做（用户意见）。
3. B15+ 扩展模块。

## 之后：B14f RTA：画面识别（什么时候开工等用户说）
ROADMAP：助手模块 `rta_draft` 读帧自动跟随——阶段、双方段位、先后手、每个位置的英雄、预禁 / 后禁；用户打几场 RTA 采 fixture（**只截图、不点击**）；验收 fixture + 单元测试 + 实测一局。B14a 的草案只有一句：先请用户打几场 RTA 截图，再定认头像的方法（头像模板 / 名字 OCR + `heroes().find`）。开工时细化方案、和用户确认后再动手；工作量大，按习惯拆子块（例如 B14f1 采 fixture + 识别引擎 / B14f2 RTA 助手页自动跟随），拆法先问用户。
要先定的：
- **截图怎么采**：用户在 MuMu 里打 RTA，我只截图（`e7helper screenshot` / 设备层截帧），每个阶段（准备、预禁、选秀每一手、后禁、结果）各几张，双方先后手都要；国服简中界面。
- **认什么**：当前阶段、轮到谁、双方段位、先后手、开战规则（优胜者以上）、预禁 4 名、10 手各是谁（含保护位）、后禁；站位 1–4 对应游戏里哪个格子（B14a 留下的问题）。
- **认头像的方法**：随包头像（`heroes().icon(编号)`，112×112）做模板 / 特征比对，或者认名字（OCR + `find`）；只在模型里的英雄之外还要能认出「模型没见过的」（例如茉萝，B14h：页面上录不进去，识别后要提示）。
- **接进页面**：`AssistantModule` 只读帧、可以和任务并行（架构见 architecture.md「模块契约」）；RTA 助手页现在是手动录入（`lib/draft.ts` 的局面 + `draftStore`），识别结果怎么填进去（自动跟随 / 用户确认）要和用户定。英雄池数据已经放在 `<数据目录>/modules/rta_draft/pool.json`（模块编号就是 `rta_draft`）。
- 能直接用的：`core/vision`（模板匹配、OCR，B02）、`core/scene`（场景识别，B03）、事件总线的帧订阅（B03 / B08 WebSocket）。

## 往后放：B14d2 RTA：站位 / 快速分析 / 英雄统计（等 ss22 赛季更新、数据重采后再做，用户意见；B14g 已提前用 ss21 做了）
设计草案在 reviews/B14a.md「后续块的设计草案 / B14d」，ROADMAP 的 B14d2 一行也有。开工时细化、和用户确认后再动手。要做的：
- **站位建议**：采集的 `Pick.position`（1–4，被后禁的 0）。B14d1 方案阶段粗试过：只按每名英雄自己的站位分布排，留出 5,000 队上整队排对 26%、单名 51%；分布集中的英雄也有（亚露嘉 99% 在 1 号位、宝剑君主伊赛丽亚 79% 在 4 号位）。打算加「同一阵容以前怎么排」和成对的站位关系，用留出数据比。站位 1–4 对应游戏里哪个格子还没核对（B14f 截图时）。
- **快速分析**：两队（4 或 5 名）→ 胜率（5 打 5 走后禁矩阵）、每名英雄的贡献（实际阵容 − 换成这一手常见的其他英雄的平均）、搭档 / 克制（成对的二阶差）；先手方不知道时两种各算一半，选人顺序取几种平均。可以顺带给先动概率（`speed.first_mover`，有速度表时）。
- **英雄统计**：我们的统计（`rta stats` 从采集库生成随包 `stats.json`：选取 / 胜 / 预禁 / 后禁 / 第一手率、搭档 / 克制（扣掉各自强度、样本少的收缩）、套装 + 神器组合胜率、伤害、站位）+ 官方 `getPopularHero`（按段位，运行时取、缓存一天；B14h 起只用国际服的数据）。官方英雄分析（`getHeroAnalysis`）的套装 / 神器 / 技能 / 各属性直方图也能用：`herostats` 快照（B14h 取过国际服 ss21 的）或运行时按需取。有行动条后还可以加速度、先动率。

能直接用的：
- `search.load()`：快速分析的胜率用 `adv.model.win(states)`，5 打 5 走 `advise(...)["ban"]`；
- `speed.first_mover` / `speed.annotate`（B14h 起随包有速度表）；
- `herostats.SCALES`（官方各属性直方图的刻度）。

只做引擎和接口；页面（快速分析、英雄统计）也跟着往后放。

## 重训流程（B14h 按这个跑了一遍；新赛季、新英雄养成后照做）
开采集前先问用户。路径都在 `F:\e7helper-data\rta\`，训练用 GPU 环境（见「坑」里 RTA 模型训练那条）。
1. 采集：`rta crawl --server global`（国际服每人只有最近 100 场，B14h 一次约 8 小时、1.2 万次请求）；`rta herostats -s global`（约 35 分钟）。
2. 快照：按天数一下场数，最后一天不完整就用 `--until` 截掉；`rta dataset --servers global --exclude <还没养成的新英雄> --until <日期>`。
3. 切分训练 `rta train -m hybrid --d 128 --layers 3 --lambda 1 --epochs 30` + 对照 `-m fm --k 16`；`rta eval` 和上一版的模型比（**先复制上一版的 run 再评估**，见「坑」）。
4. 全量 `--full --calibration-from <切分 run> --epochs <最佳轮>`；`rta export <全量 run> --metrics-from <切分 run>`、`rta export <切分 run> --out assets/data/rta/second`。
5. 新旧主模型的直接比较：另建一份含最后一天的快照放到 `holdout\`，取那一天：`python -m uv run python tools/rta_holdout.py <留出快照> --day <日期> --train <训练快照> --model <新模型目录> --model assets/data/rta`（B14g1 起是脚本）；先动 / 后动差按阵容看 `tools/rta_first_gap.py`。B14g1 起训练默认三个胜率头、不看段位（快照段位是赛后的，**别再加进胜率模型**）。
6. `rta priors`、`tools/rta_trust.py`（B14g2 起按先动混合）、`rta audit`（机器空闲时跑，计时要和上一版同机对比；B14g2 写了个交替计时的临时脚本，没进仓库）、`rta speed`、`rta model --check`；全量单元测试放后台。默认英雄池（被选最多的 60 名，B14e2）跟着新的 priors / 主模型自动变，不用管；存过英雄池的玩家里新模型没有的英雄会被跳过。
7. 冻结引擎重新打包时带上新的 `assets/data/rta/`。

## 坑
- **从游戏截图裁图标**（B13）：脚本在 `engine/tools/`（`cut_icons.py` 彩色图标、`cut_flat_icons.py` 单色白图标、`make_team_icons.py` 群阵图示；用 `.venv/Scripts/python.exe engine/tools/<脚本> <截图> <输出目录> 名字:x,y,w,h ...`）——按和按钮底色的差距算透明度；宽的图标（SS / SSS）不要补成正方形，否则等高显示时会变小；选中行是白底黑图标，统一成白色再用；群阵图示是用一张「34」的截图按位置重新上色生成 7 种。截图时用户可能需要先点开筛选框，我只截图（用户允许时可以在列表文字区慢拖）。
- **Fribbels / e7.wiki / 配装库都不是公开 API**（B13）：哪天格式变了，`heroes --update` 或配装页会失败；随包数据不受影响。e7.wiki 的 `publish_dt` 只有 235 名有，发布日期用详情里的 `releaseDate`。
- **heredoc 里写 Python 再替换源码时，`\x89` 这类转义会被吃掉**（B13 踩过：写出了含非 ASCII 字节的 bytes 字面量，SyntaxError）。改含转义的代码用 Edit 工具。
- **断线后游戏回到标题画面**（B10a）：用户在手机上登录同一账号就能把模拟器挤下线，用来复现很方便。自动重进约 55 秒，只点屏幕、不输入账号；重进后游戏停在大厅，任务之前所在的界面没了，在别的界面里等待的任务会超时失败（只有 `tap_until` 导航能接上）。不要做「重进后整个任务重跑」，会重置天空石等预算计数。每天首次登录的签到 / 奖励画面还没登记。
- **「点击关闭」到处都有**（竞技场战斗记录、托管结算完毕、精灵之森奖励、邮件详情框）：模块弹窗要加背景场景的标题区分（B07）。
- **有些邮件点「领取」后会弹出详情框**，要再点「收信」；邮件列表按剩余时间排序，快过期的在最上面（B07）。
- **誓约召唤的免费气泡会换位置**：有免费十连时在「召唤10次」上方，只剩单抽时移到「1次召唤」上方（B07）。
- **单抽的结果是一张卡片**，只有左下「返回」，没有「召唤结果」标题；单抽动画没有「跳过」（B07）。
- **誓约页背景的星星光效会飘进顶栏**：按画面比对顶栏时单帧会多几十个像素，要多帧取交集（B07）。
- 圣域背景分白天 / 夜晚，用标题模板认，不要用背景（B07）。
- `wm size` 返回的是竖屏 900x1600，不要用它判断分辨率；用 `device.resolution`（来自 IPC）。
- `cv2.imwrite` 不支持中文路径，用 `core.imageio.read_image` / `write_image`。
- 测试点击要避开桌面图标。(800,450) 是 KernelSU 图标的位置。
- uv 不在 PATH 上，用 `python -m uv`。
- **TM_CCOEFF_NORMED 对亮度不敏感**：弹窗遮罩下的按钮照样得 1.0 分。可点击按钮的模板要设 `max_diff`（一般 30），场景判定也要先排除弹窗。
- RapidOCR 的 `__call__` 会把参数写回实例，调用时要显式传全（`ocr.py` 已经处理）。
- OCR 对全角/半角标点不稳定，比对文字前先过 `normalize_text`。
- rapidocr 导入要 3–5 秒，首次加载模型约 1.2 秒；需要即时响应时先 `warmup()`。
- 全屏彩色模板匹配约 130ms，模板尽量设检索区域。
- 在 Git Bash 里 `cat > file` 后面不跟 heredoc 会一直等 stdin、卡住命令；写文件用 Write 工具。
- 操作游戏时绝不点「确认刷新」或购买（会消耗天空石），只做导航和取消。
- **界面没静止时点击会被吞**：切换界面后标题很快就能认出，但列表飞入动画要 1–2 秒，这期间游戏忽略点击。用 `wait_scene`（默认会等画面静止），不要认出标题就立刻点。
- **识别区域 ≠ 可点区域**：例如大厅「秘密商店」文字下半部分点了没反应。遇到「点了没反应」先怀疑这个，用 `capture --tap` 设可点区域。
- 淡入淡出时画面会短暂变暗，看起来像弹窗遮罩；遮罩兜底已经加了「静止才算」的复核，不要去掉。
- Bash 里前台 `sleep` 被禁用，需要等待时用 `python -c "import time; time.sleep(n)"`，或者在脚本里 sleep。
- pytest 里根 logger 是 WARNING，要测 INFO 日志时用 `caplog.at_level("INFO")`。
- **列表滑动有惯性**：滑动结束后约 0.7 秒才停住，末段整屏帧差只有 1–2，低于整屏静止阈值 5，所以整屏判定可能在列表还在漂移时就通过。列表界面要只看列表区域（参考 `secret_shop._settle_list`）。
- **顶栏数字有滚动动画**（约 0.4 秒）：读资源要连续两帧一致才采用。顶栏布局随红点和图标数量变化，必须先定位图标再读数。
- **秘密商店每小时自动刷新一次**，过程是静默的：没有弹窗，不扣天空石，列表回到顶部。
- **游戏里的「确认」框长得不一样**：通用确认框是「取消 / 确认」，购买框是「取消 / 金币价格 + 购买」。按钮相同的框（刷新 / 结束游戏）用文字**模板**区分；不要用 OCR 文字条件，每帧要 600ms。
- `Controller.tap_template` 没有关闭点击后等待的参数。需要马上开始轮询时，用 `tap_match(ctl.wait(ref), ref=ref, delay=False)`。
- **竞技场里多个界面标题相同**（都叫「竞技场」）：标题模板不足以区分场景，要加各界面独有的锚点。别的玩法大概率也一样。
- **CLI `scene` 只加载内置场景**：模块注册的场景（如 `arena_npc`）在 CLI 里显示「未知」，要看模块场景用 `run` 的 `-v` 日志或自己写脚本注册。
- **购买框可能自动选中天空石**：竞技场补旗框在今天补过之后会自动选中天空石，「购买」仍然亮着。凡是有多个付款选项的框，点购买前都要核对选中项。
- **结算刚出现时点击会被吞**：竞技场普通战斗结算的「确认」在入场动画期间点了没反应；不消耗东西的按钮用 `tap_until(..., retry_after=2)`。
- **自动战斗的图标在转 ≠ 蓝色光圈**：蓝色光圈只是点击特效。
- 在购买框上用脚本点「取消」也可能被自动安全检查当成交易拦下；关闭这类框用模块的 dry-run（弹窗规则点取消）。
- **弹窗淡出期间还会被认成弹窗**：点了确认 / 购买 / 关闭后马上 `wait_scene` / `dismiss_popups`，会在淡出时再点一次取消或空白处（B06 实跑踩过）。先等它自己消失。
- **战后界面永远不静止**（战斗场景背景、角色待机动画）：`wait_scene` / `tap_until` 默认等静止会超时，要传 `settle=False`。
- **顶栏部分图标会变灰**：从「重新进行」回到准备界面时，托管 / 背包 / 邮件 / 菜单图标亮度降到约 0.38，红点也变暗。按颜色判断状态时要按图标亮度归一化。
- **准备界面每次回来默认是快速战斗**，「无记录」只在普通战斗模式显示。
- **讨伐的难度卡片随地下城变化**（后出的地下城只有「讨伐异界」），不能按固定位置点。
- 结算界面的「确认」入场动画期间点击会被吞，补点即可（每场多约 2 秒）。
- **不要按固定坐标点顶栏**：没有托管时时钟图标不存在，原位置变成天空石的「+」（B06 误点进过天空石充值页，没有购买）。先定位图标。
- **`find_install` 找不到显式路径时会继续找注册表和常见路径**：`--mumu-root` 指向不存在的目录**拦不住**连接真机。不想碰设备时用 `serve --no-connect`（B08 踩过：冒烟测试意外连上 MuMu 截了一张图）。
- **uvicorn 关闭后会重新抛出收到的信号**：Windows 上 SIGBREAK 的默认处理是直接结束进程，`server.run()` 之后的代码不会执行。退出时的清理放在 lifespan 关闭阶段（`create_app(on_shutdown=...)`）。被强制结束（TerminateProcess）时 api.json 会残留，读取方要用 pid 或 `/api/health` 确认。
- **Starlette TestClient 的 WS 地址默认是 `ws://testserver`**，过不了 Host 校验：测试里用绝对地址 `ws://127.0.0.1:47800/...`。TestClient 还会把默认的 `Authorization` 头带进 WS 请求。
- WS 测试里事件可能比回复先到，收消息时不要丢掉不匹配的消息（见 `test_api._recv_until`）。
- **computer-use 认不出开发中的 Tauri exe**（B09）：截 Tauri 窗口用 Win32 `PrintWindow`（见 B09 审核记录的做法，不需要窗口在最前）；点按钮在浏览器面板里打开同一个前端页面（`localhost:1420/?url=&token=`，连同一个引擎）。
- **`pnpm tauri dev` 和预览配置 `app-vite` / `app-preview` 都占 1420 端口**：先停掉预览再跑 tauri dev。
- **浏览器面板里只改 `#` 后面的部分不会重新加载页面**：要看新状态就改一下查询参数（例如加 `&r=2`）。
- **不想碰真机就用 `E7_ENGINE_ARGS="--no-connect --paused"` 加临时 `E7_DATA_DIR`**：`--paused` 会写进 schedules.json（B08 已知问题 3），不要在真实数据目录用。
- 开发版和正式版共用 `%LOCALAPPDATA%\e7helper`：开发版建的演练计划到了正式版还是演练（列表上标「演练」，正式版重新打开开关或改设置就会改成实跑）。
- React StrictMode 下 effect 会执行两次：只能发起一次的事（连接 / 拉起引擎）要用 ref 防重入（见 `ConnectGate`）。
- 测试里保存模板要 `monkeypatch.setattr(paths, "ASSETS_DIR", tmp)`，否则会写进真实的 `engine/assets`。
- Rust 的 `canonicalize` 在 Windows 上返回带 `\\?\` 前缀的路径，日志里能看到，不影响使用。
- pnpm 12 默认拦下依赖的 install 脚本（`npm warn allow-scripts`），目前没有影响。
- **`python -m uv pip install` 默认装进全局 Python**（经 `python -m uv` 调用时用调用它的解释器），要加 `--python .venv/Scripts/python.exe`（B10 踩过，已恢复）。依赖优先写进 `pyproject.toml` 的依赖组再 `uv sync --group`。
- **冻结版忽略 `PYTHON*` 环境变量**：`PYTHONIOENCODING` 等对 `e7engine.exe` 不起作用；需要的解释器选项写在 spec 里（UTF-8 模式是 `("X utf8", None, "OPTION")`，写成 `utf8_mode=1` 无效）。因为开了 UTF-8 模式，新代码读写文件、解码子进程输出都要显式写编码。
- **`tauri dev` 不要带上冻结引擎**：资源配置在 `tauri.bundle.conf.json`，只有 `pnpm bundle` 合并；直接 `pnpm tauri build` 打出的安装包里没有引擎。
- `tauri build` 会把资源也复制到 `target/release/engine/`，所以不安装也能用 `target/release/e7helper.exe` 验证 release 行为。
- NSIS `installMode: both` 用 `Highest` 权限：管理员账户运行安装程序总会弹 UAC，安装 / 卸载测试要用户来点。
- 截 Tauri 窗口、发 WM_CLOSE 的脚本做法见 reviews/B10.md「验证」（PrintWindow + PW_RENDERFULLCONTENT）。
- **浏览器面板的截图常常慢一拍**（B11）：刚点完就截，看到的是上一个状态。要确认界面状态用 `get_page_text` / `javascript_tool` 读 DOM。
- **浏览器面板截图的缩放横竖可能不一样**（视口 1440×880 截成 800×600 时 x 0.556、y 0.682）：按截图坐标拖框前先用 DOM 读一次实际结果再修正。
- **模拟鼠标拖不动 HTML5 原生拖放**：要测拖放用脚本派发 `dragstart` / `dragover` / `drop`（`new DataTransfer()`），见 reviews/B11.md。
- **React 合成事件会穿过 Portal 冒泡**：弹出菜单（radix Popover / Dialog）里的点击会触发外层元素的 onClick。外层「点空白取消选择」要判断 `e.target === e.currentTarget`。
- **`python -I` 会忽略 `PYTHONIOENCODING`**：在 Git Bash 里用 venv 的 python 跑带中文输出的脚本时加 `-X utf8`，否则是 GBK 乱码。
- 不碰真机测 GUI：可以写一个用 `tests/game_sim.py` 当设备的临时引擎（`Engine(device_factory=...)` + `create_app` + uvicorn），浏览器面板连它就能完整跑流程（做法见 reviews/B11.md「GUI」）。
- **测试会对所有模块调 `setup()`**（`test_scene.test_relogin_popups_with_all_module_popups`，用假对象）：新模块的 setup 如果要读配置或会报错，要先做完弹窗注册。
- **Windows 的 Proactor 事件循环两个毛病**（B12 反馈 7）：客户端在被 accept 的瞬间断开会报 WinError 64，Proactor 把监听 socket 关掉、API 再也连不上；对端已重置的连接关闭时 `shutdown()` 抛错（「动态」里那条 `_call_connection_lost` 红字），连接没从 `asyncio.Server` 摘掉，关服务时卡在 `wait_closed()`。`serve` 已改用 Selector 循环；以后自己起 asyncio 服务也要注意。复现做法见 reviews/B12.md 反馈 4 / 7。
- **命令行的输出指向 NUL 时起不来**（B12 发现，没修）：`e7helper serve` / `screenshot` 的 stdout 重定向到 `/dev/null`、`subprocess.DEVNULL` 时直接退出。脚本里调用命令行把输出写到文件。
- **聊天面板按一次返回键就整个关掉**（B12），包括里面的「变更频道」框；聊天关着时按返回键会退出当前界面（在商店里就回到大厅），所以先确认聊天开着再按。底部发消息的输入框和「输入」绝不能碰。
- **骑士团页签和频道页签右上的图标不一样**（B12）：骑士团页签没有 ⇆，同一个位置是别的图标；换频道前先切到「频道」。
- **聊天面板标题的 OCR 区域别太宽**：面板是半透明的，后面顶栏的天空石数字会被读进来（`chat.TITLE` 只看左边 190px）。
- **pydantic 会把枚举的 docstring 当成字段说明**显示在 GUI 表单里（B12）：枚举的说明写注释，不写 docstring。
- **GUI 保存的模块配置包含内部字段**（`save_config` 存整个 `model_dump`）：改了内部字段的默认值时，旧配置里的旧值会盖掉新默认值，要像 `secret_shop._migrate_b12` 那样迁移。
- **测试 Tauri 窗口按钮**（B12）：PrintWindow 截窗口；往窗口里 `Chrome_RenderWidgetHostHWND` 子窗口 PostMessage 鼠标消息能点到网页（不动用户的鼠标），双击用 `WM_LBUTTONDBLCLK`。做法见 reviews/B12.md 反馈 6。点「关闭」会结束 `pnpm tauri dev`。
- **浏览器面板隐藏时是后台页**：CSS 动画和计时会变慢，radix 对话框要等关闭动画播完才卸载，看起来像「关不掉」；量动画要在可见窗口里看。
- **浏览器面板里改 hash 会被当成导航**，`javascript_tool` 的脚本会被打断：要测换页就先在页面里装 `animationstart` 之类的监听，再用点击触发，下一次调用读结果。
- **我自己起的临时引擎用完要确认退出**：B12 时有三个临时引擎关不掉（原因见上面 Proactor 那条），留着会占端口、占内存。B12a 用 `POST /api/shutdown` + `/api/health` 确认退出。
- **异界胜利后没有 CLEAR**（B12a）：宝珠画面「请轻触屏幕领取奖励。」点一下直接到战后。不同玩法的胜利画面可能都不一样，新玩法实跑前先录一遍。
- **托管设置框右上的数字整组右对齐**（B12a）：位数一变位置就变，固定区域会截掉第一位（110 读成 10）。这类「图标 + 数字」并排的读数用整行 OCR 取数字。
- **光谱核心图标有光效动画**（B12a）：不同时间截图差别大，只能用图标中心的小模板，1280×720 下 0.82 分，阈值 0.75。
- **讨伐列表底边会截掉一半名字**（B12a）：OCR 照样认出（高约 18），但点不准；`find_hunt` 要求高 ≥ 26。
- **异界准备界面右下角就是「战斗开始」**：普通难度切换快速 / 普通战斗的钮在那个位置，异界没有这个钮，别按固定坐标点。
- **录屏存 JPEG 当不了按钮 fixture**：有 `max_diff` 的按钮模板颜色校验过不了。要做 fixture 的画面用 PNG 截。
- **商店买完多数商品没有「获得奖励」框**（B12b 实跑踩过）：行动力这类入场券只在顶部中间飘一条提示约 1.5 秒（挡住顶栏数字），只有普琳免费商品弹框。买成以读数差为准，读顶栏前先等提示飘完。
- **商店列表买完会重排**：买完的移到最后，其他卡片往前挪；不要记卡片位置，每次重扫。
- **商店列表甩得很远**：0.6 秒拖 740 像素会挪 5 列以上，中间的商品直接跳过；用 1 秒拖 400 像素（约 2 列）。
- **商店卡片的「1/1」OCR 常读成「11」**（斜杠丢了），买完的灰色「0/3」有时读不出：见 `shop_page.parse_counter` 和 `shop._find`。
- **商店购买框有三种布局**（有数量条 / 只能买 1 个 / 越买越贵），标题「购买商品」字号不同，要两个模板；秘密商店的购买框也是同一种框。
- **同名商品**：一般页有两张「光谱核心」（行动力买 / 生命之叶买），按「剩余/上限」和价格图标区分。
- **worktree 里没有 `.venv` 和 `node_modules`**：先 `python -m uv sync`（设 `UV_DEFAULT_INDEX`）；`pnpm typecheck` 会自动装依赖。
- **官方战绩站的坑**（B14a）：
  - 国服 `getBattleList` **不按 `season_code` 过滤**，往前翻页会翻到以前的赛季（对局本身带正确的赛季）；采集已改成翻到别的赛季就停。
  - 对手的数字编号是 `matchPlayerNicknameno`；`enemy_nick_no` 是**昵称**，拿它查接口会 405。
  - 海外 `getBattleList` 每人只返回最近 100 场（`page_no` 无效），`total_count` 也是 100；海外接口一次要 3–4 秒，要带 `Content-Type: application/json`。
  - 海外有一方低于优胜者时 `opening_rule_*` 是占位符 `_`；国服完全没有这两个字段。
  - 选秀阶段有人退出的对局双方 0 名英雄、0 回合（约 1%），解析时归为「没有选秀」。
  - `battle_day` 是 UTC，`battleCompletedate` 是韩国时间（晚 9 小时）。
  - `energyGauge` 是**开局**行动条，不是结算时的（B14c 审核时核对；B14a 误认了，B14d1 起采集保留）。`position_no` 是第几手，不是站位。
  - `getHeroAnalysis` 的属性直方图是**绝对值**（官方页面代码里的刻度，速度 110–310、每档 20，最后一档 290 以上没有上限）；段位只有大师到传说；没有数据返回码 -10002（国服还没有的英雄，例如梅琳）。B14a 以为是相对档位。
  - 不存的字段要看值：`rta probe` 只列字段名，临时脚本里直接用 `OfficialClient` 取一页。别在大库上跑 `order by added` 这类全表扫描，几分钟都出不来。
- **Claude 桌面版是 MSIX 打包应用，会重定向 `AppData`**（B14a 发现）：从 Claude 会话里跑的命令往 `%LOCALAPPDATA%` 写的文件，实际落在 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\` 下（会话里读写看起来路径正常，资源管理器和会话外启动的程序在原路径找不到）。采集库原来就落在那里，用户在资源管理器里找不到，已挪到 `F:\e7helper-data\rta\`（用户指定）并改了默认路径。以前会话里写的 `e7helper\data`、`debug`、`modules` 等也在那个私有目录里。要让外面看得到，就写到 `AppData` 以外的路径（`--db`、`E7_RTA_DB`、`E7_DATA_DIR`）。
- **Fribbels 配装接口不能批量取**（B14d1）：每 2 秒取一名，取到第 14 名就开始返回 403。只按用户点开时单个取（B13 的用法）。
- **B14h 的几个坑**：
  - 这台机器上会话里 47xxx 的端口都绑定不了（WinError 10048，`netstat` 里却没人占；预览工具起引擎也一样）：临时引擎用 `serve --port 0`，实际端口读 `<E7_DATA_DIR>/api.json`，前端开 `http://localhost:1420/?url=http://127.0.0.1:<端口>&token=x`（引擎加 `--no-auth`）。
  - `rta eval` 会把结果写进 run 自己的 `eval-test.json`：评估上一版的模型前先把 run 目录复制一份。B14b 的切分 run 只存了温度，评估时会拿当前快照的验证集重新拟合校准、长度对不上报错：副本的 `best.pt` 里写进它原来那组校准（原来的 `eval-test.json` 里有）。
  - 不带 `-d` 的 `rta train / eval / export / priors / audit` 用 `datasets\` 里**修改时间最新**的快照：额外建的快照（留出用的）放别的目录。
  - 采集库 `battles.day` 是完整时间戳；按天统计别在 sqlite 里全表 group by（几分钟都出不来），取出来在 Python 里数。
  - 官方速度直方图里混着「没算装备」的记录（基础速度或 × 1.25 那一档的孤立尖峰），`rta speed` 默认清理；B14d1 时用国服数据没发现。
- **B14e2 的几个坑**：
  - **停掉 `pnpm dev` 的后台任务后 Vite 还在**（node `vite.js` 子进程留着、1420 端口占着，之后 `pnpm tauri dev` 会起不来）：按命令行找到这个工作区的 `vite.js` 进程结束掉（`Get-NetTCPConnection -LocalPort 1420` → `Win32_Process` 看命令行再 `Stop-Process`）。
  - 浏览器面板里用脚本连着点：改了段位 / 开战规则后马上点「开始预禁」会点到还没重新渲染的灰按钮（什么都不发生）；每步之间等 0.3–0.5 秒，或者每步单独调用。
  - Git Bash 里 `python -`（系统 Python）`print` 带 emoji 的字符串会 GBK 报错（`UnicodeEncodeError`），但前面的写文件已经做了；要打印就加 `-X utf8`。
  - 新会话的工作区从 main 开：前面的块还没合进 main 时（B14e2 开工时 B14h 就不在 main 上），先看 `git worktree list` / 各分支，把本分支快进到上一块的提交再开工。
- **B14g1 的几个坑**：
  - **快照里的段位是赛后的**（官方战绩的 `grade_code` / `enemy_grade_code`）：差两档的对局段位高的一方几乎全胜，进胜率模型就是漏结果。只能用在「谁先动」上（速度表按段位），评估时按段位分子集也要记得这一点。
  - **主工作区没有 `engine/.venv-rocm`**：GPU 环境在 `.claude/worktrees/b14b-rta-winrate-model-2f2020/engine/.venv-rocm/`。在 `engine/` 下用它的 python 跑 `-m e7helper.cli rta train|eval|export …` / `-m pytest tests/test_rta_train.py tests/test_rta_export.py`，导入的是当前目录的代码。主 `.venv` 没有 torch（别 `uv sync --group train`，会和正常同步来回删装）。
  - 直接用速度表的先动概率混合比「不知道」的头还差（官方速度直方图混着 PvE 配装，抢一速的阵容上最不准）：要用 `model.effective_first`。以后换速度表或重训，先在测试期比一下「混合 / 只用速度表 / 不知道」三行。
  - 选秀中间补占位时按「这一手常见的英雄」（`slot_counts`）比按整体选取次数准（第 5 手平均先动概率 56.7% vs 62%，实际 52%）；还是偏向已选人数多的一方。
  - 赫尔赛蒂（c1153）限速的行要按 8 档速度分别算，逐行算很慢：用 `FirstCalc.prob_batch` 一批按档算。
- **B14g2 的几个坑**：
  - 显示的先动概率和算胜率用的不是同一个数（用户意见）：页面上只按已选英雄（`shown_first`），混合按补全的阵容 + 模型隐含的先动概率；推荐卡上 先动 × 先动时 + 后动 × 后动时 ≠ 预期，别再去「修」成相等。
  - 三头假模型（`FakeModel(gap=)`）的三个头隐含「一般玩家五五开」，`effective_first` 以它为底，所以混合用的先动概率不会是 0 / 1：测试里比大小，别断言绝对值。
  - 先动概率的计算放进搜索后，第一次跑 advise 4.7–5 秒、多数截断：大头是 `team_log` 的 [B, m, K] 大数组和赫尔赛蒂限速分档。搜索里用 `speed.FAST`；评估（`rta eval` / `rta_holdout`）用默认精度，B14g1 的指标才能复现。
  - Python 读写源码（`open` 默认文本模式）会把工作区的 CRLF 改成 LF（git 提示 LF will be replaced by CRLF），提交时 autocrlf 会统一，diff 正常。heredoc 里的 `\n`、`\\` 转义容易被吃掉：改 TS / 带反斜杠的文本用 Edit 工具，或先把脚本写成文件再跑。
  - 浏览器面板里点英雄网格时，上一次点击的重渲染还没完成就点下一名，可能填进下一个格子（预禁时我方第 2 名填到了对方第 1 格）：每次点完等 0.5 秒再看。
- **全量单元测试约 23 分钟**：别用 `timeout 900` 之类包着跑（B14d1 被它中途杀掉过），放后台跑、等通知。
- **桌面版窗口默认 1280×800**（`tauri.conf.json`），最窄 1100（`App.tsx` 的 `min-w-[1100px]`）：新页面按这两个尺寸核对（浏览器面板 `resize_window`），别只看 1440×900（B14e1 一开始就是只看了大尺寸）。
- **浏览器面板里 radix 下拉框（`Select`）点不中选项**（B14e1，面板隐藏时尤其明显）：按坐标、按元素引用、按键盘都不稳。用脚本派发 `pointerdown` / `pointerup`（`pointerType: "mouse"`）先打开触发器，等 0.4 秒，再对选项派发同样的事件。普通按钮直接 `click()` 就行。
- **底色不均匀的游戏图标**（B14e1 段位图标：模糊立绘 + 渐变 + 图标自己有深色描边）：`cut_icons.py` 默认按颜色差抠会留灰色方块，用 `--grabcut`；放在浅色底上预览一下边缘。
- **很长的 Bash heredoc 会被引号处理弄坏**（B14e1：几百行带 `'''` 的 Python 脚本报 `unexpected EOF while looking for matching`）：长脚本先用 Write 写到会话临时目录再 `python 脚本` 跑。
- **Git Bash 里的 `/c/...` 路径 Windows 的 python 不认**：传给 python 的路径用 `cygpath -w` 转一下（B14a 踩过）。
- **RTA 模型训练的坑**（B14b）：
  - AMD 的 Windows ROCm 版 torch 只有 Python 3.12；`uv python install` 默认装进 AppData，Claude 桌面版（MSIX）会重定向，用户自己的终端找不到 → `setup_rocm_venv.ps1` 把 Python 装在 `engine/.python`。
  - ROCm 进程出异常后、或 Ctrl+C 停下后，退出时可能卡住、杀不掉（`Stop-Process` 报找不到进程，`tasklist` 里还在占 CPU），要关掉跑它的终端标签 / 停掉后台任务才释放；每个新形状的算子第一次要编译，前几步慢。
  - 曲线页正好在读 `status.json` 时，「写临时文件再改名」会被 Windows 拒绝（WinError 5），训练进程整个崩掉 → 已加重试。以后别的地方用这种写法、又有别的进程在读，也要注意。
  - `nn.Module` 的子模块别叫 `type`（会被 `Module.type()` 方法挡住，前向时报「dtype must be a type」）；`Dataset` 类里有 `encode` 方法，类体里的默认参数写 `encode.POSTBAN` 会拿到方法而不是模块。
  - 装了 `--group train` 后，再跑不带它的 `uv sync` 会把 torch 删掉；`uv run --group build` 不会删（不是精确同步）。
  - `F:\e7rta_backend`（用户的另一个项目，和这里无关）有时在用 DirectML 跑训练，会和我们抢 GPU / CPU，测速前先看一眼。
  - 用户终端面板里用户输入过的标签，Claude 不能再往里发命令或关掉它，要新开标签。
