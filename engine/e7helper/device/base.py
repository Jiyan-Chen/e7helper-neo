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

    def back(self) -> None:
        """Android 返回键。游戏里一般用来关闭弹窗；在大厅按会弹出「结束游戏」确认框。"""
        raise DeviceError(f"{self.name} 不支持返回键")

    def input_text(self, text: str) -> None:
        """往当前获得焦点的输入框里打字（B12：换世界频道要输入频道号）。"""
        raise DeviceError(f"{self.name} 不支持输入文字")

    def close(self) -> None:  # noqa: B027 - 可选覆盖
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
