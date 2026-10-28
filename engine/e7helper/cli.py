"""命令行入口：uv run e7helper <command>"""

from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import cv2
import numpy as np
import typer
from rich.table import Table

from e7helper import GAME_PACKAGE, __version__
from e7helper.core.geometry import BASE_HEIGHT, BASE_WIDTH, FULL_SCREEN, Rect, is_16_9
from e7helper.core.imageio import read_image, write_image
from e7helper.core.log import make_console, setup_logging
from e7helper.core.runtime import PopupError, Runtime, TaskStatus
from e7helper.core.scene import SceneState, default_detector
from e7helper.core.stdio import isolate_native_stdout
from e7helper.core.vision import TemplateMeta, TemplateStore, Vision, best_match, find_all
from e7helper.device import Backend, DeviceError, MuMuManager, connect, find_install
from e7helper.modules import AssistantModule, ModuleKind, TaskModule, discover

app = typer.Typer(help=f"e7helper {__version__} — 第七史诗国服 · MuMu 专用助手", no_args_is_help=True)
console = make_console()

IndexOpt = Annotated[Optional[int], typer.Option("--index", "-i", help="MuMu 实例序号，默认取第一个已启动的")]
RootOpt = Annotated[Optional[str], typer.Option("--mumu-root", help="MuMu 安装根目录，默认自动查找")]


@app.callback()
def _main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    isolate_native_stdout()
    setup_logging(logging.DEBUG if verbose else logging.INFO)


def _ok(msg: str) -> None:
    console.print(f"[green]✔[/] {msg}")


def _warn(msg: str) -> None:
    console.print(f"[yellow]![/] {msg}")


def _fail(msg: str) -> None:
    console.print(f"[red]✘[/] {msg}")


@app.command()
def doctor(index: IndexOpt = None, mumu_root: RootOpt = None) -> None:
    """环境自检：MuMu 安装、实例、IPC/adb、分辨率、游戏、模块。"""
    problems = 0

    try:
        install = find_install(mumu_root)
    except DeviceError as e:
        _fail(str(e))
        raise typer.Exit(1)
    _ok(f"MuMu 安装目录：{install.root}")
    _ok(f"MuMuManager：{install.manager_exe}")
    if install.ipc_dll:
        _ok(f"IPC DLL：{install.ipc_dll}")
    else:
        _warn("未找到 external_renderer_ipc.dll，只能使用较慢的 adb 截图")
    manager = MuMuManager(install)
    console.print(f"  MuMu 版本：{manager.version()}")

    instances = manager.instances()
    table = Table("序号", "名称", "Android", "状态", "adb")
    for info in instances:
        state = "[green]运行中[/]" if info.android_started else "[dim]未启动[/]"
        table.add_row(str(info.index), info.name, info.android_version, state, info.adb_serial or "-")
    console.print(table)

    try:
        device = connect(index, Backend.AUTO, mumu_root)
    except DeviceError as e:
        _fail(f"连接实例失败：{e}")
        raise typer.Exit(1)

    with device:
        _ok(f"已连接 {device.name}，主通道：{device.active_backend}")
        if device.adb is None:
            _warn("adb 后备通道不可用")
            problems += 1
        w, h = device.resolution
        if (w, h) == (BASE_WIDTH, BASE_HEIGHT):
            _ok(f"分辨率 {w}x{h}（与基准一致）")
        elif is_16_9(w, h):
            _warn(f"分辨率 {w}x{h}：16:9 可自动缩放，但推荐设置为 {BASE_WIDTH}x{BASE_HEIGHT}")
        else:
            _fail(f"分辨率 {w}x{h} 不是 16:9，请在 MuMu 设置中改为平板 {BASE_WIDTH}x{BASE_HEIGHT}")
            problems += 1
        frame = device.screenshot()
        if frame.shape[:2] == (h, w) and frame.std() > 1:
            _ok("截图正常")
        else:
            _fail(f"截图异常：shape={frame.shape}, std={frame.std():.2f}")
            problems += 1
        if device.adb:
            if device.adb.has_package(GAME_PACKAGE):
                _ok(f"已安装第七史诗国服（{GAME_PACKAGE}）")
            else:
                _fail(f"未检测到第七史诗国服（{GAME_PACKAGE}）")
                problems += 1

    modules = discover()
    _ok(f"发现 {len(modules)} 个模块：{', '.join(modules) or '无'}")

    if problems:
        _warn(f"存在 {problems} 个问题")
        raise typer.Exit(1)
    _ok("全部检查通过")


def _time_capture(fn, n: int) -> list[float]:
    fn()  # 预热
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


@app.command()
def bench(index: IndexOpt = None, mumu_root: RootOpt = None, n: Annotated[int, typer.Option("-n")] = 30) -> None:
    """比较 IPC 与 adb 截图耗时。"""
    with connect(index, Backend.AUTO, mumu_root) as device:
        table = Table("通道", "次数", "平均 ms", "中位 ms", "最小 ms", "最大 ms", "约 FPS")
        for name, fn, count in (
            ("ipc", device.ipc.capture if device.ipc else None, n),
            ("adb", device.adb.screenshot if device.adb else None, max(3, n // 5)),
        ):
            if fn is None:
                table.add_row(name, "-", "不可用", "", "", "", "")
                continue
            ts = _time_capture(fn, count)
            mean = statistics.mean(ts)
            table.add_row(
                name, str(count), f"{mean:.1f}", f"{statistics.median(ts):.1f}",
                f"{min(ts):.1f}", f"{max(ts):.1f}", f"{1000 / mean:.0f}",
            )
        console.print(table)


@app.command()
def screenshot(
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
    backend: Annotated[Backend, typer.Option("--backend", "-b")] = Backend.AUTO,
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="输出 PNG 路径")] = None,
) -> None:
    """截一张图保存为 PNG。"""
    with connect(index, backend, mumu_root) as device:
        frame = device.screenshot()
        if out is None:
            out = Path("screenshots") / f"{datetime.now():%Y%m%d_%H%M%S}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", frame)  # imwrite 不支持中文路径
        if not ok:
            raise typer.Exit(1)
        out.write_bytes(buf.tobytes())
        _ok(f"{frame.shape[1]}x{frame.shape[0]}（{device.active_backend}）→ {out.resolve()}")


@app.command()
def tap(
    x: int,
    y: int,
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
    backend: Annotated[Backend, typer.Option("--backend", "-b")] = Backend.AUTO,
) -> None:
    """在设备坐标 (x, y) 点击一次（调试用）。"""
    with connect(index, backend, mumu_root) as device:
        device.tap(x, y)
        _ok(f"tap ({x}, {y}) via {device.active_backend}")


@app.command("modules")
def list_modules(schema: Annotated[bool, typer.Option("--schema", help="输出配置 JSON Schema")] = False) -> None:
    """列出已发现的模块。"""
    modules = discover()
    if schema:
        console.print_json(json.dumps({k: v.config_schema() for k, v in modules.items()}, ensure_ascii=False))
        return
    table = Table("id", "名称", "类型", "说明", "来源")
    for mid, cls in modules.items():
        table.add_row(mid, cls.name, cls.kind.value, cls.description, cls.__module__)
    console.print(table)


@app.command()
def run(
    module_id: str,
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
    config: Annotated[Optional[str], typer.Option("--config", "-c", help="模块配置 JSON 字符串")] = None,
    timeout: Annotated[Optional[float], typer.Option("--timeout", "-t", help="任务时限（秒），超时自动急停")] = None,
    duration: Annotated[Optional[float], typer.Option("--duration", "-d", help="助手模块运行时长（秒），默认直到 Ctrl+C")] = None,
) -> None:
    """经 runtime 运行一个模块：任务模块跑完即退出；助手模块持续收帧直到 Ctrl+C。"""
    modules = discover()
    cls = modules.get(module_id)
    if cls is None:
        _fail(f"未知模块：{module_id}（可用：{', '.join(modules)}）")
        raise typer.Exit(1)
    cfg = cls.config_model.model_validate_json(config) if config else cls.config_model()
    with connect(index, Backend.AUTO, mumu_root) as device, Runtime(device) as rt:
        if cls.kind is ModuleKind.TASK and issubclass(cls, TaskModule):
            result = rt.run_task(cls, cfg, timeout=timeout)
            line = f"{module_id}：{result.status.value}（{result.duration:.1f} 秒）"
            if result.ok:
                _ok(line)
                return
            (_warn if result.status is TaskStatus.STOPPED else _fail)(line)
            if result.debug_dir:
                console.print(f"  调试信息：{result.debug_dir}")
            raise typer.Exit(1)
        if cls.kind is ModuleKind.ASSISTANT and issubclass(cls, AssistantModule):
            rt.attach_assistant(cls, cfg)
            end = None if duration is None else time.monotonic() + duration
            try:
                while end is None or time.monotonic() < end:
                    time.sleep(0.2)
            except KeyboardInterrupt:
                _warn("已中断")
            return
        _fail(f"{module_id} 既不是任务模块也不是助手模块")
        raise typer.Exit(1)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="监听地址；默认只监听本机")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="端口；0 表示随机（实际端口写进 api.json）")] = 47800,
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
    token: Annotated[Optional[str], typer.Option("--token", envvar="E7_API_TOKEN",
                                                 help="指定 token；默认每次启动随机生成")] = None,
    no_auth: Annotated[bool, typer.Option("--no-auth", help="不校验 token（开发用；Host 校验仍然生效）")] = False,
    allow_host: Annotated[Optional[list[str]], typer.Option("--allow-host", help="额外允许的 Host 名，可多次指定")] = None,
    paused: Annotated[bool, typer.Option("--paused", help="调度器以暂停状态启动（会写进 schedules.json）")] = False,
    no_connect: Annotated[bool, typer.Option("--no-connect", help="启动时不自动连接设备")] = False,
) -> None:
    """启动 API 服务（REST + WebSocket + 定时调度）。端口和 token 写进 <数据目录>/api.json。"""
    import os
    import socket

    import uvicorn

    from e7helper.api import Engine, create_app, generate_token
    from e7helper.api.auth import LOCAL_HOSTS, RedactTokenFilter
    from e7helper.api.engine import default_device_factory, write_json_atomic
    from e7helper.core.paths import data_dir

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as e:
        _fail(f"无法监听 {host}:{port}：{e}")
        raise typer.Exit(1)
    port = sock.getsockname()[1]
    token = None if no_auth else (token or generate_token())
    allowed = set(LOCAL_HOSTS) | {h.lower() for h in allow_host or ()}
    if host not in ("0.0.0.0", "::"):
        allowed.add(host.lower())

    for name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(RedactTokenFilter())
    engine = Engine(device_factory=default_device_factory(mumu_root), index=index)
    info_path = data_dir() / "api.json"
    pid = os.getpid()

    def remove_info() -> None:
        try:
            if json.loads(info_path.read_text(encoding="utf-8")).get("pid") == pid:
                info_path.unlink()
        except (OSError, ValueError):
            pass

    api = create_app(engine, token=token, allowed_hosts=frozenset(allowed), autoconnect=not no_connect,
                     on_shutdown=[remove_info])
    if paused:
        api.state.services.scheduler.set_paused(True)
    url_host = f"[{host}]" if ":" in host else host
    url = f"http://{url_host}:{port}"
    write_json_atomic(info_path, {"pid": pid, "url": url, "host": host, "port": port, "token": token,
                                  "started": datetime.now().isoformat(timespec="seconds")})
    _ok(f"API 服务：{url}（接口文档 {url}/docs）")
    console.print(f"  token：{token or '[yellow]未启用（--no-auth）[/]'}；已写入 {info_path}")
    server = uvicorn.Server(server_config(api))
    # POST /api/shutdown（B09）：GUI 退出时让自己拉起的引擎正常关闭（急停任务、断开设备、删 api.json）
    api.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    try:
        server.run(sockets=[sock])
    finally:
        remove_info()  # 启动失败等没走到 lifespan 关闭的情况


