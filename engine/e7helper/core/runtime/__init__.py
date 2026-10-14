"""运行时：任务调度（互斥、急停、超时、卡死检测、调试截图）、助手模块的帧分发、任务的操作入口。

    from e7helper.core.runtime import Runtime
    with Runtime(device) as rt:
        result = rt.run_task(MyTask, timeout=600)

模块里用 `self.ctl`（Controller）操作游戏，详见 controller.py 和 docs/architecture.md。
"""

from __future__ import annotations

from .controller import AbortSignal, Controller
from .device import ReadOnlyDevice, SharedDevice
from .errors import (
    PopupError,
    RuntimeBusy,
    TaskAborted,
    TaskStatus,
    TaskStopped,
    TaskStuck,
    TaskTimeout,
    WaitTimeout,
)
from .humanize import Humanize
from .stuck import StuckConfig, StuckDetector

# runner 依赖 modules.base（模块契约），放在最后导入；modules.base 只在类型检查时引用本包
from .runner import AssistantHandle, Runtime, TaskHandle, TaskResult  # noqa: E402

__all__ = [
    "AbortSignal",
    "AssistantHandle",
    "Controller",
    "Humanize",
    "PopupError",
    "ReadOnlyDevice",
    "Runtime",
    "RuntimeBusy",
    "SharedDevice",
    "StuckConfig",
    "StuckDetector",
    "TaskAborted",
    "TaskHandle",
    "TaskResult",
    "TaskStatus",
    "TaskStopped",
    "TaskStuck",
    "TaskTimeout",
    "WaitTimeout",
]
