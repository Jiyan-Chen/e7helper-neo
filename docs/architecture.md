# 架构

```
  ┌──────────── app/ (Tauri + React，B09) ─────────────┐
  │ 外壳：顶栏/菜单/画面+动态   模块界面扩展(按 module id 挂载) │
  └───────────────▲ REST + WebSocket（B08）────────────┘
  ┌───────────────┴──── engine/ (Python) ─────────────────┐
  │ api/      核心路由 + 各模块自注册的子路由与 WS 频道           │
  │ modules/  hello(示例) automation…(B04+) rta_draft…(B13+)   │
  │ core/     geometry paths log | runtime events vision scene  │
  │           data storage（B02+ 逐步加入）                       │
  │ device/   MuMuManager + nemu IPC(主) + adb(后备)             │
  └──────────────────────────────────────────────────────┘
```

依赖方向只能自上而下：`modules → core → device`，device 不依赖任何上层。
唯一的例外是 `core.runtime`：它是模块的调度器，需要引用模块契约 `modules.base`（只引用契约，不引用任何具体模块）。

## 设备层 `e7helper.device`
| 文件 | 职责 |
|---|---|
| `base.py` | `Device` 抽象：`name` / `resolution` / `screenshot()` / `tap()` / `swipe()` / `back()`（B03，Android 返回键，默认不支持）/ `close()` |
| `mumu_manager.py` | `find_install()` 按 参数 → `E7_MUMU_ROOT` → 注册表 → 常见路径 的顺序查找安装目录；兼容 `nx_main\` 与 `shell\` 两种结构。`MuMuManager` 封装 `info` / `launch` / `shutdown` / `app launch` |
| `nemu_ipc.py` | `external_renderer_ipc.dll` 的 ctypes 封装：截图（RGBA 且上下颠倒，转成 BGR）、touch down/up/swipe |
| `adb.py` | 后备通道，直接调用 MuMu 自带的 adb.exe：`exec-out screencap -p`、`input tap/swipe`、`pm list packages` |
| `mumu_device.py` | `MuMuDevice` 组合 IPC 与 adb；`Backend.AUTO` 优先 IPC，失败时回退 adb；`back()` 走 adb `input keyevent 4`；`connect(index)` 是统一入口 |

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
    @classmethod timers(data_dir) -> list[ModuleTimer]  # 可选（B08）：GUI 显示的倒计时
    @classmethod make_vision() -> Vision  # 可选（B11）：任务的识别器，默认 本模块 → common；custom_flow 改成只查玩家模板

class TaskModule(Module):      def run(self) -> None              # 会操作游戏；用 self.ctl 操作
    @classmethod next_due(config, data_dir, last_success) -> datetime | None  # 可选（B08）：「按模块时间」调度
class AssistantModule(Module): def on_frame(self, frame) -> None  # 只读帧，不得点击
```
`ModuleContext` 提供：`device`、`logger`、`assets_dir`、`data_dir`、`stop_event`、`extras`、`vision`（B02）、`events`、`controller`（B03）。后续块只会追加字段（storage、data），不会修改已有字段。模块里用 `self.vision` / `self.ctl` / `self.events` 取对应能力（未设置时报错）。

**运行规则**（B03 runtime 落实）：同一设备上 TaskModule 互斥；AssistantModule 订阅帧事件，可以和任务并行；助手拿到的 `device` 是只读代理，tap / swipe / back 会抛 `DeviceError`。

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
- **识别区域 ≠ 可点区域**时，在 json 里设 `tap: [x, y, w, h]`（与 `box` 同时刻的基准坐标；`capture --tap`）。`ctl.tap_match` / `tap_template` 会点 tap 区域，并按命中位置平移。例：大厅「秘密商店」识别的是文字，可点的是上方图标，文字下半部分点了没反应。
- `rapidocr` 导入要 3–5 秒，所以 OCR 引擎在第一次使用时才加载；需要即时响应的场合先调 `ocr.warmup()`。

模板采集流程：
```
python -m uv run e7helper capture <module_id> <name>          # 截图并弹窗框选（回车确认，c/Esc 取消）
python -m uv run e7helper capture <module_id> <name> -f x.png -r x,y,w,h [-s 检索区域 | --full] [--max-diff 30]
python -m uv run e7helper match <module_id> [name...] [-f x.png] [-a]   # 测试分数与 diff
python -m uv run e7helper ocr [-f x.png] [-r x,y,w,h] [--line | --number]
```
`capture` 保存后会立即回验：报告原位置分数，以及检索区域内其他位置的最高分（高于阈值时会给出警告）。

## 事件总线 `e7helper.core.events`（B03）
进程内发布/订阅。`EventBus.subscribe(topic, callback, threaded=False, maxsize=1)`，`*` 订阅全部主题。
- 同步订阅在发布者线程里直接调用；`threaded=True` 时在独立线程里处理，队列满时丢最旧的（帧用 maxsize=1，只看最新帧）。
- 订阅者抛异常只记日志，不影响发布者和其他订阅者。
- 内置主题 `Topic`：`frame`（BGR 帧）、`log`（`LogBridge` 把 logging 记录转成事件）、`task`（任务开始/结束）、`scene`（场景变化）、`assistant`（助手挂载/卸下）；B08 新增 `device`（连接状态）、`schedule`（计划触发 / 排队 / 跳过 / 停用）、`stats`（任务结束，该模块的统计可能变了）。API 的 WebSocket 转发除 `frame` 以外的全部主题。

## 场景与弹窗 `e7helper.core.scene`（B03）
| 文件 | 职责 |
|---|---|
| `model.py` | `Scene(name, all_of, none_of)`；`Popup(name, all_of, dismiss, none_of, text, text_region, auto, reload)`；关闭方式 `Dismiss.tap(模板) / at(x, y) / back() / none()` |
| `detector.py` | `SceneDetector.detect(frame) → SceneState(scene, popup, obscured, matches)`，一帧约 20–35ms |
| `builtin.py` | 内置场景（lobby / secret_shop / shop / arena（只认模式选择）/ sanctuary）和弹窗（disconnected / announcement / title_start / network / notice / confirm） |