# Windows 上 asyncio 默认的 Proactor 事件循环有两个毛病（B12 反馈 7，CPython 3.13 实测）：
# - 客户端在被 accept 的瞬间断开（浏览器刷新 / 关页），accept 报 WinError 64，Proactor 会把监听 socket 关掉，
#   之后整个 API 再也连不上；
# - 对端已重置的连接，关闭时 shutdown() 抛错，连接没从 asyncio.Server 里摘掉，关服务时 wait_closed() 一直等。
# Selector 事件循环没有这两个问题；引擎不用 asyncio 子进程（Selector 在 Windows 上唯一不支持的东西）。
SERVER_LOOP = "asyncio:SelectorEventLoop"
GRACEFUL_SHUTDOWN = 5.0  # 关服务时最多等连接 / 后台任务这么多秒，超时就取消（兜底，正常 1 秒内关完）


def server_config(api) -> uvicorn.Config:  # noqa: F821 —— uvicorn 在函数里导入（启动快）
    import uvicorn

    return uvicorn.Config(api, log_config=None, access_log=False, ws="websockets-sansio", lifespan="on",
                          loop=SERVER_LOOP, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN)


def _print_state(label: str, state: SceneState) -> None:
    color = "green" if state.clear and state.scene else ("yellow" if state.popup else "red")
    extra = "（画面被压暗）" if state.obscured else ""
    hits = "  ".join(f"{k}={m.score:.2f}" for k, m in state.matches.items())
    console.print(f"{label}[{color}]{state}[/]{extra}  [dim]{state.elapsed_ms:.0f}ms  {hits}[/]")


@app.command("scene")
def scene_cmd(
    files: Annotated[Optional[list[Path]], typer.Option("--from", "-f", help="从图片文件识别（可多次指定）")] = None,
    dismiss: Annotated[bool, typer.Option("--dismiss", help="自动关闭当前弹窗（会点击游戏）")] = False,
    watch: Annotated[bool, typer.Option("--watch", "-w", help="持续识别，场景变化时打印，直到 Ctrl+C")] = False,
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
) -> None:
    """识别当前场景和弹窗；--dismiss 关闭弹窗，--watch 持续观察。"""
    detector = default_detector()
    if files:
        for f in files:
            _print_state(f"{f.name}: ", detector.detect(read_image(f)))
        return
    with connect(index, Backend.AUTO, mumu_root) as device, Runtime(device, scenes=detector) as rt:
        ctl = rt.make_controller()
        state = ctl.detect()
        _print_state("", state)
        if dismiss and not state.clear:
            try:
                closed = ctl.dismiss_popups(state=state)
            except PopupError as e:
                _fail(str(e))
                raise typer.Exit(1)
            _ok(f"已关闭：{', '.join(closed)}")
            _print_state("", ctl.detect())
        if watch:
            last = (state.scene, state.popup)
            try:
                while True:
                    time.sleep(0.5)
                    state = ctl.detect()
                    if (state.scene, state.popup) != last:
                        last = (state.scene, state.popup)
                        _print_state(f"{datetime.now():%H:%M:%S} ", state)
            except KeyboardInterrupt:
                pass


# ---------------------------------------------------------------- 视觉调试与模板采集（B02）

FromOpt = Annotated[Optional[Path], typer.Option("--from", "-f", help="从图片文件读帧，不连接设备")]
RectOpt = Annotated[Optional[str], typer.Option("--rect", "-r", help="区域 x,y,w,h（1600x900 基准）")]
LangOpt = Annotated[str, typer.Option("--lang", help="资源语言目录")]


def _grab(from_file: Optional[Path], index: Optional[int], mumu_root: Optional[str]) -> np.ndarray:
    if from_file is not None:
        return read_image(from_file)
    with connect(index, Backend.AUTO, mumu_root) as device:
        return device.screenshot()


def _to_base(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    if (w, h) == (BASE_WIDTH, BASE_HEIGHT):
        return frame
    if not is_16_9(w, h):
        _warn(f"帧尺寸 {w}x{h} 不是 16:9，缩放到基准后会变形")
    return cv2.resize(frame, (BASE_WIDTH, BASE_HEIGHT), interpolation=cv2.INTER_AREA)


def _parse_rect(value: Optional[str], what: str) -> Optional[Rect]:
    if value is None:
        return None
    try:
        return Rect.parse(value)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint=what) from e


