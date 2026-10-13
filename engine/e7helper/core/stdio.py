"""隔离原生代码的 stdout / stderr。

MuMu 的 external_renderer_ipc.dll 会把调试信息写到原生 stdout（nemu_connect）和 stderr（touch 坐标），
而且是静态 CRT 的缓冲输出，外部无法拦截。这里把进程的 fd 1/2 和 Win32 标准句柄永久指向 NUL，
Python 自己的 sys.stdout / sys.stderr 改为写到复制出来的原句柄。由入口（CLI / API 服务）显式调用一次。
"""

from __future__ import annotations

import io
import os
import sys

_done = False

# (fd, sys 属性名, Win32 STD_*_HANDLE)
_STREAMS = ((1, "stdout", -11), (2, "stderr", -12))


def _enable_vt(fd: int) -> None:
    """重定向后标准句柄指向 NUL，Rich 无法再走旧版控制台 API，因此提前给真实控制台开启 VT 模式，
    并让 Console 使用 legacy_windows=False（见 core.log.make_console）。"""
    import ctypes
    import msvcrt

    kernel32 = ctypes.windll.kernel32
    handle = msvcrt.get_osfhandle(fd)
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def _isolate(fd: int, attr: str, std_handle: int) -> None:
    stream = getattr(sys, attr)
    if stream is None:
        return
    try:
        if stream.fileno() != fd:
            return  # 已被替换（例如 pytest 捕获输出时）
    except (AttributeError, ValueError, io.UnsupportedOperation):
        return
    stream.flush()
    if sys.platform == "win32":
        _enable_vt(fd)
    py_fd = os.dup(fd)
    null_fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null_fd, fd)
    os.close(null_fd)
    if sys.platform == "win32":
        # 静态 CRT 通过 GetStdHandle 取句柄，os.dup2 不会更新它，需要显式设置
        import ctypes
        import msvcrt

        ctypes.windll.kernel32.SetStdHandle(std_handle, msvcrt.get_osfhandle(fd))
    setattr(sys, attr, _open_text(py_fd, stream.encoding or "utf-8"))


def _open_text(fd: int, encoding: str) -> io.TextIOWrapper:
    # 控制台必须走 WriteConsoleW（与 Python 默认一致），否则在 GBK 代码页下中文乱码
    console_io = getattr(io, "_WindowsConsoleIO", None)
    if console_io is not None and os.isatty(fd):
        return io.TextIOWrapper(
            io.BufferedWriter(console_io(fd, "w", closefd=True)),
            encoding="utf-8", errors="replace", line_buffering=True,
        )
    return io.TextIOWrapper(
        io.FileIO(fd, "w", closefd=True), encoding=encoding, errors="replace", line_buffering=True
    )


def isolate_native_stdout() -> None:
    global _done
    if _done:
        return
    for fd, attr, std_handle in _STREAMS:
        _isolate(fd, attr, std_handle)
    _done = True
