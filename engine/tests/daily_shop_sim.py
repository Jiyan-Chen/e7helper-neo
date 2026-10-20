"""日常收取 · 商店模拟器（B12b）：大厅 → 商店（更新精选）→ 交易所 › 竞技场 / 商店 › 一般 / 传承石。

画面用真实 fixtures（场景、页签选中、购买框按钮、获得奖励框都按模板认）；卡片内容、顶栏读数、购买框里的
文字由模型决定，测试把 `shop_page.scan_cards` / `read_top` / `read_dialog` 换成本模拟器的 `fake_*`
（截图上的文字是固定的，买完不会变）。

- 列表：每页的卡片按两行、列优先排列；一屏完整显示 4 列（第 5 列被截掉，不算）。往左滑一次挪 2 列。
  买完（剩余 0）的卡片移到最后（实测）。
- 点卡片中间 → 购买框：剩余 > 1 是有数量条的框（默认选 1，「最多」= 剩余和买得起的较小值），
  越买越贵的商品是带「价格信息」的框，其他是只能买 1 个的框。「取消」/ 返回键关掉。
- 点「购买」：扣货币、剩余减少 → 免费商品弹获得奖励框（先 1 帧光效）→「点击关闭」回到列表；其他商品直接回到列表
  （实测行动力这类只在顶部飘一条提示）。reward="all" 时都弹框。
  buy="eat" 时点购买没反应；skystone_leak=True 时买东西还扣 1 天空石；overcharge=N 时多扣 N。
- 危险（DANGER）：买不在白名单里的卡片（用生命之叶 / 天空石买的、没圈的商品），买的数量超过剩余。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from daily_sim import DailySim
from game_sim import DANGER

from e7helper.core.geometry import Rect, Scaler
from e7helper.modules.daily import shop_page
from e7helper.modules.daily.shop_page import Card, Currency, Dialog, Layout, Top

LOBBY_SHOP = Rect(1480, 629, 70, 41)
FEATURED = "daily_shop_featured"
PAGE_SCREENS = {"general": "daily_shop_general", "legacy": "daily_shop_legacy", "arena": "daily_shop_exchange"}
REWARD, REWARD_FX = "daily_shop_reward", "daily_shop_reward_fx"
DLG = {"qty": "daily_shop_dlg_core", "single": "daily_shop_dlg_energy", "free": "daily_shop_dlg_free",
       "rising": "daily_shop_dlg_box"}
SIDE_STORE, SIDE_EXCHANGE = Rect(0, 625, 300, 75), Rect(0, 725, 300, 75)
TAB_FIRST, TAB_LEGACY = Rect(390, 100, 220, 70), Rect(830, 100, 220, 70)
BACK_BTN = Rect(28, 18, 38, 44)
# 购买框按钮（和各 fixture 里模板的位置一致，留点余量）
DLG_BUTTONS = {
    "qty": {"cancel": Rect(462, 700, 248, 74), "buy": Rect(960, 700, 178, 74), "max": Rect(1088, 562, 94, 58)},
    "single": {"cancel": Rect(478, 600, 246, 74), "buy": Rect(940, 600, 184, 74)},
    "free": {"cancel": Rect(478, 600, 246, 74), "buy": Rect(940, 600, 184, 74)},
    "rising": {"cancel": Rect(366, 600, 246, 74), "buy": Rect(830, 600, 180, 74)},
}
REWARD_CLOSE = Rect(740, 636, 122, 48)
COLS_VISIBLE = 4
SWIPE_COLS = 2

# 允许买的：(页, 名字, 货币)
ALLOWED = {
    ("arena", "40点行动力", Currency.ARENA),
    ("general", "普琳每日免费商品", Currency.FREE), ("general", "40点行动力", Currency.FRIENDSHIP),
    ("general", "光谱核心", Currency.ENERGY), ("general", "亲密度献礼选择箱", Currency.FRIENDSHIP),
    ("general", "下级神器强化石", Currency.FRIENDSHIP),
    *(("legacy", n, Currency.CRYSTAL) for n in (
        "魔罗戈拉", "上级精灵之花", "潜能开发碎片", "装备炼制石选择箱", "上级神器强化石", "2个上级饰品强化石",
        "下级神器强化石", "2个下级饰品强化石")),
}


@dataclass
class SimCard:
    name: str
    currency: Currency | None  # None：用生命之叶 / 天空石等买（不能买）
    price: int
    left: int | None  # 剩余次数；None = 不限购
    limit: int | None = None
    label: str = "每日购买"
    rising: int = 0  # 越买越贵：每买一次涨这么多
    sold: bool = False

    def __post_init__(self):
        if self.limit is None:
            self.limit = self.left


def default_pages() -> dict[str, list[SimCard]]:
    """2026-10-20 实测的三页（顺序同游戏：列优先，上行先）。"""
    F, E, C, A = Currency.FRIENDSHIP, Currency.ENERGY, Currency.CRYSTAL, Currency.ARENA
    W = "每周购买"
    return {
        "arena": [
            SimCard("40点行动力", A, 30, 3), SimCard("下级装备强化石", A, 30, None, label=""),
            SimCard("上级装备强化石", A, 90, None, label=""), SimCard("下级饰品强化石", A, 40, None, label=""),
            SimCard("上级饰品强化石", A, 120, None, label=""), SimCard("2025-4赛季装备", None, 0, None, label=""),
        ],
        "general": [
            SimCard("普琳每日免费商品", Currency.FREE, 0, 1), SimCard("40点行动力", F, 100, 1),
            SimCard("光谱核心", E, 160, 3), SimCard("光谱核心", None, 2, None, label=""),
            SimCard("80点行动力", None, 1, None, label=""), SimCard("5面旗帜", F, 100, 1),
            SimCard("老练企鹅", F, 1000, 5, label=W), SimCard("亲密度献礼选择箱", F, 1000, 10, label=W, rising=900),
            SimCard("混沌票券", None, 3, None, label=""), SimCard("下级神器强化石", F, 500, 3, label=W),
        ],
        "legacy": [
            SimCard("5张银河书签", None, 6, None, label=""), SimCard("4-5★英雄召唤券", None, 6, None, label=""),
            SimCard("魔罗戈拉", C, 15, 2, label=W), SimCard("漆黑之匣", None, 10, 1, 5, label="账号限定"),
            SimCard("残梦碎片", None, 10, 1, 5, label="账号限定"), SimCard("纯白圣痕", None, 10, 1, 5, label="账号限定"),
            SimCard("盛放的黑玫瑰", None, 10, 1, 5, label="账号限定"),
            SimCard("曾为一体的瞬间之痕迹", None, 10, 1, 5, label="账号限定"),
            SimCard("上级精灵之花", C, 3, 1, label=W), SimCard("潜能开发碎片", C, 12, 2, label=W),
            SimCard("装备炼制石选择箱", C, 15, 1, label=W), SimCard("下级神器强化石", C, 3, 3, label=W),
            SimCard("上级神器强化石", C, 9, 1, label=W), SimCard("2个下级饰品强化石", C, 5, 3, label=W),
            SimCard("2个上级饰品强化石", C, 15, 1, label=W), SimCard("老练企鹅", C, 3, None, label=""),
        ],
    }


def _hit(r: Rect, x: int, y: int) -> bool:
    return r.x <= x < r.right and r.y <= y < r.bottom


@dataclass
class Purchase:
    page: str
    name: str
    count: int
    currency: Currency
    price: int


class ShopSim(DailySim):
    def __init__(self, screen: str = "daily_lobby_ready", *, pages: dict[str, list[SimCard]] | None = None,
                 money: dict[Currency, int] | None = None, skystone: int = 15871, buy: str = "ok",
                 skystone_leak: bool = False, overcharge: int = 0, reward: str = "free", **kw):
        super().__init__(screen, **kw)
        self.pages = pages or default_pages()
        self.money = {Currency.FRIENDSHIP: 185_729, Currency.ENERGY: 209, Currency.CRYSTAL: 5727,
                      Currency.ARENA: 998, **(money or {})}
        self.skystone = skystone
        self.buy_mode = buy
        self.skystone_leak = skystone_leak
        self.overcharge = overcharge
        self.reward = reward  # 哪些商品买完弹「获得奖励」："free"（只有免费商品，实测）/ "all" / "none"
        self.page = "general"
        self.offset: dict[str, int] = {k: 0 for k in self.pages}
        self.dialog: tuple[str, SimCard, int] | None = None  # (布局, 卡片, 选中数量)
        self.purchases: list[Purchase] = []
        self.dialogs_opened = 0
        self.cancels = 0
        self.max_taps = 0

    # ------------------------------------------------------------ 模型

    def cards_of(self, p: str) -> list[SimCard]:
        cards = self.pages[p]
        return [c for c in cards if not c.sold] + [c for c in cards if c.sold]  # 买完的移到最后

    def _ncols(self, p: str) -> int:
        return (len(self.pages[p]) + 1) // 2

    def visible(self) -> list[tuple[SimCard, int, int]]:
        """当前屏完整显示的卡片：(卡片, 中心 x, 名字 y)。"""
        out = []
        off = self.offset[self.page]
        for i, c in enumerate(self.cards_of(self.page)):
            col, row = divmod(i, 2)
            if off <= col < off + COLS_VISIBLE:
                out.append((c, 502 + (col - off) * 252, 203 if row == 0 else 508))
        out.sort(key=lambda t: (t[2], t[1]))
        return out

    # ------------------------------------------------------------ 换掉的识别函数

    def fake_scan(self, vision, frame) -> list[Card]:
        if self.screen not in PAGE_SCREENS.values():
            return []
        out = []
        for c, cx, ty in self.visible():
            buyable = not c.sold and (c.left is None or c.left > 0)
            counter = (c.left, c.limit) if c.left is not None else None
            out.append(Card(c.name, cx, ty, counter, c.label, buyable, c.currency if buyable else None,
                            c.price if buyable else None))
        return out

    def fake_top(self, vision, frame) -> Top:
        shown = {"general": (Currency.FRIENDSHIP, Currency.ENERGY), "legacy": (Currency.CRYSTAL,),
                 "arena": (Currency.ARENA,)}.get(self.page, ())
        return Top(self.skystone, {c: self.money[c] for c in shown})

    def fake_dialog(self, vision, frame) -> Dialog | None:
        d = _real_read_dialog(vision, frame)
        if d is None or self.dialog is None:
            return d
        layout, c, sel = self.dialog
        cur = c.currency
        unit = c.price
        if layout == "qty":
            return dataclasses.replace(d, layout=Layout.QTY, name=c.name, remaining=c.left, qty=(sel, self._qty_max()),
                                       currency=cur, price=unit * sel)
        lay = Layout.RISING if layout == "rising" else Layout.SINGLE
        return dataclasses.replace(d, layout=lay, name=c.name, remaining=c.left, qty=None, currency=cur,
                                   price=0 if cur is Currency.FREE else unit)

    def _qty_max(self) -> int:
        _, c, _ = self.dialog
        if c.currency in (None, Currency.FREE) or c.price == 0:
            return c.left or 1
        return max(1, min(c.left or 1, self.money.get(c.currency, 0) // c.price))

    # ------------------------------------------------------------ 输入

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        s = self.screen
        if s not in (FEATURED, REWARD, REWARD_FX) and s not in PAGE_SCREENS.values() and s not in DLG.values() \
                and not (s == "daily_lobby_ready"):
            return super().tap(x, y, duration)
        self.taps.append((x, y, duration))
        if self.drop_taps > 0:
            self.drop_taps -= 1
            return
        bx, by = Scaler(*self.size).to_base(x, y)
        if s == "daily_lobby_ready":
            if _hit(LOBBY_SHOP, bx, by):
                self._go(FEATURED)
                return
            return super().tap(x, y, duration)
        if s in DLG.values():
            self._tap_dialog(bx, by)
        elif s == REWARD:
            if _hit(REWARD_CLOSE, bx, by):
                self._go(PAGE_SCREENS[self.page])
        elif s == FEATURED or s in PAGE_SCREENS.values():
            self._tap_page(bx, by)

    def _tap_page(self, bx: int, by: int) -> None:
        s = self.screen
        if _hit(BACK_BTN, bx, by):
            self._go("daily_lobby_ready")
            return
        if _hit(SIDE_EXCHANGE, bx, by):
            self.page = "arena"
            self.offset["arena"] = 0
            self._go(PAGE_SCREENS["arena"])
            return
        if _hit(SIDE_STORE, bx, by) and s != PAGE_SCREENS["general"] and s != PAGE_SCREENS["legacy"]:
            self.page = "general"
            self.offset["general"] = 0
            self._go(PAGE_SCREENS["general"])
            return
        if s in (PAGE_SCREENS["general"], PAGE_SCREENS["legacy"]):
            if _hit(TAB_FIRST, bx, by):
                self.page, self.offset["general"] = "general", 0
                self._go(PAGE_SCREENS["general"])
                return
            if _hit(TAB_LEGACY, bx, by):
                self.page, self.offset["legacy"] = "legacy", 0
                self._go(PAGE_SCREENS["legacy"])
                return
        if s == FEATURED:
            return
        for c, cx, ty in self.visible():
            if _hit(Rect(cx - 60, ty + 60, 120, 120), bx, by):
                self._open(c)
                return

    def _open(self, c: SimCard) -> None:
        if c.sold or (c.left is not None and c.left <= 0):
            return  # 买完的卡片点了没反应
        self.dialogs_opened += 1
        if c.rising:
            layout = "rising"
        elif c.left is not None and c.left > 1:
            layout = "qty"
        else:
            layout = "free" if c.currency is Currency.FREE else "single"
        self.dialog = (layout, c, 1)
        self._go(DLG[layout])

    def _tap_dialog(self, bx: int, by: int) -> None:
        layout, c, sel = self.dialog
        btn = DLG_BUTTONS[layout]
        if _hit(btn["cancel"], bx, by):
            self._close_dialog()
        elif "max" in btn and _hit(btn["max"], bx, by):
            self.max_taps += 1
            self.dialog = (layout, c, self._qty_max())
        elif _hit(btn["buy"], bx, by):
            if self.buy_mode == "eat":
                return
            self._purchase(c, sel)

    def _close_dialog(self) -> None:
        self.cancels += 1
        self.dialog = None
        self._go(PAGE_SCREENS[self.page])

    def _purchase(self, c: SimCard, sel: int) -> None:
        if (self.page, c.name, c.currency) not in ALLOWED or (c.left is not None and sel > c.left):
            self._go(DANGER)
            return
        price = 0 if c.currency is Currency.FREE else c.price * sel
        if c.currency is not Currency.FREE:
            if self.money[c.currency] < price:
                self._go(DANGER)
                return
            self.money[c.currency] -= price + self.overcharge
        if self.skystone_leak:
            self.skystone -= 1
        self.purchases.append(Purchase(self.page, c.name, sel, c.currency, price))
        if c.left is not None:
            c.left -= sel
            c.sold = c.left <= 0
        c.price += c.rising
        if c.name in ("40点行动力", "普琳每日免费商品"):
            self.money[Currency.ENERGY] += 40 * sel
        self.dialog = None
        if self.reward == "all" or (self.reward == "free" and c.currency is Currency.FREE):
            self._go(REWARD_FX)
            self.then = (1, REWARD)
        else:
            self._go(PAGE_SCREENS[self.page])  # 只在顶部飘一条提示（模拟器里不画）

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        self.swipes.append((x1, y1, x2, y2, duration))
        if self.screen not in PAGE_SCREENS.values():
            return
        p = self.page
        top = max(0, self._ncols(p) - COLS_VISIBLE)
        step = SWIPE_COLS if x2 < x1 else -SWIPE_COLS
        self.offset[p] = min(top, max(0, self.offset[p] + step))

    def back(self) -> None:
        if self.screen in DLG.values():
            self.backs += 1
            self._close_dialog()
            return
        if self.screen == REWARD:
            self.backs += 1
            self._go(PAGE_SCREENS[self.page])
            return
        if self.screen == FEATURED or self.screen in PAGE_SCREENS.values():
            self.backs += 1
            self._go("daily_lobby_ready")
            return
        super().back()


_real_read_dialog = shop_page.read_dialog

__all__ = ["DANGER", "Purchase", "ShopSim", "SimCard", "default_pages"]
