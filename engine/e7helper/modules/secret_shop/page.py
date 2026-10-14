"""秘密商店界面的识别：商品列表、顶栏资源、刷新消耗、购买/刷新确认框。

全部是纯函数（输入 Vision + 帧），不点击，方便用 fixtures 离线测试。
坐标一律是 1600x900 基准，偏移量按「购买」按钮命中框换算（实测 B04）：

    购买按钮 box y=180 → 类别 y≈114、商品名 y≈152–190、价格 y≈116–156、金币图标 y≈116
    行距约 181；列表顶部能完整显示 4 行，滑到底显示第 2–6 行（共 6 行）
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from e7helper.core.geometry import Rect
from e7helper.core.vision import Match, Vision, normalize_text

if TYPE_CHECKING:
    from .config import Target

# 列表可见区域的上沿：再往上是顶栏，滑动后最上面那行的名字会被挡住
LIST_TOP = 85

# 相对「购买」按钮命中框 y 的偏移
_NAME = (850, -34, 420, 50)  # x, dy, w, h
_PRICE = (1395, -64, 150, 40)
_COIN = (1322, -74, 74, 62)  # 金币图标的检索区域（模板 42x42）
_ICON = (680, -75, 145, 140)  # 物品图标框（约 117x117，图标本体约 70px）

# 顶栏：图标右侧的数字
_NUM_GAP = 6
_NUM_H = 40
_SKYSTONE_W = 110
_GOLD_W = 150

# 购买确认框（dialog/buy_title 命中时）
BUY_DIALOG_NAME = Rect(795, 412, 430, 44)
BUY_DIALOG_PRICE = Rect(800, 615, 130, 44)

MIN_NAME_SCORE = 0.6


@dataclass(frozen=True)
class ShopItem:
    name: str  # 归一化后的商品名；读不出时为空串
    price: int | None
    gold: bool  # 价格旁是金币图标
    buy: Match  # 「购买」按钮
    icons: frozenset[str] = frozenset()  # 在物品图标位置命中的图标模板（只查目标设了 icon 的）

    @property
    def y(self) -> int:
        return self.buy.rect.y

    def __str__(self) -> str:
        price = "?" if self.price is None else f"{self.price:,}"
        unit = "金币" if self.gold else "(非金币)"
        icons = f" 图标={','.join(sorted(self.icons))}" if self.icons else ""
        return f"{self.name or '?'} {price}{unit}{icons}@y={self.y}"


@dataclass(frozen=True)
class Resources:
    skystone: int | None
    gold: int | None

    def __str__(self) -> str:
        def fmt(v: int | None) -> str:
            return "?" if v is None else f"{v:,}"

        return f"天空石 {fmt(self.skystone)}，金币 {fmt(self.gold)}"


@dataclass(frozen=True)
class BuyDialog:
    name: str
    price: int | None
    ok: Match  # 「金币价格 + 购买」按钮


def _row_rect(spec: tuple[int, int, int, int], buy_y: int) -> Rect:
    x, dy, w, h = spec
    return Rect(x, buy_y + dy, w, h)


def scan_items(vision: Vision, frame: np.ndarray, icons: Iterable[str] = ()) -> list[ShopItem]:
    """当前画面里可购买的商品（从上到下）。

    以「购买」按钮为锚点（模板设了 max_diff，按钮被压暗或变灰时不命中），所以已售的行不会出现。
    名字被顶栏挡住的半行跳过（另一个滚动位置会完整显示它）。
    icons：要在每行物品图标位置查找的图标模板（例如 item/covenant）。
    """
    icons = tuple(icons)
    items: list[ShopItem] = []
    for b in sorted(vision.find_all(frame, "buy"), key=lambda m: m.rect.y):
        name_rect = _row_rect(_NAME, b.rect.y)
        if name_rect.y < LIST_TOP:
            continue
        r = vision.ocr.read_line(frame, name_rect)
        name = normalize_text(r.text) if r.score >= MIN_NAME_SCORE else ""
        price = vision.ocr.read_number(frame, _row_rect(_PRICE, b.rect.y))
        gold = vision.find(frame, "coin", _row_rect(_COIN, b.rect.y)) is not None
        icon_rect = _row_rect(_ICON, b.rect.y).clip()
        hits = frozenset(ref for ref in icons if vision.find(frame, ref, icon_rect) is not None)
        items.append(ShopItem(name, price, gold, b, hits))
    return items


def read_resources(vision: Vision, frame: np.ndarray) -> Resources:
    """读顶栏的天空石和金币。顶栏布局随界面和红点变化，先定位图标，再读图标右侧的数字。"""
    sky_icon = vision.find(frame, "top/skystone")
    gold_icon = vision.find(frame, "top/gold")
    skystone = gold = None
    if sky_icon is not None:
        r = sky_icon.rect
        skystone = vision.ocr.read_number(frame, Rect(r.right + _NUM_GAP, r.y + r.h // 2 - _NUM_H // 2,
                                                      _SKYSTONE_W, _NUM_H))
    if gold_icon is not None:
        r = gold_icon.rect
        x = r.right + _NUM_GAP
        w = _GOLD_W
        if sky_icon is not None and sky_icon.rect.x > x:
            w = min(w, sky_icon.rect.x - 4 - x)  # 不要读进天空石图标
        gold = vision.ocr.read_number(frame, Rect(x, r.y + r.h // 2 - _NUM_H // 2, w, _NUM_H))
    return Resources(skystone, gold)


def read_refresh_cost(vision: Vision, frame: np.ndarray) -> int | None:
    """「立即更新」按钮左侧的天空石消耗。"""
    m = vision.find(frame, "refresh")
    if m is None:
        return None
    return vision.ocr.read_number(frame, Rect(m.rect.x - 130, m.rect.y + 5, 70, 40))


def read_buy_dialog(vision: Vision, frame: np.ndarray) -> BuyDialog | None:
    """购买确认框完全显示时返回其内容（淡入途中按钮偏暗，buy_ok 的 max_diff 不通过）。"""
    if vision.find(frame, "dialog/buy_title") is None:
        return None
    ok = vision.find(frame, "dialog/buy_ok")
    if ok is None:
        return None
    r = vision.ocr.read_line(frame, BUY_DIALOG_NAME)
    name = normalize_text(r.text) if r.score >= MIN_NAME_SCORE else ""
    return BuyDialog(name, vision.ocr.read_number(frame, BUY_DIALOG_PRICE), ok)


# ---------------------------------------------------------------- 决策


def name_matches(name: str, target: str) -> bool:
    """商品名与目标名一致（归一化后相等，或 OCR 多读了字符时目标名是其子串）。不做模糊匹配，宁可漏买不买错。"""
    n, t = normalize_text(name), normalize_text(target)
    return bool(n) and bool(t) and (n == t or t in n)


def match_target(item: ShopItem | str, targets: list[Target]) -> Target | None:
    """按名字匹配目标；名字没对上时，再看物品图标（目标设了 icon 且该行命中）。"""
    if isinstance(item, str):
        name, icons = item, frozenset()
    else:
        name, icons = item.name, item.icons
    by_name = next((t for t in targets if name_matches(name, t.name)), None)
    if by_name is not None:
        return by_name
    return next((t for t in targets if t.icon and t.icon in icons), None)


def target_icons(targets: list[Target]) -> list[str]:
    return [t.icon for t in targets if t.icon]


def near_miss(name: str, targets: list[Target], ratio: float = 0.6) -> Target | None:
    """和某个目标很像但没匹配上（可能是 OCR 认错了字），只用于提示日志。"""
    if not name or match_target(name, targets):
        return None
    for t in targets:
        if difflib.SequenceMatcher(None, name, normalize_text(t.name)).ratio() >= ratio:
            return t
    return None


@dataclass(frozen=True)
class Decision:
    item: ShopItem
    target: Target | None
    buy: bool
    reason: str

    def __str__(self) -> str:
        return f"{'买' if self.buy else '不买'} {self.item}：{self.reason}"


def decide(item: ShopItem, targets: list[Target], gold: int | None, gold_floor: int) -> Decision:
    """要不要买这件商品。任何一项读数可疑都不买。"""
    t = match_target(item, targets)
    if t is None:
        return Decision(item, None, False, "不是目标")
    if item.price is None:
        return Decision(item, t, False, "价格读不出")
    if not item.gold:
        return Decision(item, t, False, "价格不是金币")
    if t.price is not None and item.price != t.price:
        return Decision(item, t, False, f"价格 {item.price:,} 与预期 {t.price:,} 不符")
    if gold is None:
        return Decision(item, t, False, "金币读数未知")
    if gold - item.price < gold_floor:
        return Decision(item, t, False, f"买完金币 {gold - item.price:,} 会低于下限 {gold_floor:,}")
    return Decision(item, t, True, "目标")