判定顺序：弹窗 → 场景 → 遮罩。**只有 `state.clear`（没有弹窗）时 `scene` 才是可操作的界面**，用 `state.is_("lobby")` 判断。
- 相关系数对亮度不敏感，弹窗遮罩下的场景模板照样命中，所以必须先认弹窗。
- 遮罩检测（兜底未知弹窗）：场景锚点或探针模板（默认 `back`）命中位置的亮度（98 分位灰度）不到模板自身的 0.6 倍，就报告 `popup = "obscured"`，用返回键关闭。不用 diff 判断：白色图标在亮背景（圣域天空）上 diff 也有 30+。
  界面切换的淡入淡出也会让画面短暂变暗，所以 `Controller.dismiss_popups` 关闭 `obscured` 前会复核：画面压暗**且静止** 0.5 秒才算，在动就继续等。
- 内置弹窗的处理：`disconnected`（与服务器的连接中断）点「点击关闭」，`announcement`（登录公告窗）点右上角 X，`title_start`（标题画面）点「轻触画面开始」这行字——三者组成**断线自动重进**（B10a，见下条）；`network`（网络连接异常）点「点击重试」；`notice`（通知面板）按返回键；`confirm`（取消/确认 二次确认框）**一律点取消**。任务自己打开的确认框，必须在调用 `dismiss_popups` / `wait_scene` 之前自行处理。
- **断线自动重进（B10a）**：`reload=True` 的弹窗关闭后游戏要加载一段时间，`dismiss_popups` 会一直等（期间清零卡死计数，上限 `RELOAD_TIMEOUT` = 120 秒，超时抛 `PopupError`），直到认出场景或出现下一个弹窗。实测流程：断线框 → 公告窗 → 标题「连接中」约 15 秒 → 轻触画面开始 → 黑屏约 16 秒 → 大厅。重进游戏只需要点屏幕，不输入账号；协议勾选框保持游戏记住的状态，不去点协议链接。
  - `ctl.reloads` 记录重进次数。`wait_scene` / `tap_until` 等待途中发生重进时重新计时；`tap_until` 重进后回到点击前的场景（通常是大厅）会照常补点。
  - 重进后游戏停在大厅，**任务之前的界面状态已丢失**：任务在别的界面里等待时会超时失败（游戏本身已恢复，下次运行正常）。只有点导航（`tap_until`）的那一步能自动接上。
- 按钮相同的弹窗可以用 `text` + `text_region` 加 OCR 文字条件区分（比较慢，只在模板都命中后才做）。
- 模块注册自己的场景：在 `setup()` 里 `self.ctl.scenes.add_scene(Scene("xxx", ("<module_id>:title",)), replace=True)`。识别器由 Runtime 共享，每次启动任务都会调用 setup，所以要用 `replace=True`。模板用限定引用 `<module_id>:<name>`，它由 `Vision.template` 解析到该模块的模板目录。
- 场景标题模板统一放在 `common/title/*`，弹窗模板放在 `common/popup/*`。

## 运行时 `e7helper.core.runtime`（B03）
| 文件 | 职责 |
|---|---|
| `runner.py` | `Runtime(device)`：`start_task` / `run_task`（互斥、急停、超时、卡死、失败时保存调试信息）、`attach_assistant` / `detach_assistant`（帧订阅 + 帧泵）、`make_controller`（CLI 调试用） |
| `controller.py` | `Controller`（模块里的 `self.ctl`）：基准坐标点击、截图、等待、场景/弹窗、急停检查 |
| `humanize.py` | `Humanize`：命中框内截断正态取点、坐标抖动、随机按压时长、点击后随机等待；`Humanize.off()` 用于测试 |
| `stuck.py` | `StuckDetector`：画面静止 N 帧且 T 秒，或同一场景 N 次且 T 秒，判定卡死 |
| `device.py` | `SharedDevice`（加锁，任务线程和帧泵共用设备）、`ReadOnlyDevice`（给助手） |
| `errors.py` | `TaskStatus`；`TaskAborted`（`TaskStopped` / `TaskTimeout` / `TaskStuck`）；`RuntimeBusy`、`WaitTimeout`、`PopupError`；`TaskFailed`（B11：模块主动判定的失败，只记消息、不带调用栈） |

任务的写法：
```python
class MyTask(TaskModule):
    def run(self):
        ctl = self.ctl
        ctl.wait_scene("lobby")                         # 等到大厅（途中自动关闭弹窗、等淡入结束）
        ctl.tap_until("lobby/secret_shop", "secret_shop")  # 导航：点击直到进入目标场景
        m = ctl.wait("refresh", timeout=5)               # 等模板出现（先找本模块的，再找 common）
        ctl.tap_match(m)                                # 在命中框内随机取点点击
        ...
        ctl.progress()                                  # 取得进展时清零卡死计数
```
要点：
- `Controller` 的坐标一律是 1600×900 基准，换算到设备坐标在这一层完成。每次截图、点击、sleep 前都会检查急停、超时和卡死。
- `TaskAborted` 继承 `BaseException`，模块里的 `except Exception` 不会吞掉急停。模块不要捕获它。
- 只轮询 `self.stopped`、不用 `ctl` 的模块也能被急停/超时（返回后状态按急停原因记）。
- **界面稳定后再点**：切换界面有淡入、列表飞入等动画，标题出现后 1–2 秒内的点击会被游戏忽略（实测进秘密商店：0.6 秒认出标题，1.7 秒画面静止，2 秒后才响应返回）。`wait_scene` 默认 `settle=True`：认出场景后，还要连续截图的画面变化 < 5（160×90 灰度均差）并持续 0.5 秒才返回。待机动画的变化 ≤ 3.8，不受影响。
- 导航用 `tap_until(target, scene)`：点击后等目标场景（途中自动关闭弹窗，如网络异常重试）；`retry_after` 秒后仍停在原场景、没有弹窗，就补点一次，最多 3 次；画面已经变了就不再补点。**刷新、购买等有消耗的操作不要用 `tap_until`。** 目标界面一直有动画（例如战后界面的战斗场景背景）时传 `settle=False`（B06）。
- 点了弹窗里的确认 / 购买 / 关闭之后，**不要马上 `wait_scene`**：框淡出期间仍会被认成弹窗，弹窗规则会再点一次（取消或空白处）。先等它自己消失（参考 `repeat_battle._wait_popup_gone`）。
- 失败 / 超时 / 卡死时，调试信息保存在 `<数据目录>/debug/<时间>_<模块>_<状态>/`：`last_frame.png`（任务最后一帧）、`screen.png`（当前画面）、`info.json`、`error.txt`、`log.txt`（最近 300 条日志）。用户急停不保存。
- 一台设备在进程内只能有一个 `Runtime`。
- `dismiss_popups(only=名字集合)`（B11）：只关闭指定的弹窗，遇到别的弹窗或遮罩直接返回、不按返回键兜底。自定义流程用它只处理断线重进、网络重试和确认框。

