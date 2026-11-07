# 架构

```
  ┌──────────── app/ (Tauri + React，B09) ─────────────┐
  │ 外壳：顶栏/菜单/画面+动态   模块界面扩展(按 module id 挂载) │
  └───────────────▲ REST + WebSocket（B08）────────────┘
  ┌───────────────┴──── engine/ (Python) ─────────────────┐
  │ api/      核心路由 + 各模块自注册的子路由与 WS 频道           │
  │ modules/  hello(示例) automation…(B04+) rta_draft…(B14+)   │
  │ core/     geometry paths log | runtime events vision scene  │
  │           data（B13 英雄数据库）storage（逐步加入）             │
  │ device/   MuMuManager + nemu IPC(主) + adb(后备)             │
  └──────────────────────────────────────────────────────┘
```

依赖方向只能自上而下：`modules → core → device`，device 不依赖任何上层。
唯一的例外是 `core.runtime`：它是模块的调度器，需要引用模块契约 `modules.base`（只引用契约，不引用任何具体模块）。

## 设备层 `e7helper.device`
| 文件 | 职责 |
|---|---|
| `base.py` | `Device` 抽象：`name` / `resolution` / `screenshot()` / `tap()` / `swipe()` / `back()`（B03，Android 返回键，默认不支持）/ `input_text()`（B12，往获得焦点的输入框打字，默认不支持）/ `close()` |
| `mumu_manager.py` | `find_install()` 按 参数 → `E7_MUMU_ROOT` → 注册表 → 常见路径 的顺序查找安装目录；兼容 `nx_main\` 与 `shell\` 两种结构。`MuMuManager` 封装 `info` / `launch` / `shutdown` / `app launch` |
| `nemu_ipc.py` | `external_renderer_ipc.dll` 的 ctypes 封装：截图（RGBA 且上下颠倒，转成 BGR）、touch down/up/swipe |
| `adb.py` | 后备通道，直接调用 MuMu 自带的 adb.exe：`exec-out screencap -p`、`input tap/swipe`、`pm list packages` |
| `mumu_device.py` | `MuMuDevice` 组合 IPC 与 adb；`Backend.AUTO` 优先 IPC，失败时回退 adb；`back()` 走 adb `input keyevent 4`；`input_text()` 走 adb `input text`（只收字母和数字）；`connect(index)` 是统一入口 |

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

## 游戏数据 `e7helper.core.data`（B13）
不依赖设备的游戏资料，任务模块和助手模块都能直接用（助手只读帧，不需要别的能力）。目前只有英雄数据库。
```python
from e7helper.core.data import heroes
db = heroes()                 # 进程内缓存；联网更新后 reload_heroes()
db.get("c2111")               # Hero：code / name（国服中文名）/ name_en / aliases（昵称，含拼音）/ element / role / rarity / zodiac / stats / slug / released（发布日期）
db.find("雪国的苏莉塔妮亚")    # 中文名 / 英文名 / 别名精确匹配（忽略空白、全半角、大小写、间隔号），OCR 结果可以直接查
db.search("维德瑞")            # 包含关系：完全一致 → 开头一致 → 包含，同档按发布日期新的在前
db.icon("c2111")              # 头像 BGR（112×112），没有返回 None；以后 BP 助手认头像用
db.detail("c2111")            # HeroDetail：技能、角色奉献、专属装备（中文），没有返回 None
db.artifacts()                # 神器编号 → {name（中文）, name_en}
```
| 文件 | 职责 |
|---|---|
| `hero_db.py` | `Hero` / `HeroFile`（heroes.json 的格式）/ `HeroDB`（查询、头像、详情、详情图标、神器表；按「用户数据目录 → 随包目录」查找）；`load_heroes()` 读两份 heroes.json、用 `updated` 较新的一份；属性 / 职业 / 星座 / 套装 / 属性类型的国服叫法（套装名对照游戏核对过）、四件套列表 |
| `hero_detail.py` | `HeroDetail`（技能、灵魂燃烧、效果、强化、倍率、专属装备、角色奉献、群阵影响的位置 `devotion_slot`）；e7.wiki 数据 → 我们的格式（富文本：段落 → 片段，`hl` 是游戏里高亮的词） |
| `hero_update.py` | 联网更新（只收 `c` 开头的编号，`m` 开头的愚人节怪物英雄不要）：Fribbels 的英雄 / 神器数据 + 简中翻译（`MirrorFetcher` 依次试 raw.githubusercontent.com、jsDelivr），e7.wiki 的角色列表（中文名、昵称、更新时间）和详情；有变化才写，详情只在 e7.wiki 更新时间变了时重下，缺的头像 / 图标才下；新数据比现有少一成以上就不覆盖（只和 Fribbels 来源的比）；e7.wiki 连不上时只更新 Fribbels 那部分。B14h：e7.wiki 有、Fribbels 还没有的新英雄用 e7.wiki 详情的英文名 / 满级属性补上（`Hero.source = "wiki"`，头像用 e7.wiki 的 `static/avatar/<编号>_s.webp` 转 PNG），e7.wiki 连不上时以前补上的留着，Fribbels 有了就换成 Fribbels 的 |
| `hero_builds.py` | 配装方案：Fribbels 配装库（`getBuilds`，POST 英雄英文名）的玩家配装 → 套装组合占比 / 属性中位数 / 常用神器；带速度套的组合分前 10% / 前 25%（按速度最快的那部分）/ 全部三行，不带的按速度三等分成快 / 中 / 慢三档，每行份数 + 属性中位数；装备分换算成装备均分（÷6）；缓存一天（带格式版本） |

- **数据来源**（B13 用户确认）：
  - [Fribbels Epic 7 Optimizer](https://github.com/fribbels/Fribbels-Epic-7-Optimizer)：`data/cache/herodata.json`（编号、属性、职业、星级、星座、60 级 6 星满觉醒属性、slug）、`artifactdata.json`（神器编号）、`data/locales/zh/translation.json`（简中名）、头像 `data/cachedimages/<编号>_s.png`；配装库接口 `krivpfvxi0.execute-api.us-west-2.amazonaws.com/dev/getBuilds`。
  - e7.wiki（国服中文站）：`admin.e7.wiki/api/open/epicseven/hero/card-list`（中文名、昵称、更新时间）、`assets2.e7.wiki/static/heroes/<slug>.json`（技能等详情）和其中引用的图标。中文名优先用 e7.wiki 的。Fribbels 还没有的新英雄另取详情 JSON 的 `nameEn` / `stats` 和 `assets2.e7.wiki/static/avatar/<编号>_s.webp`（B14h；属性 / 职业 / 星级 / 星座 / slug 和 Fribbels 对现有英雄全部一致，详情里没有战斗力）。
  - 神器图标：先官方指南站 `static.smilegatemegaport.com/.../wearingStatus/images/artifact/<编号>_ico.png`，新神器那里没有，再用 e7.wiki 的 `assets2.e7.wiki/arts/assets/item_arti/<图标名>.png`（图标名来自 e7.wiki 神器列表 `admin.e7.wiki/api/open/epicseven/artifact/artifact-list`，更新时存进 `artifacts.json`）；第一次显示时下载缓存。
  - 属性 / 职业 / 套装图标：从游戏截图裁的，放在 GUI 的 `app/src/assets/game/`（见「GUI」）。
- **存储**：随包 `engine/assets/data/heroes/`：`heroes.json`（一名英雄一行）、`icons/<编号>.png`、`details/<编号>.json` + `details/icons/`（技能 / 效果 / 专属装备图标，文件名沿用 e7.wiki 的）、`artifacts.json`（一件一行）、`overrides.json`。联网更新写 `<数据目录>/data/heroes/`（同样结构，只放新的）；配装缓存 `builds/<编号>.json`、神器图标缓存 `artifacts/<编号>.png` 也在这里。详情两边都有时用 e7.wiki 更新时间新的那份。`overrides.json` 按编号改中文名、加别名，加载时套用，更新不会冲掉。
- **随包数据怎么更新**（发版前）：`python -m uv run e7helper heroes --update --bundled`（写进 `assets/data/heroes/`，补下载头像和图标，首次约 3 分钟）。玩家在 GUI「英雄图鉴」点「检查更新」= `POST /api/heroes/update`。
- CLI：`e7helper heroes [搜索词] [--update [--bundled] [--no-icons]]`。
- 接口（`api/heroes.py`，要 token；图片用 `?token=`）：

| 路由 | 说明 |
|---|---|
| `GET /api/heroes` | 全部英雄 + `source` / `origin` / `updated` / `labels`（属性、职业、星座、套装、属性类型的中文名，`percent_stats`） |
| `GET /api/heroes/{code}`、`GET /api/heroes/{code}/icon` | 一名英雄 / 头像 PNG |
| `GET /api/heroes/{code}/detail` | 详情；没有 404 `no_detail` |
| `GET /api/heroes/{code}/builds?refresh=` | 配装统计；下载失败 502 `builds_failed`（有旧缓存时返回旧的，带 `stale`） |
| `GET /api/hero-icons/{name}` | 技能 / 效果 / 专属装备图标 |
| `GET /api/artifacts/{code}/icon` | 神器图标（官方指南站 → e7.wiki）；都失败 502 `icon_failed` |
| `POST /api/heroes/update` | 联网更新；正在更新 409 `busy`，下载失败 502 `update_failed` |

## RTA 选秀 `e7helper.core.rta`（B14 起）
世界竞技场选秀助手的引擎部分，不依赖设备。B14 拆成 a–g 几块（数据 → 模型 → 选秀推荐 → 分析功能（d1 先动 / 英雄池，d2 站位 / 快速分析 / 英雄统计）→ 页面 → 画面识别 → ss22 重训加先动），目前有对局数据（B14a）、胜率 / 选人模型（B14b）、选秀推荐（B14c）、先动概率和英雄池（B14d1）；GUI 的选秀页见「GUI / RTA 选秀（B14e1）」。
```python
from e7helper.core.rta import rules, parse_battle
rules.PICK_ORDER                     # ("F","S","S","F","F","S","S","F","F","S")，F = 先手方
rules.mover(3), rules.left_in_turn(3)  # 选了 3 手后下一手是 F，这一轮还要连选 2 名
rules.validate(prebans, picks, banned, complete=True)  # 局面检查，返回中文问题列表
m = parse_battle(raw, "global")      # 官方战绩站的一场 → Match（先手方 / 后手方、10 手顺序、后禁、站位、开战规则、胜方、开局行动条和先动方）
m.sequence()                         # [(F/S, 编号), ...] 共 10 手
```
| 文件 | 职责 |
|---|---|
| `rules.py` | 选秀规则：1-2-2-2-2-1、每边第 3 手是保护位（不能被后禁）、预禁每边 2 名（可以和对方重复）；`validate()`；段位（铜牌 … 传说）和段位档（金牌及以下合成一档）；开战规则对照表（`opening_rule_desc_tid` → 攻击 / 防御 / 抵抗 / 特殊，不认识的按类别 `opening_rule_title` 给名字） |
| `battle.py` | `parse_battle(raw, server) → Match`，不合格抛 `BadBattle(reason)`（`reason` 用来归类统计）；`strip(raw)` 采集时只留 `STORE_KEYS`（不含昵称、玩家编号）；开局行动条（B14d1）：`Pick.energy`、`Match.first_mover` / `first_hero`，行动条不合格只是没有，对局照常用（`read_energy` / `energy_issue` 给原因） |
| `official.py` | 国服 / 海外官方战绩站客户端 `OfficialClient(server)`：两种返回包装统一成 `result_body`；限速（最小间隔 + 抖动）、429 / 5xx / 网络错误退避重试、其他 4xx 和非 0 返回码抛 `OfficialError`；`fetch` / 时钟可注入 |
| `crawl.py` | 开发用的采集：sqlite `F:\e7helper-data\rta\crawl.sqlite`（环境变量 `E7_RTA_DB` 可改；不放 AppData，因为 Claude 桌面版会把会话里写进 AppData 的文件重定向走）；`players` 队列 + `battles` + `meta`，滚雪球、两个服各一个线程并行、断点续采；已有对局再采到时补上开局行动条（B14d1） |
| `report.py` | 采集数据报告：场数、解析失败原因、段位 / 开战规则分布、英雄覆盖、先手胜率；有开局行动条的场数、没有的原因、先手方先动率、先动方胜率（B14d1） |
| `herostats.py` | 开发用：官方英雄分析的快照（赛季 × 段位 × 英雄，存进采集库的 `hero_stats` 表）、速度直方图、读有开局行动条的对局（B14d1） |

**官方战绩站**（两个站是同一套系统，接口同名，都是非公开接口）：`POST <地址>/gameApi/<名字>?<参数>`，没有请求体。
| | 国服 | 海外 |
|---|---|---|
| 地址 | `https://e7stats.qyzlgame.com/gameApi/` | `https://e7api.onstove.com/gameApi/`（要 `Content-Type: application/json`） |
| 返回 | `{return_code, result_body}` | `{code, message, value: {result_body, total_count}}` |
| 种子 | `getRecommendList`（5 名），没有排行榜 | `getWorldUserRankingDetail?season_code&world_code=all&current_page`（前 100 名，每页 10）+ `getRecommendList` |
| `getBattleList?nick_no&world_code&season_code` | `list_count=100&page_no=N` 能往前翻 | 只返回最近 100 场（翻页还是同一页） |
| 牌组 `my_deck` / `enemy_deck` | 对象 | JSON 字符串 |
| 开战规则 | 没有（2026-10 国服优胜者以上的对局也没有） | `opening_rule_title` / `opening_rule_desc_tid`，优胜者以上每局随机一条；有一方低于优胜者时是占位符 `_`（解析成没有规则） |