def _select_roi(frame: np.ndarray, title: str) -> Optional[Rect]:
    """弹出 OpenCV 窗口框选区域：拖动框选，回车/空格确认，c 或 Esc 取消。"""
    cv2.namedWindow(title, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)  # highgui 窗口标题不支持中文
    cv2.resizeWindow(title, 1280, 720)
    x, y, w, h = cv2.selectROI(title, frame, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(title)
    return Rect(x, y, w, h) if w > 0 and h > 0 else None


@app.command()
def capture(
    module_id: Annotated[str, typer.Argument(help="模块 id（跨模块共用的模板用 common）")],
    name: Annotated[str, typer.Argument(help="模板名，可带子目录，如 shop/refresh")],
    from_file: FromOpt = None,
    rect: Annotated[Optional[str], typer.Option("--rect", "-r", help="模板区域 x,y,w,h；省略时弹窗框选")] = None,
    search: Annotated[Optional[str], typer.Option("--search", "-s", help="检索区域 x,y,w,h；默认为模板区域外扩 --margin")] = None,
    margin: Annotated[int, typer.Option("--margin", "-m", help="默认检索区域相对模板区域的外扩像素")] = 40,
    full: Annotated[bool, typer.Option("--full", help="检索区域为全屏（位置不固定的元素）")] = False,
    threshold: Annotated[float, typer.Option("--threshold", "-t")] = 0.85,
    gray: Annotated[bool, typer.Option("--gray", help="灰度匹配")] = False,
    max_diff: Annotated[Optional[float], typer.Option("--max-diff", help="颜色校验：平均像素差上限（0-255），区分亮/暗按钮时用")] = None,
    note: Annotated[str, typer.Option("--note", "-n")] = "",
    tap: Annotated[Optional[str], typer.Option("--tap", help="点击区域 x,y,w,h（可点区域与模板不一致时）")] = None,
    lang: LangOpt = "cn",
    force: Annotated[bool, typer.Option("--force", help="覆盖已有模板")] = False,
    save_frame: Annotated[Optional[Path], typer.Option("--save-frame", help="同时把整帧（基准尺寸）存到此路径")] = None,
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
) -> None:
    """截图并框选保存模板（png + json），随后立即回验匹配分数。"""
    frame = _to_base(_grab(from_file, index, mumu_root))
    box = _parse_rect(rect, "--rect") or _select_roi(frame, f"capture {module_id}/{name}")
    if box is None:
        _warn("已取消")
        raise typer.Exit(1)
    box = box.clip()
    if box.area == 0:
        _fail("模板区域在画面外")
        raise typer.Exit(1)
    if full:
        region = None
    else:
        region = _parse_rect(search, "--search") or box.expand(margin).clip()
        if not region.contains(box):
            _fail(f"检索区域 {tuple(region)} 没有包含模板区域 {tuple(box)}")
            raise typer.Exit(1)

    store = TemplateStore.for_module(module_id, lang)
    meta = TemplateMeta(region=region, box=box, tap=_parse_rect(tap, "--tap"), threshold=threshold, grayscale=gray,
                        max_diff=max_diff, note=note)
    try:
        tpl = store.save(name, box.crop(frame).copy(), meta, overwrite=force)
    except (FileExistsError, ValueError) as e:
        _fail(f"{e}（已存在时加 --force 覆盖）" if isinstance(e, FileExistsError) else str(e))
        raise typer.Exit(1)
    _ok(f"已保存 {tpl.path}（{tpl.size[0]}x{tpl.size[1]}）")
    if save_frame is not None:
        _ok(f"整帧 → {write_image(save_frame, frame).resolve()}")

    # 回验：原位置的分数 + 检索区域内其他位置的最高分（越低说明模板区分度越好）
    m = best_match(frame, tpl, region=box.expand(4).clip())
    if m is None or m.score < threshold:
        _fail(f"回验失败：{m}")
        raise typer.Exit(1)
    _ok(f"回验：{m}")
    others = [h for h in find_all(frame, tpl, threshold=-1.0, max_count=5) if h.rect.iou(box) < 0.5]
    if others:
        o = others[0]
        msg = f"检索区域内其他位置最高分 {o.score:.3f} @ {tuple(o.rect)}（阈值 {threshold}）"
        if o.score >= threshold:
            _warn(msg + "：存在多个相似位置，find 只返回分数最高者；必要时缩小检索区域或提高阈值")
        else:
            console.print(f"  {msg}")


@app.command("match")
def match_cmd(
    module_id: Annotated[str, typer.Argument(help="模块 id")],
    names: Annotated[Optional[list[str]], typer.Argument(help="模板名；省略时测试该模块全部模板")] = None,
    from_file: FromOpt = None,
    rect: RectOpt = None,
    all_hits: Annotated[bool, typer.Option("--all", "-a", help="列出所有超过阈值的命中")] = False,
    lang: LangOpt = "cn",
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
) -> None:
    """用当前画面（或文件）测试模板匹配分数。"""
    vision = Vision.for_module(module_id, lang)
    if not names:
        names = vision.stores[0].names()
        if not names:
            _warn(f"{vision.stores[0].root} 下没有模板")
            raise typer.Exit(1)
    frame = _grab(from_file, index, mumu_root)
    region = _parse_rect(rect, "--rect")
    table = Table("模板", "阈值", "分数", "diff", "位置 x,y,w,h", "结果", "耗时 ms")
    for name in names:
        tpl = vision.template(name)
        t = time.perf_counter()
        m = best_match(frame, tpl, region)
        hits = find_all(frame, tpl, region) if all_hits else []
        dt = (time.perf_counter() - t) * 1000
        if m is None:
            table.add_row(name, f"{tpl.threshold:.2f}", "-", "-", "-", "[red]模板大于检索区域[/]", f"{dt:.1f}")
            continue
        md = tpl.meta.max_diff
        ok = m.score >= tpl.threshold and (md is None or m.diff <= md)
        result = "[green]命中[/]" if ok else "[red]未命中[/]"
        if all_hits:
            result += f" ×{len(hits)}"
        diff = f"{m.diff:.1f}" + (f"/{md:g}" if md is not None else "")
        table.add_row(name, f"{tpl.threshold:.2f}", f"{m.score:.3f}", diff, ",".join(map(str, m.rect)), result, f"{dt:.1f}")
        for h in hits:
            if h.rect != m.rect:
                table.add_row("", "", f"{h.score:.3f}", f"{h.diff:.1f}", ",".join(map(str, h.rect)), "", "")
    console.print(table)


@app.command("ocr")
def ocr_cmd(
    from_file: FromOpt = None,
    rect: RectOpt = None,
    line: Annotated[bool, typer.Option("--line", "-l", help="单行识别（跳过检测，需要 --rect）")] = False,
    number: Annotated[bool, typer.Option("--number", help="按数字解析（隐含 --line）")] = False,
    index: IndexOpt = None,
    mumu_root: RootOpt = None,
) -> None:
    """对当前画面（或文件）做 OCR。"""
    from e7helper.core.vision import default_ocr, parse_number

    frame = _grab(from_file, index, mumu_root)
    region = _parse_rect(rect, "--rect")
    if (line or number) and region is None:
        raise typer.BadParameter("单行识别需要 --rect", param_hint="--rect")
    ocr = default_ocr()
    t = time.perf_counter()
    ocr.warmup()
    console.print(f"[dim]模型加载 {(time.perf_counter() - t) * 1000:.0f} ms[/]")
    t = time.perf_counter()
    if line or number:
        r = ocr.read_line(frame, region)
        console.print(f"{r}  {(time.perf_counter() - t) * 1000:.1f} ms")
        if number:
            console.print(f"数字：{parse_number(r.text)}")
        return
    results = ocr.read(frame, region or FULL_SCREEN)
    dt = (time.perf_counter() - t) * 1000
    table = Table("文本", "置信度", "位置 x,y,w,h")
    for r in results:
        table.add_row(r.text, f"{r.score:.2f}", ",".join(map(str, r.rect)))
    console.print(table)
    console.print(f"[dim]{len(results)} 条，{dt:.0f} ms[/]")


@app.command("heroes")
def heroes_cmd(
    query: Annotated[Optional[str], typer.Argument(help="按名字 / 英文名 / 别名 / 编号搜索")] = None,
    update: Annotated[bool, typer.Option("--update", help="联网更新（写进数据目录）")] = False,
    bundled: Annotated[bool, typer.Option("--bundled", help="（开发）和 --update 一起用：更新随包数据 assets/data/heroes")] = False,
    no_icons: Annotated[bool, typer.Option("--no-icons", help="更新时不下载头像")] = False,
) -> None:
    """英雄数据库（B13）：查英雄、联网更新。"""
    from e7helper.core.data import ELEMENT_LABELS, ROLE_LABELS, heroes, load_heroes, reload_heroes
    from e7helper.core.data import hero_update
    from e7helper.core.data.hero_db import DATA_FILE, DATA_NAME, read_hero_file
    from e7helper.core.paths import bundled_data_dir, user_data_dir

    if update:
        if bundled:
            target = bundled_data_dir(DATA_NAME)
            current, other_dirs = read_hero_file(target / DATA_FILE), []
        else:
            db = load_heroes()
            target = user_data_dir(DATA_NAME)
            current, other_dirs = db.file, [d for d in db.dirs if d != target]
        t = time.perf_counter()
        try:
            res = hero_update.update_heroes(target, current, other_dirs=other_dirs, icons=not no_icons)
        except hero_update.UpdateError as e:
            _fail(str(e))
            raise typer.Exit(1) from None
        (_ok if res.changed else _warn)(
            f"{'已更新' if res.changed else '没有变化'}：{res.total} 名，新增 {len(res.added)}、删除 {len(res.removed)}、"
            f"变化 {len(res.modified)}；新头像 {res.icons}、详情 {res.details}、技能图标 {res.detail_icons}，"
            f"{time.perf_counter() - t:.1f} 秒 → {target}")
        if res.added:
            console.print(f"新增：{', '.join(res.added)}")
        if res.missing_names:
            _warn(f"没有中文名（先用英文名）：{', '.join(res.missing_names)}")
        if res.icon_failed:
            _warn(f"头像下载失败：{', '.join(res.icon_failed)}")
        if res.wiki_error:
            _warn(f"e7.wiki 没连上，这次没更新中文名和详情：{res.wiki_error}")
        if res.detail_failed:
            _warn(f"详情下载失败：{', '.join(res.detail_failed)}")
        reload_heroes()

    db = heroes()
    console.print(f"英雄 {len(db)} 名 · 来源 {db.source} · 用的是{'数据目录' if db.origin == 'user' else '随包'}的 · "
                  f"更新于 {db.updated or '—'}")
    if not query:
        return
    found = db.search(query, limit=30)
    table = Table("编号", "名字", "英文名", "属性", "职业", "星级", "速度", "头像")
    for h in found:
        table.add_row(h.code, h.name, h.name_en, ELEMENT_LABELS.get(h.element, h.element),
                      ROLE_LABELS.get(h.role, h.role), "★" * h.rarity, f"{h.stats.get('spd', 0):g}",
                      "有" if db.icon_path(h.code) else "—")
    console.print(table)
    console.print(f"[dim]{len(found)} 条[/]")


rta_app = typer.Typer(help="RTA 选秀助手（B14 起）：对局采集、数据报告（开发用）", no_args_is_help=True)
app.add_typer(rta_app, name="rta")
ServerOpt = Annotated[str, typer.Option("--server", "-s", help="cn（国服）/ global（海外）")]


@rta_app.command("probe")
def rta_probe(server: ServerOpt = "cn") -> None:
    """取一名种子玩家的一页对局，打印字段概况（不含昵称），确认接口格式没变。"""
    from collections import Counter

    from e7helper.core.rta.battle import STORE_KEYS, BadBattle, parse_battle
    from e7helper.core.rta.official import CN_WORLD, OfficialClient, OfficialError
    from e7helper.core.rta.rules import rule_label

    client = OfficialClient(server)
    try:
        season = client.current_season()
        seeds = client.recommend() or client.ranking(season)
        if not seeds:
            _fail("没有种子玩家")
            raise typer.Exit(1)
        seed = seeds[0]
        rows = client.battles(seed["nick_no"], seed.get("world_code") or CN_WORLD, season)
    except OfficialError as e:
        _fail(str(e))
        raise typer.Exit(1) from None
    console.print(f"{server} · 当前赛季 {season} · 种子 {len(seeds)} 名 · 一页 {len(rows)} 场 · 请求 {client.requests} 次")
    keys = Counter(k for r in rows for k in r)
    console.print(f"字段（{len(keys)}）：{', '.join(sorted(keys))}")
    console.print(f"[dim]不在 STORE_KEYS 里（采集时丢掉）：{', '.join(sorted(set(keys) - set(STORE_KEYS)))}[/]")
    ok, bad = [], Counter()
    for r in rows:
        try:
            ok.append(parse_battle(r, server))  # type: ignore[arg-type]
        except BadBattle as e:
            bad[e.reason] += 1
    console.print(f"解析：成功 {len(ok)}，失败 {sum(bad.values())} {dict(bad) if bad else ''}")
    if ok:
        console.print(f"时间：{min(m.day for m in ok)} ~ {max(m.day for m in ok)}")
        console.print(f"段位：{dict(Counter(f'{m.first.grade}/{m.second.grade}' for m in ok).most_common(6))}")
        console.print(f"开战规则：{dict(Counter(rule_label(m.rule) for m in ok))}")
        console.print(f"先手胜：{sum(m.winner == 'F' for m in ok)} / {len(ok)}")
        pos = Counter((p.position, p.banned) for m in ok for side in (m.first, m.second) for p in side.picks)
        console.print(f"站位（位置, 被禁）：{dict(sorted(pos.items()))}")
    ids = sum(1 for r in rows if str(r.get("matchPlayerNicknameno", "")).isdigit())
    console.print(f"带对手数字编号的对局：{ids} / {len(rows)}")


@rta_app.command("crawl")
def rta_crawl(
    server: Annotated[str, typer.Option("--server", "-s", help="cn / global / both")] = "both",
    season: Annotated[Optional[list[str]], typer.Option("--season", help="赛季代码（可多次），默认各服的当前赛季")] = None,
    min_grade: Annotated[str, typer.Option("--min-grade", help="对手段位不低于这个才入队")] = "champion",
    interval: Annotated[float, typer.Option("--interval", help="两次请求至少隔几秒")] = 1.0,
    max_requests: Annotated[Optional[int], typer.Option("--max-requests", help="这次每个服最多发几次请求")] = None,
    daily_cap: Annotated[int, typer.Option("--daily-cap", help="每个服每天最多发几次请求")] = 20000,
    max_pages: Annotated[int, typer.Option("--max-pages", help="国服每名玩家最多往前翻几页")] = 10,
    refresh_hours: Annotated[float, typer.Option("--refresh-hours", help="采过的玩家隔多久再采")] = 20.0,
    db: Annotated[Optional[Path], typer.Option("--db", help="sqlite 路径，默认 F:\\e7helper-data\\rta\\crawl.sqlite（环境变量 E7_RTA_DB 可改）")] = None,
) -> None:
    """采集世界竞技场对局（开发用，给模型训练）。Ctrl+C 安全退出，下次接着采。"""
    from e7helper.core.rta import rules
    from e7helper.core.rta.crawl import CrawlConfig, Crawler, ServerStats

    servers = ("cn", "global") if server == "both" else (server,)
    if any(s not in ("cn", "global") for s in servers) or min_grade not in rules.GRADES:
        _fail("--server 只能是 cn / global / both；--min-grade 是 champion 这种段位代码")
        raise typer.Exit(2)
    config = CrawlConfig(servers=servers, seasons={s: list(season) for s in servers} if season else None,
                         min_grade=min_grade, interval=interval, max_requests=max_requests, daily_cap=daily_cap,
                         max_pages=max_pages, refresh_hours=refresh_hours)
    started = time.time()

    def progress(st: ServerStats) -> None:
        mins = max((time.time() - started) / 60, 1e-6)
        console.print(f"[dim]{datetime.now():%H:%M:%S}[/] {st.server}：请求 {st.requests}，新对局 {st.battles_new}"
                      f"（{st.battles_new / mins:.0f}/分钟），重复 {st.battles_seen}，新玩家 {st.players_new}，出错 {st.errors}")

    crawler = Crawler(db, config, progress=progress)
    console.print(f"采集 {', '.join(servers)} → {crawler.db_path}（Ctrl+C 停止）")
    results = crawler.run()
    for st in results.values():
        console.print(f"{st.server} {st.seasons}：请求 {st.requests}，新对局 {st.battles_new}，重复 {st.battles_seen}，"
                      f"新玩家 {st.players_new}，出错 {st.errors} · {st.stopped}")
    summary = crawler.summary()
    console.print(f"库里的对局：{summary['battles']}")
    console.print(f"玩家（总数, 没采过的）：{summary['players']}")


@rta_app.command("report")
def rta_report(
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON")] = False,
    db: Annotated[Optional[Path], typer.Option("--db", help="sqlite 路径，默认 F:\\e7helper-data\\rta\\crawl.sqlite（环境变量 E7_RTA_DB 可改）")] = None,
) -> None:
    """采集数据的概况：场数、解析通过率、段位 / 开战规则分布、英雄覆盖。"""
    from e7helper.core.data import heroes
    from e7helper.core.rta.report import build_report

    db_heroes = heroes()
    rep = build_report(db, known_codes={h.code for h in db_heroes})
    if as_json:
        console.print_json(data=rep)
        return

    def name(code: str) -> str:
        h = db_heroes.get(code)
        return h.name if h else code

    console.print(f"对局 {rep['total']} 场，解析成功 {rep['parsed']}（{(rep['parse_rate'] or 0):.2%}）")
    table = Table("服务器", "场数", "通过率", "赛季", "时间范围", "先手胜率", "回合中位", "时长中位", "段位（较低一方）",
                  "开战规则", "失败原因")
    for server, s in rep["servers"].items():
        seasons = "\n".join(f"{k} {v}" for k, v in s["seasons"].items())
        if s["irregular"]:
            seasons += f"\n含 m 开头英雄 {s['irregular']}"
        table.add_row(server, str(s["total"]), f"{(s['parse_rate'] or 0):.2%}", seasons,
                      f"{s['days'][0]}\n{s['days'][1]}",
                      f"{(s['first_win_rate'] or 0):.1%}", str(s["median_turns"]), f"{s['median_seconds']} 秒",
                      "\n".join(f"{k} {v}" for k, v in s["grades"].items()),
                      "\n".join(f"{k} {v}" for k, v in s["rules"].items()),
                      "\n".join(f"{k} {v}" for k, v in s["failed"].items()) or "—")
    console.print(table)
    h = rep["heroes"]
    console.print(f"英雄：出场过 {h['picked']} 名，选过 ≥30 次 {h['picked_30']} 名，≥300 次 {h['picked_300']} 名"
                  + (f"；数据库里没有：{', '.join(h['unknown'])}" if h.get("unknown") else ""))
    console.print("选取最多：" + "、".join(f"{name(c)} {n}" for c, n in h["top_picks"]))
    console.print("预禁最多：" + "、".join(f"{name(c)} {n}" for c, n in h["top_prebans"]))
    console.print("后禁最多：" + "、".join(f"{name(c)} {n}" for c, n in h["top_bans"]))
    console.print("开战规则：" + "、".join(f"{tid}（{v['label']}）{v['count']}" for tid, v in rep["rules_seen"].items()))
    console.print(f"玩家队列（总数, 没采过的）：{rep['queue']}")


DatasetOpt = Annotated[Optional[Path], typer.Option("--dataset", "-d", help="快照路径，默认 datasets/ 里最新的")]


def _latest_dataset(path: Path | None) -> Path:
    from e7helper.core.rta.dataset import default_dir

    if path:
        return path
    found = sorted(default_dir().glob("*.npz"), key=lambda p: p.stat().st_mtime)
    if not found:
        _fail(f"{default_dir()} 里没有快照，先跑 e7helper rta dataset")
        raise typer.Exit(1)
    return found[-1]


@rta_app.command("dataset")
def rta_dataset(
    until: Annotated[Optional[str], typer.Option("--until", help="只要这一天（UTC，含）以前的对局，例如 2026-10-23")] = None,
    season: Annotated[str, typer.Option("--season", help="赛季代码")] = "pvp_rta_ss21",
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="快照路径，默认 datasets/<赛季>-<截止日>.npz")] = None,
    db: Annotated[Optional[Path], typer.Option("--db", help="采集库路径，默认 F:\\e7helper-data\\rta\\crawl.sqlite")] = None,
    show: Annotated[Optional[Path], typer.Option("--show", help="不建新的，只看这个快照的概况")] = None,
) -> None:
    """建训练数据快照（B14b）：解析、过滤、编码采集库里一个赛季的对局，存成 npz。"""
    from e7helper.core.rta import dataset as rds

    if show:
        ds = rds.Dataset.load(show)
        path = show
    else:
        path = out or rds.default_dir() / f"{season.removeprefix('pvp_rta_')}-{until or time.strftime('%Y-%m-%d')}.npz"
        last = [0.0]

        def progress(read: int, kept: int) -> None:
            if time.time() - last[0] > 5:
                last[0] = time.time()
                console.print(f"[dim]{datetime.now():%H:%M:%S}[/] 已读 {read}，收下 {kept}")

        ds = rds.build(db, season=season, until=until, progress=progress)
        ds.save(path)
    info = rds.summary(ds)
    meta = info["meta"]
    console.print(f"快照 {path}（{path.stat().st_size / 1e6:.1f} MB）：{meta['season']}，{meta['first_day']} ~ "
                  f"{meta['last_day']}，读 {meta['read']} 场、收下 {meta['kept']}，用时 {meta['seconds']} 秒")
    console.print(f"去掉的：{meta['dropped']}")
    console.print(f"每服：{meta['per_server']} · 较低一方的段位：{info['grade_mix']}")
    table = Table("份", "场数", "双方 ≥ 优胜者", "日期", "先手胜率", "每服")
    for name, s in info["splits"].items():
        table.add_row(name, str(s["matches"]), str(s["champion_plus"]), f"{s['from']} ~ {s['to']}",
                      f"{s['first_win_rate']:.2%}", str(s["per_server"]))
    console.print(table)
    console.print(f"英雄 {info['heroes']} 名，词表（训练集选过 ≥ 30 次）{info['vocab']} 名；开战规则 {info['rules']}")