CLI：
```
python -m uv run e7helper run <id> [-c JSON] [-t 超时秒] [-d 助手运行秒]   # 经 runtime 运行
python -m uv run e7helper scene [-f 图片 ...] [--dismiss] [--watch]        # 识别场景/弹窗、关闭弹窗、持续观察
```

## API 层 `e7helper.api`（B08）
```
python -m uv run e7helper serve [--port 47800] [--index N] [--no-connect] [--paused] [--no-auth] [--token X] [--allow-host H]
```
| 文件 | 职责 |
|---|---|
| `engine.py` | `Engine`：与 HTTP 无关的后台状态。设备连接 / 断开（自己持有 `EventBus` 和 `LogBridge`，设备重连不丢订阅）、`Runtime`（`bridge_logs=False`）、启停任务（记录来源，结束后写 `tasks.jsonl` 并发布 `stats`）、保存的模块配置、统计 / 计时读取、日志缓存（2000 条）。错误统一抛 `ApiError(status, code, message)` |
| `scheduler.py` | `Scheduler`：计划的增删改查和触发（见下文），一个后台线程每秒 `tick()` |
| `auth.py` | 随机 token（`Authorization: Bearer` 或 `?token=`）、Host 头校验中间件、日志里的 `token=` 打码 |
| `ws.py` | `/ws` 控制 + 事件频道，`/ws/frames` 帧频道 |
| `app.py` | `create_app(engine, token=...)`：核心路由、模块子路由挂载、CORS、lifespan（启动时后台自动连接设备、启动调度器；退出时急停任务、关设备） |

- **启动**：`serve` 先绑定端口（`--port 0` 随机），把 `{pid, url, port, token}` 写进 `<数据目录>/api.json`（正常退出时删除），再启动 uvicorn。默认只监听 127.0.0.1。
- **鉴权**：除 `GET /api/health`、`/docs`、`/openapi.json` 外都要 token。Host 头必须是 localhost / 127.0.0.1 / ::1（或 `--allow-host` 指定的），防 DNS rebinding。WebSocket 不受 CORS 限制，所以 token 是必须的。
- **错误格式**：`{"error": {"code": "...", "message": "...", "detail": ...}}`。常见：404 `unknown_module` / `unknown_schedule`，409 `busy`（有任务在跑 / 不能断开），422 `invalid_config`（`detail` 是 pydantic 的错误列表），503 `no_device`。请求体本身的校验错误是 FastAPI 默认的 422 格式。

### 核心路由（前缀 `/api`）
| 路由 | 说明 |
|---|---|
| `GET /health` | 不需要 token |
| `GET /status` | 设备、当前任务、助手、调度器概况（和 WS 的 hello 相同） |
| `GET /logs?limit&level&since` | 最近的日志 |
| `GET /device`、`POST /device/connect {index?}`、`POST /device/disconnect`、`GET /device/instances` | 设备状态 / 连接 / 断开（有任务时 409）/ MuMu 实例列表 |
| `GET /device/screenshot?format=png\|jpeg&scale&quality`、`GET /scene` | 只读：截图、识别当前场景和弹窗（不关弹窗） |
| `GET /modules`、`GET /modules/{id}` | 模块列表；单个模块含 `config_schema` 和保存的配置 |
| `GET/PUT /modules/{id}/config` | 保存的配置（`modules/<id>/config.json`，整体替换、补全默认值） |
| `GET /modules/{id}/stats?limit`、`GET /modules/{id}/timers` | `stats.json` + `history.jsonl` 最近 N 行；模块计时 |
| `POST /tasks {module, config?, timeout?}` → 202 | 不给 config 用保存的配置；有任务在跑 409 |
| `GET /tasks/current`、`POST /tasks/stop`、`GET /tasks/history?limit&module` | 当前任务 / 急停 / 记录（新的在前） |
| `GET /assistants`、`POST /assistants/{id}`、`DELETE /assistants/{id}` | 助手模块挂载 / 卸下 |
| `GET/POST /schedules`、`GET/PATCH/DELETE /schedules/{id}`、`POST /schedules/{id}/run`、`PUT /scheduler {paused}` | 定时调度 |
| `POST /shutdown` → 202（B09） | 关闭服务（GUI 退出时关掉自己拉起的引擎）；只有 `serve` 起的服务支持，其他 501 |
| `/capture/...`（B09，开发工具） | 模板采集，见下文 |
| `/flows/...`、`/user-templates/...`（B11） | 自定义流程和玩家模板，见下文 |

