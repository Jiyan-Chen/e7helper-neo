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
`ModuleContext` 提供：`device`、`logger`、`assets_dir`、`data_dir`、`stop_event`、`extras`。后续块只会追加字段（vision、events、storage、data），不会修改已有字段。

**运行规则**（B03 runtime 落实）：同一设备上 TaskModule 互斥；AssistantModule 订阅帧事件，可以和任务并行。

## 新增一个模块
1. 新建 `engine/e7helper/modules/<id>/__init__.py`，继承 `TaskModule` 或 `AssistantModule`，设置 `id`、`name`、`config_model`。
2. 模板和资源放在 `engine/assets/<id>/cn/`，通过 `self.ctx.assets_dir` 访问。
3. 运行 `uv run e7helper modules` 确认已被发现；用 `uv run e7helper run <id> -c '{...}'` 试跑。
4. 外部包也可以注册：在它的 `pyproject.toml` 里声明
   ```toml
   [project.entry-points."e7helper.modules"]
   my_mod = "my_pkg.my_mod"
   ```
   entry-point 可以指向模块类本身，也可以指向包含模块类的 Python 模块。
5. 同名 id 会报 `ModuleRegistryError`。

参考实现：`modules/hello/`。
