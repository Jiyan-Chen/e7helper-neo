# HANDOFF

> 新会话从这里读起。上次更新：2026-10-19（B11 已通过）

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
- 下一块：**B12 试用打磨（开发版）**（用户意见：先打磨已完成的部分，用户自由使用开发版、反馈问题，我逐条修改）。扩展模块顺延为 B13+，第一项是英雄数据库。

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
    - `common`：`back`、`top/skystone`、`top/gold`、`dialog/cancel`、`dialog/confirm`、`lobby/secret_shop`（带 `tap`）、`lobby/shop`；B05 新增 `lobby/arena`、`top/flag`、`arena/mode_arena`；B06 新增 `lobby/battle`、`title/battle`、`title/prep`、`top/energy`（行动力）、`top/auto_clock`（托管图标表盘）；B03 新增 `title/secret_shop`、`title/shop`、`title/arena`、`title/sanctuary`、`popup/notice`、`popup/network_error`、`popup/network_retry`；B07 新增 `lobby/sanctuary`（带 `tap`）、`lobby/summon`、`top/mail`、`title/mail`、`title/forest`、`title/summon`；B10a 新增 `popup/disconnected`、`popup/tap_close`、`popup/announce_close`、`popup/announce_faq`、`title/start`（游戏标题画面「轻触画面开始」）
    - `secret_shop`：`title`、`refresh`、`buy`；B04 新增 `coin`、`dialog/buy_title`、`dialog/buy_ok`、`dialog/refresh_text`、`item/covenant`、`item/mystic`
    - `arena_npc`（B05）：`tab/npc`、`npc/*`、`prep/*`、`battle/*`、`result/*`、`record/*`、`buy/*`，共 21 个
    - `repeat_battle`（B06）：`menu/hunt`、`hunt/header`、`prep/*`、`auto/*`、`battle/*`、`clear`、`result/*`、`after/*`、`energy/*`，共 27 个
    - `daily`（B07）：`sanctuary/forest`、`forest/*`、`mail/*`、`summon/*`，共 18 个
- fixtures：`engine/tests/fixtures/`（B07 后约 137MB）。B07 新增 35 张 `daily_*`（大厅、圣域白天 / 夜晚、精灵之森各状态和奖励框、邮件列表 / 详情框 / 领取后、召唤页、誓约页 21/21 · 11/21 · 1/21 · 用完 · 带光效、召唤动画、十连结果、单抽结果；期望结果在 `tests/test_daily.py`）。B06 新增 36 张 `rb_*`（讨伐导航、准备界面各状态、托管各框、战斗、CLEAR、结算、战后、行动力不足；期望结果在 `tests/test_repeat_battle.py`）。此前的包括 `lobby`、`secret_shop`、`secret_shop_scrolled`、`secret_shop_refresh_confirm`；B05 新增 17 张 `arena_*`（模式选择外的竞技场各界面、战斗中、两种结算、补旗框三种状态）；B04 新增 `secret_shop_relist(_scrolled)`、`secret_shop_buy_confirm`、`secret_shop_sold`、`secret_shop_bought_toast`；B03 新增 `shop`、`arena`、`arena_notice`、`sanctuary`、`sanctuary_help`、`lobby_exit_confirm`、`lobby_network_error`；B10a 新增 `lobby_disconnected`、`summon_disconnected`、`title_announcement`、`title_connecting`、`title_start`、`title_start_forest`（约 5.9MB）。模板的期望结果在 `tests/test_vision_fixtures.py`，场景的期望结果在 `tests/test_scene.py`。
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

### 重复刷关 `repeat_battle`（B06，详见 architecture.md「已有模块」和 reviews/B06.md）
- 游戏的「重复战斗」已重做成**托管战斗**：准备界面设份数（1 份 = 4 次，行动力或叶子付费），后台按最快通关记录自动打，完成后在托管框「结算」。无记录的关卡开不了。
- `python -m uv run e7helper run repeat_battle`：默认 **dry-run**（导航到 讨伐双足飞龙 地狱级，打开托管设置框核对后关闭，切普通战斗后停下）
- 实跑：`-c '{"dry_run": false, "manual_runs": N}'`。表单字段：`hunt`（飞龙 / 魔像 / 报丧妖）、`tier`（中级 / 上级 / 地狱级）、`start_here`、`auto_battle`、`auto_leaves`、`manual`、`manual_runs`、`refill_leaf` / `max_leaf_refills`、`refill_skystone` / `max_skystone_refills`、`dry_run`；内部字段 `auto_max_units`（托管最多几份，控制实跑规模）、`auto_prefer_energy`、`skystone_keep` 等
- 托管和手动是两个独立开关；只开托管时处理一次就退出（周期性结算重开由 B08 定时调度反复启动模块，用户确认）
- 统计：`%LOCALAPPDATA%\e7helper\modules\repeat_battle\history.jsonl`、`stats.json`
- 实测：手动一场约 2 分钟（地狱级，自动战斗）；托管 1 份约 7 分钟
- 可以复用的做法：
  - 点了弹窗的确认 / 购买 / 关闭后，**等框自己淡出**（`_wait_popup_gone`），不要马上 `wait_scene`；
  - 位置会变的列表（讨伐列表、难度卡片）用 OCR `read` 找整行文字再点；
  - 状态图标的红点要按图标亮度归一化，并用多帧排除转动的光效（`auto_state` + `dots_match`）；
  - 离线测试用 `tests/rb_sim.py`（战后界面一直在动、弹窗淡出、点到「推荐配置」= DANGER）。