**模块子路由**：`Module.routes()` 返回的路由挂到 `/api/modules/<id>/`，同样要 token。第一段路径不能是 `config` / `stats` / `timers` 或路径参数，否则启动时报 `ModuleRegistryError`。fastapi 在 `routes()` 里再导入。已有：`GET /api/modules/daily/ledger`。

### WebSocket
- `/ws?token=`：连上后先收到 `{"type":"hello","data":<status>}`。请求 `{"id", "op", ...}`，每个都有回复 `{"type":"reply","id","ok","data"|"error"}`：
  - `ping`、`status`
  - `subscribe {topics, log_level?}` / `unsubscribe {topics?}`：默认什么都不订阅，`*` = 除帧以外全部
  - `start_task {module, config?, timeout?}`、`stop_task`
  - `run_schedule {schedule}`、`pause_scheduler`、`resume_scheduler`

  事件格式：`{"type":"event","topic","time","data"}`。每个客户端的事件队列 1000 条，满了丢最旧的；回复单独排队，不丢。
- `/ws/frames?token=&fps=2&scale=0.5&quality=70`：二进制 JPEG。有任务时转发任务截图（节流）；任务 1 秒没截图或空闲时自己截图（只读）。设备没连上时每秒发一条文本 `{"type":"status","connected":false}`。

### 定时调度
计划 = 用户部分 `ScheduleSpec`（`module`、`name`、`enabled`、`trigger`、`config`、`timeout`、`on_busy`、`max_wait_minutes`）+ 调度器维护的 `state`（`next_run`、`last_*`、`failures`、`queued_since`、`running_task`），存在 `<数据目录>/schedules.json`。
- 触发方式：
  - `{"type":"interval","minutes":30}`：新建 / 重新启用后立即跑，之后从上次**结束**算起；
  - `{"type":"daily","at":"03:05"}`：北京时间（固定 UTC+8）；
  - `{"type":"module","min_interval_minutes":10}`：由 `TaskModule.next_due()` 决定，至少隔 min_interval，连续失败时按 2 的幂增大。
- **配置是完整快照**：新建时不给 `config` 就复制模块保存的配置。调度器不改 `dry_run`，所以计划要实跑，必须在计划里写 `dry_run: false`。
- **补跑**：错过的时刻启动后只补一次。
- **忙时**：`on_busy="queue"`（默认）排队，空闲后按入队先后启动，超过 `max_wait_minutes`（默认 30）放弃这一次；`"skip"` 直接跳过。
- **设备**：到点时设备没连上，先试连一次，连不上就跳过。
- **失败**：failed / stuck / timeout 连续 3 次自动停用；急停不计。
- **总开关**：`PUT /scheduler {"paused": true}` 只停触发，不影响正在跑的任务。
- 已知需求：
  - `repeat_battle` 托管：`interval`，config `{"manual": false, "auto_battle": true, "dry_run": false}`；
  - `daily` 持续收菜：`module`（`next_due` = 本游戏日没成功跑过就马上跑，否则取下一次重置和 `forest_next` 中较早的）；单次收菜直接 `POST /tasks`。

### 模板采集接口（B09，`api/capture.py`）
GUI「模板采集」页（只在开发版出现）用，和 CLI `capture` / `match` / `ocr` 等价。前缀 `/api/capture`，要 token。
| 路由 | 说明 |
|---|---|
| `POST /frames`、`POST /frames/upload`（请求体是图片字节）、`GET /frames/{id}` | 冻结当前画面（只读截图）或上传图片，统一缩放到 1600×900；内存里只留最近 8 张 |
| `GET /stores`、`GET /templates?module=`、`GET /templates/{module}/image/{name}` | 有模板目录的模块、模板列表和元数据、模板图片 |
| `POST /templates/{module}`、`DELETE /templates/{module}/{name}` | 按矩形保存（png + json，写进 `engine/assets`）并回验：原位置分数 + 其他位置最高分；已存在时要 `overwrite`。保存 / 删除后清掉运行时识别器的模板缓存 |
| `POST /match`、`POST /ocr` | 在冻结的画面上测试模板（不设阈值的最佳位置，`hit` 表示过阈值和 max_diff）/ OCR（read / line / number） |

### 自定义流程和玩家模板接口（B11，`api/flows.py`）
GUI「我的流程」「我的模板」页用，要 token。冻结画面和开发版采集共用 `POST /api/capture/frames`（`FrameCache` 在 `create_app` 里建一个，两个路由共用）。
| 路由 | 说明 |
|---|---|
| `GET /flows` | 全部流程概况：步数、限制、`missing`（缺少的模板）、`last_run`（`custom_flow/history.jsonl` 里最近一次） |
| `GET /flows/{id}`、`POST /flows` → 201、`PUT /flows/{id}` | 读 / 新建（服务端分配 id）/ 整体保存；请求里的 `id`、`missing`、`created`、`updated` 忽略。校验失败 422 `invalid_flow`，`detail` 是 pydantic 错误（GUI 按 `loc` 定位到步骤） |
| `POST /flows/{id}/copy` → 201 | 复制（名字加「副本」） |
| `DELETE /flows/{id}?force=` | 有计划在用时 409 `in_use`（`detail` 是计划列表）；`force=true` 连同这些计划一起删 |
| `GET /user-templates` | `{mine, common}`：玩家模板 + 内置共用模板（只读，不含 `popup/*`），各带 `used_by`（哪些流程用到） |
| `GET /user-templates/image?ref=` | 模板图片；`ref` 是 `名字`（玩家）或 `common:名字`（内置） |
| `POST /user-templates` | `{frame, name, box, tap?, moving, dim_check, threshold}` 保存到数据目录并回验：`quality` = `good` / `ambiguous`（画面上别处分数 ≥ 阈值 - 0.05）/ `weak`（原位置都认不出）。`moving=false` 时检索区域是框外扩 40 像素；`dim_check` = `max_diff: 30`。名字不能带 `/` |
| `DELETE /user-templates/{name}?force=` | 有流程在用时 409 `in_use` |
| `POST /user-templates/test` | `{templates, frame?}`：不给 frame 就截当前画面（只读），返回每个模板的最佳位置和 `hit` |

