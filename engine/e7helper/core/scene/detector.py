"""场景识别：一帧 → 当前场景 + 是否有弹窗。

判定顺序：
1. 弹窗：按注册顺序，第一个条件满足的弹窗；
2. 场景：按注册顺序，第一个条件满足的场景；
3. 遮罩：没认出弹窗时，检查画面是否被压暗——命中场景的锚点模板，或探针模板（默认左上角返回键，
   只要分数够高），所在位置的亮度（98 分位灰度）不到模板自身亮度的 dim_ratio 倍。
   满足即认为有未知弹窗（popup = OBSCURED，用返回键关闭）。
   不用 diff 判断压暗：白色图标在亮背景上 diff 也会到 30+，亮度比更稳（正常 ≈1.0，压暗 ≈0.15–0.25）。

相关系数对亮度不敏感，被遮罩压暗的场景模板照样能命中，所以「场景」不能单看模板分数，
必须结合弹窗/遮罩一起判断：只有 `state.clear` 为真时，scene 才是可以直接操作的界面。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import cv2
import numpy as np

from e7helper.core.geometry import Scaler
from e7helper.core.vision import Match, Vision, normalize_text

from .model import OBSCURED, OBSCURED_POPUP, Popup, Scene

log = logging.getLogger(__name__)

# 命中位置亮度 / 模板亮度 低于此值视为被遮罩压暗（实测正常 ≈1.0，压暗 0.15–0.33）
DEFAULT_DIM_RATIO = 0.6
DEFAULT_DIM_PROBES = ("back",)


@dataclass
class SceneState:
    scene: str | None
    popup: str | None = None
    obscured: bool = False  # 画面被压暗（有遮罩类弹窗）
    matches: dict[str, Match] = field(default_factory=dict)  # 本次判定命中的模板
    elapsed_ms: float = 0.0

    @property
    def clear(self) -> bool:
        """没有弹窗，scene 就是当前可操作的界面。"""
        return self.popup is None

    def is_(self, *scenes: str) -> bool:
        """当前是这些场景之一，且没有弹窗。"""
        return self.clear and self.scene in scenes

    def __str__(self) -> str:
        s = self.scene or "未知"
        if self.popup:
            s += f" + 弹窗 {self.popup}"
        return s


class SceneDetector:
    def __init__(
        self,
        vision: Vision,
        scenes: Iterable[Scene] = (),
        popups: Iterable[Popup] = (),
        *,
        dim_ratio: float = DEFAULT_DIM_RATIO,
        dim_probes: Iterable[str] = DEFAULT_DIM_PROBES,
    ):
        self.vision = vision
        self.dim_ratio = dim_ratio
        self.dim_probes = tuple(dim_probes)
        self._scenes: dict[str, Scene] = {}
        self._popups: dict[str, Popup] = {}
        for s in scenes:
            self.add_scene(s)
        for p in popups:
            self.add_popup(p)

    # ------------------------------------------------------------ 注册

    @property
    def scenes(self) -> list[Scene]:
        return list(self._scenes.values())

    @property
    def popups(self) -> list[Popup]:
        return list(self._popups.values())

    def add_scene(self, scene: Scene, *, replace: bool = False, first: bool = False) -> None:
        """注册场景。first=True 时排到最前（更具体的场景应该先判定）。"""
        self._scenes = _insert(self._scenes, scene.name, scene, replace, first, "场景")

    def add_popup(self, popup: Popup, *, replace: bool = False, first: bool = False) -> None:
        if popup.name == OBSCURED:
            raise ValueError(f"弹窗名 {OBSCURED} 是保留的")
        self._popups = _insert(self._popups, popup.name, popup, replace, first, "弹窗")

    def scene(self, name: str) -> Scene:
        return self._scenes[name]

    def popup(self, name: str) -> Popup:
        if name == OBSCURED:
            return OBSCURED_POPUP
        return self._popups[name]

    # ------------------------------------------------------------ 判定

    def detect(self, frame: np.ndarray) -> SceneState:
        t0 = time.perf_counter()
        memo: dict[str, Match | None] = {}

        def find(ref: str) -> Match | None:
            if ref not in memo:
                memo[ref] = self.vision.find(frame, ref)
            return memo[ref]

        def satisfied(all_of: tuple[str, ...], none_of: tuple[str, ...]) -> bool:
            return all(find(r) is not None for r in all_of) and all(find(r) is None for r in none_of)

        popup: str | None = None
        for p in self._popups.values():
            if satisfied(p.all_of, p.none_of) and self._text_ok(frame, p):
                popup = p.name
                break

        scene: str | None = None
        for s in self._scenes.values():
            if satisfied(s.all_of, s.none_of):
                scene = s.name
                break

        obscured = False
        if scene is not None:
            obscured = any(self._dimmed(frame, m, r) for r in self._scenes[scene].all_of if (m := memo.get(r)) is not None)
        if not obscured:
            for ref in self.dim_probes:
                m = self.vision.best(frame, ref)
                if m is not None and m.score >= self.vision.template(ref).threshold and self._dimmed(frame, m, ref):
                    obscured = True
                    break
        if popup is None and obscured:
            popup = OBSCURED

        used = {k: m for k, m in memo.items() if m is not None}
        return SceneState(scene, popup, obscured, used, (time.perf_counter() - t0) * 1000)

    def _dimmed(self, frame: np.ndarray, m: Match, ref: str) -> bool:
        # ref 是注册时的引用（可能是限定引用），m.name 只是模板名，不能拿来查找
        tpl = self.vision.template(ref)
        ref_bright = _bright(tpl.image)
        if ref_bright < 40:
            return False  # 模板本身很暗，看不出压暗
        patch = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(m.rect).crop(frame)
        return patch.size > 0 and _bright(patch) < ref_bright * self.dim_ratio

    def _text_ok(self, frame: np.ndarray, popup: Popup) -> bool:
        if popup.text is None:
            return True
        text = self.vision.ocr.read_text(frame, popup.text_region)
        return normalize_text(popup.text) in normalize_text(text)


def _bright(img: np.ndarray) -> float:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(np.percentile(gray, 98))


def _insert(d: dict, key: str, value, replace: bool, first: bool, what: str) -> dict:
    if key in d and not replace:
        raise ValueError(f"{what} {key} 已注册")
    d = {k: v for k, v in d.items() if k != key}
    return {key: value, **d} if first else {**d, key: value}
