# HANDOFF

> 新会话从这里读起。上次更新：2026-10-14（B03 已通过）

## 当前进度
- **B01 骨架 + 模块契约 + MuMu 设备层**：✅ 已通过，记录见 [reviews/B01.md](reviews/B01.md)。
- **B02 视觉层 + 模板工具**：✅ 已通过，记录见 [reviews/B02.md](reviews/B02.md)。
- **B03 运行时 + 事件总线 + 场景/弹窗**：✅ 已通过，记录见 [reviews/B03.md](reviews/B03.md)。
- 下一块：**B04 刷神秘商店**（模块 id `secret_shop`）。

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
    - `common`：`back`、`top/skystone`、`top/gold`、`dialog/cancel`、`dialog/confirm`、`lobby/secret_shop`（带 `tap`）、`lobby/shop`；B03 新增 `title/secret_shop`、`title/shop`、`title/arena`、`title/sanctuary`、`popup/notice`、`popup/network_error`、`popup/network_retry`
    - `secret_shop`：`title`、`refresh`、`buy`
- fixtures：`engine/tests/fixtures/`，包括 `lobby`、`secret_shop`、`secret_shop_scrolled`、`secret_shop_refresh_confirm`；B03 新增 `shop`、`arena`、`arena_notice`、`sanctuary`、`sanctuary_help`、`lobby_exit_confirm`、`lobby_network_error`。模板的期望结果在 `tests/test_vision_fixtures.py`，场景的期望结果在 `tests/test_scene.py`。
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
- 场景判定：`state.is_("secret_shop")` 表示在该场景且没有弹窗。内置场景 `lobby` / `secret_shop` / `shop` / `arena` / `sanctuary`；内置弹窗 `network`（点重试）、`notice`（返回键）、`confirm`（**一律点取消**）、`obscured`（压暗且静止时按返回键兜底）
- 模块注册自己的场景：`self.ctl.scenes.add_scene(Scene(..., ("secret_shop:xxx",)), replace=True)`（限定引用 `module_id:name`）
- `Runtime(device)`：`run_task` / `start_task`（互斥、`timeout`、急停、卡死），失败时调试信息存到 `%LOCALAPPDATA%\e7helper\debug\`；`attach_assistant`（只读设备、帧订阅）
- 事件总线：`self.events`，主题 `frame` / `log` / `task` / `scene` / `assistant`
- 测试：`tests/game_sim.py` 用 fixtures 截图模拟游戏（点到「确认」会进入 DANGER），任务逻辑可以离线测；`tests/test_runtime_live.py` 是真机端到端测试

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

## 下一块（B04 刷神秘商店）要做
1. 新建模块 `engine/e7helper/modules/secret_shop/`（TaskModule，id `secret_shop`，资源已有 `assets/secret_shop/cn/`：`title`、`refresh`、`buy`）。
2. 配置（pydantic）：天空石预算、金币下限、要买的物品（至少书签类：圣约书签 / 神秘奖牌，名称以 OCR 为准）、最多刷新次数、dry-run。
3. 流程：`wait_scene("lobby")` → `tap_until("lobby/secret_shop", "secret_shop")` → 每页识别物品（OCR 商品名列，可能需要新采集物品图标模板）→ 买目标 → 滑到底部再识别 → 刷新 → 循环。
4. 计数与安全：
   - **只有确认成功后才计数**：对比天空石和金币的读数，不按点击次数计；网络重试（`network` 弹窗）会重发原请求，重试后要重新核对。
   - 已购买的物品要跳过（按钮变灰或显示已售）；连续失败 N 次就自己停下；统计结果写到 `data_dir`。
   - 购买和刷新的确认框要在调用 `wait_scene` / `dismiss_popups` **之前**自行点「确认」，否则会被内置的 `confirm` 规则点掉（取消）。
   - 读天空石时先用 `top/skystone` 定位再按偏移读数字：大厅顶栏布局已经和 B02 的 fixture 不同（右移了）。
5. 需要的新 fixtures（购买确认框、已售状态、刷新后的列表等）告诉用户切到哪个界面。**dry-run 测试阶段绝不能点确认刷新或购买**；实跑 3 次刷新必须得到用户明确同意。
6. 验收：dry-run 决策正确（离线用 fixtures + game_sim）；用户同意后实跑 3 次刷新。

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
