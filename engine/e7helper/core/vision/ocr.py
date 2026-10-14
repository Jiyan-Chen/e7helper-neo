"""OCR：RapidOCR（onnxruntime，PP-OCR 简中模型，随 wheel 附带，无需联网）。

两种用法：
- `read()`：检测 + 识别，适合不确定文字位置的区域，约数百毫秒。
- `read_line()` / `read_number()`：已知单行文字的区域，跳过检测只做识别，约 10ms。

区域都用 1600x900 基准坐标；识别结果的位置也换算回基准坐标。
rapidocr 导入要好几秒，所以推迟到第一次使用时才加载。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from e7helper.core.geometry import FULL_SCREEN, Rect, Scaler

if TYPE_CHECKING:
    from rapidocr import RapidOCR

log = logging.getLogger(__name__)

# 识别模型输入高度为 48，文字太矮时先放大
_MIN_LINE_HEIGHT = 32
_PAD = 6


@dataclass(frozen=True)
class OcrResult:
    text: str
    score: float
    rect: Rect  # 基准坐标

    def __str__(self) -> str:
        return f"{self.text!r}({self.score:.2f})@{tuple(self.rect)}"


# ---------------------------------------------------------------- 文本解析

_FULLWIDTH = str.maketrans("０１２３４５６７８９，．／：", "0123456789,./:")
# 只纠正数字场景下最常见、不会有歧义的误识别
_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1"})
_UNITS = {"万": 10_000, "亿": 100_000_000}
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


# 全角 ASCII（U+FF01–FF5E）→ 半角；全角空格去掉
_HALFWIDTH = {cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)}


def normalize_text(text: str) -> str:
    """文字比对前的归一化：全角标点/字母/数字转半角，去掉所有空白。

    OCR 对同一个标点有时给全角有时给半角（如「？」与「?」），比对弹窗文字时先归一化。
    """
    return "".join(text.translate(_HALFWIDTH).split())


def parse_number(text: str) -> int | None:
    """从 OCR 文本解析整数。支持千分位（1,234,567）、单位（12.5万 / 3亿）、全角数字。

    文本里有多个数字时取第一个；没有数字返回 None。
    """
    s = text.translate(_FULLWIDTH).replace(" ", "")
    unit = 1
    for ch, mul in _UNITS.items():
        if ch in s:
            unit = mul
            s = s.split(ch, 1)[0]
            break
    s = s.translate(_DIGIT_FIX)
    if unit == 1:
        # 没有单位时 , 和 . 都按千分位处理（游戏里的资源数都是整数）
        s = re.sub(r"(?<=\d)[,.](?=\d{3})", "", s)
    else:
        s = s.replace(",", "")
    m = _NUMBER_RE.search(s)
    if not m:
        return None
    return int(round(float(m.group()) * unit))


def parse_fraction(text: str) -> tuple[int, int] | None:
    """解析 "35/120" 这类当前值/上限文本。"""
    s = text.translate(_FULLWIDTH)
    if "/" not in s:
        return None
    left, right = s.split("/", 1)
    a, b = parse_number(left), parse_number(right)
    if a is None or b is None:
        return None
    return a, b


# ---------------------------------------------------------------- 引擎


class Ocr:
    """RapidOCR 的薄封装。线程安全（内部加锁串行推理）。"""

    def __init__(self, params: dict[str, Any] | None = None):
        self._params = {"Global.log_level": "warning", **(params or {})}
        self._engine: RapidOCR | None = None
        self._lock = threading.RLock()  # engine 懒加载与推理共用，需可重入

    @property
    def engine(self) -> RapidOCR:
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    from rapidocr import RapidOCR

                    self._engine = RapidOCR(params=self._params)
        return self._engine

    def warmup(self) -> None:
        """预先加载模型并跑一次推理，避免第一次识别时卡顿。"""
        self.read_line(np.zeros((90, 160, 3), np.uint8), Rect(0, 0, 160, 90))

    def _crop(self, frame: np.ndarray, region: Rect | None) -> tuple[np.ndarray, Rect, Scaler]:
        fh, fw = frame.shape[:2]
        scaler = Scaler(fw, fh)
        dev = scaler.rect_to_device((region or FULL_SCREEN).clip()).clip(fw, fh)
        if dev.area == 0:
            raise ValueError(f"OCR 区域在画面外：{region}")
        return dev.crop(frame), dev, scaler

    def read(self, frame: np.ndarray, region: Rect | None = None, min_score: float = 0.5) -> list[OcrResult]:
        """检测 + 识别。结果按行（从上到下）、行内从左到右排序。"""
        img, dev, scaler = self._crop(frame, region)
        with self._lock:
            # RapidOCR 的 __call__ 会把参数写回实例，必须每次显式传全；游戏文字都是横排，不需要方向分类
            out = self.engine(img, use_det=True, use_cls=False, use_rec=True)
        if out.txts is None:
            return []
        results = []
        for box, text, score in zip(out.boxes, out.txts, out.scores, strict=True):
            if score < min_score or not text.strip():
                continue
            xs, ys = box[:, 0], box[:, 1]
            x1, y1 = int(xs.min()) + dev.x, int(ys.min()) + dev.y
            x2, y2 = int(np.ceil(xs.max())) + dev.x, int(np.ceil(ys.max())) + dev.y
            rect = scaler.rect_to_base(Rect(x1, y1, x2 - x1, y2 - y1))
            results.append(OcrResult(text.strip(), float(score), rect))
        return _reading_order(results)

    def read_text(self, frame: np.ndarray, region: Rect | None = None, min_score: float = 0.5, sep: str = "") -> str:
        return sep.join(r.text for r in self.read(frame, region, min_score))

    def read_line(self, frame: np.ndarray, region: Rect) -> OcrResult:
        """只识别不检测：region 应该紧贴一行文字（留几像素边距即可）。"""
        img, dev, scaler = self._crop(frame, region)
        h = img.shape[0]
        if h < _MIN_LINE_HEIGHT:
            f = _MIN_LINE_HEIGHT / h
            img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        img = cv2.copyMakeBorder(img, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_REPLICATE)
        with self._lock:
            out = self.engine(img, use_det=False, use_cls=False, use_rec=True)
        text = (out.txts or ("",))[0].strip()
        score = float((out.scores or (0.0,))[0])
        return OcrResult(text, score, scaler.rect_to_base(dev))

    def read_number(self, frame: np.ndarray, region: Rect, min_score: float = 0.5) -> int | None:
        r = self.read_line(frame, region)
        if r.score < min_score:
            log.debug("数字识别置信度低：%s", r)
            return None
        return parse_number(r.text)

    def read_fraction(self, frame: np.ndarray, region: Rect, min_score: float = 0.5) -> tuple[int, int] | None:
        r = self.read_line(frame, region)
        if r.score < min_score:
            log.debug("分数识别置信度低：%s", r)
            return None
        return parse_fraction(r.text)


def _reading_order(results: list[OcrResult]) -> list[OcrResult]:
    """按行聚类：纵向中心相差不到半个行高视为同一行。"""
    rows: list[list[OcrResult]] = []
    for r in sorted(results, key=lambda r: r.rect.y + r.rect.h / 2):
        cy = r.rect.y + r.rect.h / 2
        if rows:
            last = rows[-1][-1]
            if abs(cy - (last.rect.y + last.rect.h / 2)) < max(r.rect.h, last.rect.h) / 2:
                rows[-1].append(r)
                continue
        rows.append([r])
    return [r for row in rows for r in sorted(row, key=lambda r: r.rect.x)]


_default: Ocr | None = None
_default_lock = threading.Lock()


def default_ocr() -> Ocr:
    """进程内共享的 OCR 实例（模型只加载一次）。"""
    global _default
    with _default_lock:
        if _default is None:
            _default = Ocr()
        return _default
