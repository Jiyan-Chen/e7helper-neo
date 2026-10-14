# HANDOFF

> 新会话从这里读起。上次更新：2026-10-15（B05 已通过）

## 当前进度
- **B01 骨架 + 模块契约 + MuMu 设备层**：✅ 已通过，记录见 [reviews/B01.md](reviews/B01.md)。
- **B02 视觉层 + 模板工具**：✅ 已通过，记录见 [reviews/B02.md](reviews/B02.md)。
- **B03 运行时 + 事件总线 + 场景/弹窗**：✅ 已通过，记录见 [reviews/B03.md](reviews/B03.md)。
- **B04 刷神秘商店**：✅ 已通过，记录见 [reviews/B04.md](reviews/B04.md)。
- **B05 竞技场 NPC**：✅ 已通过，记录见 [reviews/B05.md](reviews/B05.md)。
- 下一块：**B06 重复刷关 / 讨伐 / 迷宫**。

## 已有能力
### 设备（B01）
- `from e7helper.device import connect; d = connect()`
  - `d.screenshot()`：返回 BGR 帧，IPC 约 10ms
  - `d.tap(x, y)` / `d.swipe(...)`：坐标是设备像素
  - `d.adb.shell(...)`

### 视觉（B02，详见 architecture.md 的“视觉层”一节）
- 模块里用 `self.vision`：
  - `find` / `exists` / `best` / `find_all` / `find_any`
  - `self.vision.ocr.read_number(frame, Rect(...))`、`read_line`、`read_fraction`、`read`
- 坐标一律是 1600×900 基准。任务里点击用 `self.ctl`（B03），它负责换算到设备坐标。
- 模板：`engine/assets/<module_id>/cn/<name>.png` + `.json`。
  - 查找顺序：模块自己的 → `common`。
  - 已有模板：
    - `common`：`back`、`top/skystone`、`top/gold`、`dialog/cancel`、`dialog/confirm`、`lobby/secret_shop`（带 `tap`）、`lobby/shop`；B05 新增 `lobby/arena`、`top/flag`、`arena/mode_arena`；B03 新增 `title/secret_shop`、`title/shop`、`title/arena`、`title/sanctuary`、`popup/notice`、`popup/network_error`、`popup/network_retry`
    - `secret_shop`：`title`、`refresh`、`buy`；B04 新增 `coin`、`dialog/buy_title`、`dialog/buy_ok`、`dialog/refresh_text`、`item/covenant`、`item/mystic`
    - `arena_npc`（B05）：`tab/npc`、`npc/*`、`prep/*`、`battle/*`、`result/*`、`record/*`、`buy/*`，共 21 个
- fixtures：`engine/tests/fixtures/`，包括 `lobby`、`secret_shop`、`secret_shop_scrolled`、`secret_shop_refresh_confirm`；B05 新增 17 张 `arena_*`（模式选择外的竞技场各界面、战斗中、两种结算、补旗框三种状态）；B04 新增 `secret_shop_relist(_scrolled)`、`secret_shop_buy_confirm`、`secret_shop_sold`、`secret_shop_bought_toast`；B03 新增 `shop`、`arena`、`arena_notice`、`sanctuary`、`sanctuary_help`、`lobby_exit_confirm`、`lobby_network_error`。模板的期望结果在 `tests/test_vision_fixtures.py`，场景的期望结果在 `tests/test_scene.py`。
- CLI：
  - `capture <module> <name>`：弹窗框选，或用 `-f 文件 -r x,y,w,h` 指定
  - `match <module> [names] [-f] [-a]`
  - `ocr [-f] [-r] [--line|--number]`

### 运行时 / 场景 / 事件（B03，详见 architecture.md 对应三节）
- 任务模块里用 `self.ctl`（`Controller`），坐标一律 1600×900 基准：
  - 截图与识别：`screenshot` / `find` / `wait(ref)` / `wait_until(probe)` / `detect() → SceneState`
  - 点击：`tap(x, y)` / `tap_rect` / `tap_match(m)` / `tap_template(ref)` / `swipe` / `back()`。自带随机偏移、按压时长和点击后等待；模板 json 设了 `tap` 时点 tap 区域
  - 场景：`wait_scene("lobby")`（途中自动关弹窗，并等画面静止 0.5 秒）；导航用 `tap_until(target, scene)`（会补点，**不要用于刷新/购买**）
  - 弹窗：`dismiss_popups()`；`progress()` 清零卡死计数；`sleep()` 可被急停打断