### 日常收取 `daily`（B07，详见 architecture.md「已有模块」和 reviews/B07.md）
- `python -m uv run e7helper run daily`：默认 **dry-run**（三项都进去识别，不点领取 / 照料 / 召唤 / 收信）
- 实跑：`-c '{"dry_run": false}'`；表单只有 `mail`、`forest`、`covenant`、`dry_run`；内部字段 `mail_max_hours`（默认 24）、`mail_max_claims`、`covenant_max`、`force`（忽略账本）
- 按天记账：`%LOCALAPPDATA%\e7helper\modules\daily\ledger.json`（游戏日北京时间 3 点切换；誓约当天用完就不进去；精灵之森按最短倒计时记下次时间）；统计 `history.jsonl`、`stats.json`
- 实测：全部三项约 20–35 秒；免费十连约 7–10 秒，单抽约 15 秒（动画不能跳过）
- 可以复用的做法：
  - 「有没有花东西」对比**顶栏货币区域的画面**，前后各两帧、两两都变才算（排除背景光效；见 `page.changed_pixels_all`）；
  - 点了按钮后弹出的确认 / 详情框要核对内容再点（邮件详情框核对剩余时间）；认不出的静止画面就停，不乱点；
  - 一项失败不影响其他项（`ItemFailed`），核对异常立即停止整个任务（`DailyAnomaly`）。
- 离线测试用 `tests/daily_sim.py`（「全部领取」、非第一行领取、不免费的召唤、「再召唤一次」都是 DANGER）。

### API 层（B08，详见 architecture.md「API 层」和 reviews/B08.md）
- `python -m uv run e7helper serve [--port 47800] [--index N] [--no-connect] [--paused] [--no-auth] [--token X] [--allow-host H]`
  - 默认只监听 127.0.0.1；`--port 0` 随机端口；
  - `{pid, url, port, token}` 写进 `<数据目录>/api.json`，正常退出（Ctrl+C / CTRL_BREAK）时删除；
  - 启动后在后台自动连接设备（`--no-connect` 关掉），调度器同时启动。
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
- **页面**：各模块页（通用：说明、计时胶囊、设置自动保存、最近运行、底部开始 / 停止）、计划（列表、新建 / 编辑、推荐计划、总开关）、运行记录、统计、日志、设置（模拟器连接 / 切换实例）、模板采集（开发版）。外壳：顶栏（模拟器、当前画面、下个计划、停止）、左侧菜单、右侧「实时画面 + 动态」。
- **模块界面扩展**：`src/modules/<id>/index.tsx` 默认导出 `ModuleUI`，自动收集（图标、菜单名、字段图标 / 依赖 / 开发版字段、统计项中文名、推荐计划、`RunExtra`、`Header`、`onConfigSaved`）。daily 的「持续收菜」是 `RunExtra`；repeat_battle 推荐「托管自动结算」计划。
- **样式**：游戏风（原型 `docs/prototypes/b09/d-epic.html`，用户选定），主题和组件类在 `src/index.css`；背景是压暗的圣域图 `src/assets/bg_sanctuary.jpg`。
- **引擎新增**：`POST /api/shutdown`；`/api/capture/*` 模板采集接口（`api/capture.py`）；各模块配置字段补了中文 `title`。
- 测试：前端 `src/lib/*.test.ts`（vitest）；引擎 `tests/test_capture_api.py`。全量 `705 passed, 7 skipped`。
- 实测：拉起引擎 2.8–5.8 秒；经 GUI 跑 daily 演练 12.4 秒，中途停止立即生效；关闭应用时引擎正常退出并删除 api.json。

