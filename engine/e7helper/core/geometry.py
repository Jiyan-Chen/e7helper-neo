"""基准坐标系。

所有模板、坐标、区域都以 1600x900 为基准记录，运行时按设备实际分辨率缩放。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

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

    def rect_to_device(self, rect: Rect) -> Rect:
        x1, y1 = self.to_device(rect.x, rect.y)
        x2, y2 = self.to_device(rect.right, rect.bottom)
        return Rect(x1, y1, x2 - x1, y2 - y1)

    def rect_to_base(self, rect: Rect) -> Rect:
        x1, y1 = self.to_base(rect.x, rect.y)
        x2, y2 = self.to_base(rect.right, rect.bottom)
        return Rect(x1, y1, x2 - x1, y2 - y1)


class Rect(NamedTuple):
    """矩形区域 (x, y, w, h)，左上角 + 宽高。坐标系由上下文决定（一般是 1600x900 基准）。"""

    x: int
    y: int
    w: int
    h: int

    @classmethod
    def parse(cls, value: str | Sequence[int]) -> Rect:
        """接受 "x,y,w,h" 字符串或 4 元素序列。"""
        if isinstance(value, str):
            parts = [p for p in value.replace(" ", ",").split(",") if p]
        else:
            parts = list(value)
        if len(parts) != 4:
            raise ValueError(f"区域需要 4 个数 x,y,w,h，得到：{value!r}")
        x, y, w, h = (int(round(float(p))) for p in parts)
        if w <= 0 or h <= 0:
            raise ValueError(f"区域宽高必须为正：{value!r}")
        return cls(x, y, w, h)

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def area(self) -> int:
        return self.w * self.h

    def expand(self, margin: int) -> Rect:
        return Rect(self.x - margin, self.y - margin, self.w + 2 * margin, self.h + 2 * margin)

    def clip(self, width: int = BASE_WIDTH, height: int = BASE_HEIGHT) -> Rect:
        """裁到 [0, width) x [0, height) 内；完全在外时返回宽高为 0 的矩形。"""
        x1, y1 = max(self.x, 0), max(self.y, 0)
        x2, y2 = min(self.right, width), min(self.bottom, height)
        return Rect(x1, y1, max(x2 - x1, 0), max(y2 - y1, 0))

    def contains(self, other: Rect) -> bool:
        return self.x <= other.x and self.y <= other.y and other.right <= self.right and other.bottom <= self.bottom

    def iou(self, other: Rect) -> float:
        iw = min(self.right, other.right) - max(self.x, other.x)
        ih = min(self.bottom, other.bottom) - max(self.y, other.y)
        if iw <= 0 or ih <= 0:
            return 0.0
        inter = iw * ih
        return inter / (self.area + other.area - inter)

    def crop(self, image: np.ndarray) -> np.ndarray:
        """按本矩形裁剪图像（坐标需与图像同一坐标系），返回视图。"""
        r = self.clip(image.shape[1], image.shape[0])
        return image[r.y : r.bottom, r.x : r.right]


FULL_SCREEN = Rect(0, 0, BASE_WIDTH, BASE_HEIGHT)