运行流程就是普通任务：`POST /api/tasks {"module": "custom_flow", "config": {"flow": "<id>"}}`；计划同理（config 快照只有流程 id，流程改了计划跟着用新的）。

## GUI `app/`（B09）
Tauri 2 + React 19 + TypeScript + Vite + Tailwind 4，组件用 radix-ui（shadcn 的做法：源码放在 `src/components/ui/`，按游戏风改了样式）。
```
cd app
pnpm install
pnpm tauri dev          # 桌面应用（会起 Vite 1420 端口，Rust 端连接或拉起引擎）
pnpm dev                # 只起网页，在浏览器里打开 http://localhost:1420/?url=http://127.0.0.1:47800&token=...
pnpm test               # vitest
pnpm typecheck
```
**引擎连接**（`src-tauri/src/engine.rs`）：先读 `<数据目录>/api.json`，`/api/health` 正常就直接连（开发时手动 `serve`）；否则自己拉起引擎：开发版（debug 构建）是 `engine/.venv/Scripts/python.exe -m e7helper.cli serve --port 0`，打包版（release 构建，B10）是随包的 `<安装目录>/engine/e7engine.exe serve --port 0`。token 随机生成后经 `E7_API_TOKEN` 传入，按 token 认出自己的服务。
- 拉起的进程放进 Windows 作业对象（关闭时结束整棵进程树）。应用退出时先 `POST /api/shutdown` 让引擎正常退出，8 秒没退再强制结束。连上的是外部服务时退出不动它。
- 环境变量（开发用，打包版也认）：`E7_ENGINE_DIR` 源码引擎目录（开发版默认编译期的 `app/../engine`；打包版设了它就改走 venv）、`E7_ENGINE_ARGS` 附加给 `serve` 的参数（例如 `--no-connect --paused`）、`E7_DATA_DIR` 数据目录（引擎和 Rust 端都认）。引擎的 stdout 写到 `<数据目录>/logs/engine-stdout.log`。
- 前端通过 Tauri 命令 `engine_connection` 拿 `{url, token, spawned}`；普通浏览器里用地址栏的 `?url=&token=` 或 `VITE_E7_URL` / `VITE_E7_TOKEN`。

**开发版 / 正式版**（`src/lib/env.ts`，用户意见：正式版面向玩家）：`pnpm tauri dev` / `pnpm dev` 是开发版。
- 演练（dry_run）开关只在开发版显示（默认演练，切到实跑要确认）；正式版没有这个开关，启动任务、建计划一律发 `dry_run: false`（`lib/run.ts` 的 `runConfig`）。引擎这边模块默认仍是演练，CLI 不受影响。
- 只在开发版出现：模板采集页、示例模块、日志的「全部」（带来源）、设备后端名、引擎地址。
- `VITE_E7_DEV=1` 可以在打包版里打开开发者功能。

| 目录 | 职责 |
|---|---|
| `src/lib/` | `api.ts`（REST）、`ws.ts`（/ws，断线重连）、`frames.ts`（/ws/frames → object URL）、`store.ts`（zustand：状态、场景、日志；事件到来时让 react-query 失效）、`time.ts`（三种时间格式统一转 Date）、`schema.ts`（JSON Schema → 字段）、`labels.ts`（场景名、状态、日志的中文化） |
| `src/components/shell/` | 启动画面、顶栏（模拟器、当前画面、下个计划、停止）、左侧菜单、右侧「实时画面 + 动态」（可收起）、背景 |
| `src/components/module/` | 通用模块页：说明、计时胶囊、（开发版）演练条、自动表单、最近运行、底部行动条 |
| `src/pages/` | 计划、运行记录、统计、日志、设置、模板采集（开发版，菜单里叫「内置模板采集」）；B11：`FlowsPage`（我的流程）、`FlowEditorPage`（编辑流程）、`TemplatesPage`（我的模板） |
| `src/components/flow/` | B11：步骤树（嵌套积木、拖动排序）、属性面板、模板选择 / 现场采集、坐标点选、冻结画面画布 |
| `src/lib/flow.ts` | B11：流程的数据形状和步骤树操作（按 id 定位、插入 / 移动 / 复制、编号、中文描述、本地检查、校验错误定位） |
| `src/modules/<id>/index.tsx` | 模块的界面扩展，见下 |

**模块界面扩展**：在 `src/modules/<id>/index.tsx` 默认导出 `ModuleUI`（`src/modules/types.ts`），`import.meta.glob` 自动收集、按 module id 挂载；没有的模块用通用页。可以提供：图标和菜单顺序、菜单短名、运行按钮文字、字段图标、字段依赖（控制项关掉时变灰）、只在开发版显示的字段、统计项中文名（统计页按它显示）、推荐计划（计划页一键添加）、`RunExtra`（运行条左侧控件）、`Header`、`onConfigSaved`。
- 例：`daily` 的「持续收菜」= `RunExtra`，开关一条 `module` 触发的计划；`onConfigSaved` 把新设置同步进这条计划的配置快照。
- 例：`repeat_battle` 的推荐计划「托管自动结算」= 每 30 分钟、`manual: false`。

**自动表单**：按 `config_schema` 生成，每个字段一行（仿邮件列表），布尔是勾选框、枚举是下拉、数字带范围校验、对象数组是表格。字段名用 schema 的 `title`（B09 给各模块配置补了中文 title；没写时退回说明的第一句）。改动后 400ms 自动保存（`PUT /config`），保存失败按 pydantic 错误标到字段上。