### 打包（B10，详见 architecture.md「打包发布」和 reviews/B10.md）
- `cd engine && python -m uv run --group build python packaging/build.py`：检查 5 处版本号 → PyInstaller onedir → 冒烟测试（不碰设备）。产物 `engine/dist/e7engine/` 约 272MB、352 个文件。
- `cd app && pnpm bundle`（= `tauri build --config src-tauri/tauri.bundle.conf.json`）：安装包 `app/src-tauri/target/release/bundle/nsis/第七史诗助手_0.1.0_x64-setup.exe`，约 96MB。
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

### 模块与 CLI（B01，B03 / B08 更新）
- 模块：继承 `TaskModule` / `AssistantModule`，放到 `e7helper/modules/<id>/` 就会被自动发现。参考 `modules/hello/`。
- CLI：`doctor`、`bench`、`screenshot`、`tap`、`modules`、`run <id> [-c JSON] [-t 超时]`（经 runtime）、`scene [-f 图片] [--dismiss] [--watch]`、`capture`（新增 `--tap`）、`match`、`ocr`、`serve`（B08）。

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

## 下一块（B12 试用打磨）要做
用户意见（2026-10-19）：B13 之前先 fine tune 已完成的部分。用户自由使用**开发版**，有问题反馈给我修改。
- **怎么用开发版**（主工作区 `F:\e7helper-neo`，main 上）：
  - 第一次：`cd engine && python -m uv sync`；`cd app && pnpm install`；
  - 启动：`cd app && pnpm tauri dev`（没有在运行的引擎时自己拉起 venv 引擎，连 MuMu；数据目录是真实的 `%LOCALAPPDATA%\e7helper`）；
  - 开发版有演练开关（内置功能默认演练，切实跑要确认）、内置模板采集、示例模块；自定义流程没有演练，会真的点击。
- **这一块的工作方式**（和以往的块不同，是一个持续的反馈循环）：
  1. 开工时在 ROADMAP 把 B12 标为进行中，建 `docs/reviews/B12.md`，里面按「反馈 N」逐条记：用户原话 → 原因 → 修改（文件）→ 验证（测试 / 截图 / 实测输出）。
  2. 每条反馈先复现、定位再改；改完跑相关测试（必要时全量 `pytest` / `pnpm test` / `pnpm typecheck`），告诉用户怎么验证（开发版大多热更新；改了引擎要重启 `pnpm tauri dev` 或重启引擎）。
  3. 需要我自己操作真机复现时先征得同意，只做不消耗资源的操作；用户自己操作时看日志、`debug/` 目录里的调试截图、`tasks.jsonl` 定位。
  4. 一条反馈可能牵出新的弹窗 / 场景 / 模板：按 B10a 的方式采 fixture、写离线测试。
  5. 不加新模块、不扩大范围；用户提的新功能先记进审核记录的「新需求」，问用户要不要现在做还是排进后面的块。
  6. 用户宣布打磨结束时：ROADMAP 改「待审核」→ 审核通过后照常收尾。改动较多时结束前重新打包，按 B10 / B11 的方法在本机模拟干净环境验证一次。
- 定位问题常用的东西：`%LOCALAPPDATA%\e7helper\logs\engine-stdout.log`、`debug\<时间>_<模块>_<状态>\`（last_frame.png / screen.png / log.txt）、`tasks.jsonl`、各模块 `history.jsonl`；GUI 的「日志」页；CLI `e7helper scene -f 图片`、`match`。

## 之后（B13 英雄数据库）要做（B12 结束后再开始）
ROADMAP「B13+ 扩展模块」：英雄数据库（core/data）→ RTA BP 助手（assistant）→ 装备扫描 → GVG 作业查询 → 兑换码 → 资源统计，每个单独立项和审核。B13 先做英雄数据库，它是后面 RTA BP 助手的基础。
1. **先和用户确认**：
   - 数据来源（官方指南站 / epic7db / Fribbels 的 `herodata.json` 等，B10 找图标时用过）、更新方式（随包内置 + 联网更新？）、许可和版权；
   - 存哪些字段（中文名 / 英文名 / 编号 `c2111` 这类 id / 属性 / 职业 / 星级 / 头像 / 技能 / 套装推荐…），国服中文名怎么对上；
   - 存储位置和格式（随包放 `engine/assets/data/`？用户数据目录放更新后的版本？sqlite 还是 json）；
   - GUI 要不要有「英雄图鉴」页，还是只作为 RTA BP 助手的底层数据；
   - 头像要不要用于识别（BP 界面认英雄），要不要现在就做识别。
2. 放在 `core/data`（architecture.md 顶部的分层图里预留的位置），不依赖设备；接口要能被助手模块（只读帧）使用。
3. 不操作游戏的部分优先做；要读游戏界面时先征得用户同意，只截图、不点击。

## 坑
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