def _cal(cal) -> str:
    """校准参数：后禁后（n = 11）的斜率 / 截距。"""
    if not cal:
        return "—"
    from e7helper.core.rta.model import calibration_arrays

    scale, bias = calibration_arrays(cal)
    return f"{scale[-1]:.2f} / {bias[-1]:+.3f}"


def _train_mod(name: str):
    """导入 e7helper.core.rta.train 的子模块；没装 torch 时提示装依赖组。"""
    import importlib

    from e7helper.core.rta.train import require_torch

    try:
        require_torch()
    except RuntimeError as e:
        _fail(str(e))
        raise typer.Exit(1) from None
    return importlib.import_module(f"e7helper.core.rta.train.{name}")


@rta_app.command("train")
def rta_train(
    model: Annotated[str, typer.Option("--model", "-m", help="lr0（先手 + 段位）/ lr（英雄强度）/ fm（因子分解机）/ transformer / hybrid（Transformer + 因子分解机）")] = "transformer",
    d: Annotated[int, typer.Option("--d", help="Transformer 宽度")] = 64,
    layers: Annotated[int, typer.Option("--layers", help="Transformer 层数")] = 2,
    lam: Annotated[float, typer.Option("--lambda", help="选人损失的权重")] = 1.0,
    k: Annotated[int, typer.Option("--k", help="因子分解机的隐向量维度")] = 16,
    epochs: Annotated[int, typer.Option("--epochs", help="最多几轮")] = 30,
    patience: Annotated[int, typer.Option("--patience", help="早停：学习率降到峰值三成以下后，验证连续几轮没变好就停；0 = 跑满整个周期（默认）")] = 0,
    weight_decay: Annotated[float, typer.Option("--weight-decay", help="AdamW 权重衰减")] = 0.01,
    schedule: Annotated[str, typer.Option("--schedule", help="cosine（余弦退火）/ constant（预热后恒定，grokking 实验用）")] = "cosine",
    batch: Annotated[int, typer.Option("--batch", help="每批几场")] = 512,
    lr: Annotated[float, typer.Option("--lr", help="学习率")] = 2e-3,
    device: Annotated[str, typer.Option("--device", help="auto / cuda / cpu")] = "auto",
    full: Annotated[bool, typer.Option("--full", help="全量重训：不留验证 / 测试，跑满 --epochs（校准用 --calibration-from）")] = False,
    calibration_from: Annotated[Optional[str], typer.Option("--calibration-from", help="全量重训时用这个 run（切分训练的）在验证集上拟合的校准参数")] = None,
    name: Annotated[Optional[str], typer.Option("--name", help="run 名字，默认按模型和参数生成")] = None,
    max_steps: Annotated[int, typer.Option("--max-steps", help="只跑这么多步（测速用）")] = 0,
    dataset: DatasetOpt = None,
) -> None:
    """训练 RTA 模型（B14b，开发用）：进度在终端，曲线在 e7helper rta watch。Ctrl+C 停下并保留最好的一轮。"""
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

    from e7helper.core.rta.dataset import Dataset

    fit = _train_mod("fit")
    path = _latest_dataset(dataset)
    ds = Dataset.load(path)
    calibration = None
    if calibration_from:
        src = _run_dir(calibration_from)
        calibration = json.loads((src / "result.json").read_text(encoding="utf-8")).get("calibration")
        if not calibration and (src / "eval-test.json").exists():  # 早期的 run 只存了温度：用 rta eval 从验证集拟合的
            calibration = json.loads((src / "eval-test.json").read_text(encoding="utf-8")).get("calibration")
        if not isinstance(calibration, dict):
            _fail(f"{src.name} 没有校准参数，先跑 e7helper rta eval {src.name}")
            raise typer.Exit(1)
    cfg = fit.TrainConfig(name=name or "", model=model, d=d, layers=layers, lam=lam, k=k, epochs=epochs,
                          patience=patience, weight_decay=weight_decay, schedule=schedule, batch=batch, lr=lr, device=device, full=full, calibration=calibration,
                          max_steps=max_steps, dataset=str(path))
    run = fit.runs_dir() / cfg.run_name()
    console.print(f"训练 {cfg.run_name()} · 数据 {path.name}（{len(ds)} 场）· 设备 {fit.pick_device(device)} → {run}")
    with Progress(TextColumn("[bold]{task.description}"), BarColumn(), TextColumn("{task.percentage:>4.0f}%"),
                  TextColumn("{task.fields[info]}"), TimeRemainingColumn(), console=console) as progress:
        task = progress.add_task(cfg.run_name(), total=None, info="准备数据…")

        def on_step(rec: dict) -> None:
            pick = f" / 选人 {rec['pick']:.3f}" if rec.get("pick") is not None else ""
            progress.update(task, total=cfg.epochs, completed=rec["frac"],
                            info=f"第 {rec['epoch']} 轮 · loss {rec['loss']:.4f}（胜率 {rec['win']:.4f}{pick}）· "
                                 f"{rec['speed'] / 1e4:.1f} 万场/秒")

        def on_epoch(v: dict) -> None:
            if "n11" not in v:
                progress.console.print(f"第 {v['epoch']} 轮完成")
                return
            pick = v.get("pick")
            ptxt = f" · 选人前5 {pick['top5']:.3f} 前8 {pick['top8']:.3f}" if pick else ""
            mark = "[green]↓[/]" if v["improved"] else (f"[dim]早停计数 {v['bad_epochs']}[/]" if patience else "")
            if "train_win_loss" in v:
                ptxt += f" · 训练集 {v['train_win_loss']:.4f} / 验证 {v['win_loss']:.4f}"
            progress.console.print(
                f"第 {v['epoch']} 轮验证：loss {v['loss']:.4f} · n11 log loss {v['n11']['log_loss']:.4f} "
                f"AUC {v['n11']['auc']:.4f} ECE {v['n11']['ece']:.4f}（≥优胜者 AUC {v['n11_champ']['auc']:.4f}）{ptxt} {mark}")

        result = fit.train(ds, cfg, on_step=on_step, on_epoch=on_epoch)
    console.print(f"{result['status']}：最佳第 {result['best_epoch']} 轮，校准 {_cal(result['calibration'])}，"
                  f"用时 {result['seconds'] / 60:.1f} 分钟 · {result['run']}")


