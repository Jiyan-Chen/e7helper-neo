"""基准坐标系。

所有模板、坐标、区域都以 1600x900 为基准记录，运行时按设备实际分辨率缩放。
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_WIDTH = 1600
BASE_HEIGHT = 900


def is_16_9(width: int, height: int) -> bool:
    return width * 9 == height * 16


@dataclass(frozen=True)
class Scaler:
    """在基准坐标（1600x900）和设备坐标之间换算。"""

    device_width: int
    device_height: int

    @property
    def factor(self) -> float:
        return self.device_width / BASE_WIDTH

    @property
    def is_base(self) -> bool:
        return (self.device_width, self.device_height) == (BASE_WIDTH, BASE_HEIGHT)

    def to_device(self, x: float, y: float) -> tuple[int, int]:
        return round(x * self.device_width / BASE_WIDTH), round(y * self.device_height / BASE_HEIGHT)

    def to_base(self, x: float, y: float) -> tuple[int, int]:
        return round(x * BASE_WIDTH / self.device_width), round(y * BASE_HEIGHT / self.device_height)
