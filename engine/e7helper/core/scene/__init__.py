"""场景识别与弹窗：

    detector = default_detector()
    state = detector.detect(frame)       # SceneState(scene="lobby", popup=None, ...)
    if state.is_("lobby"): ...

任务里一般通过 `self.ctl`（runtime.Controller）使用：`ctl.detect()`、`ctl.dismiss_popups()`、
`ctl.wait_scene("lobby")`。详见 docs/architecture.md。
"""

from __future__ import annotations

from e7helper.core.vision import COMMON_ID, Vision

from . import builtin
from .detector import DEFAULT_DIM_RATIO, SceneDetector, SceneState
from .model import OBSCURED, OBSCURED_POPUP, Dismiss, DismissKind, Popup, Scene


def default_detector(vision: Vision | None = None) -> SceneDetector:
    """带内置场景和弹窗的识别器；vision 默认用 common 模板。"""
    return SceneDetector(vision or Vision.for_module(COMMON_ID), builtin.SCENES, builtin.POPUPS)


__all__ = [
    "DEFAULT_DIM_RATIO",
    "OBSCURED",
    "OBSCURED_POPUP",
    "Dismiss",
    "DismissKind",
    "Popup",
    "Scene",
    "SceneDetector",
    "SceneState",
    "default_detector",
]