def _run_dir(name: str) -> Path:
    from e7helper.core.rta.train import runs_dir

    path = Path(name) if Path(name).is_absolute() else runs_dir() / name
    if not (path / "best.pt").exists():
        _fail(f"{path} 里没有 best.pt")
        raise typer.Exit(1)
    return path


@rta_app.command("eval")
def rta_eval(
    runs: Annotated[list[str], typer.Argument(help="run 名字（runs/ 下的目录名）或路径")],
    split: Annotated[str, typer.Option("--split", help="test / val")] = "test",
    device: Annotated[str, typer.Option("--device", help="cpu / cuda")] = "cpu",
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON")] = False,
    dataset: DatasetOpt = None,
) -> None:
    """在快照的测试集上评估、对比多个 run（B14b）：胜率按局面 / 子集、选人对比热度基线。结果另存 run/eval-<split>.json。"""
    from e7helper.core.rta.dataset import Dataset

    ev = _train_mod("evaluate")
    ds = Dataset.load(_latest_dataset(dataset))
    results = [ev.evaluate_run(_run_dir(r), ds, split, device) for r in runs]
    if as_json:
        console.print_json(data=results)
        return
    table = Table("run", "参数", "n10 log loss", "n10 AUC", "n11 log loss", "n11 AUC", "n11 ECE", "n11 Brier",
                  "≥优胜者 n11 log loss", "≥优胜者 n11 AUC", "选人 前1/前5/前8", "校准 n11（斜率 / 截距）")
    for r in results:
        a, c = r["win"]["all"], r["win"].get("champion+", {})
        pk = r.get("pick")
        table.add_row(r["run"], f"{(r['params'] or 0) / 1000:.0f}k", f"{a['10']['log_loss']:.4f}", f"{a['10']['auc']:.4f}",
                      f"{a['11']['log_loss']:.4f}", f"{a['11']['auc']:.4f}", f"{a['11']['ece']:.4f}", f"{a['11']['brier']:.4f}",
                      f"{c['11']['log_loss']:.4f}" if c else "—", f"{c['11']['auc']:.4f}" if c else "—",
                      f"{pk['top1']:.3f}/{pk['top5']:.3f}/{pk['top8']:.3f}" if pk else "—", _cal(r["calibration"]))
    pop = results[0]["pop"]
    table.add_row("选人热度基线", "—", "", "", "", "", "", "", "", "", f"{pop['top1']:.3f}/{pop['top5']:.3f}/{pop['top8']:.3f}", "")
    console.print(f"{split}：{results[0]['n']} 场")
    console.print(table)
    curve = Table("run", *[f"n={n}" for n in range(12)], title="各局面的 AUC（全部）")
    for r in results:
        curve.add_row(r["run"], *[f"{r['win']['all'][str(n)]['auc']:.3f}" for n in range(12)])
    console.print(curve)


@rta_app.command("export")
def rta_export(
    run: Annotated[str, typer.Argument(help="要导出的 run（transformer / hybrid）")],
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="输出目录，默认随包的 assets/data/rta/")] = None,
    metrics_from: Annotated[Optional[str], typer.Option("--metrics-from", help="测试指标取自这个 run 的 eval-test.json（全量重训的模型自己没有测试集）")] = None,
    parity: Annotated[int, typer.Option("--parity", help="parity 样例几个局面")] = 48,
    dataset: DatasetOpt = None,
) -> None:
    """导出随包模型（B14b）：model.onnx + meta.json + parity.json，并核对 onnxruntime 和 torch 一致。"""
    import numpy as np

    from e7helper.core.rta.dataset import Dataset
    from e7helper.core.rta.model import bundled_dir

    fit = _train_mod("fit")
    export = _train_mod("export")
    path = _latest_dataset(dataset)
    ds = Dataset.load(path)
    run_dir = _run_dir(run)
    model, vocab, ckpt = fit.load_run(run_dir)
    cfg = ckpt["config"]
    if cfg["model"] not in ("transformer", "hybrid"):
        _fail("只有 transformer / hybrid 能导出 ONNX")
        raise typer.Exit(2)
    if not isinstance(ckpt.get("calibration"), dict) and (run_dir / "eval-test.json").exists():
        # 早期的 run 只存了温度：用 rta eval 从验证集拟合的 Platt 参数（B14c 导出切分模型时补）
        ckpt["calibration"] = json.loads((run_dir / "eval-test.json").read_text(encoding="utf-8")).get("calibration")
    parts = ds.split(7, 7)
    rng = np.random.default_rng(0)
    rows = rng.choice(parts["test"], parity, replace=False)
    states = [ds.state(int(r), int(n)) for r, n in zip(rows, np.resize(np.arange(12), parity))]
    check_rows = rng.choice(parts["test"], 2000, replace=False)
    x = ds.encode(vocab, check_rows)
    src = _run_dir(metrics_from) if metrics_from else run_dir
    ev_file = src / "eval-test.json"
    test_metrics = json.loads(ev_file.read_text(encoding="utf-8")) if ev_file.exists() else None
    info = {"run": run_dir.name, "trained_on": {k: int(len(v)) for k, v in ds.split(0 if cfg["full"] else 7, 7).items()},
            "dataset": {k: ds.meta.get(k) for k in ("season", "until", "first_day", "last_day", "kept")},
            "test_metrics_from": src.name if test_metrics else None,
            "test_metrics": {k: test_metrics[k] for k in ("n", "win", "pick", "pop")} if test_metrics else None}
    out = out or bundled_dir()
    check = export.write_bundle(model, vocab, ckpt, out, states=states, check_inputs=(x["heroes"], x["ctx"]), info=info)
    sizes = {p.name: p.stat().st_size for p in out.iterdir() if p.is_file()}
    console.print(f"导出到 {out}：{', '.join(f'{k} {v / 1e6:.2f} MB' for k, v in sizes.items())}")
    console.print(f"onnxruntime vs torch（{check['n']} 场 × 17 个位置）：胜率 logit 最大差 {check['win_logit']:.2e}，"
                  f"选人 logit 最大差 {check['pick_logit']:.2e}，胜率概率最大差 {check['win_prob']:.2e}")


@rta_app.command("priors")
def rta_priors(
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="输出文件，默认随包的 assets/data/rta/priors.json")] = None,
    dataset: DatasetOpt = None,
) -> None:
    """生成选秀推荐用的数据先验（B14c）：英雄被选次数、预禁组合频率、后禁率。重训后和 rta export 一起跑。"""
    from e7helper.core.rta import priors as rpriors
    from e7helper.core.rta.dataset import Dataset

    path = _latest_dataset(dataset)
    data = rpriors.build(Dataset.load(path), source=path.name)
    out = out or rpriors.bundled_path()
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    p = rpriors.Priors.from_dict(data)
    rare = sum(1 for n in p.picks.values() if n < 1000)
    console.print(f"写入 {out}（{out.stat().st_size / 1e3:.0f} KB）：{data['matches']} 场（双方 ≥ 优胜者 {data['champion_plus']}），"
                  f"英雄 {len(p.picks)} 名（被选 < 1000 次的 {rare} 名），预禁组合 先手 {len(p.preban['F']['pairs'])} / 后手 "
                  f"{len(p.preban['S']['pairs'])} 组，后禁率 {len(p.postban)} 名（平均 {p.mean_ban_rate():.1%}）")