**自定义流程（B11）**：引擎里是一个通用模块 `custom_flow`（config 选流程，用户选择），GUI 不在菜单里单独列它（`ModuleUI.menuHidden`），入口是左侧菜单的「我的流程」「我的模板」（正式版也有）。
- 我的流程：列表（运行 / 停止、编辑、复制、加入计划、删除；显示缺少的模板和上次结果），空列表时可以一键添加示例「去圣域再回来」（只用内置模板）。「加入计划」打开计划编辑框，预填 `custom_flow` + 流程 id；计划编辑里流程字段是下拉框（引擎 `config_schema` 给 `enum` + `x-enum-labels`）。
- 编辑流程：左边步骤树（「如果」「重复」是积木，里面再放步骤；拖动步骤左边的把手调整顺序、拖进 / 拖出积木，也有上移 / 下移），右边选中步骤的属性（模板缩略图选择、现场采集、在画面上点选坐标 / 画滑动线、「在当前画面上找」只截图测试），底部保存 / 运行。运行时按 `custom_flow.step` 事件高亮正在执行的那一步。离开页面时有未保存的修改会提醒（`useBlocker`）。
- 我的模板：截图（或打开截图）→ 框要认的东西（可选框能点的地方）→ 起名、选「固定 / 会移动」「识别严格度」「变暗时不算」→ 保存并自测。下面列出玩家模板（用在哪些流程、在当前画面上找、删除）。
- 运行记录里自定义流程显示成「流程「名字」」。流程编辑器和我的模板页需要宽画面，不显示右侧栏。

**样式**：游戏风（原型见 `docs/prototypes/b09/d-epic.html`），配色和组件类在 `src/index.css`。背景是圣域（进入圣域时 UI 淡入前的一帧，`src/assets/bg_sanctuary.jpg`），用 CSS 压暗。只用系统字体（数字用 Bahnschrift）。

## 打包发布（B10）
```
cd engine
python -m uv sync --group build                                   # 装 PyInstaller（只在打包时需要）
python -m uv run --group build python packaging/build.py          # 版本号检查 → 冻结引擎 → 冒烟测试
cd ../app
pnpm bundle                                                       # = tauri build --config src-tauri/tauri.bundle.conf.json
```
产物：`engine/dist/e7engine/`（约 270MB，350 个文件），安装包 `app/src-tauri/target/release/bundle/nsis/第七史诗助手_<版本>_x64-setup.exe`（约 96MB）。

**引擎冻结**（`engine/packaging/`）：PyInstaller **onedir**（onefile 每次启动要解压 270MB）。
| 文件 | 职责 |
|---|---|
| `entry.py` | 入口，等同 `e7helper` 命令（`app(prog_name="e7engine")`） |
| `e7engine.spec` | `collect_submodules("e7helper")`（模块按 pkgutil 自动发现）、`uvicorn`、`websockets`（按字符串导入）；`assets/` 和 `collect_data_files("rapidocr")`（配置和 onnx 模型）；解释器选项 `-X utf8`；控制台程序（GUI 拉起时加 `CREATE_NO_WINDOW`） |
| `build.py` | 检查 5 处版本号一致（`e7helper/__init__.py`、`pyproject.toml`、`package.json`、`tauri.conf.json`、`Cargo.toml`），构建，冒烟测试（`modules`、`match`、`ocr`、`serve --no-connect --paused` 的 REST / WS / 帧频道 / shutdown，数据目录用临时目录，不碰设备） |
- 冻结后 `paths.FROZEN = True`，`ENGINE_ROOT` = `sys._MEIPASS`（即 `e7engine/_internal/`），模板在 `_internal/assets/`。开发版的模板采集在打包版里会写进安装目录；玩家模板（B11）在数据目录，不受安装目录权限影响。
- **冻结版忽略 `PYTHON*` 环境变量**（PyInstaller 的隔离配置）：`PYTHONIOENCODING` 不起作用，所以 spec 里直接开 UTF-8 模式；引擎里的文件读写和子进程输出都显式写了编码，不受影响。
- entry-point 注册的外部模块在冻结版里不可用（没有带包元数据，也没有 site-packages），只有随包的内置模块。
- IPC DLL、adb 来自用户的 MuMu 安装目录，不打包。VC 运行库（msvcp140 / vcruntime140）PyInstaller 会带上。

**Tauri 打包**：
- `tauri.conf.json`：`productName` 「第七史诗助手」（窗口标题、开始菜单、卸载列表），`mainBinaryName` `e7helper`（exe 名），NSIS `installMode: "both"`（安装时选「仅为我」或「所有用户」；安装程序以 `Highest` 权限运行，管理员账户启动时总会弹 UAC），简体中文界面。
- `tauri.bundle.conf.json`：只在 `pnpm bundle` 时合并，`bundle.resources` 把 `engine/dist/e7engine/` 放到安装目录的 `engine/` 下。放在单独文件里是为了 `tauri dev` 不去复制（也不要求存在）冻结引擎。
- 图标：`src-tauri/icons/source/make_icon.py` 用「雪之国的索尔缇娅」头像（官方指南站 `c2111_s.png`，112×112）加金色头像框合成 `icon-1024.png`，再 `pnpm tauri icon src-tauri/icons/source/icon-1024.png` 生成各尺寸（删掉生成的 `android/`、`ios/`）。引擎 exe 也用 `icon.ico`。
- 安装包没有签名，安装时 SmartScreen 会提示「未知发布者」。不做自动更新。

## 已有模块
### `secret_shop` 刷神秘商店（B04）
| 文件 | 职责 |
|---|---|
| `__init__.py` | `SecretShopModule`：进店 → 每页扫描顶部/底部 → 买目标 → 刷新 → 循环；`setup()` 注册弹窗 `shop_refresh` / `shop_buy`（自动关闭时都点取消） |
| `page.py` | 纯函数识别：`scan_items`（以「购买」按钮为锚点读名字/价格/金币图标/物品图标）、`read_resources`（先定位顶栏图标再读数）、`read_refresh_cost`、`read_buy_dialog`；决策 `decide` |
| `config.py` | `SecretShopConfig`（预算、保底、金币下限、最多刷新、连续失败、`dry_run` 默认开启、`probe_dialogs`）、`Target(name, price, icon)` |
| `stats.py` | `data_dir/history.jsonl`（每次运行一行）、`stats.json`（实跑累计） |

