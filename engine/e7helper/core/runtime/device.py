"""运行时交给模块的设备代理。

- SharedDevice：所有调用加同一把锁。任务线程和帧泵（给助手模块截图）会并发访问设备。
- ReadOnlyDevice：给 AssistantModule 用，只能截图，点击/滑动/返回键直接报错。

代理的 close() 不关闭底层设备，底层设备由创建它的人（CLI / API 服务）负责关闭。
"""

from __future__ import annotations

import threading

import numpy as np

from e7helper.device import Device, DeviceError


class SharedDevice(Device):
    def __init__(self, device: Device, lock: threading.RLock | None = None):
        self.inner = device
        self.lock = lock or threading.RLock()

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def resolution(self) -> tuple[int, int]:
        return self.inner.resolution

    def screenshot(self) -> np.ndarray:
        with self.lock:
            return self.inner.screenshot()

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        with self.lock:
            self.inner.tap(x, y, duration)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        with self.lock:
            self.inner.swipe(x1, y1, x2, y2, duration)

    def back(self) -> None:
        with self.lock:
            self.inner.back()

    def input_text(self, text: str) -> None:
        with self.lock:
            self.inner.input_text(text)

    def close(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"SharedDevice({self.inner.name!r})"


class ReadOnlyDevice(SharedDevice):
    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        raise DeviceError("助手模块不能操作游戏（tap）")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        raise DeviceError("助手模块不能操作游戏（swipe）")

    def back(self) -> None:
        raise DeviceError("助手模块不能操作游戏（back）")

    def input_text(self, text: str) -> None:
        raise DeviceError("助手模块不能操作游戏（input_text）")