- 一场对局：`battle_seq`（**两边视角相同**，去重键）、`battle_day`（UTC）、`iswin`（1 胜 / 2 负）、`grade_code` / `enemy_grade_code`、牌组的 `preban_list` 和 `hero_list[{hero_code, first_pick, ban, mvp}]`（先手方第一手的英雄 `first_pick=1`）、字符串化的 `teamBettleInfo(enemy)`（`"my_team":[...]`，`pick_order` 1–5、`position` 1–4（被后禁的是 0）、神器、套装、伤害、击杀、等级、觉醒、复活次数）。
- `energyGauge`（`"energy_gauge":[{hero_code, energy, team, position_no}]`）是**开局行动条**（B14d1 核对 198 场全部成立）：第一个行动的正好 100，被后禁的两名 0，其余 ≈ 开局随机 + 100 × 自己速度 ÷ 先动者速度 + 开局效果；`team` "1" = 采集视角那一方，`position_no` = 第几手（不是站位）。B14d1 之前没存（B14a 误认成结算行动条）。原始记录 29 个字段里没存的其余都是昵称、编号、重复字段。
- 对手的数字编号是 `matchPlayerNicknameno`（`enemy_nick_no` 是昵称，拿它查会 405）。
- 选秀阶段有人退出的对局双方都没有英雄、0 回合（约 0.9%），解析时归为「没有选秀」。
- 另有 `getSeasonList`、`getPopularHero?season_code&grade_code`（每名英雄 pick / win / ban 率、搭档 3、难对付 3、套装）、`getHeroAnalysis?hero_code&season_code&grade_code`（段位只有大师到传说；没有数据返回码 -10002）：套装 / 神器 / 技能、按选人顺序的选取 / 后禁率、各赛季胜率，以及 `abillity` 属性直方图，口径「60 级 / 6 星满觉醒 / 穿戴全部装备」，每项 10 档等宽、最后一档没有上限，刻度是绝对值（官方页面代码里的 `re` / `ie`）：攻击 1200–6000、防御 800–3000、生命 9000–40000、**速度 110–310（每档 20）**、暴击率 15–100、暴击伤害 150–350、效果命中 0–200、效果抗性 0–300。B14a 以为只是「+1…+10」相对档位，B14d1 改正。

