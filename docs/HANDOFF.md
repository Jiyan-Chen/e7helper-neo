# HANDOFF

> 新会话从这里读起。上次更新：2026-10-14（B02 已通过）

## 当前进度
- **B01 骨架 + 模块契约 + MuMu 设备层**：✅ 已通过，记录见 [reviews/B01.md](reviews/B01.md)。
- **B02 视觉层 + 模板工具**：✅ 已通过，记录见 [reviews/B02.md](reviews/B02.md)。
- 下一块：**B03 运行时 + 事件总线 + 场景/弹窗**。

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
- 坐标一律是 1600×900 基准，点击前用 `Scaler(*device.resolution).to_device(*m.center)` 换算。
- 模板：`engine/assets/<module_id>/cn/<name>.png` + `.json`。
  - 查找顺序：模块自己的 → `common`。
  - 已有模板：
    - `common`：`back`、`top/skystone`、`top/gold`、`dialog/cancel`、`dialog/confirm`、`lobby/secret_shop`、`lobby/shop`
    - `secret_shop`：`title`、`refresh`、`buy`
- fixtures：`engine/tests/fixtures/`，包括 `lobby`、`secret_shop`、`secret_shop_scrolled`、`secret_shop_refresh_confirm`；期望结果写在 `tests/test_vision_fixtures.py` 的 `EXPECTED` 里。
- CLI：
  - `capture <module> <name>`：弹窗框选，或用 `-f 文件 -r x,y,w,h` 指定
  - `match <module> [names] [-f] [-a]`
  - `ocr [-f] [-r] [--line|--number]`

### 模块与 CLI（B01）
- 模块：继承 `TaskModule` / `AssistantModule`，放到 `e7helper/modules/<id>/` 就会被自动发现。参考 `modules/hello/`。
- CLI：`doctor`、`bench`、`screenshot`、`tap`、`modules`、`run`。`run` 会注入 `vision`。

## 关键决策
- 基准分辨率 1600×900。本机 MuMu 已经是 1600×900（平板模式 tablet.2）。
- IPC 为主、adb 为后备。adb 用 MuMu 自带的 `nx_main\adb.exe`。
- 所有入口必须先调用 `isolate_native_stdout()`（原因见 architecture.md）。
- 依赖安装走华为云镜像。`pyproject.toml` 里已经写了 `[[tool.uv.index]]`，`uv.lock` 也保留镜像 URL（用户确认）。
- `[tool.uv] override-dependencies` 排除了 `opencv-python-headless`。它是 rapidocr 带进来的，会覆盖带 GUI 的 cv2。**不要删这条。**
- 共用模板放 `common`（这个 id 保留），刷商店模块的 id 定为 `secret_shop`。
- fixtures 截图直接进 git，不用 LFS（用户确认）。
- 代码由 git 管理；每块审核通过后由用户确认再提交。

## 下一块（B03）要做
1. `core/runtime`：runner。
   - 同一设备上 task 互斥，支持急停（stop_event）和超时。
   - 卡死检测：连续 N 帧画面不变或场景不变时判定卡死。
   - 失败时把调试截图保存到用户数据目录。
   - CLI `run` 改为经 runtime 调度。
2. 事件总线：帧订阅，供 `AssistantModule.on_frame` 使用，可以和任务并行；日志和状态事件以后给 B08 的 WebSocket 用。
3. `core/scene`：
   - 场景识别：用模板组合判定当前界面，例如大厅 = `lobby/shop` + `lobby/secret_shop`，秘密商店 = `secret_shop/title`。
   - 弹窗处理：识别常见弹窗并自动关闭，`dialog/cancel` / `dialog/confirm` 已有。
   - 需要更多 fixtures（各类弹窗、网络断开、每日登录奖励等），到时告诉用户要切到哪个界面。
4. 点击封装：随机延迟、在命中框内随机偏移；基准坐标 → 设备坐标的换算放在这一层。
5. 在 `ModuleContext` 里追加 events / runtime 相关字段（只增不改）。

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
