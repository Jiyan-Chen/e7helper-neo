"""点击随机化：在命中框内随机取点、随机按压时长、点击后随机等待。坐标均为 1600x900 基准。"""

from __future__ import annotations

import random
from dataclasses import dataclass

from e7helper.core.geometry import BASE_HEIGHT, BASE_WIDTH, Rect


@dataclass(frozen=True)
class Humanize:
    jitter_px: float = 2.0  # 点击固定坐标时的高斯抖动标准差（基准像素）
    rect_spread: float = 0.15  # 点击矩形时，偏移的标准差 = 宽/高 × 该值
    rect_margin: float = 0.2  # 点击矩形时，离边缘至少留 宽/高 × 该值
    press: tuple[float, float] = (0.04, 0.09)  # 按压时长范围（秒）
    delay: tuple[float, float] = (0.25, 0.55)  # 点击/滑动后的随机等待（秒）
    swipe_jitter_px: float = 4.0  # 滑动起止点的抖动
    swipe_stretch: tuple[float, float] = (0.9, 1.15)  # 滑动时长的随机倍率

    @classmethod
    def off(cls) -> Humanize:
        """不随机、不等待（测试和调试用）。"""
        return cls(0.0, 0.0, 0.0, (0.05, 0.05), (0.0, 0.0), 0.0, (1.0, 1.0))

    def jitter(self, x: float, y: float, rng: random.Random, sigma: float | None = None) -> tuple[int, int]:
        s = self.jitter_px if sigma is None else sigma
        if s > 0:
            # 截断在 ±2σ，避免偶发的大偏移点到旁边的按钮
            x += max(-2 * s, min(2 * s, rng.gauss(0, s)))
            y += max(-2 * s, min(2 * s, rng.gauss(0, s)))
        return _clamp(round(x), BASE_WIDTH), _clamp(round(y), BASE_HEIGHT)

    def point_in(self, rect: Rect, rng: random.Random) -> tuple[int, int]:
        """矩形内的随机点：以中心为均值的截断正态分布，不会落到边缘 rect_margin 以内。"""
        cx, cy = rect.x + rect.w / 2, rect.y + rect.h / 2
        x = cx + _truncated(rng, rect.w * self.rect_spread, rect.w * (0.5 - self.rect_margin))
        y = cy + _truncated(rng, rect.h * self.rect_spread, rect.h * (0.5 - self.rect_margin))
        return _clamp(round(x), BASE_WIDTH), _clamp(round(y), BASE_HEIGHT)

    def press_time(self, rng: random.Random) -> float:
        return rng.uniform(*self.press)

    def delay_time(self, rng: random.Random) -> float:
        return rng.uniform(*self.delay)


def _truncated(rng: random.Random, sigma: float, limit: float) -> float:
    if sigma <= 0 or limit <= 0:
        return 0.0
    return max(-limit, min(limit, rng.gauss(0, sigma)))


def _clamp(v: int, size: int) -> int:
    return max(0, min(size - 1, v))
