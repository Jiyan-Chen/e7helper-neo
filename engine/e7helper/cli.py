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


if __name__ == "__main__":
    app()
