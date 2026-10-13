"""统一设备接口。上层（视觉、任务、助手模块）只依赖这个接口。

坐标均为设备原生像素；与 1600x900 基准之间的换算见 core.geometry.Scaler。
截图统一返回 BGR、uint8、形状 (H, W, 3) 的 numpy 数组（OpenCV 习惯）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class DeviceError(RuntimeError):
    pass


class Device(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def resolution(self) -> tuple[int, int]:
        """(width, height)，横屏方向。"""

    @abstractmethod
    def screenshot(self) -> np.ndarray: ...

    @abstractmethod
    def tap(self, x: int, y: int, duration: float = 0.05) -> None: ...

    @abstractmethod
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None: ...

    def close(self) -> None:  # noqa: B027 - 可选覆盖
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
