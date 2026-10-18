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

class TaskModule(Module):      def run(self) -> None              # 会操作游戏；用 self.ctl 操作
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
- 内置主题 `Topic`：`frame`（BGR 帧）、`log`（`LogBridge` 把 logging 记录转成事件）、`task`（任务开始/结束）、`scene`（场景变化）、`assistant`（助手挂载/卸下）。B08 的 WebSocket 会订阅这些主题。

## 场景与弹窗 `e7helper.core.scene`（B03）
| 文件 | 职责 |
|---|---|
| `model.py` | `Scene(name, all_of, none_of)`；`Popup(name, all_of, dismiss, none_of, text, text_region, auto)`；关闭方式 `Dismiss.tap(模板) / at(x, y) / back() / none()` |
| `detector.py` | `SceneDetector.detect(frame) → SceneState(scene, popup, obscured, matches)`，一帧约 20–35ms |
| `builtin.py` | 内置场景（lobby / secret_shop / shop / arena（只认模式选择）/ sanctuary）和弹窗（network / notice / confirm） |

判定顺序：弹窗 → 场景 → 遮罩。**只有 `state.clear`（没有弹窗）时 `scene` 才是可操作的界面**，用 `state.is_("lobby")` 判断。
- 相关系数对亮度不敏感，弹窗遮罩下的场景模板照样命中，所以必须先认弹窗。
- 遮罩检测（兜底未知弹窗）：场景锚点或探针模板（默认 `back`）命中位置的亮度（98 分位灰度）不到模板自身的 0.6 倍，就报告 `popup = "obscured"`，用返回键关闭。不用 diff 判断：白色图标在亮背景（圣域天空）上 diff 也有 30+。
  界面切换的淡入淡出也会让画面短暂变暗，所以 `Controller.dismiss_popups` 关闭 `obscured` 前会复核：画面压暗**且静止** 0.5 秒才算，在动就继续等。
- 内置弹窗的处理：`network`（网络连接异常）点「点击重试」；`notice`（通知面板）按返回键；`confirm`（取消/确认 二次确认框）**一律点取消**。任务自己打开的确认框，必须在调用 `dismiss_popups` / `wait_scene` 之前自行处理。
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
| `errors.py` | `TaskStatus`；`TaskAborted`（`TaskStopped` / `TaskTimeout` / `TaskStuck`）；`RuntimeBusy`、`WaitTimeout`、`PopupError` |

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

CLI：
```
python -m uv run e7helper run <id> [-c JSON] [-t 超时秒] [-d 助手运行秒]   # 经 runtime 运行
python -m uv run e7helper scene [-f 图片 ...] [--dismiss] [--watch]        # 识别场景/弹窗、关闭弹窗、持续观察
```

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

## 新增一个模块
1. 新建 `engine/e7helper/modules/<id>/__init__.py`，继承 `TaskModule` 或 `AssistantModule`，设置 `id`、`name`、`config_model`。
2. 模板和资源放在 `engine/assets/<id>/cn/`，通过 `self.ctx.assets_dir` 访问；模板用 `e7helper capture <id> <name>` 采集，代码里用 `self.vision.find(frame, name)`。
3. 运行 `uv run e7helper modules` 确认已被发现；用 `uv run e7helper run <id> -c '{...}'` 试跑。任务里用 `self.ctl` 操作游戏（见上文“运行时”一节）。
4. 外部包也可以注册：在它的 `pyproject.toml` 里声明
   ```toml
   [project.entry-points."e7helper.modules"]
   my_mod = "my_pkg.my_mod"
   ```
   entry-point 可以指向模块类本身，也可以指向包含模块类的 Python 模块。
5. 同名 id 会报 `ModuleRegistryError`。

参考实现：`modules/hello/`。
