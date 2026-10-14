"""模板匹配（TM_CCOEFF_NORMED）。

输入帧可以是任意 16:9 分辨率。模板以 1600x900 基准保存，匹配时按帧宽缩放到设备尺寸，
只在检索区域内搜索，结果统一换算回基准坐标。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from e7helper.core.geometry import Rect, Scaler

from .template_store import Template

DEFAULT_NMS_IOU = 0.3
_MAX_REJECTED = 20  # 颜色校验不通过时最多再看多少个候选


@dataclass(frozen=True)
class Match:
    name: str
    score: float
    rect: Rect  # 基准坐标
    scale: float = 1.0  # 命中的相对缩放（多尺度时有意义）
    diff: float = 0.0  # 命中位置与模板的平均像素差（0-255），用于颜色/亮度校验

    @property
    def center(self) -> tuple[int, int]:
        return self.rect.center

    def __str__(self) -> str:
        r = self.rect
        return f"{self.name}@({r.x},{r.y},{r.w},{r.h}) score={self.score:.3f} diff={self.diff:.1f}"


def _gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _peaks(
    res: np.ndarray, tw: int, th: int, threshold: float, max_count: int,
    accept: Callable[[int, int], bool] | None = None,
) -> list[tuple[float, int, int]]:
    """在相关图上依次取最大值，并抑制其邻域（模板尺寸的一半），得到互不重叠的候选。

    accept 不通过的候选会被跳过（同样抑制邻域），继续找下一个。
    """
    if max_count == 1 and accept is None:
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        return [(float(score), x, y)] if score >= threshold else []
    out: list[tuple[float, int, int]] = []
    res = res.copy()
    rx, ry = max(tw // 2, 1), max(th // 2, 1)
    for _ in range(max_count + _MAX_REJECTED):
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if score < threshold:
            break
        res[max(y - ry, 0) : y + ry + 1, max(x - rx, 0) : x + rx + 1] = -1.0
        if accept is None or accept(x, y):
            out.append((float(score), x, y))
            if len(out) >= max_count:
                break
    return out


def nms(matches: list[Match], iou: float = DEFAULT_NMS_IOU) -> list[Match]:
    """按分数从高到低贪心保留，去掉与已保留结果 IoU 超过阈值的。"""
    kept: list[Match] = []
    for m in sorted(matches, key=lambda m: m.score, reverse=True):
        if all(m.rect.iou(k.rect) <= iou for k in kept):
            kept.append(m)
    return kept


def match_template(
    frame: np.ndarray,
    template: Template,
    region: Rect | None = None,
    threshold: float | None = None,
    max_count: int = 1,
    nms_iou: float = DEFAULT_NMS_IOU,
) -> list[Match]:
    """返回分数 >= threshold 的命中（按分数降序，最多 max_count 个）。

    threshold 传 -1 可以拿到最佳匹配而不管分数，此时也不做颜色校验（用于回验和调试）。
    region 为基准坐标，省略时用模板自己的 region。

    TM_CCOEFF_NORMED 对亮度/对比度的线性变化不敏感：被弹窗遮罩压暗的按钮照样能得高分。
    模板 meta 设置了 max_diff 时，命中位置与模板的平均像素差超过它就不算命中。
    """
    fh, fw = frame.shape[:2]
    scaler = Scaler(fw, fh)
    thr = template.threshold if threshold is None else threshold
    search = (region or template.region).clip()
    roi_rect = scaler.rect_to_device(search).clip(fw, fh)
    if roi_rect.area == 0:
        return []
    gray = template.meta.grayscale
    max_diff = template.meta.max_diff
    roi = roi_rect.crop(frame)
    if gray:
        roi = _gray(roi)

    found: list[Match] = []
    for rel in template.meta.scales:
        tmpl = template.scaled(scaler.factor * rel, gray)
        th, tw = tmpl.shape[:2]
        if th > roi.shape[0] or tw > roi.shape[1]:
            continue
        res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
        # 纯色区域会产生 nan/inf
        np.nan_to_num(res, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

        def diff_at(x: int, y: int, tmpl=tmpl, th=th, tw=tw) -> float:
            patch = roi[y : y + th, x : x + tw]
            return float(cv2.absdiff(patch, tmpl).mean())

        accept = None
        if max_diff is not None and thr >= 0:
            accept = lambda x, y, d=diff_at: d(x, y) <= max_diff  # noqa: E731
        for score, x, y in _peaks(res, tw, th, thr, max_count, accept):
            dev = Rect(roi_rect.x + x, roi_rect.y + y, tw, th)
            found.append(Match(template.name, min(score, 1.0), scaler.rect_to_base(dev), rel, diff_at(x, y)))

    if len(template.meta.scales) > 1 or max_count > 1:
        found = nms(found, nms_iou)
    else:
        found.sort(key=lambda m: m.score, reverse=True)
    return found[:max_count]


def find(frame: np.ndarray, template: Template, region: Rect | None = None, threshold: float | None = None) -> Match | None:
    hits = match_template(frame, template, region, threshold, max_count=1)
    return hits[0] if hits else None


def best_match(frame: np.ndarray, template: Template, region: Rect | None = None) -> Match | None:
    """不设阈值的最佳匹配；模板比检索区域还大时返回 None。"""
    return find(frame, template, region, threshold=-1.0)


def find_all(
    frame: np.ndarray,
    template: Template,
    region: Rect | None = None,
    threshold: float | None = None,
    max_count: int = 50,
    nms_iou: float = DEFAULT_NMS_IOU,
) -> list[Match]:
    return match_template(frame, template, region, threshold, max_count=max_count, nms_iou=nms_iou)


__all__ = ["Match", "best_match", "find", "find_all", "match_template", "nms"]