写有消耗操作的任务可以参考它的做法：
- **按资源读数差确认**，不按点击次数计。读数差为 0 不计数，算失败；为其他值立即停止（任务记为失败）。
- 有消耗的确认框注册成本模块的弹窗，`Dismiss` 点取消；只有任务自己在核对内容后点确认。
- 顶栏数字连续两帧一致才采用（数字有滚动动画）。
- 离线测试用 `tests/shop_sim.py` 这类模拟器：点到确认默认进入 DANGER，按需模拟扣费、吞点击、网络重试、重复扣费。

### `arena_npc` 竞技场 NPC（B05）
| 文件 | 职责 |
|---|---|
| `__init__.py` | `ArenaNpcModule`：大厅 → 模式选择 → NPC对战页 → 选第一行 → 挑战 → 准备界面（优先快速对战，当天次数用完切普通战斗）→ 结算点确认 → 循环；旗帜用完且开了补旗时，点顶栏「+」用友情点数补一次。`setup()` 注册场景 `arena_main` / `arena_npc` / `arena_prep` / `arena_battle` / `arena_result` 和弹窗 `arena_record`（点击关闭）/ `arena_buy_flags`（点取消） |
| `page.py` | 纯函数识别：`read_flags`（顶栏旗帜）、`read_prep`（模式 + 快速对战剩余次数）、`is_victory`、`read_buy_dialog`（哪个选项被选中、消耗、持有）、`auto_icon`（自动战斗图标区域，用于判断是否在转） |
| `config.py` | `ArenaNpcConfig`：表单只有 `buy_flags`（默认关）、`dry_run`（默认开）；其余字段用 `SkipJsonSchema` 隐藏，只供引擎/CLI 使用 |
| `stats.py` | `data_dir/history.jsonl`、`stats.json`（场次、胜场、消耗旗帜、补旗次数、最近一次补旗时间） |

- 一场 = 看到结算 + 旗帜读数减少 1；补旗 = 旗帜读数增加 5。读数差异常立即停止（任务记为失败）。
- 自动战斗：图标静止约 0.6 秒才认为没开（开启后图标一直旋转），点完再观察，不会误关。
- 普通战斗中不按返回键（会打开暂停菜单）：只有网络异常立即重试，其他弹窗持续 10 秒才交给内置规则。
- 内置场景 `arena` 从 B05 起只认模式选择界面（加了 `common/arena/mode_arena`）；竞技场里其他界面的标题也是「竞技场」，由本模块注册的场景区分。CLI `scene` 只加载内置场景，在这些界面上显示「未知」。

### `repeat_battle` 重复刷关：托管战斗 + 手动刷关（B06）
| 文件 | 职责 |
|---|---|
| `__init__.py` | `RepeatBattleModule`：大厅 → 战斗 → 讨伐 → 选地下城（OCR，必要时翻页）→ 选难度（OCR，难度卡片随地下城变化）→ 准备界面（或 `start_here`）；托管：完成就结算、没有就按配置重开；手动：切普通战斗 → 战斗开始 → CLEAR → 确认 → 重新进行 → 循环，每回到准备界面检查托管；行动力不够时可选叶子 / 天空石补充。`setup()` 注册场景 `rb_menu` / `rb_hunt` / `rb_prep` / `rb_battle` / `rb_clear` / `rb_result` / `rb_after` 和弹窗 `rb_auto`（托管进度框）/ `rb_auto_setup` / `rb_auto_settled` / `rb_auto_confirm`（点取消）/ `rb_energy`（点取消） |
| `page.py` | 纯函数识别：顶栏行动力 / 天空石 / 托管图标（`auto_state` + `auto_dot` + `dots_match`）、讨伐列表与难度、准备界面、托管进度框 / 设置框、`plan_auto`（份数与将使用的行动力 / 叶子）、行动力不足框、战后读数、自动战斗图标 |
| `config.py` | `RepeatBattleConfig`、`Hunt`（飞龙 / 魔像 / 报丧妖）、`Tier`（中级 / 上级 / 地狱级；异界用专用代币，暂不支持） |
| `stats.py` | `history.jsonl`、`stats.json`（手动场次、托管结算 / 重开、行动力、叶子、天空石） |

- 托管 = 游戏以前的「重复战斗」：设份数（1 份 = 4 次），用行动力或叶子付费，后台按最快通关记录自动打；「无记录」的关卡开不了，且「无记录」只在普通战斗模式显示。
- 托管是否完成看顶栏图标左上的红点。图标可能整体变灰（从「重新进行」回到准备界面时），要按表盘亮度归一化；进行中的光弧单帧可能扫过红点位置，要隔 0.6 秒看 3 帧、红点位置不变才算完成。
- 一场按战后「持有行动力」的减少量核对：讨伐会掉落行动力，只检查「不超过一场的消耗」。
- 进行中的托管框只点底部空白关闭，绝不点「中断」。