- 场景判定：`state.is_("secret_shop")` 表示在该场景且没有弹窗。内置场景 `lobby` / `secret_shop` / `shop` / `arena`（B05 起只认模式选择）/ `sanctuary`；内置弹窗 `network`（点重试）、`notice`（返回键）、`confirm`（**一律点取消**）、`obscured`（压暗且静止时按返回键兜底）
- 模块注册自己的场景：`self.ctl.scenes.add_scene(Scene(..., ("secret_shop:xxx",)), replace=True)`（限定引用 `module_id:name`）
- `Runtime(device)`：`run_task` / `start_task`（互斥、`timeout`、急停、卡死），失败时调试信息存到 `%LOCALAPPDATA%\e7helper\debug\`；`attach_assistant`（只读设备、帧订阅）
- 事件总线：`self.events`，主题 `frame` / `log` / `task` / `scene` / `assistant`
- 测试：`tests/game_sim.py` 用 fixtures 截图模拟游戏（点到「确认」会进入 DANGER），任务逻辑可以离线测；`tests/test_runtime_live.py` 是真机端到端测试

### 刷神秘商店 `secret_shop`（B04，详见 architecture.md「已有模块」和 reviews/B04.md）
- `python -m uv run e7helper run secret_shop`：默认 **dry-run**（只滑动、识别、决策）
- 实跑：`-c '{"dry_run": false, "max_refreshes": N, "skystone_budget": M}'`；默认目标是誓约书签（184,000）和神秘奖牌（280,000），按名字或图标识别，并核对价格
- 统计：`%LOCALAPPDATA%\e7helper\modules\secret_shop\history.jsonl`、`stats.json`
- 实测：每页（扫两屏 + 刷新）约 3 秒，一次购买约 2 秒
- 可以复用的做法：
  - 有消耗的操作**按资源读数差确认**，不按点击次数计；
  - 有消耗的确认框注册成本模块弹窗，自动关闭时点取消；
  - 列表类界面用「列表区域停稳」代替整屏静止（`_settle_list`）；
  - 离线测试用 `tests/shop_sim.py` 式的模拟器（点到确认默认进入 DANGER）。

### 竞技场 NPC `arena_npc`（B05，详见 architecture.md「已有模块」和 reviews/B05.md）
- `python -m uv run e7helper run arena_npc`：默认 **dry-run**（导航到准备界面、决定模式后返回）
- 实跑：`-c '{"dry_run": false}'` 打到旗帜用完；加 `"buy_flags": true` 用完后用友情点数补一次（100 换 5 面，每天一次）再打完
- 表单只有 `buy_flags`、`dry_run`；内部字段（`max_battles`、`prefer_quick`、`probe_dialogs` 等）用 `SkipJsonSchema` 隐藏，CLI 仍可传
- 统计：`%LOCALAPPDATA%\e7helper\modules\arena_npc\history.jsonl`、`stats.json`
- 实测：快速对战一场约 7 秒（从点按钮到核对完成），普通战斗约 33 秒
- 可以复用的做法：
  - 普通战斗中的**自动战斗**：图标静止约 0.6 秒 = 没开（开启后一直旋转），点完再观察（`_ensure_auto`）；
  - 战斗中不按返回键（会打开暂停菜单），只有网络异常立即重试；战斗画面在动就 `progress()`；
  - 两个选项的购买框：点购买前核对**哪个选项被选中**（边框亮度），不能只看按钮；
  - 离线测试用 `tests/arena_sim.py`（战斗、结算、自动图标旋转都能模拟）。

### 模块与 CLI（B01，B03 更新）
- 模块：继承 `TaskModule` / `AssistantModule`，放到 `e7helper/modules/<id>/` 就会被自动发现。参考 `modules/hello/`。
- CLI：`doctor`、`bench`、`screenshot`、`tap`、`modules`、`run <id> [-c JSON] [-t 超时]`（经 runtime）、`scene [-f 图片] [--dismiss] [--watch]`、`capture`（新增 `--tap`）、`match`、`ocr`。

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

## 下一块（B06 重复刷关 / 讨伐 / 迷宫）要做
ROADMAP：在游戏自带的重复战斗基础上处理结算、体力不足、背包满，支持次数和体力上限；验收标准是实跑一轮小次数。
1. 先和用户确认范围：先做哪一种（普通关卡 / 讨伐 / 迷宫），从哪个界面开始（建议用户先停在关卡的准备界面，模块只负责开重复战斗和收尾），模块 id 怎么拆。
2. 需要采集的界面（告诉用户切到哪个界面；录屏由用户控制，说「开始」才录、说「好了」就停，录屏做法见 reviews/B05.md「录屏做法」）：
   - 关卡准备界面（重复战斗开关、次数设置、体力消耗）；
   - 重复战斗进行中、重复战斗结束的结算/统计框；
   - 体力不足提示（以及补体力的确认框——**绝不自动补体力用天空石/叶子，除非用户另行同意**）；
   - 背包已满提示。
3. 计数照搬 B04/B05：按资源读数差（体力）和结算确认，不按点击次数计；有消耗的确认框注册成本模块弹窗，自动关闭时点取消。
4. 安全：dry-run 和离线测试阶段绝不点「开始战斗」或任何补体力；实跑之前必须得到用户明确同意。
5. 验收：dry-run 决策正确（离线用 fixtures + 模拟器）；用户同意后实跑一轮小次数。

## 坑
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
