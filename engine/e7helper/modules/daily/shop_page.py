"""日常收取 · 商店日常购买的界面识别：商品卡片、购买商品框、获得奖励框、顶栏货币读数、页签。

全部是纯函数（输入 Vision + 帧），不点击，方便用 fixtures 离线测试。坐标一律是 1600x900 基准（实测 B12b）。

商店的商品列表是两行卡片，横向滑动；卡片间距 252，宽约 233。商品名在卡片顶部居中，所以名字的 OCR 框中心
就是卡片的中心。买过之后列表会重新排序（买完的移到最后），所以每次都按名字重新找卡片，不记位置。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from e7helper.core.geometry import Rect, Scaler
from e7helper.core.vision import Match, Vision
from e7helper.core.vision.ocr import normalize_text, parse_fraction, parse_number


# 用注释不用 docstring：pydantic 会把枚举的 docstring 当成字段说明。
class Currency(StrEnum):
    FREE = "free"  # 免费
    FRIENDSHIP = "friendship"  # 友情点数
    ENERGY = "energy"  # 行动力
    CRYSTAL = "crystal"  # 银光传承石（传承石页签里的绿色图标；橙色的是传承石）
    ARENA = "arena"  # 竞技场点数（交易所 › 竞技场）


CURRENCY_LABELS = {
    Currency.FREE: "免费", Currency.FRIENDSHIP: "友情点数", Currency.ENERGY: "行动力",
    Currency.CRYSTAL: "银光传承石", Currency.ARENA: "竞技场点数",
}

# 卡片按钮 / 购买框里的价格图标（免费是文字「免费」）
_CARD_PRICE = {c: f"shop/price/{c.value}" for c in Currency}
_DLG_PRICE = {c: f"shop/dlg/{c.value}" for c in Currency}
# 顶栏图标（行动力、天空石、金币用 common 的）
TOP_ICONS = {
    Currency.FRIENDSHIP: "shop/top/friendship",
    Currency.ENERGY: "top/energy",
    Currency.CRYSTAL: "shop/top/crystal",
    Currency.ARENA: "shop/top/arena",
}
_TOP_OTHERS = ("top/skystone", "top/gold")

LIST = Rect(380, 190, 1220, 600)  # 商品列表区域（两行卡片）
_NAME_STRIPS = (Rect(380, 200, 1220, 34), Rect(380, 506, 1220, 34))  # 两行商品名
CARD_HALF_W = 117
LIST_LEFT, LIST_RIGHT = 380, 1600  # 卡片完整显示在这个范围里才处理（两边被截掉的卡片滑过来再说）
BUYABLE_GREEN = 15.0  # 按钮绿色（可以买）：G 通道比 B 通道平均高这么多。买完 / 倒计时的按钮是蓝灰色（B 比 G 高 30+）

# 页签：选中的页签下面有一条亮蓝色光带（实测选中约 135，没选中约 22）
TAB_SELECTED_BRIGHT = 80
_TAB_GLOW_DY, _TAB_GLOW_H, _TAB_GLOW_HALF_W = 36, 14, 90  # 相对页签文字模板命中框的上边

_TOP_GAP, _TOP_H, _TOP_W = 6, 40, 160
_ENERGY_GAP = 8  # common/top/energy 的命中框在图标内部，数字在它右边约 17 像素处


@dataclass(frozen=True)
class Card:
    name: str
    center_x: int
    name_y: int  # 商品名 OCR 框的上边
    counter: tuple[int, int] | None  # 右上角「剩余/上限」，没有（不限购）或读不出为 None
    label: str  # 按钮上方的「每日购买 / 每周购买 / 账号限定 / 可购买5个」
    buyable: bool  # 按钮是绿色（不是「完成购买」「N天后可购买」）
    currency: Currency | None  # 价格图标；认不出（生命之叶、天空石、传承石等）为 None
    price: int | None  # 免费为 0

    @property
    def rect(self) -> Rect:
        return Rect(self.center_x - CARD_HALF_W, self.name_y - 13, CARD_HALF_W * 2, 288)

    @property
    def tap_rect(self) -> Rect:
        """点卡片中间的商品图标打开购买框。"""
        return Rect(self.center_x - 50, self.name_y + 75, 100, 90)

    @property
    def remaining(self) -> int | None:
        return self.counter[0] if self.counter else None

    def __str__(self) -> str:
        cnt = f"{self.counter[0]}/{self.counter[1]}" if self.counter else "-"
        price = "?" if self.currency is None else (
            "免费" if self.currency is Currency.FREE else f"{self.price} {CURRENCY_LABELS[self.currency]}")
        return f"{self.name}（{cnt}，{self.label or '?'}，{price}{'' if self.buyable else '，不能买'}）"


class Layout(StrEnum):
    QTY = "qty"  # 有数量条（最少 / -1 / +1 / 最多），剩余次数 > 1 时
    SINGLE = "single"  # 只能买 1 个
    RISING = "rising"  # 越买越贵（右边有「价格信息」）


@dataclass(frozen=True)
class Dialog:
    layout: Layout
    name: str
    remaining: int | None  # 「剩余可购买次数：N次」
    qty: tuple[int, int] | None  # 数量条上的「选中/最多」；没有数量条为 None
    currency: Currency | None
    price: int | None  # 按钮上的总价（免费为 0）
    buy: Match
    cancel: Match
    max_btn: Match | None
    min_btn: Match | None
    plus_btn: Match | None

    @property
    def count(self) -> int:
        """这次会买几个。"""
        return self.qty[0] if self.qty else 1

    def __str__(self) -> str:
        qty = f"{self.qty[0]}/{self.qty[1]}" if self.qty else "1"
        price = "?" if self.currency is None else (
            "免费" if self.currency is Currency.FREE else f"{self.price} {CURRENCY_LABELS[self.currency]}")
        return f"{self.name} × {qty}（剩余 {self.remaining}，{price}，{self.layout.value}）"


# 购买框各布局的文字位置（标题模板命中后才读）
_DLG_TEXT = {
    Layout.QTY: (Rect(800, 370, 360, 40), Rect(800, 418, 320, 34)),
    Layout.SINGLE: (Rect(795, 415, 360, 40), Rect(795, 471, 320, 34)),
    Layout.RISING: (Rect(795, 415, 360, 40), Rect(795, 471, 320, 34)),
}
_DLG_QTY = Rect(715, 512, 170, 60)
_DLG_PRICE_W = 160


def _bgr_mean(frame: np.ndarray, rect: Rect) -> np.ndarray:
    r = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(rect)
    patch = r.crop(frame)
    return patch.reshape(-1, 3).mean(axis=0) if patch.size else np.zeros(3)


def _gray_mean(frame: np.ndarray, rect: Rect) -> float:
    r = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(rect)
    patch = r.crop(frame)
    return float(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).mean()) if patch.size else 0.0


def _first_match(vision: Vision, frame: np.ndarray, refs: dict, region: Rect):
    """在 region 里依次找 refs 的模板，返回 (key, match)；都没找到返回 (None, None)。"""
    best = (None, None)
    for key, ref in refs.items():
        m = vision.find(frame, ref, region)
        if m is not None and (best[1] is None or m.score > best[1].score):
            best = (key, m)
    return best


# ---------------------------------------------------------------- 商品卡片

def scan_cards(vision: Vision, frame: np.ndarray) -> list[Card]:
    """当前屏完整显示的商品卡片（按名字认），从左到右、先上行后下行。"""
    ocr = vision.ocr
    cards: list[Card] = []
    for strip in _NAME_STRIPS:
        for r in ocr.read(frame, strip):
            cx = r.rect.x + r.rect.w // 2
            if cx - CARD_HALF_W < LIST_LEFT or cx + CARD_HALF_W > LIST_RIGHT:
                continue
            ty = r.rect.y
            button = Rect(cx - 100, ty + 223, 200, 44)
            b, g, _ = _bgr_mean(frame, Rect(cx - 90, ty + 228, 180, 34))
            buyable = g - b > BUYABLE_GREEN
            currency, price = None, None
            if buyable:
                currency, m = _first_match(vision, frame, _CARD_PRICE, button)
                if currency is Currency.FREE:
                    price = 0
                elif m is not None:
                    x = m.rect.right + 4
                    price = ocr.read_number(frame, Rect(x, ty + 229, button.right - x, 32))
            counter = parse_counter(ocr.read_line(frame, Rect(cx + 28, ty + 33, 86, 36)).text)
            label = normalize_text(ocr.read_line(frame, Rect(cx - 75, ty + 192, 150, 28)).text)
            cards.append(Card(normalize_text(r.text), cx, ty, counter, label, buyable, currency, price))
    return cards


def parse_counter(text: str) -> tuple[int, int] | None:
    """卡片右上角的「剩余/上限」。OCR 常把「1/1」的斜杠丢掉读成「11」：商店的限购上限只有个位数和 10，
    所以没有斜杠时两位数按 a/b、以 10 结尾的三位数按 a/10 解释；剩余比上限大的不要。"""
    text = normalize_text(text)
    frac = parse_fraction(text)
    if frac is None:
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) == 2:
            frac = int(digits[0]), int(digits[1])
        elif len(digits) == 3 and digits.endswith("10"):
            frac = int(digits[0]), 10
    if frac is None or frac[1] == 0 or frac[0] > frac[1]:
        return None
    return frac


def list_signature(cards: list[Card]) -> tuple[tuple[str, int], ...]:
    """用来判断滑动有没有动：卡片名 + 大致位置。"""
    return tuple((c.name, c.center_x // 20) for c in cards)


def tab_selected(vision: Vision, frame: np.ndarray, tab_ref: str) -> bool | None:
    """页签有没有选中；页签文字都没认出返回 None。"""
    m = vision.find(frame, tab_ref)
    if m is None:
        return None
    cx = m.rect.x + m.rect.w // 2
    glow = Rect(cx - _TAB_GLOW_HALF_W, m.rect.y + _TAB_GLOW_DY, _TAB_GLOW_HALF_W * 2, _TAB_GLOW_H)
    return _gray_mean(frame, glow) >= TAB_SELECTED_BRIGHT


# ---------------------------------------------------------------- 购买商品框

def read_dialog(vision: Vision, frame: np.ndarray) -> Dialog | None:
    """购买商品框完全显示时（取消 / 购买按钮的 max_diff 都通过）返回其内容。"""
    if vision.find(frame, "shop/dlg/title") is not None:
        layout = Layout.QTY
    elif vision.find(frame, "shop/dlg/title2") is not None:
        layout = Layout.RISING if vision.find(frame, "shop/dlg/price_info") is not None else Layout.SINGLE
    else:
        return None
    buy, cancel = vision.find(frame, "shop/dlg/buy"), vision.find(frame, "shop/dlg/cancel")
    if buy is None or cancel is None:
        return None
    ocr = vision.ocr
    name_r, remain_r = _DLG_TEXT[layout]
    name = normalize_text(ocr.read_line(frame, name_r).text)
    remain_text = normalize_text(ocr.read_line(frame, remain_r).text)
    remaining = parse_number(remain_text.split(":")[-1]) if "剩余" in remain_text else None
    qty = max_btn = min_btn = plus_btn = None
    if layout is Layout.QTY:
        qty = ocr.read_fraction(frame, _DLG_QTY)
        max_btn = vision.find(frame, "shop/dlg/max")
        min_btn = vision.find(frame, "shop/dlg/min")
        plus_btn = vision.find(frame, "shop/dlg/plus")
    pill = Rect(cancel.rect.right + 40, buy.rect.y - 30, buy.rect.x - cancel.rect.right - 50, buy.rect.h + 60)
    currency, m = _first_match(vision, frame, _DLG_PRICE, pill)
    price = None
    if currency is Currency.FREE:
        price = 0
    elif m is not None:
        x = m.rect.right + 6
        w = min(_DLG_PRICE_W, buy.rect.x - 20 - x)
        price = ocr.read_number(frame, Rect(x, m.rect.y + m.rect.h // 2 - 18, w, 36))
    return Dialog(layout, name, remaining, qty, currency, price, buy, cancel, max_btn, min_btn, plus_btn)


def is_reward(vision: Vision, frame: np.ndarray) -> bool:
    """购买成功后的「获得奖励」框（「成功购买商品，已获得以下道具。」+「点击关闭」）。"""
    return vision.find(frame, "shop/reward/text") is not None and vision.find(frame, "shop/reward/close") is not None


# ---------------------------------------------------------------- 顶栏

@dataclass(frozen=True)
class Top:
    skystone: int | None
    values: dict[Currency, int]  # 这一页顶栏上显示的货币（不在顶栏上的没有键）

    def get(self, c: Currency) -> int | None:
        return self.values.get(c)

    def __str__(self) -> str:
        parts = [f"{CURRENCY_LABELS[c]} {v:,}" for c, v in self.values.items()]
        return "，".join(parts + [f"天空石 {self.skystone if self.skystone is not None else '?'}"])


def read_top(vision: Vision, frame: np.ndarray) -> Top:
    """顶栏的货币读数。顶栏布局随页签变化，先定位图标，再读图标右边、到下一个图标为止的数字。"""
    icons: list[tuple[str | Currency, Match]] = []
    for key, ref in [*TOP_ICONS.items(), *((r, r) for r in _TOP_OTHERS)]:
        m = vision.find(frame, ref)
        if m is not None:
            icons.append((key, m))
    icons.sort(key=lambda km: km[1].rect.x)
    ocr = vision.ocr
    values: dict[Currency, int] = {}
    skystone = None
    for i, (key, m) in enumerate(icons):
        r = m.rect
        x = r.right + (_ENERGY_GAP if key is Currency.ENERGY else _TOP_GAP)
        w = _TOP_W
        if i + 1 < len(icons):
            nxt = icons[i + 1][1].rect.x - (14 if icons[i + 1][0] is Currency.ENERGY else 4)
            w = min(w, nxt - x)
        if w < 20:
            continue
        region = Rect(x, r.y + r.h // 2 - _TOP_H // 2, w, _TOP_H)
        if key is Currency.ENERGY:
            frac = ocr.read_fraction(frame, region)
            value = frac[0] if frac else None
        else:
            value = ocr.read_number(frame, region)
        if value is None:
            continue
        if key == "top/skystone":
            skystone = value
        elif isinstance(key, Currency):
            values[key] = value
    return Top(skystone, values)


__all__ = [
    "CURRENCY_LABELS", "Card", "Currency", "Dialog", "Layout", "Top", "is_reward", "list_signature", "read_dialog",
    "parse_counter", "read_top", "scan_cards", "tab_selected",
]
