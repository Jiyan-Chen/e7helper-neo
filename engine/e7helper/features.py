"""可选功能：打包时可以不带的部分（发布 0.3.0 起）。

正式版用 `packaging/build.py --no-rta` 冻结，产物里没有 `e7helper.core.rta` / `e7helper.api.rta`
和 `assets/data/rta`；引擎按代码在不在决定挂不挂 RTA 接口，`GET /api/status` 的 `features`
告诉 GUI 显示哪些页面。开发环境里代码都在，所以总是全部打开。
"""

from __future__ import annotations

import importlib.util
from functools import cache


@cache
def has_rta() -> bool:
    """RTA 选秀助手（B14）在不在这个版本里。"""
    return importlib.util.find_spec("e7helper.core.rta") is not None and \
        importlib.util.find_spec("e7helper.api.rta") is not None


def features() -> dict[str, bool]:
    return {"rta": has_rta()}
