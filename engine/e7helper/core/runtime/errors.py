"""运行时异常。

TaskAborted 系列继承 BaseException：模块里常见的 `except Exception` 重试逻辑不会把急停/超时/卡死吞掉，
与 KeyboardInterrupt 同理。模块不要捕获它们。
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    STOPPED = "stopped"  # 用户急停
    TIMEOUT = "timeout"  # 超过任务时限
    STUCK = "stuck"  # 卡死检测触发
    FAILED = "failed"  # 模块抛出异常


class TaskAborted(BaseException):  # noqa: N818 - 与 KeyboardInterrupt 同类，不叫 Error
    status: TaskStatus = TaskStatus.STOPPED

    def __init__(self, message: str = ""):
        super().__init__(message or self.status.value)


class TaskStopped(TaskAborted):
    status = TaskStatus.STOPPED


class TaskTimeout(TaskAborted):
    status = TaskStatus.TIMEOUT


class TaskStuck(TaskAborted):
    status = TaskStatus.STUCK


class RuntimeBusy(RuntimeError):
    """设备上已经有任务在跑（TaskModule 互斥），或设备已被另一个 Runtime 占用。"""


class WaitTimeout(TimeoutError):
    """ctl.wait / wait_scene 等待超时。普通异常，任务可以捕获后自行处理。"""


class PopupError(RuntimeError):
    """弹窗无法自动关闭：auto=False 的弹窗，或反复关闭仍然存在。"""

    def __init__(self, popup: str, message: str):
        super().__init__(message)
        self.popup = popup