@rta_app.command("model")
def rta_model(
    check: Annotated[bool, typer.Option("--check", help="用 parity.json 核对编码和推理，并测推理耗时")] = False,
    folder: Annotated[Optional[Path], typer.Option("--dir", help="模型目录，默认随包的")] = None,
) -> None:
    """随包的 RTA 模型信息（B14b）；--check 核对一致性（冻结引擎的冒烟测试用它）。"""
    import numpy as np

    from e7helper.core.rta import model as rmodel

    folder = folder or rmodel.bundled_dir()
    if not rmodel.available(folder):
        _fail(f"{folder} 里没有模型")
        raise typer.Exit(1)
    m = rmodel.RtaModel(folder)
    meta = m.meta
    arch = meta.get("arch", {})
    console.print(f"模型 {folder}：{meta['kind']} d={arch.get('d')} L={arch.get('layers')} · {meta.get('params')} 参数 · "
                  f"词表 {m.vocab.size} · 校准 n11 {_cal(m.calibration)} · 导出于 {meta.get('built')} · 加载 {m.load_seconds * 1000:.0f} ms")
    ds = meta.get("dataset") or {}
    console.print(f"训练数据：{ds.get('season')} {ds.get('first_day')} ~ {ds.get('last_day')}，{meta.get('trained_on')}")
    tm = meta.get("test_metrics")
    if tm:
        a = tm["win"]["all"]["11"]
        console.print(f"测试指标（{meta.get('test_metrics_from')}，{tm['n']} 场）：n11 log loss {a['log_loss']:.4f} AUC {a['auc']:.4f} "
                      f"ECE {a['ece']:.4f}；选人前 5 {tm['pick']['top5']:.3f}（热度 {tm['pop']['top5']:.3f}）")
    if not check:
        return
    res = m.check()
    color = "green" if res["ok"] else "red"
    console.print(f"[{color}]parity {'通过' if res['ok'] else '不通过'}[/]：{res['cases']} 个局面，编码一致 {res['encode_ok']}，"
                  f"胜率最大差 {res['win_diff']:.2e}，下一手最大差 {res['pick_diff']:.2e}（容差 {res['tolerance']:g}）")
    rng = np.random.default_rng(0)
    heroes = rng.integers(2, m.vocab.size, (256, 17))
    ctx = np.zeros((256, 3), dtype=np.int64)
    m.run(heroes, ctx)
    times = []
    for _ in range(10):
        t = time.perf_counter()
        m.run(heroes, ctx)
        times.append(time.perf_counter() - t)
    console.print(f"推理：一批 256 场（每场 12 个局面）中位 {statistics.median(times) * 1000:.1f} ms")
    if not res["ok"]:
        raise typer.Exit(1)


@rta_app.command("predict")
def rta_predict(
    first: Annotated[str, typer.Option("--first", "-f", help="先手方按顺序选的英雄（中文名 / 昵称，逗号分隔）")] = "",
    second: Annotated[str, typer.Option("--second", "-s", help="后手方按顺序选的英雄")] = "",
    pre_first: Annotated[str, typer.Option("--pre-first", help="先手方的预禁")] = "",
    pre_second: Annotated[str, typer.Option("--pre-second", help="后手方的预禁")] = "",
    ban_first: Annotated[str, typer.Option("--ban-first", help="先手方被禁的那名")] = "",
    ban_second: Annotated[str, typer.Option("--ban-second", help="后手方被禁的那名")] = "",
    grades: Annotated[str, typer.Option("--grades", help="双方段位，如 legend,emperor")] = "",
    rule: Annotated[str, typer.Option("--rule", help="开战规则：unknown（国服）/ none / opening_rule_desc_tid")] = "unknown",
    k: Annotated[int, typer.Option("--top", help="下一手列几名")] = 8,
) -> None:
    """用随包模型试算一个局面（B14b）：先手方胜率 + 下一手最可能的英雄。"""
    from e7helper.core.data import heroes as hero_db
    from e7helper.core.rta import model as rmodel
    from e7helper.core.rta.encode import UNKNOWN_RULE, DraftState

    db = hero_db()

    def codes(text: str) -> list[str]:
        out = []
        for name in filter(None, (s.strip() for s in text.replace("，", ",").split(","))):
            h = db.find(name) or next(iter(db.search(name, limit=1)), None)
            if not h:
                _fail(f"找不到英雄：{name}")
                raise typer.Exit(2)
            out.append(h.code)
        return out

    def name(code: str | None) -> str:
        h = db.get(code) if code else None
        return h.name if h else (code or "—")

    g = [x.strip() or None for x in grades.split(",")] if grades else [None, None]
    st = DraftState(prebans={"F": codes(pre_first), "S": codes(pre_second)}, picks={"F": codes(first), "S": codes(second)},
                    banned={"F": (codes(ban_first) or [None])[0], "S": (codes(ban_second) or [None])[0]},
                    grades=(g[0], g[1] if len(g) > 1 else None),
                    rule=UNKNOWN_RULE if rule == "unknown" else None if rule == "none" else rule)
    problems = st.problems()
    if problems:
        _fail("；".join(problems))
        raise typer.Exit(2)
    m = rmodel.load()
    ev = m.evaluate([st])
    console.print(f"局面 {st.state}（已选 {st.n_picks} 手）：先手方胜率 [bold]{ev.win[0]:.1%}[/]，后手方 {1 - ev.win[0]:.1%}")
    if st.state < 10:
        side = "先手方" if st.mover() == "F" else "后手方"
        top = m.next_picks(st, k)
        console.print(f"下一手（{side}）：" + "、".join(f"{name(c)} {p:.1%}" for c, p in top))


def _rta_codes(db, text: str | None) -> list[str]:
    """中文名 / 昵称 / 编号（逗号分隔）→ 英雄编号；找不到就报错退出。"""
    out = []
    for name in filter(None, (s.strip() for s in (text or "").replace("，", ",").split(","))):
        h = db.get(name) or db.find(name) or next(iter(db.search(name, limit=1)), None)
        if not h:
            _fail(f"找不到英雄：{name}")
            raise typer.Exit(2)
        out.append(h.code)
    return out


def _rta_name(db, code: str | None) -> str:
    h = db.get(code) if code else None
    return h.name if h else (code or "—")


def _rta_rule(rule: str):
    from e7helper.core.rta.encode import UNKNOWN_RULE

    return UNKNOWN_RULE if rule == "unknown" else None if rule == "none" else rule


def _rta_grades(text: str) -> tuple[str | None, str | None]:
    g = [x.strip() or None for x in text.split(",")] if text else []
    g += [None, None]
    return g[0], g[1]


def _rta_advisor():
    from e7helper.core.rta import search

    if not search.available():
        _fail("没有随包的 RTA 模型或 priors.json")
        raise typer.Exit(1)
    return search.load()


def _print_advice(out: dict, db) -> None:
    """advise 的结果打成表（胜率都是我方的）。"""
    nm = lambda c: _rta_name(db, c)  # noqa: E731
    names = lambda cs: "+".join(map(nm, cs))  # noqa: E731
    pct = lambda x: f"{x:.1%}"  # noqa: E731
    sec = f"（另一个模型 {out['second_win']:.1%}）" if out.get("second_win") is not None else ""
    phase = {"pick": "选秀", "ban": "后禁", "done": "结束"}[out["phase"]]
    head = f"{phase} · 已选 {out['n']} 手 · 当前我方胜率 [bold]{out['win']:.1%}[/]{sec}"
    if out["phase"] == "pick":
        head += f" · 轮到{'我方' if out['turn'] == 'mine' else '对手'}（这一轮 {out['slots']} 名）"
    console.print(head)
    if out.get("unknown"):
        console.print(f"[yellow]英雄池里这些模型没有数据，不推荐：{'、'.join(map(nm, out['unknown']))}[/]")
    recs = out.get("recommend") or []
    if recs:
        t = Table("#", "推荐", "分数", "预期", "被针对时", "差距", "这一手常见度", "两模型差", "对手最可能的回应", "最坏的回应",
                  title="推荐（分数 = ½ 预期 + ½ 被针对时）")
        for i, r in enumerate(recs):
            heroes = "+".join(nm(c) + ("（保护位）" if c == r["protected"] else "") for c in r["heroes"])
            flags = [f for f, on in (("差距不明显", r["close"]), ("数据少", r["rare"]), ("不确定", r.get("uncertain"))) if on]
            resp = r["responses"][0] if r["responses"] else None
            th = r["threat"]
            th_txt = "后禁（矩阵）" if r["end"] and not th else "—"
            if th:
                th_txt = f"{names(th['heroes'])} {pct(th['win'])}"
                if "reply" in th:
                    th_txt += f" → 你再选 {names(th['reply'])} {pct(th['reply_win'])}"
            t.add_row(str(i + 1), heroes + (f" [dim]{'、'.join(flags)}[/]" if flags else ""), pct(r["score"]), pct(r["win"]),
                      pct(r["worst"]), f"{r['gap']:+.1%}", " / ".join(f"{x:.1%}" for x in r["common"]),
                      f"{r['second']['spread']:+.1%}" if r.get("second") else "—",
                      f"{names(resp['heroes'])} {resp['prob']:.0%} → {pct(resp['win'])}" if resp else "—", th_txt)
        console.print(t)
        if out.get("heroes"):
            console.print("按英雄：" + "、".join(f"{nm(h['code'])}（配 {nm(h['partner'])}）{pct(h['score'])}" for h in out["heroes"]))
    opp = out.get("opponent")
    if opp:
        t = Table("对手可能选", "这一手的概率", "之后我方胜率", title="轮到对手")
        for x in opp["likely"]:
            t.add_row(names(x["heroes"]), f"{x['prob']:.1%}", pct(x["win"]))
        console.print(t)
        console.print("对我方威胁最大：" + "、".join(f"{names(x['heroes'])} → {pct(x['win'])}（{x['prob']:.1%}）"
                                         for x in opp["threats"]))
    b = out.get("ban")
    if b:
        t = Table("我方禁 ↓ / 对方禁 →", *[nm(c) for c in b["cols"]], "最坏", "预期", "分数", "两模型差",
                  title="后禁：我方胜率（保护位不能禁；★ = 推荐）")
        for i, code in enumerate(b["rows"]):
            s = b["row_stats"][i]
            t.add_row(("★ " if code == b["recommend"] else "") + nm(code), *[pct(v) for v in b["matrix"][i]], pct(s["worst"]),
                      pct(s["win"]), pct(s["score"]), f"{s['second']['spread']:+.1%}" if s.get("second") else "—")
        console.print(t)
        console.print("对方可能禁（按后禁率）：" + "、".join(f"{nm(x['code'])} {x['prob']:.0%}" for x in b["their_likely"]))
        nash = b["nash"]
        mix = lambda codes, ps: "、".join(f"{nm(c)} {p:.0%}" for c, p in zip(codes, ps) if p > 0.005)  # noqa: E731
        console.print(f"[dim]均衡混合策略：我方 {mix(b['rows'], nash['mine'])}；对方 {mix(b['cols'], nash['theirs'])}；"
                      f"值 {pct(nash['value'])}[/]")
    s = out["stats"]
    console.print(f"[dim]用时 {s['ms']} ms · {s['states']} 个局面 · 搜了 {s.get('depth', 1)} 层"
                  f"{' · 时间到了，没算完' if s['truncated'] else ''}{' · 缓存' if s.get('cached') else ''}[/]")


