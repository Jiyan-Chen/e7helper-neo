"""卡死检测。

两种信号，任一满足即判定卡死（帧数和时长两个条件都要达到，避免截图频率不同导致误判）：
- 画面不变：连续 still_frames 帧与参照帧的平均差 < still_diff，且持续 still_seconds 秒；
- 场景不变：连续 scene_checks 次场景识别结果（场景 + 弹窗）相同，且持续 scene_seconds 秒。
  大厅这类有动画的界面画面一直在变，只能靠这一条。

任务在取得进展时（买到东西、打完一场……）调用 `ctl.progress()` 清零计数，
否则长时间停留在同一场景里正常工作也会被判定卡死。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

_THUMB = (160, 90)


def thumbnail(frame: np.ndarray) -> np.ndarray:
    """160x90 灰度缩略图，用于比较画面变化。"""
    return cv2.cvtColor(cv2.resize(frame, _THUMB, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)


def thumb_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(cv2.absdiff(a, b).mean())


@dataclass(frozen=True)
class StuckConfig:
    enabled: bool = True
    still_frames: int = 30
    still_seconds: float = 60.0
    still_diff: float = 1.5  # 160x90 灰度缩略图的平均像素差
    scene_checks: int = 120
    scene_seconds: float = 300.0


class StuckDetector:
    def __init__(self, config: StuckConfig | None = None, clock: Callable[[], float] = time.monotonic):
        self.config = config or StuckConfig()
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        now = self._clock()
        self._ref: np.ndarray | None = None
        self._still_count = 0
        self._still_since = now
        self._scene: str | None = None
        self._scene_count = 0
        self._scene_since = now

    def feed_frame(self, frame: np.ndarray) -> None:
        thumb = thumbnail(frame)
        now = self._clock()
        # 和「静止开始时」的参照帧比，而不是和上一帧比：缓慢渐变的画面也能被看作在变化
        if self._ref is not None and thumb_diff(thumb, self._ref) < self.config.still_diff:
            self._still_count += 1
        else:
            self._ref = thumb
            self._still_count = 0
            self._still_since = now

    def feed_scene(self, key: str) -> None:
        now = self._clock()
        if key == self._scene:
            self._scene_count += 1
        else:
            self._scene = key
            self._scene_count = 0
            self._scene_since = now

    @property
    def reason(self) -> str | None:
        """卡死时返回原因，否则 None。"""
        c = self.config
        if not c.enabled:
            return None
        now = self._clock()
        if self._still_count >= c.still_frames and now - self._still_since >= c.still_seconds:
            return f"画面连续 {self._still_count} 帧、{now - self._still_since:.0f} 秒没有变化"
        if self._scene_count >= c.scene_checks and now - self._scene_since >= c.scene_seconds:
            return f"场景 {self._scene} 连续 {self._scene_count} 次、{now - self._scene_since:.0f} 秒没有推进"
        return None
