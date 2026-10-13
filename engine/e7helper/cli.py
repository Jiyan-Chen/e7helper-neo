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
import typer
from rich.table import Table

from e7helper import GAME_PACKAGE, __version__
from e7helper.core.geometry import BASE_HEIGHT, BASE_WIDTH, is_16_9
from e7helper.core.log import make_console, setup_logging
from e7helper.core.paths import module_assets_dir, module_data_dir
from e7helper.core.stdio import isolate_native_stdout
from e7helper.device import Backend, DeviceError, MuMuManager, connect, find_install
from e7helper.modules import ModuleContext, ModuleKind, TaskModule, discover

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
) -> None:
    """直接运行一个任务模块（B03 之后会改由 runtime 调度）。"""
    modules = discover()
    cls = modules.get(module_id)
    if cls is None:
        _fail(f"未知模块：{module_id}（可用：{', '.join(modules)}）")
        raise typer.Exit(1)
    if cls.kind is not ModuleKind.TASK or not issubclass(cls, TaskModule):
        _fail(f"{module_id} 不是任务模块")
        raise typer.Exit(1)
    cfg = cls.config_model.model_validate_json(config) if config else cls.config_model()
    with connect(index, Backend.AUTO, mumu_root) as device:
        ctx = ModuleContext(
            device=device,
            logger=logging.getLogger(f"module.{module_id}"),
            assets_dir=module_assets_dir(module_id),
            data_dir=module_data_dir(module_id),
        )
        module = cls(ctx, cfg)
        try:
            module.run()
        except KeyboardInterrupt:
            ctx.stop_event.set()
            _warn("已中断")


if __name__ == "__main__":
    app()