### 胜率 / 选人模型（B14b）
```python
from e7helper.core.rta import model
from e7helper.core.rta.encode import DraftState
m = model.load()                                   # 随包 assets/data/rta/（onnxruntime，不要 torch）
st = DraftState(prebans={"F": [...], "S": [...]}, picks={"F": [...], "S": [...]}, grades=("legend", "emperor"), rule="unknown")
m.win([st])                                        # 「先手方赢」的概率（后手方 = 1 − p）
m.next_picks(st, k=8)                              # 下一手（轮到的一方）最可能选的 [(编号, 概率)]
m.evaluate(states)                                 # 一批局面一次前向：win [B] + picks [B, V]（B14c 搜索用）
```
| 文件 | 职责 |
|---|---|
| `encode.py` | 训练和运行共用的编码：一场 = 17 个 token（0 CTX、1–4 预禁、5–14 选秀、15–16 双方被禁的），类型 / 位置编号、注意力掩码（0–4 互相可见、之后因果）、12 个局面的读出位置（已选 n 手读 4 + n，后禁后读 16）、选人标签（连选 2 名的回合两名各 0.5）；`Vocab`（英雄词表 + 开战规则表，没见过的规则按类别兜底）、`DraftState`（运行时的局面）、`pick_mask` |
| `dataset.py` | 训练数据快照：采集库一个赛季 → 多进程解析、过滤（解析失败 / `m` 开头英雄 / 0 回合 / 截止日之后 / 不在 `servers` 里的服 / 含 `exclude` 里英雄的对局，预禁和被禁也算）、编码 → `F:\e7helper-data\rta\datasets\<赛季>-<截止日>.npz`；按日期切分（最后 7 天测试、再前 7 天验证）；`state(row, n)` 还原某场在局面 n 的 `DraftState` |
| `metrics.py` | log loss、Brier、AUC、ECE / 校准表、选人命中前 k |
| `model.py` | 运行时：读 `model.onnx` + `meta.json`（词表、温度、训练数据、测试指标）+ `parity.json`；`win` / `next_picks` / `evaluate` / `check()`（parity 核对，冻结引擎的冒烟测试用） |
| `train/`（不随包，要 torch） | `nets.py`（混合结构 `HybridTransformer`、纯 Transformer 和三个基线：只看段位的逻辑回归、英雄强度、因子分解机）、`fit.py`（训练循环、按验证集的胜率保存最好的一轮、可选早停、恒定 / 余弦学习率、每轮在训练子集上同口径评估、Platt 校准，过程写进 run 目录）、`evaluate.py`（按局面 / 子集的指标、热度基线）、`export.py`（ONNX + parity）、`watch.py`（训练曲线页） |

