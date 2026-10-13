from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

_configured = False


def make_console(stderr: bool = False) -> Console:
    # 固定走 VT 转义序列：isolate_native_stdout() 之后 Win32 标准句柄指向 NUL，旧版控制台 API 不可用
    return Console(stderr=stderr, legacy_windows=False)


def setup_logging(level: int | str = logging.INFO) -> None:
    global _configured
    if _configured:
        logging.getLogger().setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format="%(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=make_console(), show_path=False, rich_tracebacks=True)],
    )
    _configured = True
