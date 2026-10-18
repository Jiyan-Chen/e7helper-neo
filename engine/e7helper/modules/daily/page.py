"""日常收取的界面识别（纯函数，坐标一律 1600×900 基准）。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

from e7helper.core.geometry import Rect, Scaler
from e7helper.core.vision import Match, Vision
from e7helper.core.vision.ocr import normalize_text

# ---------------------------------------------------------------- 邮件

MAIL_LIST = Rect(1300, 105, 270, 670)  # 「领取」按钮的检索区域（列表可见部分；露出一半的行不算）
_REMAIN = (396, 14, 175, 52)  # 剩余时间文字相对「领取」模板命中框的偏移 (dx, dy, w, h)
MAIL_COUNT = Rect(1165, 810, 125, 48)  # 底部「超出上限将无法接收新邮件 11/100」的数字部分

_DAYS = re.compile(r"(\d+)天")
_HOURS = re.compile(r"(\d+)小时")
_MINUTES = re.compile(r"(\d+)分")
_SECONDS = re.compile(r"(\d+)秒")


def parse_remaining(text: str) -> float | None:
    """剩余时间文字 → 小时数。「无限制」= inf；认不出返回 None（调用方按不领处理）。

    游戏只显示最大的单位（「剩余6天」），这里按显示的数字算下限：6 天 = 144 小时。
    """
    t = normalize_text(text).replace(" ", "")
    if "无限" in t:
        return math.inf
    total, found = 0.0, False
    for pattern, hours in ((_DAYS, 24.0), (_HOURS, 1.0), (_MINUTES, 1 / 60), (_SECONDS, 1 / 3600)):
        m = pattern.search(t)
        if m:
            total += int(m.group(1)) * hours
            found = True
    return total if found else None


@dataclass
class MailRow:
    claim: Match  # 这一行的「领取」按钮
    text: str  # 剩余时间原文
    hours: float | None  # parse_remaining 的结果

    @property
    def y(self) -> int:
        return self.claim.rect.y


def scan_mail(vision: Vision, frame: np.ndarray) -> list[MailRow]:
    """当前屏能看到的邮件行（自上而下）。只要「领取」按钮完整露出的行。"""
    rows = []
    for m in sorted(vision.find_all(frame, "mail/claim", MAIL_LIST), key=lambda m: m.rect.y):
        dx, dy, w, h = _REMAIN
        region = Rect(m.rect.x - dx, m.rect.y + dy, w, h)
        text = vision.ocr.read_line(frame, region).text
        rows.append(MailRow(m, text, parse_remaining(text)))
    return rows


MAIL_DETAIL_REMAIN = Rect(362, 260, 220, 48)  # 邮件详情框里发件人下面的「剩余6天」


def read_mail_detail_remaining(vision: Vision, frame: np.ndarray) -> str:
    return vision.ocr.read_line(frame, MAIL_DETAIL_REMAIN).text


def read_mail_count(vision: Vision, frame: np.ndarray) -> int | None:
    """邮箱里的邮件数（底部「11/100」的分子）。"""
    frac = vision.ocr.read_fraction(frame, MAIL_COUNT)
    return frac[0] if frac else None


# ---------------------------------------------------------------- 精灵之森

CARD_NAMES = ("企鹅巢穴", "精灵之泉", "魔罗戈拉种植地")
CARDS = (Rect(1145, 258, 415, 110), Rect(1145, 403, 415, 110), Rect(1145, 547, 415, 110))
_CARD_TEXT = Rect(1185, 258, 240, 400)  # 三张卡左边的文字列（名字、倒计时、休息期）
CARE_ROW = Rect(1145, 662, 415, 60)
_CARE_TIMER = Rect(1192, 670, 125, 44)
_CARE_COUNT = Rect(1400, 668, 130, 48)
_TIMER = re.compile(r"(\d+):(\d{2}):(\d{2})")


def parse_timer(text: str) -> int | None:
    """「08:41:54」「149:05:06」→ 秒数。"""
    m = _TIMER.search(normalize_text(text).replace(" ", ""))
    if not m:
        return None
    h, mi, s = map(int, m.groups())
    return h * 3600 + mi * 60 + s


@dataclass
class Card:
    name: str
    rect: Rect
    ready: bool  # 显示「领取奖励」
    seconds: int | None  # 倒计时（ready 时为 None）


@dataclass
class Care:
    done: int
    total: int
    seconds: int | None  # 下次可照料的倒计时；None = 没有倒计时
    button: Match

    @property
    def available(self) -> bool:
        """还有次数、而且没在倒计时。可照料时按钮的样子还没见过（B07 只采到不可照料的状态）。"""
        return self.done < self.total and self.seconds is None


@dataclass
class Forest:
    cards: list[Card] = field(default_factory=list)
    care: Care | None = None

    @property
    def ready(self) -> list[Card]:
        return [c for c in self.cards if c.ready]

    def next_seconds(self) -> int | None:
        """下一次有东西可领 / 可照料还要多久；有可做的返回 0；都认不出返回 None。"""
        if self.ready or (self.care and self.care.available):
            return 0
        times = [c.seconds for c in self.cards if c.seconds is not None]
        if self.care and self.care.done < self.care.total and self.care.seconds is not None:
            times.append(self.care.seconds)
        return min(times) if times else None


def read_forest(vision: Vision, frame: np.ndarray) -> Forest:
    """读三张卡（可领 / 倒计时）和照料按钮。"""
    lines = vision.ocr.read(frame, _CARD_TEXT)
    forest = Forest()
    for name, rect in zip(CARD_NAMES, CARDS, strict=True):
        ready = vision.find(frame, "forest/claim", rect) is not None
        seconds = None
        if not ready:
            for r in lines:
                cy = r.rect.y + r.rect.h / 2
                if rect.y <= cy < rect.bottom and (s := parse_timer(r.text)) is not None:
                    seconds = s
                    break
        forest.cards.append(Card(name, rect, ready, seconds))
    button = vision.find(frame, "forest/care", CARE_ROW)
    if button is not None:
        frac = vision.ocr.read_fraction(frame, _CARE_COUNT)
        if frac is not None:
            forest.care = Care(frac[0], frac[1], parse_timer(vision.ocr.read_line(frame, _CARE_TIMER).text), button)
    return forest


# ---------------------------------------------------------------- 誓约召唤

TOP_CURRENCY = Rect(700, 5, 510, 60)  # 召唤页顶栏的召唤券 / 书签 / 天空石数字
# 「21/21可免费召唤！」气泡：有免费十连时在「召唤10次」上方，只剩单抽时移到「1次召唤」上方（实测 1/21）
_FREE_LEFT = (Rect(1290, 740, 270, 40), Rect(955, 740, 300, 40))
_FRACTION = re.compile(r"(\d+)/(\d+)")
CURRENCY_PIXEL_DIFF = 40  # 顶栏像素差超过这个值算变了
CURRENCY_CHANGED_PIXELS = 60  # 变了的像素超过这么多算读数变了（实测：没变 0，一个数字变了 5000+）
CURRENCY_FRAMES_GAP = 0.6  # 前后各取两帧，间隔这么多秒（排除背景光效，见 changed_pixels_all）


@dataclass
class Covenant:
    free_1: Match | None  # 「1次召唤」按钮上的「免费」
    free_10: Match | None  # 「召唤10次」按钮上的「免费」
    left: tuple[int, int] | None  # 气泡里的剩余免费次数 (剩余, 总数)

    @property
    def free(self) -> Match | None:
        """要点的按钮：优先免费十连。"""
        return self.free_10 or self.free_1


def read_covenant(vision: Vision, frame: np.ndarray) -> Covenant:
    left = None
    for region in _FREE_LEFT:
        text = normalize_text(vision.ocr.read_line(frame, region).text)
        if "免费" in text and (m := _FRACTION.search(text)) is not None:
            left = (int(m.group(1)), int(m.group(2)))
            break
    return Covenant(vision.find(frame, "summon/free_1"), vision.find(frame, "summon/free_10"), left)


def currency_patch(frame: np.ndarray) -> np.ndarray:
    """顶栏货币区域（缩放到基准尺寸），用来核对召唤前后读数没变。"""
    import cv2

    s = Scaler(frame.shape[1], frame.shape[0])
    patch = s.rect_to_device(TOP_CURRENCY).crop(frame)
    r = TOP_CURRENCY
    if patch.shape[:2] != (r.h, r.w):
        patch = cv2.resize(patch, (r.w, r.h), interpolation=cv2.INTER_AREA)
    return patch


def _changed_mask(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > CURRENCY_PIXEL_DIFF


def changed_pixels(a: np.ndarray, b: np.ndarray) -> int:
    return int(_changed_mask(a, b).sum())


def changed_pixels_all(before: list[np.ndarray], after: list[np.ndarray]) -> int:
    """前后各几帧，两两比较都变了的像素才算。

    誓约页的背景立绘有一闪而过的星星光效，会飘进顶栏区域（实测单帧 6–80 个像素），只出现在一帧里；
    数字真的变了时每一对都不一样（5000+ 个像素）。
    """
    mask = None
    for a in before:
        for b in after:
            m = _changed_mask(a, b)
            mask = m if mask is None else mask & m
    return int(mask.sum()) if mask is not None else 0


def read_currency_text(vision: Vision, frame: np.ndarray) -> str:
    """顶栏货币的 OCR 文字（只用于日志）。"""
    return " ".join(r.text for r in vision.ocr.read(frame, TOP_CURRENCY))