- 输入：一场选秀的 17 个 token，每个 = 英雄嵌入 + 类型嵌入（7 种）+ 位置嵌入；CTX 再加双方段位档 + 开战规则（海外四条 / 无 / 「不知道」）。B14h 起训练集只有海外，没有「不知道」：训练时以 10% 的概率把规则换成「不知道」（`TrainConfig.rule_unknown_rate`，`rta train --rule-unknown`），学到的是各条规则的平均。胜率一律是**先手方**赢的概率。
- 网络（随包的是混合结构，d = 128、3 层、λ = 1，66.5 万参数）：胜率 logit = 因子分解机（强度 + 搭档 + 克制，显式去掉被禁的英雄）+ Pre-LN Transformer（手写注意力）的 `Linear(d→1)`；选人头 `Linear(d→d)` 后乘英雄嵌入的转置（共享权重）。损失 = 12 个局面胜率 BCE 平均 + λ × 10 个局面选人交叉熵平均；默认跑满整个余弦周期、按验证集的胜率损失保存最好的一轮（`--patience N` 打开早停，学习率降到峰值三成以下才计数）；验证集上每个局面拟合 Platt 校准（σ(a · logit + b)，存在 `meta.json` 的 `calibration`）。纯 Transformer 打不过因子分解机、也几乎用不上后禁信息，所以加了宽部分（B14b 审核记录）。架构图：[reviews/B14b-architecture.html](reviews/B14b-architecture.html)。
- 测试集（B14h：10-26 ~ 11-01，17.4 万场，只有海外，后禁后，切分训练的模型）：log loss 0.6125、AUC 0.721、ECE 0.005（因子分解机 0.6208 / 0.713）；选人前 5 命中 0.610（热度 0.416）。随包的全量模型和 B14b 的全量模型在两者都没见过的 11-02（2 万场）上：0.6099 / 0.6124。B14b 时（10-17 ~ 10-23，两服）是 0.6166 / 0.717。
- 训练数据：只用本赛季、**只用海外**（B14h 用户意见：国服已同步海外，数据质量不如海外），全段位（段位作为输入）；还没得到开发的新英雄整场去掉（`--exclude`，B14h 是侦探茉萝 c2187）。模型词表里没有的英雄（这些新英雄、训练集里选过不到 30 次的）不进 RTA 助手和英雄池，只在图鉴里看（B14h 用户意见）。B14h 前的随包模型是两服合并的。随包模型 = 用切分选好结构和轮数后、全量数据重训的那个。
- 训练（开发机）：`python -m uv sync --group train`（CPU 版 torch，测试和导出用）；GPU 训练环境 `engine/.venv-rocm`（`tools/setup_rocm_venv.ps1`：AMD 官方 Windows ROCm 版 torch 2.9，只有 Python 3.12，装在 `engine/.python`），本机 RX 7700 XT 比 CPU 快约 16 倍。网格 `tools/rta_grid.ps1`。
- CLI（开发用）：`rta dataset [--until] [--servers global] [--exclude 编号或名字,...]`、`rta train -m lr0|lr|fm|transformer|hybrid [--d --layers --lambda] [--rule-unknown 0.1] [--full --calibration-from <run>]`、`rta watch`（曲线页 `http://127.0.0.1:47900/`）、`rta eval <run>...`、`rta export <run> [--metrics-from]`、`rta model [--check]`、`rta predict --first ... --second ...`（中文名试算）、`rta sim [--side F|S] [--opponent ai|manual]`（终端里模拟 BP：一层估算的推荐 + 后禁矩阵；候选按选人头先验筛，见 B14b 审核记录「冷门英雄外推」）。run 目录 `F:\e7helper-data\rta\runs\<名字>\`。
- 冻结：`e7engine.spec` 的 `collect_submodules` 跳过 `e7helper.core.rta.train`，`excludes` 加 torch / onnx / onnxscript；冒烟测试跑 `rta model --check` 并检查产物里没有 torch。

### 选秀推荐（B14c）
```python
from e7helper.core.rta import search
adv = search.load()                                   # 随包主模型 + 第二个模型（assets/data/rta/second/）+ priors.json
adv.advise(state, "F", pool=None, budget=5.0)         # 当前局面：轮到我方 → recommend；轮到对手 → opponent；选完 → ban
adv.preban(None, grades=("legend", "emperor"))        # 预禁推荐（先后手不知道传 None；grades = (我方, 对方)）
```
| 文件 | 职责 |
|---|---|
| `search.py` | 推荐搜索：`Advisor`（`advise` / `preban` / `info`、按局面缓存、同一时间只跑一个）、`SearchConfig`（所有门槛和规模）、`nash`（零和矩阵博弈的混合策略，支撑集枚举）、`correction`（少见选择的高估修正）、`protected_index` |
| `priors.py` | 数据先验 `priors.json`：每名英雄训练时被选的次数（冷门 = < 1000 次）、双方 ≥ 优胜者时先手方 / 后手方的预禁组合频率（各前 300 组）、后禁率（可被禁时被禁的比例）；`e7helper rta priors` 从训练快照生成 |
| `audit.py` | 验收统计（开发用，要训练快照）：冷门比例和用时、自对弈 + 不筛的一层贪心对照（每局阵容留在 JSON 里，终端列出 ≥ 90% 的那几局）、跟着推荐的实际兑现（用切分模型） |

- **轮到我方**：
  1. 候选只从选人头先验里取：这一手常见度 ≥ 0.5%，或常见度前 40 且训练时被选 ≥ 1000 次；英雄池（请求里传）里过不了筛的冷门英雄也进候选。英雄池里能选的（没被选、没被禁）不够这一轮要选的名数时，这一轮不限制（B14e2：根上这一轮在结果里标 `pool_short`，第 3 层我方再回应也按同样的规则）。
  2. 三层：我方这一轮（所有候选；两手回合是所有两两组合）→ 前 24 个算对手回应（先验前 12 名 ∪ 威胁前 4 名；对手连选两名时是两两组合，组合先验 q(a)·q(b|a) + q(b)·q(a|b)）→ 前 8 个再算我方再回应（回应取先验前 10 + 最坏 2，我方取先验前 12 名）。分数 = ½ 预期（按回应先验加权）+ ½ 最坏；算得深的排前面。
  3. 两手回合：没有保护位的回合两个顺序取平均；含保护位的（先手第 4–5 手、后手第 6–7 手）取对出手方好的顺序，`protected` 给出放保护位的那名；对手的普通两手回合只算先验高的在前的顺序。
  4. 选秀最后几手（先手第 8–9 手、后手第 10 手，以及后手第 6–7 手的第 3 层）搜到后禁：叶子 = 后禁博弈的值。
  5. **少见选择的高估修正**：一手的单步变化里对出手方有利的部分，有 (1 − 可信度) 当成高估，从这一手之后的所有结果里扣掉；可信度 = q / (q + 1.5%) × min(1, 被选次数 / 1000)，q = 这一手的常见度；我方后面几手的可信度不超过候选那一手的。依据见 reviews/B14c.md「少见选择的高估」。
  6. 截止时间（默认 5 秒）：第 2 / 3 层按名次一个个算，时间不够就停（`stats.truncated`），没算到的按浅一层排在后面。
- **第二个模型**（切分训练的那个，没见过最后 14 天；B14h 起是 b14h-hy-d128-L3-lam1）：列出的推荐重算到第 2 层（同样的回应和修正），`second.spread` = 两个模型的预期之差，|差| ≥ 5 个百分点标 `uncertain`。两个模型词表不同（B14h：274 / 260 名），局面统一按主模型编号拼、推理时换成各自的。
- **轮到对手**：对手可能的选择（两手回合 = 先验前 16 名两两组合）按先验排，带之后我方胜率；威胁 = 之后我方胜率最低的 3 个。B14e2 审核起「之后我方胜率」是**我方的读数**：对手最可能的 8 种 + 模型读数最差的 4 种选法，各自算我方这一轮从英雄池里挑的最好回应（先验前 16 名，分数 = ½ 预期 + ½ 最坏，按对手再下一轮先验前 12 名回应），取那个回应的预期（对手最后一手之后 = 后禁推荐行的预期）；`opponent.win` 按选法的先验加权，模型读数留在每项的 `now`。随包模型 p95 2.3 秒。
- **后禁**（10 手选完）：4 × 4 矩阵（行 = 我方禁对方哪名，列 = 对方禁我方哪名，保护位除外）；每行 最坏 / 预期（对方按后禁率）/ 分数（½ / ½），推荐分数最高的行；另给纳什均衡混合策略。
- **预禁**：我方候选 = 数据里（我方这个先后手）占比 ≥ 0.2% 的组合或前 60 组（可以 `fixed` 一名）；对手 = 对方那个先后手最常见的 100 组按频率加权；胜率读模型「已选 0 手」的局面（不用选人头模拟）；分数 = ½ 预期 + ½ 最坏（对手最常见的 10 组里最差的）；先后手不知道时两种各算一半。
- 返回的胜率一律是**我方**的；`close` = 和第一名差 < 1 个百分点（差距不明显）；`rare` = 训练时被选 < 1000 次；`pool_only` = 只因为英雄池才放进来的冷门英雄；`trust` = 这一手的可信度。`unknown` = 模型没见过的英雄（按 UNK 算）：局面里的和英雄池里的（B14h 前只列英雄池里的；页面上选不到这些英雄，命令行 / 接口直接传时才有）；后禁矩阵的行列编号从局面里取，模型没见过的英雄也有编号。预禁的组合只用模型里有的英雄（`_Preban.pairs`，B14h）。
- 接口（`api/rta.py`，要 token）：`GET /api/rta/model`（B14e1 起带 `options.rules`：开战规则列表；B14h 起带 `codes`：主模型里有的英雄）、`POST /api/rta/advise {side, state, pool?, top?, budget?}`（局面不合法 422 `invalid_state`，detail 是中文问题列表）、`POST /api/rta/preban {side?, grades, rule, fixed?, top?, budget?}`（结果里 `theirs`、每组的 `share` / `worst_vs` 都以**我方**的先后手为键）、`GET /api/rta/priors`（B14e1：每名英雄被选次数、是否冷门、后禁率、预禁比例）；没有模型 503 `no_model`。
- CLI：`rta advise --side F --pre-mine … --pre-theirs … --mine … --theirs … [--ban-mine/--ban-theirs] [--grades 我方,对方] [--pool …] [--json]`、`rta preban [--side] [--fixed]`、`rta sim`（B14c 起用这里的搜索）、`rta priors`、`rta audit`（开发用）。
- 每次重训（新赛季）：`rta export` 主模型 + 切分模型（`--out assets/data/rta/second`）→ `rta priors`；可信度的常数要用新的切分模型在测试期重新量一次：`python -m uv run python tools/rta_trust.py <快照.npz> assets/data/rta/second`（B14h 写成脚本）。

**采集**（`e7helper rta crawl`，开发用）：种子 → 采他们的对局 → 对手段位 ≥ `--min-grade`（默认优胜者）就入队。国服一名玩家往前翻到这个赛季的头（最多 `--max-pages` 页，一页里没有新对局也停）；海外每人只有最近 100 场，隔 `--refresh-hours`（默认 20）再采；国服翻完的玩家也按这个间隔回来看第 1 页。没采过的、段位高的、离种子近的优先。每个服默认 1 次 / 秒（另加 0–0.3 秒抖动）、每天 2 万次上限、连续出错 10 次就停；取不到的玩家（多半是 405）隔一段时间再试，失败 3 次不再采。对局表只存 `strip()` 后的字段，**玩家编号只在队列表里**，采集库不进 git、不随包。
- 补开局行动条（B14d1）：已有、但原始字段里没有 `energyGauge` 的对局再采到时整行换成新的（视角可能换成另一方），算「补」，翻页时和新对局一样会让国服继续往前翻；`rta crawl --backfill` 开跑时把国服这些赛季的玩家重置到第 1 页，整个赛季重翻一遍（约 3–4 千次请求）。海外只有最近 100 场，采集器每 20 小时回来看第 1 页时顺带补上。
- CLI：`e7helper rta probe -s cn|global`（采一页看字段，不打印昵称）、`rta crawl [--server both] [--season …] [--max-requests N] [--backfill]`、`rta report [--json]`。

### 先动概率 / 英雄池（B14d1）
```python
from e7helper.core.rta import speed, pool
table = speed.load()                                   # 随包 assets/data/rta/speed.json；没有返回 None
speed.first_mover(table, [speed.Unit("mine", "c1168", "legend", speed=335), speed.Unit("theirs", "c5190", "legend")])
speed.annotate(out, state, "F", table, pool.load().speeds)   # 在 advise 结果上加先动概率（不改胜率）
```
| 文件 | 职责 |
|---|---|
| `speed.py` | 速度表 `SpeedTable`（每名英雄每个段位 13 档：官方 110–290 九档 + 290 以上拆成 290–310 / 310–330 / 330–350 / 350–370）、`first_mover`（蒙特卡洛，固定种子）、开局规则 `RULES`、`annotate`；开发用的 `fit_tails` / `implied_speeds` / `residuals` / `evaluate` / `choose_jitter` / `build` |
| `pool.py` | 英雄池 `<数据目录>/modules/rta_draft/pool.json`：`{heroes: [{code, speed?}]}`，速度 50–400，同一名英雄留最后一次；B14e2：没设置过（没有文件、文件坏了，`load_saved()` 返回 None）时用 `default()`（主模型里训练时被选最多的 60 名，不写进文件），`reset()` 删掉文件 |

- **速度**：290 以下用官方英雄分析的速度直方图（按对局双方各自的段位；没有这个段位用最近的，一样近取高的；段位不知道按人数混合；没有这名英雄用这个段位所有英雄的合计并标 `no_data`）。290 以上官方只给占比，用开局行动条反推：同场 290 以上占比 < 20%、第 1 档占比 < 30%、行动条 20–95 的英雄当参照（至少 3 名），经过的时间 = 中位数（(行动条 − 开局随机的一半) ÷ 参照的速度中位数），再反推其余英雄的速度；290 以上四档每名英雄每个段位一份，向这个段位的合计收缩（强度 20 场），段位合计再向先验（方案阶段 198 场的粗估）收缩（强度 50 场）。核对：反推出 ≥ 290 的比例应接近官方 290 以上的占比。有限速英雄（赫尔赛蒂）的对局、有开局加行动条的英雄不参与反推。
- **直方图清理**（B14h）：官方直方图里混着「没算装备」的记录，表现为基础速度或基础 × 1.25（只算速度套）那一档的孤立尖峰（传说段修里 55%）。`clean_hists`：低档（下边界 ≤ 基础 × 1.25 + 5，基础速度取英雄数据库的满觉醒属性）里最高一档比紧挨的上一档多 5 倍以上时，低档整块清零；`refit_low`：用清理后的表从开局行动条反推这名英雄在这个段位的速度，低于低档上界的比例（至少 30 次，向 0 收缩 20 次）就是真的不堆速度的配装（宝剑君主伊赛丽亚八成低于 150），低档按官方原来的比例恢复到这个占比。依据见 reviews/B14h.md。
- **开局规则**：智武首次战斗开始 +30% 行动条；赫尔赛蒂（PvP）把其他英雄的速度限制在她的 90% 以下。天秤之主是别人加行动条时跟着加，开局不触发（用户意见），不算。没登记的开局效果靠 `rta speed` 的残差（行动条比速度应有的高出多少）找。
- **开局随机**：每名英雄 0–`jitter`% 行动条，默认 5%（社区说法）；`rta speed` 在拟合用的对局上比 0 / 2.5 / 5 / 7.5 / 10，比 5% 好不到 0.002 的 log loss 就不换（合成数据里各取值只差约 0.001，从「谁先动」上很难分辨）。
- **先动概率**：每名英雄抽速度（英雄池里填了速度的用填的），到 100 的时间 = (100 − 开局行动条) ÷ 速度，最先到的先动；4000 次抽样，同样的输入结果相同。
- **不进胜率模型**（用户意见）：有的阵容抢到一速胜率差几十个点，有的几乎不差，不能在模型外统一修正；推荐和后禁矩阵只在旁边显示先动概率。ss22 重训时把「谁先动」作为模型输入（B14g）。
- 接口：`POST /api/rta/first {mine, theirs, grades?, speeds?}`（没有速度表 503 `no_speed_data`）、`GET/PUT/DELETE /api/rta/pool`（B14h 起只收模型里有的英雄：PUT 有别的 422 `not_in_model`，GET / advise 跳过以前存的；B14e2 起没设置过时是默认的、带 `default: true`，DELETE 回到默认）；`POST /api/rta/advise` 不传 `pool` 时用保存的英雄池（`use_saved_pool: false` 不限制；池里能选的不够这一轮时这一轮不限制、结果 `pool_short: true`，B14e2），结果加 `first`（目前双方在场的，`partial` = 还不是最终 4 打 4）、每个推荐的 `first`、后禁矩阵的 `ban.first`（每格 4 打 4），都是我方先动的概率；`GET /api/rta/model` 加 `speed`（速度表信息）。
- 生成速度表（开发用）：`rta herostats [--season] [--grades] [--min-picks 300] [-s global]`（每名英雄每个段位一次请求，约 200 名 × 6 段 ≈ 35 分钟，72 小时内取过的跳过）→ `rta speed [--season] [--servers global] [--no-clean]`（直方图用第一个服的；前 80% 有行动条的对局拟合、最近的 20%（最多 3000 场）验收，打印核对表、残差、清理掉和补回的低档，验收另给「官方原样」「只去掉」两种对照）→ `assets/data/rta/speed.json`。B14h 起两步都默认海外。试算：`rta first --mine … --theirs … [--grades] [--speed 名字=速度]`；`rta advise` 也显示先动概率（`--speed`）。
- 快照（`rta dataset`）带上 10 手各自的开局行动条（按选秀顺序，-1 = 没有）和 `first_mover`（1 = 先手方先动、0 = 后手方、-1 = 不知道），旧快照读出来是 -1；给 B14g 用。

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

- **启动**：`serve` 先绑定端口（`--port 0` 随机），把 `{pid, url, port, token}` 写进 `<数据目录>/api.json`（正常退出时删除），再启动 uvicorn。默认只监听 127.0.0.1。uvicorn 配置在 `cli.server_config()`：事件循环用 **Selector**（Windows 默认的 Proactor 在客户端断开太快时会关掉监听 socket、关服务时卡住，B12 反馈 7），关服务最多等 5 秒。
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
| `/heroes/...`（B13） | 英雄数据库，见「游戏数据」 |
| `/rta/...`（B14c、B14d1、B14e1） | RTA 选秀推荐、先动概率、英雄池、英雄出场数据，见「RTA 选秀 / 选秀推荐」「先动概率 / 英雄池」 |

**模块子路由**：`Module.routes()` 返回的路由挂到 `/api/modules/<id>/`，同样要 token。第一段路径不能是 `config` / `stats` / `timers` 或路径参数，否则启动时报 `ModuleRegistryError`。fastapi 在 `routes()` 里再导入。已有：`GET /api/modules/daily/ledger`、`GET /api/modules/secret_shop/report`（B12c）。

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
| `src/components/shell/` | 启动画面、顶栏（左边固定是索尔缇娅头像 + 「第七史诗助手」；右边模拟器、当前画面、下个计划、停止、窗口按钮）、左侧菜单、右侧「实时画面 + 动态」（可收起）、背景。窗口没有系统标题栏（`decorations: false`，B12）：顶栏就是标题栏（`data-tauri-drag-region`：拖动、双击最大化），`WindowControls` 画最小化 / 最大化 / 关闭（只在 Tauri 里显示）；启动画面顶上有一条 `WindowDragStrip` |
| `src/components/module/` | 通用模块页：说明、计时胶囊、（开发版）演练条、自动表单、最近运行、底部行动条 |
| `src/pages/` | 计划、运行记录、日志、设置、模板采集（开发版，菜单里叫「内置模板采集」）；B11：`FlowsPage`（我的流程）、`FlowEditorPage`（编辑流程）、`TemplatesPage`（我的模板）；B13：`HeroesPage`（英雄图鉴）；B14e1：`DraftPage`（RTA 选秀） |
| `src/components/heroes/` | B13：`HeroDetailDialog`；B14e1：`HeroGrid.tsx`（头像、筛选条、头像网格，图鉴和选秀页共用；B14e2 加 `PoolMark`、筛选条 `shrink`）；B14e2：`PoolEditor.tsx`（图鉴的英雄池模式） |
| `src/components/rta/`、`src/lib/draft.ts`、`draftStore.ts`、`rta.ts` | B14e1：选秀页的阵容栏 / 各步面板、局面和撤销、`/api/rta/*` 的数据形状和「只要最新的」请求 |
| `src/lib/pool.ts` | B14e2：英雄池的数据形状、勾选 / 速度、速度输入解析、自动保存（`autoSave`：400ms 防抖、同一时间一个请求）（`autoSave` 也排「恢复默认」`RESET`） |
| `src/components/flow/` | B11：步骤树（嵌套积木、拖动排序）、属性面板、模板选择 / 现场采集、坐标点选、冻结画面画布 |
| `src/lib/flow.ts` | B11：流程的数据形状和步骤树操作（按 id 定位、插入 / 移动 / 复制、编号、中文描述、本地检查、校验错误定位） |
| `src/modules/<id>/index.tsx` | 模块的界面扩展，见下 |

**模块界面扩展**：在 `src/modules/<id>/index.tsx` 默认导出 `ModuleUI`（`src/modules/types.ts`），`import.meta.glob` 自动收集、按 module id 挂载；没有的模块用通用页。可以提供：图标和菜单顺序、菜单短名、运行按钮文字、字段图标、字段依赖（控制项关掉时变灰）、附加选项 `subFields`（画在主开关那一行里，B12）、自己画的字段 `fieldRenderers`（例如书签刷取的商品选择，B12）、按设置锁定字段 `fieldLocks`（例如重复刷关选食人魔时难度锁定成异界，锁定值会自动写进设置，B12a）、只在开发版显示的字段、推荐计划（计划页一键添加）、`RunExtra`（运行条左侧控件）、`Header`、`RunsPanel`（代替通用的「最近运行」，B12c）、`onConfigSaved`。
- 例：`daily` 的「持续收菜」= `RunExtra`，开关一条 `module` 触发的计划；`onConfigSaved` 把新设置同步进这条计划的配置快照。
- 例：`repeat_battle` 的推荐计划「托管自动结算」= 每 30 分钟、`manual: false`。

**自动表单**：按 `config_schema` 生成，每个字段一行（仿邮件列表），布尔是勾选框、枚举是下拉、数字带范围校验、对象数组是表格。字段名用 schema 的 `title`（B09 给各模块配置补了中文 title；没写时退回说明的第一句）。改动后 400ms 自动保存（`PUT /config`），保存失败按 pydantic 错误标到字段上。

**自定义流程（B11）**：引擎里是一个通用模块 `custom_flow`（config 选流程，用户选择），GUI 不在菜单里单独列它（`ModuleUI.menuHidden`），入口是左侧菜单的「我的流程」「我的模板」（正式版也有）。
- 我的流程：列表（运行 / 停止、编辑、复制、加入计划、删除；显示缺少的模板和上次结果），空列表时可以一键添加示例「去圣域再回来」（只用内置模板）。「加入计划」打开计划编辑框，预填 `custom_flow` + 流程 id；计划编辑里流程字段是下拉框（引擎 `config_schema` 给 `enum` + `x-enum-labels`）。
- 编辑流程：左边步骤树（「如果」「重复」是积木，里面再放步骤；拖动步骤左边的把手调整顺序、拖进 / 拖出积木，也有上移 / 下移），右边选中步骤的属性（模板缩略图选择、现场采集、在画面上点选坐标 / 画滑动线、「在当前画面上找」只截图测试），底部保存 / 运行。运行时按 `custom_flow.step` 事件高亮正在执行的那一步。离开页面时有未保存的修改会提醒（`useBlocker`）。
- 我的模板：截图（或打开截图）→ 框要认的东西（可选框能点的地方）→ 起名、选「固定 / 会移动」「识别严格度」「变暗时不算」→ 保存并自测。下面列出玩家模板（用在哪些流程、在当前画面上找、删除）。
- 运行记录里自定义流程显示成「流程「名字」」。流程编辑器和我的模板页需要宽画面，不显示右侧栏。

**英雄图鉴（B13）**：左侧菜单「我的模板」下面，正式版也有。头像网格（属性色边框 + 右下角属性图标），默认按发布日期新的在前（没有日期的最后），搜索（中文名 / 英文名 / 昵称 / 编号）、属性 / 职业 / 星级筛选（`lib/heroes.ts` 的 `filterHeroes`，排序同引擎 `search`），右上「检查更新」。宽页面，不显示右侧栏。点开是 `components/heroes/HeroDetailDialog.tsx`（参照 e7.wiki 的角色详情）：角色信息（星级、属性 / 职业 / 星座、发布日期、简介、角色奉献、专属装备（主属性 + 三选一的效果，不显示背景说明）、满级属性；昵称只用来搜索，不显示）/ 技能详情（描述、灵魂燃烧、专属装备效果、技能特效、强化、倍率）/ 配装方案（Fribbels 玩家配装的套装组合、属性中位数表（带速度套的分前 10% / 前 25% / 中位，不带的分快 / 中 / 慢三档）、常用神器）。
- **英雄池模式**（B14e2，`components/heroes/PoolEditor.tsx`；没设置过时一开始就勾着默认的 60 名，右栏标「默认」，底下「恢复默认」（`DELETE /api/rta/pool`）/「全部清空」）：顶部「英雄池」按钮进入（`#/heroes?pool=1`；从 RTA 助手进来的带 `&from=rta`，按钮是「返回 RTA 助手」）。只列选秀模型里有的英雄（`/rta/model` 的 `codes`），按发布日期排；点头像勾选 / 取消（金色描边 + 右上 ✓），筛选条多「只看已勾选」，搜索框按 Enter 勾上第一名；右边 300 像素一列是已勾的英雄（同样按发布日期排）、速度输入（空 = 按段位的常见速度，50–400，不合法标红、不保存）、×、「全部清空」（要确认）。改了 400ms 后 `PUT /api/rta/pool`（`lib/pool.ts` 的 `autoSave`），保存后写进 react-query 的 `qk.rtaPool`；离开页面时立刻保存。窗口不到 1200 宽时属性 / 职业筛选只画图标（`HeroFilters` 的 `shrink`），一行放得下。
- **游戏图标**（B13 审核后加）：属性 `element_<键>`、职业 `role_<键>`、套装 `set_<键>`、属性类型 `stat_<键>`（cp / atk / def / hp / spd / chc / chd / eff / efr / dac）、等级 `grade_<b…sss>`、刻印 `devotion_self` / `devotion_team_<位置>`（群阵影响的位置，1 右、2 下、3 上、4 左）的 PNG 放在 `src/assets/game/`，是从游戏截图里裁出来、按按钮底色抠成透明的；`lib/gameIcons.ts` 用 `import.meta.glob` 按文件名收集，`gameIcon(name)` 没有时返回 undefined（调用方退回色块 / 文字）。

**RTA 助手（B14e1）**：左侧菜单「英雄图鉴」下面，`#/rta`，宽页面。五步手动模式：准备（双方段位、先后手、开战规则（双方都在优胜者以上才有））→ 预禁（`/rta/preban`；只填了一名时按它 `fixed`）→ 选秀（`/rta/advise`：轮到我方给推荐卡，轮到对方给对方可能的选择）→ 后禁（`advise` 的 `ban` 矩阵）→ 结果。布局参考 e7rtabot.com/draft（用户意见）：准备是一张居中卡片（段位 5 个图标：挑战者及以下合成一项、按挑战者发给引擎；开战规则和先后手是分段按钮；有一方不到优胜者时开战规则发 `null`（没有规则，海外这种局就是这么记的），B14h 前发的是「不知道」）；预禁 / 选秀右边一整列是英雄网格（`HeroGrid`，只放模型里有的英雄（`/rta/model` 的 `codes`，`inModel`，B14h 用户意见），按 `/rta/priors` 的被选次数排，预禁时按预禁比例）；选秀左边是信息条 + 双方阵容并排 + 推荐卡，正在选的格子里直接放前 3 名；后禁 / 结果阵容每队一行，下面是矩阵 / 结果。段位图标是 `assets/game/rank_<段位>.png`（从游戏截图裁，没有时写段位名）。
- 局面（`lib/draft.ts`）按「我方 / 对方」记，整局按顺序存 10 手；发给引擎时 `apiState` 换成先手 F / 后手 S，后禁双方都填了才带上。撤销记录和当前局面在 `lib/draftStore.ts`（zustand，放在页面外，切页面不丢；准备里的段位和先后手记在 localStorage）。
- 请求（`lib/rta.ts` 的 `useLatest`）：同一时间只发一个，在途时局面变了只记最新的；结果按局面缓存在页面外。引擎同一时间只跑一个搜索，所以前端不能让旧请求排队。
- 信息条上是「当前胜率」（模型对当前局面的读数），推荐卡上是「预期」（搜索值），两者含义不同（B14e1 审核记录「发现」）；后禁这一步信息条改显示推荐行（已选时是选的那一行）的预期（`banHeadline`，用户意见）。开战规则只有四个按钮：有规则（双方都在优胜者以上）时玩家一定知道是哪条，没选不能开始；每局清空重选。先动概率（`first`）引擎给了才显示（B14h 起随包有速度表）；信息条加上「先动 x%」后 1280 宽放不下一行，1440 以下去掉「段位 / 开战规则 / 预禁」三个文字标签、1200 以下再去掉手数。
- **英雄池**（B14e2）：始终按英雄池推荐我方选人（审核第 2 轮去掉了开关，用户意见）；顶栏（撤销左边）是「英雄池 N 名」（没设置过加「默认」）+「编辑」，去图鉴的英雄池模式。预禁推荐完全不管英雄池（用户选）；填的速度用在先动概率上。advise 的缓存键带上英雄池的 `updated`（`adviceKey`），英雄池改了就重算。右边网格里英雄池的英雄右上角打勾（`PoolMark`），筛选「只看我的」只在轮到我方选人时能用。推荐卡上只因为英雄池才推荐的冷门英雄标「英雄池：名字」（和「数据少」合成一个标记，`rareTag`）；`pool_short` 时推荐上面提示「英雄池里能选的不够，这一轮推荐全部英雄」。信息条在选秀时始终是「我方的读数」（B14e2 审核用户意见：模型读数不知道英雄池，会比所有推荐都高）：标「预期」，我方回合 = 推荐第 1 名的预期和先动，对方回合 = advise 的 `opponent.win`（`pickHeadline`）。英雄池读不到时当没有，推荐照常。顶栏 1200 以下收紧间距才放得下。

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

**两种版本**（发布 0.3.0 起）：
- **正式版**（不带 RTA）：`build.py --no-rta`。`e7engine.spec` 读环境变量 `E7_NO_RTA=1`，不收 `e7helper.core.rta` / `e7helper.api.rta`（`collect_submodules` 过滤 + `excludes`），也不带 `assets/data/rta`（模型、priors、速度表）。冒烟测试改成核对没有 RTA 模型、`/api/rta/model` 是 404。
- **测试版 / 开发**（带 RTA）：不加参数。
- 引擎按代码在不在决定挂不挂 RTA 接口（`e7helper/features.py` 的 `has_rta()`），`GET /api/status`（和 WS 的 hello）带 `features: {"rta": bool}`。GUI 只看这个字段（`lib/store.ts` 的 `useHasRta()`）：没有 RTA 时菜单不显示「RTA 助手」、`#/rta` 回首页、图鉴没有「英雄池」按钮。前端只有一份，用哪种引擎打包就是哪种版本，`pnpm bundle` 不用加参数。
- 两种版本先后打的时候：每次 `build.py` 都会先删掉 `dist/e7engine/` 再冻结，所以打完一种马上 `pnpm bundle`，再打另一种。

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
### `secret_shop` 书签刷取（B04，B12 改版）
| 文件 | 职责 |
|---|---|
| `__init__.py` | `SecretShopModule`（菜单名「书签刷取」）：进店 → 每页扫描顶部/底部 → 买选中的商品 → 没出就计数（够数就停止 / 换世界频道）→ 刷新 → 循环；`setup()` 注册弹窗 `shop_refresh` / `shop_buy`（自动关闭时都点取消）和聊天的 `shop_chat` / `shop_chat_change`（返回键关闭） |
| `page.py` | 纯函数识别：`scan_items`（以「购买」按钮为锚点读名字/价格/金币图标/物品图标）、`read_resources`（先定位顶栏图标再读数）、`read_refresh_cost`、`read_buy_dialog`；决策 `decide` |
| `chat.py` | 换世界频道（B12）：`ChannelSwitcher.switch()`：聊天图标 → 停在骑士团页签就先点「频道」→ 读标题「频道#N」→ ⇆ → 「变更频道」框 → 点输入框 → `ctl.input_text(N+1)` → 核对输入框里的数字 → 点框里的「输入」→ 标题变成 N+1 → 返回键关掉聊天。9999 之后回到 1；底部发消息的输入框绝不碰 |
| `config.py` | `SecretShopConfig`：表单 `items`（三种固定商品，`CATALOG`：誓约书签 / 神秘奖牌 / 友情点数）、`max_refreshes`、`stop_after_misses`、`channel_after_misses`、`dry_run`；开发版 `refresh_cost` / `max_failures` / `probe_dialogs`；内部 `targets`（直接指定，测试用）、`skystone_budget`（默认不限）、`skystone_keep`、`gold_floor`、`probe_channel`（演练时换过去再换回来）。`_migrate_b12` 去掉 B12 之前保存的旧默认值 |
| `stats.py` | `data_dir/history.jsonl`（每次运行一行，含 dry-run、`max_misses`、`channel_switches`）、`stats.json`（实跑累计，含换频道次数）；B12c：`load_history` / `report`（实跑记录按天汇总 + 每次运行明细，中断原因换成「手动停止」等），给 `GET /api/modules/secret_shop/report?runs=500` 用 |

- **刷取历史**（B12c，GUI `src/modules/secret_shop/ShopHistory.tsx`，数据和汇总在 `report.ts`）：书签刷取页底部代替「最近运行」。时间范围 近 7 天 / 近 30 天 / 全部（记在 localStorage）；商品卡（出了几次、共几个、平均刷几次出一次 = 页数 ÷ 次数）、刷新次数 / 天空石 / 金币 / 运行次数；每天刷新次数柱状图（「全部」跨度超过 45 天按周），柱子上方标出买到的书签 / 奖牌，悬停看明细；每次运行列表（默认 6 条，可展开）。dry-run 的记录不算。原「统计」页 B12c 删掉了，引擎的 `GET /api/modules/{id}/stats` 留着。
- 「没出」= 这一页（进店时的列表 + 每次刷新后）没有任何选中的商品，买没买到都不算没出；出了就清零。连续 N 页没出就停止（不再刷新）；连续页数是 M 的倍数时换一次频道。
- 换频道失败（界面没出现、数字没输进去、标题没变）只记一次失败，关掉聊天接着刷。

写有消耗操作的任务可以参考它的做法：
- **按资源读数差确认**，不按点击次数计。读数差为 0 不计数，算失败；为其他值立即停止（任务记为失败）。
- 有消耗的确认框注册成本模块的弹窗，`Dismiss` 点取消；只有任务自己在核对内容后点确认。
- 顶栏数字连续两帧一致才采用（数字有滚动动画）。
- 离线测试用 `tests/shop_sim.py` 这类模拟器：点到确认默认进入 DANGER，按需模拟扣费、吞点击、网络重试、重复扣费。

### `repeat_battle` 重复刷关：托管战斗 + 手动刷关（B06，讨伐异界 B12a）
| 文件 | 职责 |
|---|---|
| `__init__.py` | `RepeatBattleModule`：大厅 → 战斗 → 讨伐 → 选地下城（OCR，必要时翻页）→ 选难度（OCR，难度卡片随地下城变化）→ 准备界面（或 `start_here`）；托管：完成就结算、没有就按配置重开；手动：切普通战斗 → 战斗开始 → CLEAR → 确认 → 重新进行 → 循环，每回到准备界面检查托管；行动力（异界：光谱核心）不够时可选叶子 / 天空石补充。`setup()` 注册场景 `rb_menu` / `rb_hunt` / `rb_prep` / `rb_battle` / `rb_clear` / `rb_result` / `rb_after` 和弹窗 `rb_auto`（托管进度框）/ `rb_auto_setup` / `rb_auto_settled` / `rb_auto_confirm`（点取消）/ `rb_energy`（点取消）/ `rb_core`（购买光谱核心，点取消） |
| `page.py` | 纯函数识别：顶栏行动力 / 天空石 / 光谱核心 / 托管图标（`auto_state` + `auto_dot` + `dots_match`）、讨伐列表与难度、准备界面、托管进度框 / 设置框、`plan_auto`（份数与将使用的行动力或核心 / 叶子）、行动力不足框、购买光谱核心框（`read_core_dialog`）、战后读数、自动战斗图标 |
| `config.py` | `RepeatBattleConfig`、`Hunt`（飞龙 / 魔像 / 报丧妖 / 阿吉玛纳克 / 卡戴斯 / 食人魔）、`Tier`（中级 / 上级 / 地狱级 / 异界）、`OTHERWORLD_ONLY`（只有异界的地下城：食人魔） |
| `stats.py` | `history.jsonl`、`stats.json`（手动场次、托管结算 / 重开、行动力、光谱核心、叶子、天空石） |

- 托管 = 游戏以前的「重复战斗」：设份数（1 份 = 4 次），用行动力或叶子付费，后台按最快通关记录自动打；「无记录」的关卡开不了，且「无记录」只在普通战斗模式显示。
- 托管是否完成看顶栏图标左上的红点。图标可能整体变灰（从「重新进行」回到准备界面时），要按表盘亮度归一化；进行中的光弧单帧可能扫过红点位置，要隔 0.6 秒看 3 帧、红点位置不变才算完成。
- 一场按战后「持有行动力」的减少量核对：讨伐会掉落行动力，只检查「不超过一场的消耗」。
- 托管份数上限 `auto_max_units`（表单「托管最多几份」，B12a 起在表单里）：0 = 能凑几份就几份。
- 进行中的托管框只点底部空白关闭，绝不点「中断」。
- **讨伐异界**（B12a）消耗**光谱核心**（顶栏行动力左边的红色图标，只在讨伐列表 / 准备界面显示）：
  - 准备界面没有快速战斗，也没有切换钮（原来切换钮的位置是「战斗开始」按钮的右端，不能点）；按钮上是核心「消耗/持有」；
  - 胜利后没有 CLEAR 和结算页：宝珠画面「请轻触屏幕领取奖励。」（场景 `rb_ow_reward`）点一下，直接到战后界面「完成奖励」（`rb_after`，按钮和普通难度相同）；
  - 托管 1 次 = 1 个核心或 2 片叶子；份数框显示叶子数（最少 2，+1 加 2）；勾选框是「优先使用持有的光谱核心」。`plan_auto` 用 `runs_per_unit` / `leaves_per_unit` 区分（普通 4 / 1，异界 1 / 2）；设置框「1 次消耗」的叶子读数（0.25 / 2）不对就不开；
  - 补充：点顶栏核心图标打开「购买光谱核心」框（叶子 2 换 1、天空石 80 换 1、数量「1/N」保持 1），不点「战斗开始」去触发；核对后买 1 个，按顶栏核心 +1 和天空石读数差确认。核心不会自然回复，核对不留余量；
  - 只有食人魔只有异界一种难度；GUI 选食人魔时难度锁定成异界（`ModuleUI.fieldLocks`），引擎收到别的难度直接停止并提示。

### `daily` 日常收取：邮件 / 精灵之森 / 誓约免费召唤 / 商店 / 竞技场（B07，竞技场 B12 并入，商店 B12b）
| 文件 | 职责 |
|---|---|
| `__init__.py` | `DailyModule`：按 邮件 → 精灵之森 → 誓约召唤 → 商店 → 竞技场 的顺序做（各有开关），每项前后回到大厅；一项失败不影响其他项（任务最后记为失败），核对异常（`DailyAnomaly`）立即停止整个任务。`setup()` 注册场景 `daily_mail` / `daily_forest` / `daily_covenant` / `daily_summon` / `daily_summon_anim` / `daily_summon_hero` / `daily_summon_results` 和弹窗 `daily_forest_reward`（点击关闭）/ `daily_mail_detail`（自动关闭时点「点击关闭」，不收信） |
| `page.py` | 纯函数识别：邮件行（「领取」锚点 + 剩余时间 OCR）、邮件数、邮件详情框；精灵之森三张卡和照料；誓约召唤的免费按钮、剩余免费气泡、顶栏货币区域 |
| `ledger.py` | 按天记账 `ledger.json`：游戏日（北京时间 3 点 = UTC 19:00 切换）、当天做完的项（`covenant`、`arena_buy`、商店每日商品 `shop:<id>`）、精灵之森下次时间；B12b 加按周记账：游戏周（周一的每日重置切换，用那周周一命名）、本周买完的商店每周商品 `week_done` |
| `config.py` / `stats.py` | `DailyConfig`（表单是五项开关、商店的 `shop_items`、`arena_buy_flags` 和 `dry_run`）；`ShopItem` 枚举；`history.jsonl`、`stats.json`（含竞技场场次 / 胜场 / 旗帜 / 补旗、商店购买次数） |
| `errors.py` | 各项共用的 `StopItem` / `ItemFailed` / `DailyAnomaly` |

- 账本只用来省导航：誓约召唤当天用完就不进去；竞技场当天补过旗就不再打开补旗框；精灵之森按界面上最短的倒计时决定下次进入时间。能不能领、领没领到都以画面为准。
- 「有没有花东西」的核对：召唤前后对比**顶栏货币区域的画面**，比逐个 OCR 读数可靠，不受图标和数字宽度影响。前后各取两帧（间隔 0.6 秒），两两比较都变了的像素 ≤ 60 才算没变：背景立绘的星星光效会飘进这块区域（单帧最多约 80 个像素，只出现一帧）；数字真的变化时是 5000+。其他有多种货币的界面也可以这样核对。
- 「点击关闭」在多个弹窗里都有（竞技场战斗记录、托管结算完毕、精灵之森奖励），模块弹窗要加背景场景的标题来区分。

#### 商店（`shop.py` / `shop_page.py`；B12b）
| 文件 | 职责 |
|---|---|
| `shop.py` | `Shop`（不是模块，借用日常收取的 ctl / vision / 统计 / 账本）：大厅「商店」→ 交易所 › 竞技场 → 商店 › 一般 → 商店 › 传承石，每页从左往右扫、按名字找 `CATALOG` 里选中的商品，买完重新扫（买完的会移到列表最后），滑不动就是到头，买过东西就从头再扫一遍。`register()` 注册场景 `daily_shop_store` / `daily_shop_exchange` 和弹窗 `daily_shop_buy` / `daily_shop_buy1`（购买商品框，点取消）/ `daily_shop_reward`（获得奖励，点击关闭）。`ShopAnomaly` 是 `DailyAnomaly` |
| `shop_page.py` | 纯函数识别：`scan_cards`（两行商品名 OCR → 卡片中心；右上「剩余/上限」、按钮绿 = 能买、价格图标 + 数字）、`read_dialog`（三种布局：有数量条 / 只能买 1 个 / 越买越贵）、`read_top`（顶栏按图标定位读数）、`tab_selected`（页签下的亮光带）、`is_reward` |

- `CATALOG`：每件商品的名字、所在页、货币、单价（越买越贵的为 None）、限购上限、每日 / 每周。同名商品用上限和价格图标区分（一般页有一张用生命之叶买的光谱核心）。
- 只用 免费 / 友情点数 / 行动力 / 银光传承石 / 竞技场点数；价格图标认不出的（天空石、生命之叶、传承石）一律不买。
- 点「购买」前核对购买框（名字、货币、剩余次数、数量条按「最多」、总价 = 单价 × 数量、够付）；买完核对天空石不变、付款货币正好减少总价（行动力允许少减 3 点，自然恢复），核对不过立即停止整个任务。「获得奖励」框只有部分商品有（入场券类只在顶部飘一条提示），出现就点击关闭，只有免费商品要求看到它。
- 亲密度献礼选择箱每周只买 `shop_affinity_weekly`（默认 5）次，按卡片上的「剩余/上限」算。
- 内部字段：`shop_affinity_weekly`、`shop_max_buys`、`shop_probe_dialogs`。模板在 `assets/daily/cn/shop/`；流程守卫引用 `daily:shop/dlg/*`。

#### 竞技场（`arena.py` / `arena_page.py`；B05 的 `arena_npc` 模块，B12 按用户意见并入日常收取）
| 文件 | 职责 |
|---|---|
| `arena.py` | `Arena`（不是模块，借用日常收取的 ctl / vision / 统计 / 账本）：大厅 → 模式选择 → NPC对战页 → 选第一行 → 挑战 → 准备界面（优先快速对战，当天次数用完切普通战斗）→ 结算点确认 → 循环；旗帜用完且开了补旗时，点顶栏「+」用友情点数补一次（成功后账本记 `arena_buy`，当天不再打开补旗框）。`register()` 注册场景 `arena_main` / `arena_npc` / `arena_prep` / `arena_battle` / `arena_result` 和弹窗 `arena_record`（点击关闭）/ `arena_buy_flags`（点取消）。`StopArena` 是 `StopItem`，`ArenaAnomaly` 是 `DailyAnomaly` |
| `arena_page.py` | 纯函数识别：`read_flags`（顶栏旗帜）、`read_prep`（模式 + 快速对战剩余次数）、`is_victory`、`read_buy_dialog`（哪个选项被选中、消耗、持有）、`auto_icon`（自动战斗图标区域，用于判断是否在转） |

- 模板在 `assets/daily/cn/arena/`（`arena/tab/npc`、`arena/buy/ok` 等）；流程守卫引用 `daily:arena/buy/*`。
- 配置：表单 `arena`（默认开）、`arena_buy_flags`（默认关）；内部 `arena_max_battles`、`arena_prefer_quick`、`arena_friendship_keep`、`arena_battle_timeout`、`arena_probe_dialogs`。
- 一场 = 看到结算 + 旗帜读数减少 1；补旗 = 旗帜读数增加 5。读数差异常立即停止整个任务（任务记为失败）。
- 自动战斗：图标静止约 0.6 秒才认为没开（开启后图标一直旋转），点完再观察，不会误关。
- 普通战斗中不按返回键（会打开暂停菜单）：只有网络异常立即重试，其他弹窗持续 10 秒才交给内置规则。
- 内置场景 `arena` 从 B05 起只认模式选择界面（加了 `common/arena/mode_arena`）；竞技场里其他界面的标题也是「竞技场」，由日常收取注册的场景区分。CLI `scene` 只加载内置场景，在这些界面上显示「未知」。
- 回大厅：结算点「确认」，其余界面点返回（准备界面 → NPC 页 → 模式选择 → 大厅）。

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
