"""视觉层：模板匹配 + 模板存储 + OCR。

模块里通过 `self.ctx.vision` 使用：
    frame = self.device.screenshot()
    m = self.ctx.vision.find(frame, "shop/refresh")      # 命中返回 Match，否则 None
    n = self.ctx.vision.ocr.read_number(frame, Rect(...))

坐标一律是 1600x900 基准；点击前用 Scaler(*device.resolution).to_device(*m.center) 换算。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

from e7helper.core.geometry import Rect

from . import matcher
from .matcher import DEFAULT_NMS_IOU, Match, best_match, find, find_all, match_template, nms
from .ocr import Ocr, OcrResult, default_ocr, normalize_text, parse_fraction, parse_number
from .template_store import (
    DEFAULT_LANG,
    DEFAULT_THRESHOLD,
    Template,
    TemplateMeta,
    TemplateNotFound,
    TemplateStore,
)

# 跨模块共用的界面模板（返回键、主页、资源图标等）放在 assets/common/<lang>/
COMMON_ID = "common"

TemplateRef = str | Template


class Vision:
    """按顺序在多个 TemplateStore 中查找模板（模块自己的优先，其次 common）。"""

    def __init__(self, stores: Sequence[TemplateStore], ocr: Ocr | None = None):
        self.stores = list(stores)
        self._ocr = ocr

    @classmethod
    def for_module(cls, module_id: str, lang: str = DEFAULT_LANG, ocr: Ocr | None = None) -> Vision:
        stores = [TemplateStore.for_module(module_id, lang)]
        if module_id != COMMON_ID:
            stores.append(TemplateStore.for_module(COMMON_ID, lang))
        return cls(stores, ocr)

    @property
    def ocr(self) -> Ocr:
        if self._ocr is None:
            self._ocr = default_ocr()
        return self._ocr

    def template(self, ref: TemplateRef) -> Template:
        if isinstance(ref, Template):
            return ref
        for store in self.stores:
            if ref in store:
                return store.get(ref)
        raise TemplateNotFound(f"模板不存在：{ref}（已查找：{', '.join(str(s.root) for s in self.stores)}）")

    def find(self, frame: np.ndarray, ref: TemplateRef, region: Rect | None = None,
             threshold: float | None = None) -> Match | None:
        return find(frame, self.template(ref), region, threshold)

    def exists(self, frame: np.ndarray, ref: TemplateRef, region: Rect | None = None,
               threshold: float | None = None) -> bool:
        return self.find(frame, ref, region, threshold) is not None

    def best(self, frame: np.ndarray, ref: TemplateRef, region: Rect | None = None) -> Match | None:
        return best_match(frame, self.template(ref), region)

    def find_all(self, frame: np.ndarray, ref: TemplateRef, region: Rect | None = None,
                 threshold: float | None = None, max_count: int = 50,
                 nms_iou: float = DEFAULT_NMS_IOU) -> list[Match]:
        return find_all(frame, self.template(ref), region, threshold, max_count, nms_iou)

    def find_any(self, frame: np.ndarray, refs: Iterable[TemplateRef],
                 region: Rect | None = None) -> Match | None:
        """多个模板中分数最高的命中（例如识别当前是哪个界面）。"""
        hits = [m for r in refs if (m := self.find(frame, r, region)) is not None]
        return max(hits, key=lambda m: m.score, default=None)


__all__ = [
    "COMMON_ID",
    "DEFAULT_LANG",
    "DEFAULT_THRESHOLD",
    "Match",
    "Ocr",
    "OcrResult",
    "Template",
    "TemplateMeta",
    "TemplateNotFound",
    "TemplateStore",
    "Vision",
    "best_match",
    "default_ocr",
    "find",
    "find_all",
    "match_template",
    "matcher",
    "nms",
    "normalize_text",
    "parse_fraction",
    "parse_number",
]
