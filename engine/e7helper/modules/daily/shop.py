"""日常收取 · 商店：买掉商店里每天、每周限购的商品（B12b，用户圈定商品，见 docs/reviews/B12b.md）。

顺序：交易所 › 竞技场 → 商店 › 一般 → 商店 › 传承石。先买两份 40 点行动力和普琳的免费商品（会给行动力），
再用行动力买光谱核心。每一页从左往右扫：按名字找到要买的卡片 → 判断 → 买 → 重新扫（买完的商品会移到列表最后，
其他卡片跟着挪位置）；滑不动了就是到头。

安全规则：
- 只买 CATALOG 里列出的商品，而且价格图标必须是规定的货币（免费 / 友情点数 / 行动力 / 银光传承石 / 竞技场点数），
  天空石、生命之叶、传承石买的一律不碰（同名的「光谱核心」有一张是用生命之叶买的，按价格图标区分）。
- 点「购买」前核对购买框：商品名、价格图标、剩余次数和卡片一致；数量条按「最多」；固定价格的商品总价 = 单价 × 数量；
  顶栏读数够付。任一项不符就点取消，跳过这件商品。
- 买完核对：顶栏天空石不变；付款货币正好减少总价（行动力会自然恢复，允许少减 3 点）；免费的要出现「获得奖励」。
  「获得奖励」框只有部分商品有（行动力这类入场券只在顶部飘一条提示），出现了就点击关闭。
  天空石变了或扣的数不对 → `DailyAnomaly`，整个任务立即停止。
- 亲密度献礼选择箱越买越贵，每周只买 `shop_affinity_weekly`（默认 5）次（按卡片上的「剩余/上限」算买了几次）。
- 购买框、获得奖励框注册成模块弹窗：自动关闭时购买框点取消，获得奖励框点「点击关闭」。
- dry_run 只导航和识别，记下会买什么，不点购买（shop_probe_dialogs 时打开购买框核对后点取消）。
- 账本：买完 / 显示买完的商品记进 ledger（每日的记 done，每周的记 week_done），全记上了的页不进去。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np

from e7helper.core.geometry import Scaler
from e7helper.core.runtime.stuck import thumb_diff, thumbnail
from e7helper.core.scene import Dismiss, Popup, Scene

from . import shop_page as page
from . import stats
from .config import SHOP_ITEM_LABELS, ShopItem
from .errors import DailyAnomaly, ItemFailed, StopItem
from .shop_page import Card, Currency, Dialog, Layout, Top

if TYPE_CHECKING:
    from e7helper.core.scene import SceneDetector

    from . import DailyModule
    from .config import DailyConfig

SHOP = "shop"  # 内置场景：商店（更新精选等其他页）
STORE = "daily_shop_store"  # 商店 › 商店（页签：一般 / 天空石 / 传承石 …）
EXCHANGE = "daily_shop_exchange"  # 商店 › 交易所（页签：竞技场 / 荣耀的轨迹 …）
POPUP_BUY = "daily_shop_buy"  # 购买商品框（有数量条）
POPUP_BUY1 = "daily_shop_buy1"  # 购买商品框（只能买 1 个 / 越买越贵）
POPUP_REWARD = "daily_shop_reward"  # 获得奖励（成功购买商品）
POPUP_NETWORK = "network"
SCENES = (SHOP, STORE, EXCHANGE)  # 可以从这些界面回到大厅

POLL = 0.15
STILL_DIFF = 2.0  # 弹窗完全显示：连续两帧缩略图差小于这个值
TOP_SETTLE = 0.5  # 关掉获得奖励框后顶栏数字有滚动动画，等一会再读
LIST_DIFF = 2.0  # 列表区域缩略图帧差小于这个值算停稳
LIST_STILL = 0.4
POPUP_GRACE = 1.0
DIALOG_WAIT = 5.0  # 点卡片后等购买框
DIALOG_SETTLE = 0.15
REWARD_WAIT = 10.0  # 点购买后最多等这么久回到列表
DIALOG_EATEN = 4.0  # 点了购买这么久购买框还在，认为点击被吞
RESULT_GRACE = 2.0  # 回到列表后再等这么久：「获得奖励」可能稍后弹出；行动力这类商品只在顶部飘一条提示（约 1.5 秒，挡住顶栏数字）
TAB_TRIES = 4
MAX_SCREENS = 10  # 一页最多滑几屏（传承石 19 件商品约 3 屏）
MAX_PASSES = 3  # 买过东西后列表会重排（或有商品一直没看到），从头再扫的次数
MAX_ATTEMPTS = 2  # 同一件商品点了购买没买成这么多次就不再试
ENERGY_REGEN = 3  # 买光谱核心期间行动力自然恢复，扣的数允许比总价少这么多
# 往左拖 400 像素、1 秒：列表约挪 520 像素 ≈ 2 列（一屏完整显示 4 列，留 2 列重叠）。
# 实测拖得快会甩出去很远（0.6 秒拖 740 像素挪了 5 列以上，中间的商品直接跳过）
SWIPE = ((1250, 650), (850, 650))
SWIPE_DURATION = 1.0
SWIPE_BACK_MAX = 6


class Page(StrEnum):
    ARENA = "arena"  # 交易所 › 竞技场
    GENERAL = "general"  # 商店 › 一般
    LEGACY = "legacy"  # 商店 › 传承石


@dataclass(frozen=True)
class PageInfo:
    label: str
    scene: str
    side: str  # 左侧菜单（未选中时的文字模板）
    tab: str  # 页签文字模板


PAGES: dict[Page, PageInfo] = {
    Page.ARENA: PageInfo("交易所 › 竞技场", EXCHANGE, "shop/side_exchange", "shop/tab_arena"),
    Page.GENERAL: PageInfo("商店 › 一般", STORE, "shop/side_shop", "shop/tab_general"),
    Page.LEGACY: PageInfo("商店 › 传承石", STORE, "shop/side_shop", "shop/tab_legacy"),
}


@dataclass(frozen=True)
class Spec:
    item: ShopItem
    name: str  # 游戏里的商品名
    page: Page
    currency: Currency
    unit: int | None  # 单价；None 表示不核对总价（越买越贵 / 没见过价格）
    limit: int  # 每期限购（卡片上「剩余/上限」的上限）
    weekly: bool

    @property
    def key(self) -> str:
        return f"shop:{self.item.value}"

    @property
    def label(self) -> str:
        return SHOP_ITEM_LABELS[self.item]


F, E, C, A, FREE = Currency.FRIENDSHIP, Currency.ENERGY, Currency.CRYSTAL, Currency.ARENA, Currency.FREE
# 价格、限购都是 2026-10-20 实测（「下级神器强化石（一般）」当时已买完，价格没见过，按友情点数算、不核对总价）
CATALOG: dict[ShopItem, Spec] = {s.item: s for s in (
    Spec(ShopItem.ARENA_ENERGY, "40点行动力", Page.ARENA, A, 30, 3, weekly=False),
    Spec(ShopItem.FREE, "普琳每日免费商品", Page.GENERAL, FREE, 0, 1, weekly=False),
    Spec(ShopItem.ENERGY, "40点行动力", Page.GENERAL, F, 100, 1, weekly=False),
    Spec(ShopItem.CORE, "光谱核心", Page.GENERAL, E, 160, 3, weekly=False),
    Spec(ShopItem.AFFINITY_BOX, "亲密度献礼选择箱", Page.GENERAL, F, None, 10, weekly=True),
    Spec(ShopItem.ARTIFACT_LOW_GENERAL, "下级神器强化石", Page.GENERAL, F, None, 3, weekly=True),
    Spec(ShopItem.MOLAGORA, "魔罗戈拉", Page.LEGACY, C, 15, 2, weekly=True),
    Spec(ShopItem.FLOWER, "上级精灵之花", Page.LEGACY, C, 3, 1, weekly=True),
    Spec(ShopItem.POTENTIAL, "潜能开发碎片", Page.LEGACY, C, 12, 2, weekly=True),
    Spec(ShopItem.CATALYST_BOX, "装备炼制石选择箱", Page.LEGACY, C, 15, 1, weekly=True),
    Spec(ShopItem.ARTIFACT_HIGH, "上级神器强化石", Page.LEGACY, C, 9, 1, weekly=True),
    Spec(ShopItem.ACCESSORY_HIGH, "2个上级饰品强化石", Page.LEGACY, C, 15, 1, weekly=True),
    Spec(ShopItem.ARTIFACT_LOW, "下级神器强化石", Page.LEGACY, C, 3, 3, weekly=True),
    Spec(ShopItem.ACCESSORY_LOW, "2个下级饰品强化石", Page.LEGACY, C, 5, 3, weekly=True),
)}
RISING = frozenset({ShopItem.AFFINITY_BOX})  # 越买越贵，一次只买 1 个
# 同一页有同名商品的（一般页还有一张用生命之叶买的光谱核心）：买完的卡片次数读不出时不能认
AMBIGUOUS = frozenset({ShopItem.CORE})


class StopShop(StopItem):
    """商店这一项正常结束。"""


class ShopAnomaly(DailyAnomaly):
    """买完核对不通过（天空石变了、扣的数不对），立即停止整个任务。"""


def register(sc: SceneDetector, q: str) -> None:
    """注册商店的场景和弹窗。q 是模板的模块前缀（"daily:"）。"""
    s = q + "shop/"
    for scene in (
        Scene(STORE, ("title/shop", s + "tab_general"), note="商店 › 商店（一般 / 传承石 …）"),
        Scene(EXCHANGE, ("title/shop", s + "tab_arena"), note="商店 › 交易所（竞技场 …）"),
    ):
        sc.add_scene(scene, replace=True, first=True)
    for popup in (
        Popup(POPUP_BUY, (s + "dlg/title", s + "dlg/cancel"), Dismiss.tap(s + "dlg/cancel"),
              note="商店购买商品框（自动关闭时点取消）"),
        Popup(POPUP_BUY1, (s + "dlg/title2", s + "dlg/cancel"), Dismiss.tap(s + "dlg/cancel"),
              note="商店购买商品框，没有数量条（自动关闭时点取消）"),
        Popup(POPUP_REWARD, (s + "reward/text", s + "reward/close"), Dismiss.tap(s + "reward/close"),
              note="商店获得奖励（点击关闭）"),
    ):
        sc.add_popup(popup, replace=True, first=True)


def wanted(cfg: DailyConfig) -> list[Spec]:
    return [CATALOG[i] for i in ShopItem if i in cfg.shop_items]


class Shop:
    """商店这一项。借用日常收取模块的 ctl / vision / log / 统计 / 账本 / 失败计数。"""

    def __init__(self, m: DailyModule):
        self.m = m
        self.ctl = m.ctl
        self.vision = m.vision
        self.log = m.log
        self.cfg: DailyConfig = m.config
        self.r: stats.RunStats = m.run_stats
        self._attempts: dict[ShopItem, int] = {}
        self._buys = 0

    # ------------------------------------------------------------ 账本

    def _done(self, spec: Spec) -> bool:
        lg = self.m.ledger
        return lg.is_week_done(spec.key) if spec.weekly else lg.is_done(spec.key)

    def _mark(self, spec: Spec, why: str) -> None:
        if self.cfg.dry_run:
            return
        lg = self.m.ledger
        (lg.mark_week_done if spec.weekly else lg.mark_done)(spec.key, note=why)

    # ------------------------------------------------------------ 主流程

    def run(self) -> None:
        cfg = self.cfg
        specs = wanted(cfg)
        if not specs:
            raise StopShop("没有选要买的商品")
        todo = [s for s in specs if cfg.force or not self._done(s)]
        if not todo:
            raise StopShop("要买的都买过了（账本）")
        self.log.info("商店：要看 %d 件（%s）", len(todo), "、".join(s.label for s in todo))
        self._enter()
        for p in PAGES:
            specs_here = [s for s in todo if s.page is p]
            if not specs_here:
                continue
            self._open_page(p)
            self._sweep(p, specs_here)
        n = len(self.r.shop_buys)
        if cfg.dry_run:
            raise StopShop(f"dry-run，会买：{'；'.join(w for w in self.r.would if w.startswith('商店')) or '没有'}")
        raise StopShop(f"买了 {n} 次（{'、'.join(f'{b.name}×{b.count}' for b in self.r.shop_buys) or '无'}）")

    def _enter(self) -> None:
        self.ctl.tap_until("lobby/shop", SCENES)

    def _open_page(self, p: Page) -> None:
        """切到左侧菜单的商店 / 交易所，再选中页签。"""
        ctl = self.ctl
        info = PAGES[p]
        state = ctl.wait_scene(SCENES, timeout=20, settle=False)
        if not state.is_(info.scene):
            ctl.tap_until(info.side, info.scene)
        for _ in range(TAB_TRIES):
            frame = self._settle_list(info.scene)
            sel = page.tab_selected(self.vision, frame, info.tab)
            if sel:
                self.log.info("商店：%s", info.label)
                return
            if sel is None:
                raise ItemFailed(f"认不出页签（{info.label}）")
            ctl.tap_template(info.tab)
            ctl.sleep(0.5)
        raise ItemFailed(f"点了 {TAB_TRIES} 次也没切到 {info.label}")

    # ------------------------------------------------------------ 扫一页

    def _sweep(self, p: Page, specs: list[Spec]) -> None:
        scene = PAGES[p].scene
        pending = list(specs)
        logged: set[str] = set()
        seen: set[ShopItem] = set()
        for pass_no in range(MAX_PASSES):
            if pass_no:
                self._to_start(scene)
            bought_before = self._buys
            prev_sig = None
            for _ in range(MAX_SCREENS):
                cards = self._scan(scene)
                for c in cards:
                    if c.name not in logged and any(s.name == c.name for s in specs):
                        logged.add(c.name)
                        self.log.info("  %s", c)
                seen.update(s.item for s in pending if _find(cards, s) is not None)
                sig = page.list_signature(cards)
                if sig == prev_sig:
                    break  # 滑不动了：到头
                cards = self._process(scene, pending, cards)
                prev_sig = page.list_signature(cards)
                if not pending:
                    break
                self.ctl.swipe(*SWIPE[0], *SWIPE[1], SWIPE_DURATION)
            unseen = [s for s in pending if s.item not in seen]
            if not pending or (self._buys == bought_before and not (unseen and pass_no == 0)):
                break
        for s in pending:
            self.log.warning("商店：%s 没找到「%s」（%s）", PAGES[p].label, s.name, s.label)

    def _process(self, scene: str, pending: list[Spec], cards: list[Card]) -> list[Card]:
        """处理当前屏能处理的目标，直到没有可做的；返回最后一次扫描的卡片。"""
        while True:
            hit = next(((s, c) for s in pending if (c := _find(cards, s)) is not None), None)
            if hit is None:
                return cards
            spec, card = hit
            if not self._handle(spec, card):
                pending.remove(spec)
            cards = self._scan(scene)

    def _handle(self, spec: Spec, card: Card) -> bool:
        """处理一张目标卡片。返回 True 表示还要继续看它（买了一部分、或越买越贵的还没到次数）。"""
        cfg = self.cfg
        rem = card.remaining
        if not card.buyable or rem == 0:
            self.log.info("  %s：已买完", spec.label)
            self._mark(spec, "已买完")
            return False
        want = rem  # None：卡片上的次数读不出，按购买框里的剩余次数买
        if spec.item in RISING:
            if card.counter is None:
                self.log.warning("  %s：读不出剩余次数，不买", spec.label)
                return False
            bought = card.counter[1] - card.counter[0]
            if bought >= cfg.shop_affinity_weekly:
                self.log.info("  %s：本周买了 %d 次，到上限 %d", spec.label, bought, cfg.shop_affinity_weekly)
                self._mark(spec, f"本周买了 {bought} 次")
                return False
            want = 1
        if card.currency is not spec.currency:
            self.log.warning("  %s：价格图标不是%s，不买", spec.label, page.CURRENCY_LABELS[spec.currency])
            return False
        if spec.unit is not None and card.price != spec.unit:
            self.log.warning("  %s：价格读数 %s 和单价 %d 不符，不买", spec.label, card.price, spec.unit)
            return False
        if cfg.shop_max_buys and self._buys >= cfg.shop_max_buys:
            self.log.info("  %s：达到每次最多 %d 次，不买", spec.label, cfg.shop_max_buys)
            return False
        if self._attempts.get(spec.item, 0) >= MAX_ATTEMPTS:
            self.log.warning("  %s：点了 %d 次都没买成，跳过", spec.label, MAX_ATTEMPTS)
            return False
        top = self._read_top()
        held = None if spec.currency is FREE else top.get(spec.currency)
        if spec.currency is not FREE:
            if held is None:
                self.log.warning("  %s：顶栏读不出%s，不买", spec.label, page.CURRENCY_LABELS[spec.currency])
                return False
            if card.price is None or held < card.price:
                self.log.info("  %s：%s不够（持有 %s，单价 %s）", spec.label, page.CURRENCY_LABELS[spec.currency],
                              held, card.price)
                return False
        if cfg.dry_run and not cfg.shop_probe_dialogs:
            count = want if want is not None else 1
            if spec.currency is not FREE and card.price:
                count = min(count, held // card.price)  # 数量条「最多」也是按买得起的算
            self._would(spec, card, count)
            return False
        result = self._buy(spec, card, want, top)
        if result is None:
            return False  # dry-run 核对完 / 购买框不对，跳过
        got, left = result
        if not got:
            self._attempts[spec.item] = self._attempts.get(spec.item, 0) + 1
        if spec.item in RISING:
            return got > 0
        if got and left <= 0:
            self._mark(spec, "买完")
            return False
        return got > 0  # 只买到一部分（例如行动力只够买 1 个光谱核心）：再看一次，买不起就停

    def _would(self, spec: Spec, card: Card, count: int) -> None:
        price = "免费" if spec.currency is FREE else f"{card.price} {page.CURRENCY_LABELS[spec.currency]}"
        msg = f"商店：{spec.label} × {count}（{price}）"
        self.r.would.append(msg)
        self.log.info("  [dry-run] 会买 %s", msg[3:])

    # ------------------------------------------------------------ 买

    def _buy(self, spec: Spec, card: Card, want: int | None, top: Top) -> tuple[int, int] | None:
        """打开购买框、核对、点购买、核对结果。返回（买到的个数，还剩几次）；买到 0 个 = 没买成；
        None = 核对不过或 dry-run，没点购买。"""
        ctl = self.ctl
        dialog = self._open_dialog(card)
        if dialog is None:
            self.m._fail(f"点了{spec.label}，购买框没出现（{ctl.last_state}）")
            self._back_to_list()
            return 0, 1
        if want is None:
            want = dialog.remaining or 1
        if dialog.layout is Layout.QTY and dialog.max_btn is not None and dialog.count != want:
            ctl.tap_match(dialog.max_btn, ref="shop/dlg/max", delay=False)
            ctl.sleep(0.3)
            dialog = self.m._wait_for(lambda f: self._dialog_probe(f, settled=True), timeout=3.0) or dialog
        problem = self._check_dialog(spec, card, dialog, want, top)
        if problem:
            self.log.warning("  %s：购买框核对不过：%s（%s），点取消", spec.label, problem, dialog)
            self._cancel()
            return None
        if self.cfg.dry_run:
            self._would(spec, card, dialog.count)
            self.log.info("  [dry-run] 购买框核对通过（%s），点取消", dialog)
            self._cancel()
            return None

        self.log.info("购买 %s（顶栏：%s）", dialog, top)
        ctl.sleep(DIALOG_SETTLE)
        ctl.tap_match(dialog.buy, ref="shop/dlg/buy", delay=False)
        rewarded = self._wait_result()
        ctl.sleep(TOP_SETTLE)
        after = self._read_top()
        ok = self._verify(spec, dialog, top, after, rewarded)
        remaining = dialog.remaining if dialog.remaining is not None else want
        if not ok:
            return 0, remaining
        self._buys += 1
        price = dialog.price or 0
        self.r.shop_buys.append(stats.ShopBuy(spec.item.value, spec.name, dialog.count, spec.currency.value, price))
        if spec.currency is F:
            self.r.friendship_spent += price
        self.log.info("✔ 买到 %s × %d（顶栏：%s）", spec.label, dialog.count, after)
        self.m._ok()
        return dialog.count, remaining - dialog.count

    def _check_dialog(self, spec: Spec, card: Card, d: Dialog, want: int, top: Top) -> str | None:
        """返回不能购买的原因；可以买返回 None。"""
        if d.name != spec.name:
            return f"商品名「{d.name}」不是「{spec.name}」"
        if d.currency is not spec.currency:
            return f"价格不是{page.CURRENCY_LABELS[spec.currency]}"
        if card.remaining is not None and d.remaining != card.remaining:
            return f"剩余次数 {d.remaining} 和卡片上的 {card.remaining} 不一致"
        k = d.count
        if d.layout is Layout.QTY:
            if d.qty is None:
                return "数量读不出"
            if k < 1 or k > want or k != d.qty[1]:
                return f"数量 {d.qty[0]}/{d.qty[1]} 不对（要买 {want}）"
        elif spec.item in RISING and d.layout is not Layout.RISING:
            return "不是越买越贵的购买框"
        if spec.currency is FREE:
            return None
        if d.price is None:
            return "总价读不出"
        if spec.unit is not None and d.price != spec.unit * k:
            return f"总价 {d.price} ≠ 单价 {spec.unit} × {k}"
        held = top.get(spec.currency)
        if held is None or held < d.price:
            return f"不够付（持有 {held}）"
        return None

    def _verify(self, spec: Spec, d: Dialog, before: Top, after: Top, rewarded: bool) -> bool:
        """买完核对顶栏：天空石不变；付款货币正好减少总价（免费的要看到获得奖励）。返回买成没有。

        天空石变了、扣的数不对立即停止整个任务；没扣钱（点击被吞）算这次失败。
        「获得奖励」框只有部分商品有（行动力这类入场券只在顶部飘一条提示，实测 B12b），不作为买成的条件。"""
        if before.skystone is None or after.skystone is None:
            raise ShopAnomaly(f"买{spec.label}后天空石读不出（{before} → {after}）")
        if after.skystone != before.skystone:
            raise ShopAnomaly(f"买{spec.label}后天空石变了：{before.skystone} → {after.skystone}")
        if spec.currency is FREE:
            if not rewarded:
                self.m._fail(f"点了购买（{spec.label}），没有出现获得奖励")
            return rewarded
        b, a = before.get(spec.currency), after.get(spec.currency)
        if b is None or a is None:
            raise ShopAnomaly(f"买{spec.label}后{page.CURRENCY_LABELS[spec.currency]}读不出（{before} → {after}）")
        spent = b - a
        price = d.price or 0
        low = price - (ENERGY_REGEN if spec.currency is E else 0)
        if low <= spent <= price:
            return True
        if spent == 0:
            self.m._fail(f"点了购买（{spec.label}），{page.CURRENCY_LABELS[spec.currency]}没变")
            return False
        raise ShopAnomaly(f"买{spec.label}（总价 {price}）后{page.CURRENCY_LABELS[spec.currency]} {b} → {a}")

    def _open_dialog(self, card: Card) -> Dialog | None:
        self.ctl.tap_rect(card.tap_rect, delay=False)
        return self.m._wait_for(lambda f: self._dialog_probe(f, settled=True), timeout=DIALOG_WAIT)

    def _dialog_probe(self, frame: np.ndarray, *, settled: bool = False) -> Dialog | None:
        state = self.ctl.detect(frame)
        if state.popup not in (POPUP_BUY, POPUP_BUY1):
            return None
        d = page.read_dialog(self.vision, frame)
        if d is None or not settled:
            return d
        # 购买框淡入、数量变化时数字会动：连续两帧读到一样的才采用
        nxt = page.read_dialog(self.vision, self.ctl.screenshot())
        return d if nxt is not None and (nxt.name, nxt.qty, nxt.price) == (d.name, d.qty, d.price) else None

    def _cancel(self) -> None:
        """购买框点取消（模块弹窗规则就是点取消），等它消失。"""
        self._back_to_list()

    def _back_to_list(self) -> None:
        self.ctl.wait_scene((STORE, EXCHANGE), timeout=20, settle=False)

    def _wait_result(self) -> bool:
        """点了购买后：等购买框消失、回到列表并停留 RESULT_GRACE 秒（顶部的获得提示飘完）。
        期间出现「获得奖励」就等它完全显示 → 点击关闭 → 等它消失。返回有没有出现获得奖励。

        购买框 DIALOG_EATEN 秒还在（点击被吞）就不等了，按弹窗规则点取消，交给读数核对。
        """
        ctl = self.ctl
        t0 = time.monotonic()
        prev = None
        list_since = None
        rewarded = False
        while True:
            state = ctl.detect()
            now = time.monotonic()
            thumb = thumbnail(ctl.last_frame)
            if state.popup == POPUP_REWARD:
                list_since = None
                if prev is not None and thumb_diff(thumb, prev) < STILL_DIFF:
                    ctl.tap_template("shop/reward/close")
                    self.m._wait_popup_gone(POPUP_REWARD)
                    rewarded = True
                    break
                prev = thumb
            else:
                prev = None
                if state.popup == POPUP_NETWORK:
                    ctl.dismiss_popups(state=state)
                elif state.popup in (POPUP_BUY, POPUP_BUY1):
                    if now - t0 >= DIALOG_EATEN:
                        self.log.warning("点了购买 %.0f 秒购买框还在", DIALOG_EATEN)
                        break
                elif state.is_(STORE, EXCHANGE):
                    list_since = list_since or now
                    if now - list_since >= RESULT_GRACE:
                        break
            if now - t0 >= REWARD_WAIT:
                self.log.warning("点了购买 %.0f 秒还没回到列表（%s）", REWARD_WAIT, ctl.last_state)
                break
            ctl.sleep(POLL)
        self._back_to_list()  # 购买框还在就按弹窗规则点取消
        return rewarded

    # ------------------------------------------------------------ 列表

    def _scan(self, scene: str) -> list[Card]:
        return page.scan_cards(self.vision, self._settle_list(scene))

    def _settle_list(self, scene: str, timeout: float = 15.0) -> np.ndarray:
        """等到没有弹窗、列表区域停稳（滑动有惯性），返回那一帧。弹窗交给内置规则。"""
        ctl = self.ctl
        deadline = time.monotonic() + timeout
        prev = None
        prev_at = still_since = popup_since = None
        while True:
            state = ctl.detect()
            now = time.monotonic()
            if state.is_(scene):
                popup_since = None
                frame = ctl.last_frame
                thumb = thumbnail(Scaler(frame.shape[1], frame.shape[0]).rect_to_device(page.LIST).crop(frame))
                if prev is not None and thumb_diff(thumb, prev) < LIST_DIFF:
                    still_since = still_since or prev_at
                    if now - still_since >= LIST_STILL:
                        return ctl.last_frame
                else:
                    still_since = None
                prev, prev_at = thumb, now
            else:
                prev = still_since = None
                popup_since = popup_since or now
                if state.popup == POPUP_NETWORK or now - popup_since >= POPUP_GRACE:
                    ctl.wait_scene(scene, timeout=max(1.0, deadline - now), settle=False)
                    popup_since = None
                    continue
            if now >= deadline:
                raise ItemFailed(f"商品列表一直没停稳（{ctl.last_state}）")
            ctl.sleep(POLL)

    def _to_start(self, scene: str) -> None:
        """滑回列表最左边（滑不动为止）。"""
        prev = None
        for _ in range(SWIPE_BACK_MAX):
            sig = page.list_signature(self._scan(scene))
            if sig == prev:
                return
            prev = sig
            self.ctl.swipe(*SWIPE[1], *SWIPE[0], SWIPE_DURATION)

    def _read_top(self) -> Top:
        """顶栏读数（连续两帧一致才采用；数字有滚动动画）。"""
        ctl = self.ctl
        prev = None
        for _ in range(8):
            top = page.read_top(self.vision, ctl.screenshot())
            if prev is not None and top == prev:
                return top
            prev = top
            ctl.sleep(POLL)
        raise ItemFailed(f"顶栏读数不稳定（最后一次：{prev}）")


def _find(cards: list[Card], spec: Spec) -> Card | None:
    """当前屏里 spec 对应的卡片：名字一样，并且「剩余/上限」的上限一样；次数读不出时要求能买、价格图标一样。
    同名的另一张（用生命之叶买的光谱核心，不限购、没有次数）因此不算。"""
    for c in cards:
        if c.name != spec.name:
            continue
        if c.counter is not None:
            if c.counter[1] == spec.limit:
                return c
        elif c.buyable and c.currency is spec.currency:
            return c
        elif not c.buyable and spec.item not in AMBIGUOUS:
            return c  # 买完的卡片次数是灰字，有时读不出
    return None


__all__ = ["CATALOG", "PAGES", "SCENES", "Page", "Shop", "ShopAnomaly", "Spec", "StopShop", "register", "wanted"]
