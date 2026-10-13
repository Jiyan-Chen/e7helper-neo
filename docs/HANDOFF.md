# HANDOFF

> 新会话从这里读起。上次更新：2026-10-13（B01 已通过）

## 当前进度
- **B01 骨架 + 模块契约 + MuMu 设备层**：✅ 已通过，记录见 [reviews/B01.md](reviews/B01.md)。
- 下一块：**B02 视觉层 + 模板工具**。

## 已有能力（B01）
- 连接设备：`from e7helper.device import connect; d = connect()`
  - `d.screenshot()` 返回 BGR 帧，IPC 约 10ms
  - `d.tap(x, y)` / `d.swipe(...)`
  - `d.adb.shell(...)`
- 模块：继承 `TaskModule` / `AssistantModule`，放到 `e7helper/modules/<id>/` 就会被自动发现。参考 `modules/hello/`。
- CLI：`doctor`、`bench`、`screenshot`、`tap`、`modules`、`run`。

## 关键决策
- 基准分辨率 1600×900。本机 MuMu 已经是 1600×900（平板模式 tablet.2）。
- IPC 为主、adb 为后备。adb 用 MuMu 自带的 `nx_main\adb.exe`。
- 所有入口必须先调用 `isolate_native_stdout()`（原因见 architecture.md）。
- 依赖安装走华为云镜像（`UV_DEFAULT_INDEX`），`uv.lock` 保留镜像 URL（用户确认）。
- 代码由 git 管理；每块审核通过后由用户确认再提交。

## 下一块（B02）要做
1. `core/vision/matcher.py`：模板匹配。
   - 支持 `TM_CCOEFF_NORMED`、region 限定、按 `Scaler` 缩放（模板以 1600×900 为基准）、多目标 + NMS、阈值。
2. `core/vision/template_store.py`：模板以 `assets/<module_id>/cn/<name>.png` + 同名 `.json` 的形式存放（字段：`ref_size`、`region`、`threshold`、`note`），按模块加载。
3. `core/vision/ocr.py`：RapidOCR（onnxruntime），重点是天空石、金币、体力等数字，以及简中短文本。
4. CLI `capture`：截图后框选区域（OpenCV 窗口 `selectROI`），保存模板，并立即回验匹配分数。
5. `tests/fixtures/`：收集真实游戏截图（需要用户把游戏打开到主界面、商店等页面）。
6. 在 `ModuleContext` 里追加 `vision` 字段（只增不改）。

注意：安装 rapidocr / onnxruntime 时要带上 `UV_DEFAULT_INDEX`，否则会非常慢。

## 坑
- `wm size` 返回的是竖屏 900x1600，不要用它判断分辨率；用 `device.resolution`（来自 IPC）。
- `cv2.imwrite` 不支持中文路径，用 `cv2.imencode` + `write_bytes`。
- 测试点击要避开桌面图标。(800,450) 是 KernelSU 图标的位置。
- uv 不在 PATH 上，用 `python -m uv`。
