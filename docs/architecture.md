# 架构

```
  ┌──────────── app/ (Tauri + React，B09) ─────────────┐
  │ 外壳：设备栏/日志/设置   模块页面注册表(按 module id 挂载) │
  └───────────────▲ REST + WebSocket（B08）────────────┘
  ┌───────────────┴──── engine/ (Python) ─────────────────┐
  │ api/      核心路由 + 各模块自注册的子路由与 WS 频道           │
  │ modules/  hello(示例) automation…(B04+) rta_draft…(B11+)   │
  │ core/     geometry paths log | runtime events vision scene  │
  │           data storage（B02+ 逐步加入）                       │
  │ device/   MuMuManager + nemu IPC(主) + adb(后备)             │
  └──────────────────────────────────────────────────────┘
```

依赖方向只能自上而下：`modules → core → device`，device 不依赖任何上层。

## 设备层 `e7helper.device`
| 文件 | 职责 |
|---|---|
| `base.py` | `Device` 抽象：`name` / `resolution` / `screenshot()` / `tap()` / `swipe()` / `close()` |
| `mumu_manager.py` | `find_install()` 按 参数 → `E7_MUMU_ROOT` → 注册表 → 常见路径 的顺序查找安装目录；兼容 `nx_main\` 与 `shell\` 两种结构。`MuMuManager` 封装 `info` / `launch` / `shutdown` / `app launch` |
| `nemu_ipc.py` | `external_renderer_ipc.dll` 的 ctypes 封装：截图（RGBA 且上下颠倒，转成 BGR）、touch down/up/swipe |
| `adb.py` | 后备通道，直接调用 MuMu 自带的 adb.exe：`exec-out screencap -p`、`input tap/swipe`、`pm list packages` |
| `mumu_device.py` | `MuMuDevice` 组合 IPC 与 adb；`Backend.AUTO` 优先 IPC，失败时回退 adb；`connect(index)` 是统一入口 |

坐标为设备原生像素。与 1600×900 基准的换算用 `core.geometry.Scaler`；B02 起由 vision 层统一处理。

**原生输出隔离**：IPC DLL 静态链接了 CRT，会把调试信息写到原生 stdout（连接时）和 stderr（每次触控都写），而且是缓冲后再写，外部无法拦截。任何进程入口（CLI、以后的 API 服务）都必须先调用 `core.stdio.isolate_native_stdout()`，它会做三件事：
- 把 fd 1/2 和 Win32 标准句柄永久指向 NUL；
- 让 Python 的 `sys.stdout` / `sys.stderr` 改写到复制出来的原句柄（控制台下用 `_WindowsConsoleIO`，避免 GBK 代码页乱码）；
- Rich 的 Console 必须用 `core.log.make_console()` 创建（`legacy_windows=False`）。

## 模块契约 `e7helper.modules`
```python
class Module(ABC):
    id: ClassVar[str]                     # 全局唯一
    name: ClassVar[str]
    kind: ClassVar[ModuleKind]            # task | assistant
    description: ClassVar[str] = ""
    config_model: ClassVar[type[BaseModel]] = EmptyConfig
    def __init__(self, ctx: ModuleContext, config=None)  # 实例化后调用 setup()
    def setup(self) -> None               # 钩子：加载模板/数据
    @classmethod config_schema() -> dict  # JSON Schema，前端用来自动生成表单
    @classmethod routes() -> APIRouter | None  # 可选，B08 挂载到 /api/modules/<id>/

class TaskModule(Module):      def run(self) -> None              # 会操作游戏；应轮询 self.stopped
class AssistantModule(Module): def on_frame(self, frame) -> None  # 只读帧，不得点击
```
`ModuleContext` 提供：`device`、`logger`、`assets_dir`、`data_dir`、`stop_event`、`extras`、`vision`（B02）。后续块只会追加字段（events、storage、data），不会修改已有字段。模块里用 `self.vision` 取视觉层（未设置时报错）。

**运行规则**（B03 runtime 落实）：同一设备上 TaskModule 互斥；AssistantModule 订阅帧事件，可以和任务并行。

## 视觉层 `e7helper.core.vision`（B02）
| 文件 | 职责 |
|---|---|
| `matcher.py` | `TM_CCOEFF_NORMED` 模板匹配：`find` / `find_all`（多目标 + NMS）/ `best_match`（不设阈值，调试用）。模板按帧宽缩放后在检索区域内匹配，结果统一是基准坐标的 `Match(name, score, rect, scale, diff)` |
| `template_store.py` | `TemplateStore`：`<name>.png` + 同名 `.json`，name 可带子目录；`TemplateMeta` 字段见文件头注释 |
| `ocr.py` | RapidOCR 封装：`read`（检测+识别，约 0.6–1s）、`read_line` / `read_number` / `read_fraction`（只识别，约 10ms）；`parse_number`、`normalize_text` |
| `__init__.py` | `Vision` 门面：按顺序在多个 store 里找模板（模块自己的 → `common`），共享一个 OCR 实例 |

约定：
- 所有区域、坐标都是 1600×900 基准。点击前用 `Scaler(*device.resolution).to_device(*match.center)` 换算。
- 跨模块共用的界面模板（返回键、顶栏图标、通用弹窗按钮、大厅入口）放在 `assets/common/cn/`，`common` 这个 id 保留，不要给模块用。
- **相关系数对亮度/对比度不敏感**：被弹窗遮罩压暗的按钮也能得 1.0 分。需要点击的按钮应在 json 里设 `max_diff`（平均像素差上限，实测正常 ≤ 9、压暗 ≥ 60，一般取 30）。
- 文字比对先过 `normalize_text`（OCR 对全角/半角标点不稳定）。
- `rapidocr` 导入要 3–5 秒，所以 OCR 引擎在第一次使用时才加载；需要即时响应的场合先调 `ocr.warmup()`。

模板采集流程：
```
python -m uv run e7helper capture <module_id> <name>          # 截图并弹窗框选（回车确认，c/Esc 取消）
python -m uv run e7helper capture <module_id> <name> -f x.png -r x,y,w,h [-s 检索区域 | --full] [--max-diff 30]
python -m uv run e7helper match <module_id> [name...] [-f x.png] [-a]   # 测试分数与 diff
python -m uv run e7helper ocr [-f x.png] [-r x,y,w,h] [--line | --number]
```
`capture` 保存后会立即回验：报告原位置分数，以及检索区域内其他位置的最高分（高于阈值时会给出警告）。

## 新增一个模块
1. 新建 `engine/e7helper/modules/<id>/__init__.py`，继承 `TaskModule` 或 `AssistantModule`，设置 `id`、`name`、`config_model`。
2. 模板和资源放在 `engine/assets/<id>/cn/`，通过 `self.ctx.assets_dir` 访问；模板用 `e7helper capture <id> <name>` 采集，代码里用 `self.vision.find(frame, name)`。
3. 运行 `uv run e7helper modules` 确认已被发现；用 `uv run e7helper run <id> -c '{...}'` 试跑。
4. 外部包也可以注册：在它的 `pyproject.toml` 里声明
   ```toml
   [project.entry-points."e7helper.modules"]
   my_mod = "my_pkg.my_mod"
   ```
   entry-point 可以指向模块类本身，也可以指向包含模块类的 Python 模块。
5. 同名 id 会报 `ModuleRegistryError`。

参考实现：`modules/hello/`。