@rta_app.command("advise")
def rta_advise(
    side: Annotated[str, typer.Option("--side", help="我方是 F（先手）还是 S（后手）")],
    pre_mine: Annotated[str, typer.Option("--pre-mine", help="我方的预禁（中文名 / 昵称，逗号分隔）")] = "",
    pre_theirs: Annotated[str, typer.Option("--pre-theirs", help="对方的预禁")] = "",
    mine: Annotated[str, typer.Option("--mine", help="我方按顺序选的英雄")] = "",
    theirs: Annotated[str, typer.Option("--theirs", help="对方按顺序选的英雄")] = "",
    ban_mine: Annotated[str, typer.Option("--ban-mine", help="我方禁了对方哪名")] = "",
    ban_theirs: Annotated[str, typer.Option("--ban-theirs", help="对方禁了我方哪名")] = "",
    grades: Annotated[str, typer.Option("--grades", help="我方,对方 的段位，如 legend,emperor")] = "",
    rule: Annotated[str, typer.Option("--rule", help="开战规则：unknown（国服）/ none / opening_rule_desc_tid")] = "unknown",
    pool: Annotated[str, typer.Option("--pool", help="我的英雄池（逗号分隔；不填 = 不限制）")] = "",
    top: Annotated[int, typer.Option("--top", help="推荐几个")] = 8,
    budget: Annotated[float, typer.Option("--budget", help="最多算几秒")] = 5.0,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON（和 /api/rta/advise 一样）")] = False,
) -> None:
    """选秀推荐（B14c）：轮到我方 → 推荐 + 对手的回应；轮到对手 → 对手可能怎么选；选完 → 后禁矩阵。胜率是我方的。"""
    from e7helper.core.data import heroes as hero_db
    from e7helper.core.rta.encode import DraftState

    db = hero_db()
    side = side.upper()
    if side not in ("F", "S"):
        _fail("--side 只能是 F / S")
        raise typer.Exit(2)
    foe = "S" if side == "F" else "F"
    g = dict(zip((side, foe), _rta_grades(grades)))
    first = lambda xs: xs[0] if xs else None  # noqa: E731
    st = DraftState(prebans={side: _rta_codes(db, pre_mine), foe: _rta_codes(db, pre_theirs)},
                    picks={side: _rta_codes(db, mine), foe: _rta_codes(db, theirs)},
                    banned={foe: first(_rta_codes(db, ban_mine)), side: first(_rta_codes(db, ban_theirs))},
                    grades=(g["F"], g["S"]), rule=_rta_rule(rule))
    adv = _rta_advisor()
    try:
        out = adv.advise(st, side, pool=_rta_codes(db, pool) if pool else None, top=top, budget=budget)
    except ValueError as e:
        _fail("；".join(e.args[0]))
        raise typer.Exit(2) from None
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    _print_advice(out, db)


@rta_app.command("preban")
def rta_preban(
    side: Annotated[Optional[str], typer.Option("--side", help="我方是 F（先手）/ S（后手）；不知道就不填")] = None,
    grades: Annotated[str, typer.Option("--grades", help="我方,对方 的段位")] = "",
    rule: Annotated[str, typer.Option("--rule", help="开战规则：unknown（国服）/ none / opening_rule_desc_tid")] = "unknown",
    fixed: Annotated[str, typer.Option("--fixed", help="固定预禁这一名，只推荐另一名")] = "",
    top: Annotated[int, typer.Option("--top", help="推荐几组")] = 8,
    budget: Annotated[float, typer.Option("--budget", help="最多算几秒")] = 4.0,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON（和 /api/rta/preban 一样）")] = False,
) -> None:
    """预禁推荐（B14c）：候选是数据里常见的组合，对手按数据里最常见的 100 组加权。"""
    from e7helper.core.data import heroes as hero_db

    db = hero_db()
    side = side.upper() if side else None
    adv = _rta_advisor()
    try:
        out = adv.preban(side, grades=_rta_grades(grades), rule=_rta_rule(rule),
                         fixed=(_rta_codes(db, fixed) or [None])[0], top=top, budget=budget)
    except ValueError as e:
        _fail("；".join(e.args[0]))
        raise typer.Exit(2) from None
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    nm = lambda c: _rta_name(db, c)  # noqa: E731
    role = {"F": "先手", "S": "后手"}
    t = Table("#", "预禁", "分数", "预期", "最坏", "最坏时对手禁的", "差距", "数据里占比", "两模型差",
              title=f"预禁推荐（我方{role[side] if side else '先后手不知道'}；分数 = ½ 预期 + ½ 最坏）")
    for i, r in enumerate(out["recommend"]):
        flags = [f for f, on in (("差距不明显", r["close"]), ("不确定", r.get("uncertain"))) if on]
        t.add_row(str(i + 1), "+".join(map(nm, r["heroes"])) + (f" [dim]{'、'.join(flags)}[/]" if flags else ""),
                  f"{r['score']:.1%}", f"{r['win']:.1%}", f"{r['worst']:.1%}",
                  " / ".join(f"{role[k]} {'+'.join(map(nm, v))}" for k, v in r["worst_vs"].items()), f"{r['gap']:+.1%}",
                  " / ".join(f"{role[k]} {v:.2%}" for k, v in r["share"].items()),
                  f"{r['second']['spread']:+.1%}" if r.get("second") else "—")
    console.print(t)
    for k, v in out["theirs"].items():
        console.print(f"我方{role[k]}时，对手最常见的预禁：" + "、".join(f"{'+'.join(map(nm, x['heroes']))} {x['share']:.1%}" for x in v))
    s = out["stats"]
    console.print(f"[dim]用时 {s['ms']} ms · {s['states']} 个局面 · 候选 {s['candidates']} 组{' · 时间到了，没算完' if s['truncated'] else ''}[/]")