### `daily` 日常收取：邮件 / 精灵之森 / 誓约免费召唤（B07）
| 文件 | 职责 |
|---|---|
| `__init__.py` | `DailyModule`：按 邮件 → 精灵之森 → 誓约召唤 的顺序做（各有开关），每项前后回到大厅；一项失败不影响其他项（任务最后记为失败），核对异常（`DailyAnomaly`）立即停止整个任务。`setup()` 注册场景 `daily_mail` / `daily_forest` / `daily_covenant` / `daily_summon` / `daily_summon_anim` / `daily_summon_hero` / `daily_summon_results` 和弹窗 `daily_forest_reward`（点击关闭）/ `daily_mail_detail`（自动关闭时点「点击关闭」，不收信） |
| `page.py` | 纯函数识别：邮件行（「领取」锚点 + 剩余时间 OCR）、邮件数、邮件详情框；精灵之森三张卡和照料；誓约召唤的免费按钮、剩余免费气泡、顶栏货币区域 |
| `ledger.py` | 按天记账 `ledger.json`：游戏日（北京时间 3 点 = UTC 19:00 切换）、当天做完的项、精灵之森下次时间 |
| `config.py` / `stats.py` | `DailyConfig`（表单只有三个开关和 `dry_run`）；`history.jsonl`、`stats.json` |

- 账本只用来省导航：誓约召唤当天用完就不进去；精灵之森按界面上最短的倒计时决定下次进入时间。能不能领、领没领到都以画面为准。
- 「有没有花东西」的核对：召唤前后对比**顶栏货币区域的画面**，比逐个 OCR 读数可靠，不受图标和数字宽度影响。前后各取两帧（间隔 0.6 秒），两两比较都变了的像素 ≤ 60 才算没变：背景立绘的星星光效会飘进这块区域（单帧最多约 80 个像素，只出现一帧）；数字真的变化时是 5000+。其他有多种货币的界面也可以这样核对。
- 「点击关闭」在多个弹窗里都有（竞技场战斗记录、托管结算完毕、精灵之森奖励），模块弹窗要加背景场景的标题来区分。

### `custom_flow` 自定义流程（B11）
玩家在「我的流程」里编排的流程：步骤 + 条件分支 + 循环（嵌套积木，用户选择）。流程定义和存储在 `core/flows`（不依赖模块），执行器是这个模块。
| 文件 | 职责 |
|---|---|
| `core/flows/model.py` | `Flow`（名字、说明、`limits`、`steps`）和 12 种步骤（`type` 区分）：点击模板 / 点击坐标 / 滑动 / 返回键 / 等待 / 等画面静止 / 等模板（出现或消失）/ 等界面 / 结束流程 / 跳出循环 / 如果（`then` / `else`）/ 重复（`times` / `until` / `while`，`count` 1–999）。条件 = 模板（任一）出现 / 不出现，或在某个内置界面，最多等 `wait` 秒。单步最多等 300 秒，最多嵌套 6 层、300 步；`break` 只能在循环里；不能点 `common:dialog/confirm` |
| `core/flows/store.py` | `FlowStore`：`<数据目录>/flows/<id>.json`（id 由服务端分配，`f` + 7 位十六进制，原子写入）；玩家模板库 `<数据目录>/flows/templates/`；`flow_vision()`（不带前缀只查玩家模板，`common:` 走限定引用）；`missing_templates()` |
| `modules/custom_flow/__init__.py` | `CustomFlow`：`setup()` 先把守卫弹窗排到最前，再加载流程（不存在、没步骤、缺模板时启动就报错）；`run()` 按流程的「最多运行时间」开计时器（到点按超时急停）；写 `history.jsonl`（每次一行：流程、状态、步数、点击数、处理的弹窗数、用时、错误）和 `stats.json`（总数 + 每个流程） |
| `modules/custom_flow/runner.py` | `FlowRunner`：逐步执行，编号和 GUI 一致（`如果` 先编「那么」再接着编「否则」）；每步发布 `custom_flow.step` 事件；每次截图先处理允许的弹窗；失败抛 `FlowFailed`（`TaskFailed`，只记消息）；日志里模板用玩家看得懂的名字（玩家模板名 / 内置模板备注） |
| `modules/custom_flow/guard.py` | 安全规则（用户确认：确认框一律点取消，禁止点确认） |

- **安全规则**：
  - 只自动处理断线重进（`disconnected` / `announcement` / `title_start`）、网络重试（`network`）和守卫弹窗：秘密商店购买框、竞技场补旗框、行动力框、开始托管确认、通用「取消 / 确认」框，**一律点取消**后继续。其他弹窗和遮罩不碰（遮罩兜底的返回键在流程里不生效），留给玩家自己的步骤处理。
  - 每次点击 / 滑动前，在当前画面上找已知的「确认 / 购买」按钮（`common:dialog/confirm`、秘密商店购买、竞技场补旗购买、行动力购买、召唤结果「再召唤一次」），落点碰到就拦下并停止流程（`FlowBlocked`，统计里记 `blocked`）。
  - 流程级上限：最多运行时间（默认 10 分钟，0.5–120）、最多点击 / 滑动次数（默认 200，1–5000）；每个等待都有超时，每个循环都有次数上限。每步开始时清零卡死计数（有自己的超时）。
- 玩家自己采集的「购买 / 召唤」按钮不在拦截清单里：靠 GUI 提示「不要采集会花资源的按钮」+ 确认框一律点取消兜底。

## 新增一个模块
1. 新建 `engine/e7helper/modules/<id>/__init__.py`，继承 `TaskModule` 或 `AssistantModule`，设置 `id`、`name`、`config_model`。
2. 模板和资源放在 `engine/assets/<id>/cn/`，通过 `self.ctx.assets_dir` 访问；模板用 `e7helper capture <id> <name>` 采集，代码里用 `self.vision.find(frame, name)`。
3. 运行 `uv run e7helper modules` 确认已被发现；用 `uv run e7helper run <id> -c '{...}'` 试跑。任务里用 `self.ctl` 操作游戏（见上文“运行时”一节）。
4. 外部包也可以注册：在它的 `pyproject.toml` 里声明
   ```toml
   [project.entry-points."e7helper.modules"]
   my_mod = "my_pkg.my_mod"
   ```
   entry-point 可以指向模块类本身，也可以指向包含模块类的 Python 模块。冻结版（安装包）不支持 entry-point 模块。
5. 同名 id 会报 `ModuleRegistryError`。

参考实现：`modules/hello/`。