@rta_app.command("audit")
def rta_audit(
    matches: Annotated[int, typer.Option("--matches", help="冷门比例 / 用时：多少场真实对局（每场 6 个回合开头）")] = 100,
    games: Annotated[int, typer.Option("--selfplay", help="自对弈几局（先后手各一半）")] = 100,
    follow: Annotated[int, typer.Option("--follow", help="跟着推荐：多少场真实对局（用切分模型）")] = 200,
    budget: Annotated[float, typer.Option("--budget", help="advise 的预算（秒）")] = 5.0,
    follow_budget: Annotated[float, typer.Option("--follow-budget", help="跟着推荐那项的预算（秒）")] = 1.0,
    parts: Annotated[str, typer.Option("--parts", help="跑哪几项：rare,selfplay,follow")] = "rare,selfplay,follow",
    seed: Annotated[int, typer.Option("--seed", help="随机种子")] = 0,
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="结果 JSON，默认 F:\\e7helper-data\\rta\\audit\\<时间>.json")] = None,
    dataset: DatasetOpt = None,
) -> None:
    """选秀推荐的验收统计（B14c，开发用，要训练快照）：冷门比例、用时、自对弈会不会推到极端、跟着推荐的实际胜率。"""
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

    from e7helper.core.data import heroes as hero_db
    from e7helper.core.rta import audit, search
    from e7helper.core.rta import model as rmodel
    from e7helper.core.rta.dataset import Dataset

    ds = Dataset.load(_latest_dataset(dataset))
    adv = _rta_advisor()
    rows = audit.test_rows(ds, max(matches, games, follow), np.random.default_rng(seed))
    want = {p.strip() for p in parts.split(",")}
    results: dict = {"dataset": ds.meta.get("until"), "seed": seed}
    with Progress(TextColumn("[bold]{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
                  TimeRemainingColumn(), console=console) as bar:
        tasks: dict = {}

        def progress(label: str, done: int, total: int) -> None:
            if label not in tasks:
                tasks[label] = bar.add_task(label, total=total)
            bar.update(tasks[label], completed=done)

        if "rare" in want:
            results["rare"] = audit.rare_check(adv, ds, rows[:matches], budget, progress)
        if "selfplay" in want:
            results["selfplay"] = audit.selfplay(adv, ds, rows[:games], seed, progress)
        if "follow" in want:
            split = rmodel.load(rmodel.bundled_dir() / search.SECOND_DIR)
            results["follow"] = audit.follow_check(search.Advisor(split, adv.priors), ds, rows[:follow], follow_budget, progress)
    path = out or Path(r"F:\e7helper-data\rta\audit") / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = lambda b: "[green]✓[/]" if b else "[red]✗[/]"  # noqa: E731
    r = results.get("rare")
    if r:
        s, p = r["seconds"], r["preban_seconds"]
        console.print(f"冷门比例（{r['states']} 个回合开头）：推荐第一名有冷门英雄 {r['top1_rare']:.1%} {ok(r['top1_rare'] <= 0.02)}"
                      f"（前 8 名里有 {r['top8_rare']:.1%}；真实玩家实际选的 {r['real_rare']:.1%}）")
        console.print(f"  第一名这一手的常见度：中位 {r['top1_common']['median']:.1%}，< 0.5% 的 {r['top1_common']['below_0.5%']:.1%}、"
                      f"< 1% 的 {r['top1_common']['below_1%']:.1%}（真实玩家 {r['real_common']['median']:.1%} / "
                      f"{r['real_common']['below_0.5%']:.1%} / {r['real_common']['below_1%']:.1%}）；第一名标「不确定」的 {r['top1_uncertain']:.1%}")
        console.print(f"用时：advise p50 {s['p50']:.2f} s、p95 {s['p95']:.2f} s {ok(s['p95'] <= 6)}、最长 {s['max']:.2f} s；"
                      f"搜满 3 层 {r['depth3']:.0%}、截断 {r['truncated']:.1%}；"
                      + "、".join(f"第 {n + 1} 手 {v['p95']:.2f}" for n, v in s["by_n"].items()))
        console.print("  预禁：" + "、".join(f"{'先后手已知' if k == 'known' else '不知道'} p95 {v['p95']:.2f} s {ok(v['p95'] <= 5)}"
                                         for k, v in p.items()))
    sp = results.get("selfplay")
    if sp:
        for label, v in (("自对弈（按推荐）", sp["advise"]), ("对照：不筛的一层贪心", sp["greedy"])):
            console.print(f"{label}（{v['games']} 局）：最终胜率中位 {v['median']:.1%}、p95 {v['p95']:.1%}、最高 {v['max']:.1%}、最低 {v['min']:.1%}；"
                          f"≥ 90% 的 {v['ge90']} 局、≥ 95% 的 {v['ge95']} 局；每局我方冷门英雄 {v['rare_heroes_per_game']:.2f} 名")
        a, db = sp["advise"], hero_db()
        console.print(f"  门槛：没有一局 ≥ 95% {ok(a['ge95'] == 0)}，≥ 90% 的不超过 2% {ok(a['ge90'] <= 0.02 * a['games'])}")
        for g in sorted(a.get("lineups", []), key=lambda g: -g["final"]):
            if g["final"] < 0.9:
                break
            lu, me = g["lineup"], g["side"]
            foe = "S" if me == "F" else "F"
            names = lambda cs: "、".join(_rta_name(db, c) for c in cs)  # noqa: E731
            console.print(f"    {g['final']:.1%} · 我方{'先手' if me == 'F' else '后手'} · 预禁 {names(lu['prebans'][me])} | "
                          f"{names(lu['prebans'][foe])} · 我方 {names(lu['picks'][me])}（被禁 {_rta_name(db, lu['banned'][me])}）"
                          f" · 对手 {names(lu['picks'][foe])}（被禁 {_rta_name(db, lu['banned'][foe])}）")
    f = results.get("follow")
    if f:
        console.print("跟着推荐（切分模型，没见过测试期；提升 = 相对选之前的模型胜率，出手方视角）：")
        for label, key in (("全部", "all"), ("选的在推荐前 8 名里", "in_top8"), ("不在", "not_in_top8"), ("正好是第一名", "top1")):
            v = f[key]
            if not v.get("n"):
                continue
            adv_txt = f"，推荐给的提升 {v['advised_gain']:+.3f}（兑现 {v['realized_advised']:.2f}）" if "advised_gain" in v else ""
            console.print(f"  {label} {v['n']} 手：实际 {v['real_gain']:+.3f}（±{1.96 * v['se']:.3f}），模型原始 {v['model_gain']:+.3f}"
                          f"（兑现 {v['realized']:.2f}）{adv_txt}")
    console.print(f"[dim]结果写入 {path}[/]")


@rta_app.command("sim")
def rta_sim(
    side: Annotated[Optional[str], typer.Option("--side", help="你是 F（先手）还是 S（后手），默认随机")] = None,
    grades: Annotated[str, typer.Option("--grades", help="我方,对方 的段位，如 emperor,warlord")] = "emperor,emperor",
    rule: Annotated[str, typer.Option("--rule", help="开战规则：unknown（国服）/ none / opening_rule_desc_tid")] = "unknown",
    opponent: Annotated[str, typer.Option("--opponent", help="ai（模型按常见选法选）/ manual（对手也由你输入，复盘用）")] = "ai",
    pool: Annotated[str, typer.Option("--pool", help="我的英雄池（逗号分隔；不填 = 不限制）")] = "",
    seed: Annotated[Optional[int], typer.Option("--seed", help="随机种子（对手的预禁和选人）")] = None,
) -> None:
    """模拟 BP（B14b 加的，B14c 起用正式的推荐搜索）：你选一方，推荐 + 对手的回应 + 后禁矩阵；
    输入中文名或昵称，直接回车 = 第一个推荐（两手回合回车 = 推荐的那一对）。"""
    from e7helper.core.data import heroes as hero_db
    from e7helper.core.rta import rules, sim
    from e7helper.core.rta.audit import sample_preban
    from e7helper.core.rta.encode import UNK, DraftState

    db = hero_db()
    adv = _rta_advisor()
    m = adv.model
    rng = np.random.default_rng(seed)
    side = (side or str(rng.choice(["F", "S"]))).upper()
    if side not in ("F", "S") or opponent not in ("ai", "manual"):
        _fail("--side 只能是 F / S；--opponent 只能是 ai / manual")
        raise typer.Exit(2)
    foe = sim.other(side)
    nm = lambda c: _rta_name(db, c)  # noqa: E731
    my_pool = _rta_codes(db, pool) if pool else None

    def resolve(text: str) -> str | None:
        text = text.strip()
        h = db.get(text) or db.find(text) or next(iter(db.search(text, limit=1)), None)
        if not h:
            console.print(f"[red]找不到英雄：{text}[/]")
            return None
        if m.vocab.hero(h.code) == UNK:
            console.print(f"[yellow]{h.name} 不在模型词表里（训练数据里选得太少），按「其他英雄」算[/]")
        return h.code

    def ask(prompt: str, k: int, default: list[str] | None = None, ok=lambda codes: True) -> list[str]:
        while True:
            text = console.input(prompt).replace("，", ",").strip()
            if not text and default:
                return default
            codes = [resolve(s) for s in text.split(",") if s.strip()]
            if 1 <= len(codes) <= k and all(codes) and len(set(codes)) == len(codes) and ok(codes):
                return codes  # type: ignore[return-value]
            console.print(f"[red]要 {k} 名以内、不重复、能选的英雄[/]")

    me_label = "先手" if side == "F" else "后手"
    mine_g, theirs_g = _rta_grades(grades)
    grade = {side: mine_g, foe: theirs_g}
    rule_tid = _rta_rule(rule)
    console.print(f"[bold]模拟 BP[/]：你是 [bold]{me_label}[/] · 段位 我方 {mine_g} / 对方 {theirs_g} · 对手 "
                  f"{'模型（按常见选法）' if opponent == 'ai' else '你输入'}{' · 英雄池 ' + str(len(my_pool)) + ' 名' if my_pool else ''}")
    pre = adv.preban(side, grades=(mine_g, theirs_g), rule=rule_tid)
    console.print("预禁推荐：" + "、".join(f"{'+'.join(map(nm, r['heroes']))} {r['score']:.1%}" for r in pre["recommend"][:5]))
    my_pre = ask("你的 2 名预禁（逗号分隔，回车 = 第一个推荐）：", 2, default=pre["recommend"][0]["heroes"],
                 ok=lambda c: len(c) == 2)
    foe_pre = sample_preban(adv, foe, rng) if opponent == "ai" else ask("对手的 2 名预禁：", 2, ok=lambda c: len(c) == 2)
    console.print(f"预禁：你 {'、'.join(map(nm, my_pre))}；对手 {'、'.join(map(nm, foe_pre))}")
    state = DraftState(prebans={side: my_pre, foe: foe_pre}, grades=(grade["F"], grade["S"]), rule=rule_tid)
    curve = [("预禁后", float(sim.my_win(m.win([state])[0], side)))]

    def legal(codes: list[str], who: str) -> bool:
        st = state
        for c in codes:
            st = sim.with_pick(st, who, c)
        return not st.problems() and (who != side or my_pool is None or all(c in my_pool for c in codes))

    while state.n_picks < len(rules.PICK_ORDER):
        n = state.n_picks
        mover = rules.mover(n)
        if mover == side:
            out = adv.advise(state, side, pool=my_pool)
            _print_advice(out, db)
            left = rules.left_in_turn(n)
            codes = ask(f"第 {n + 1} 手 · 你选（{left} 名以内，回车 = 第一个推荐）：", left,
                        default=out["recommend"][0]["heroes"] if out["recommend"] else None, ok=lambda c: legal(c, side))
        elif opponent == "manual":
            codes = ask(f"第 {n + 1} 手 · 对手选：", rules.left_in_turn(n), ok=lambda c: legal(c, foe))
        else:
            code, p = sim.opponent_pick(m, state, rng)
            console.print(f"第 {n + 1} 手 · 对手选了 [bold]{nm(code)}[/]（模型认为这一手 {p:.0%} 的人会选它）")
            codes = [code]
        for code in codes:
            state = sim.with_pick(state, mover, code)
            curve.append((f"{'你' if mover == side else '对手'}：{nm(code)}", float(sim.my_win(m.win([state])[0], side))))
        console.print(f"当前你的胜率 [bold]{curve[-1][1]:.1%}[/]")

    out = adv.advise(state, side)
    _print_advice(out, db)
    b = out["ban"]
    mine = ask(f"你禁对方哪名（回车 = 推荐的 {nm(b['recommend'])}）：", 1, default=[b["recommend"]],
               ok=lambda c: c[0] in b["rows"])[0]
    if opponent == "manual":
        theirs = ask("对手禁了你哪名：", 1, ok=lambda c: c[0] in b["cols"])[0]
    else:
        theirs = b["cols"][sim.minimax_col(np.array(b["matrix"]))]
        console.print(f"对手禁了你的 [bold]{nm(theirs)}[/]（对它最稳妥的选择）")
    state = sim.with_bans(state, {foe: mine, side: theirs})
    curve.append(("后禁后", float(sim.my_win(m.win([state])[0], side))))
    console.print(f"\n[bold]最终你的胜率 {curve[-1][1]:.1%}[/]")
    console.print(f"你（{me_label}）：" + "、".join(nm(c) + ("（被禁）" if c == theirs else "") for c in state.picks[side]))
    console.print("对手：" + "、".join(nm(c) + ("（被禁）" if c == mine else "") for c in state.picks[foe]))
    console.print("胜率变化：" + " → ".join(f"{label} {p:.0%}" for label, p in curve))


@rta_app.command("watch")
def rta_watch(
    port: Annotated[int, typer.Option("--port", help="端口")] = 47900,
    root: Annotated[Optional[Path], typer.Option("--root", help="runs 目录，默认 F:\\e7helper-data\\rta\\runs")] = None,
) -> None:
    """训练曲线页（B14b）：浏览器打开 http://127.0.0.1:<端口>/，每 5 秒刷新。"""
    import uvicorn

    from e7helper.core.rta.train import runs_dir
    from e7helper.core.rta.train.watch import create_app

    root = root or runs_dir()
    root.mkdir(parents=True, exist_ok=True)
    config = server_config(create_app(root))
    config.host, config.port = "127.0.0.1", port
    console.print(f"训练曲线：http://127.0.0.1:{port}/ · 读 {root}（Ctrl+C 停止）")
    uvicorn.Server(config).run()


if __name__ == "__main__":
    app()
