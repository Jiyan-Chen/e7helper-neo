"""刷神秘商店：扫描列表买目标商品（默认誓约书签 / 神秘奖牌），然后消耗天空石刷新，循环。

安全规则（详见 docs/reviews/B04.md）：
- 只有扣费确认后才计数：按顶栏天空石/金币的读数差计，不按点击次数。
  网络异常时内置的 network 弹窗会点「重试」重发请求，读数差照样能反映实际结果。
- 读数差既不是 0 也不是预期值（例如重试导致扣了两次）时立即停止，任务记为失败并保存调试截图。
- 购买/刷新确认框由本任务自己点确认；内置规则和本模块注册的弹窗规则在自动关闭时一律点「取消」。
- 每页每个商品最多尝试 2 次；扣费没有发生算一次失败，连续失败 max_failures 次就停止。
- dry_run（默认开启）只识别和决策，不点购买和刷新；probe_dialogs 时打开确认框核对内容后点取消。

效率（B04 审核时优化）：不用整屏静止判定，而是等列表区域停稳；点确认后轮询顶栏读数，变了就继续；
顶栏读数在每次核对后复用为下一次操作的「操作前」读数。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from e7helper.core.geometry import Rect, Scaler
from e7helper.core.runtime.stuck import thumb_diff, thumbnail
from e7helper.core.scene import Dismiss, Popup, SceneState
from e7helper.modules.base import TaskModule

from . import page, stats
from .config import SecretShopConfig, Target
from .page import Resources, ShopItem

SCENE = "secret_shop"
POPUP_BUY = "shop_buy"
POPUP_REFRESH = "shop_refresh"
POPUP_NETWORK = "network"

# 列表滑动（基准坐标）：在名称列和价格列之间的空白处竖直滑动，一次就能从顶部滑到底部
SWIPE_X = 1150
SWIPE_TOP, SWIPE_BOTTOM = 210, 760

# 列表停稳：右侧列表区域（不含左边有待机动画的人物）的缩略图连续 LIST_STILL 秒变化 < LIST_DIFF。
# 实测（B04）：滑动结束后约 0.7 秒停稳；惯性末段整屏帧差只有 1–2，所以不能用整屏静止判定。
LIST_REGION = Rect(540, 85, 1060, 815)
LIST_DIFF = 1.0
LIST_STILL = 0.25
POLL = 0.08  # 等列表/弹窗/读数时的轮询间隔
POPUP_GRACE = 1.0  # 确认框之类的弹窗先等它自己消失（淡出途中不要去点取消），超过这个时间再交给内置规则
DIALOG_SETTLE = 0.15  # 确认框完全显示（按钮模板 max_diff 通过）后再稍等，避免点在动画末尾
VERIFY_TIMEOUT = 6.0  # 点确认后等扣费读数变化的时间，超时按没扣费处理
MAX_ATTEMPTS = 2  # 每页每个商品最多尝试购买的次数


class StopShop(Exception):
    """正常停止（预算用完、连续失败等），任务仍算成功。"""


class ShopAnomaly(RuntimeError):
    """扣费与预期不符，立即停止，任务记为失败。"""


def _list_thumb(frame: np.ndarray) -> np.ndarray:
    region = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(LIST_REGION)
    return thumbnail(region.crop(frame))


class SecretShopModule(TaskModule):
    id = "secret_shop"
    name = "刷神秘商店"
    description = "在秘密商店购买目标商品（誓约书签、神秘奖牌），消耗天空石刷新，按预算和次数自动停止"
    config_model = SecretShopConfig

    def setup(self) -> None:
        if self.ctx.controller is None:
            return
        scenes = self.ctl.scenes
        # 放在内置 confirm 之前：刷新确认框和内置 confirm 的按钮完全一样，靠文字模板区分
        scenes.add_popup(Popup(
            POPUP_REFRESH, ("secret_shop:dialog/refresh_text", "dialog/cancel", "dialog/confirm"),
            Dismiss.tap("dialog/cancel"), note="要消耗天空石立即更新吗？（自动关闭时点取消）",
        ), replace=True, first=True)
        scenes.add_popup(Popup(
            POPUP_BUY, ("secret_shop:dialog/buy_title", "dialog/cancel"), Dismiss.tap("dialog/cancel"),
            note="购买商品确认框（自动关闭时点取消）",
        ), replace=True, first=True)

    # ------------------------------------------------------------ 主流程

    def run(self) -> None:
        cfg: SecretShopConfig = self.config
        self.run_stats = stats.RunStats(dry_run=cfg.dry_run)
        self._consecutive_failures = 0
        self._scrolled = False
        self._last_res: Resources | None = None  # 最近一次核对过的顶栏读数，作为下一次操作的「操作前」读数
        self._page_index = 0
        mode = "dry-run（不点购买和刷新）" if cfg.dry_run else "实跑"
        self.log.info("刷神秘商店：%s；目标 %s；最多刷新 %d 次，天空石预算 %d",
                      mode, "、".join(_target_str(t) for t in cfg.targets), cfg.max_refreshes, cfg.skystone_budget)
        try:
            self._enter()
            res = self._resources()
            self.run_stats.skystone_start, self.run_stats.gold_start = res.skystone, res.gold
            self.log.info("开始：%s", res)
            while True:
                self._scan_page()
                self._refresh()
                self._page_index += 1
        except StopShop as e:
            self.run_stats.stop_reason = str(e)
            self.log.info("停止：%s", e)
        except BaseException as e:
            self.run_stats.stop_reason = f"{type(e).__name__}：{e}"
            raise
        finally:
            r = self.run_stats
            if self._last_res is not None:
                r.skystone_end, r.gold_end = self._last_res.skystone, self._last_res.gold
            r.ended = stats.now()
            stats.save(self.ctx.data_dir, r)
            self.log.info("统计：%s", r.summary())

    def _enter(self) -> None:
        ctl = self.ctl
        state = ctl.wait_scene(("lobby", SCENE), timeout=20)
        if state.is_("lobby"):
            self.log.info("从大厅进入秘密商店")
            ctl.tap_until("lobby/secret_shop", SCENE)
            self._scrolled = False  # 进店时列表在顶部
        else:
            self._scrolled = True  # 本来就在商店里，列表可能被滑动过，第一页先滑到顶

    # ------------------------------------------------------------ 扫描与购买

    def _scan_page(self) -> None:
        self.run_stats.pages += 1
        self._seen: set[str] = set()
        self._done: set[str] = set()  # 本页已买 / 已决定不买 / dry-run 已记下的商品
        self._attempts: dict[str, int] = {}
        self.log.info("第 %d 页", self._page_index)
        if self._scrolled:
            self._scroll(down=False)
        self._scan_view()
        self._scroll(down=True)
        self._scan_view()

    def _scroll(self, *, down: bool) -> None:
        y1, y2 = (SWIPE_BOTTOM, SWIPE_TOP) if down else (SWIPE_TOP, SWIPE_BOTTOM)
        self.ctl.swipe(SWIPE_X, y1, SWIPE_X, y2, delay=False)
        self._scrolled = down

    def _scan_view(self) -> None:
        cfg: SecretShopConfig = self.config
        for _ in range(12):  # 每买一件都重新扫描（画面变了）；上限防止意外死循环
            frame = self._settle_list()
            items = page.scan_items(self.vision, frame, page.target_icons(cfg.targets))
            for it in items:
                if it.name not in self._seen:
                    self._seen.add(it.name)
                    self.log.info("  %s", it)
                    if (t := page.near_miss(it.name, cfg.targets)) is not None:
                        self.log.warning("  「%s」和目标「%s」很像但没匹配上，可能是 OCR 认错了字", it.name, t.name)
            todo = [it for it in items
                    if it.name not in self._done and page.match_target(it, cfg.targets) is not None]
            if not todo:
                return
            self._handle_target(todo[0])
        self.log.warning("本屏处理次数超过上限，跳过")

    def _handle_target(self, item: ShopItem) -> None:
        cfg: SecretShopConfig = self.config
        res = self._last_res
        decision = page.decide(item, cfg.targets, res.gold, cfg.gold_floor)
        self.log.info("  决策：%s", decision)
        if not decision.buy:
            self._done.add(item.name)
            return
        if cfg.dry_run:
            self._done.add(item.name)
            self.run_stats.would_buy.append(stats.Purchase(item.name, item.price, self._page_index))
            if cfg.probe_dialogs:
                self._probe_buy(item, decision.target)
            return
        self._attempts[item.name] = n = self._attempts.get(item.name, 0) + 1
        if n >= MAX_ATTEMPTS:
            self._done.add(item.name)
        if self._buy(item, decision.target, res):
            self._done.add(item.name)

    def _open_buy_dialog(self, item: ShopItem, target: Target) -> page.BuyDialog | None:
        """点「购买」打开确认框并核对内容；不符时点取消，返回 None。"""
        ctl = self.ctl
        ctl.tap_match(item.buy, ref="buy", delay=False)

        def probe(frame):
            state = ctl.detect(frame)
            return page.read_buy_dialog(self.vision, frame) if state.popup == POPUP_BUY else None

        dialog = self._wait_for(probe)
        if dialog is None:
            self._fail(f"点购买 {item.name} 后确认框没出现")
            self._back_to_shop()
            return None
        # 确认框里的名字要和列表这一行一致（按图标认出的目标，名字可能和配置的不同）
        same = page.name_matches(dialog.name, item.name) or page.name_matches(dialog.name, target.name)
        if not same or dialog.price != item.price:
            self._back_to_shop()  # 购买确认框会按取消关闭
            self._fail(f"确认框内容与商品不符：期望 {item.name} {item.price}，读到 {dialog.name} {dialog.price}")
            return None
        ctl.sleep(DIALOG_SETTLE)
        return dialog

    def _probe_buy(self, item: ShopItem, target: Target) -> None:
        dialog = self._open_buy_dialog(item, target)
        if dialog is not None:
            self.log.info("  [dry-run] 购买确认框核对通过：%s %s，点取消", dialog.name, f"{dialog.price:,}")
            self._back_to_shop()
            self._ok(progress=False)

    def _buy(self, item: ShopItem, target: Target, before: Resources) -> bool:
        dialog = self._open_buy_dialog(item, target)
        if dialog is None:
            return False
        self.log.info("  确认购买 %s（%s 金币）", item.name, f"{item.price:,}")
        self.ctl.tap_match(dialog.ok, ref="dialog/buy_ok", delay=False)
        spent, after = self._verify(lambda r: before.gold - r.gold, item.price)
        if spent == item.price:
            self.run_stats.gold_spent += spent
            self.run_stats.purchases.append(stats.Purchase(item.name, item.price, self._page_index))
            self.log.info("  ✔ 买到 %s，金币 %s → %s", item.name, f"{before.gold:,}", f"{after.gold:,}")
            self._ok()
            return True
        if spent == 0:
            self._fail(f"购买 {item.name} 后金币没有变化")
            return False
        self.run_stats.gold_spent += spent
        raise ShopAnomaly(f"购买 {item.name} 后金币减少 {spent:,}，预期 {item.price:,}（{before} → {after}）")

    # ------------------------------------------------------------ 刷新

    def _refresh(self) -> None:
        cfg: SecretShopConfig = self.config
        r = self.run_stats
        if r.refreshes >= cfg.max_refreshes:
            raise StopShop(f"达到最多刷新次数 {cfg.max_refreshes}")
        ctl = self.ctl
        before = self._last_res
        cost = page.read_refresh_cost(self.vision, ctl.last_frame)  # 最后一帧是刚扫描过的列表
        if cost != cfg.refresh_cost:
            raise StopShop(f"刷新消耗读数 {cost} 与配置的 {cfg.refresh_cost} 不符")
        if r.skystone_spent + cost > cfg.skystone_budget:
            raise StopShop(f"天空石预算用完（已花 {r.skystone_spent}，预算 {cfg.skystone_budget}）")
        if before.skystone - cost < cfg.skystone_keep:
            raise StopShop(f"天空石 {before.skystone} 刷新后会低于保底 {cfg.skystone_keep}")
        prices = [t.price for t in cfg.targets]
        if prices and None not in prices and before.gold - min(prices) < cfg.gold_floor:
            raise StopShop(f"金币 {before.gold:,} 已经不够在下限 {cfg.gold_floor:,} 之上买任何目标")

        if cfg.dry_run:
            self.log.info("[dry-run] 下一步会刷新：消耗 %d 天空石（%d → %d），预算剩 %d",
                          cost, before.skystone, before.skystone - cost, cfg.skystone_budget - r.skystone_spent)
            if cfg.probe_dialogs and self._open_refresh_dialog() is not None:
                self.log.info("[dry-run] 刷新确认框核对通过，点取消")
                self._back_to_shop()
            raise StopShop("dry-run 只扫描当前列表")

        state = self._open_refresh_dialog()
        if state is None:
            return
        self.log.info("确认刷新（第 %d 次，消耗 %d 天空石）", r.refreshes + 1, cost)
        ctl.tap_match(state.matches["dialog/confirm"], ref="dialog/confirm", delay=False)
        spent, after = self._verify(lambda x: before.skystone - x.skystone, cost)
        if spent == cost:
            r.refreshes += 1
            r.skystone_spent += spent
            self._scrolled = False  # 游戏刷新后列表自动回到顶部
            self.log.info("✔ 刷新成功（%d/%d），天空石 %d → %d", r.refreshes, cfg.max_refreshes,
                          before.skystone, after.skystone)
            self._ok()
            return
        if spent == 0:
            self._fail("刷新后天空石没有变化")
            self._page_index -= 1  # 列表没变，下一轮还是这一页
            return
        r.skystone_spent += spent
        raise ShopAnomaly(f"刷新后天空石减少 {spent}，预期 {cost}（{before} → {after}）")

    def _open_refresh_dialog(self) -> SceneState | None:
        ctl = self.ctl
        ctl.tap_match(ctl.wait("refresh", timeout=3.0), ref="refresh", delay=False)
        # dialog/refresh_text 设了 max_diff：淡入途中不命中，命中时确认框已完全显示
        state = self._wait_for(lambda f: s if (s := ctl.detect(f)).popup == POPUP_REFRESH else None)
        if state is None or "dialog/confirm" not in state.matches:
            self._fail(f"点立即更新后确认框没出现（{ctl.last_state}）")
            self._back_to_shop()
            return None
        ctl.sleep(DIALOG_SETTLE)
        return state

    # ------------------------------------------------------------ 等待

    def _wait_for(self, probe: Callable[[np.ndarray], object], timeout: float = 5.0):
        """轮询 probe(frame) 直到返回非 None；超时返回 None。"""
        ctl = self.ctl
        deadline = time.monotonic() + timeout
        while True:
            result = probe(ctl.screenshot())
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                return None
            ctl.sleep(POLL)

    def _popup_overdue(self, state: SceneState, since: float | None, now: float) -> bool:
        """弹窗要不要交给内置规则关闭：网络异常立即重试；其他（确认框淡出、未知弹窗）先等 POPUP_GRACE 秒。"""
        if state.clear:
            return False
        return state.popup == POPUP_NETWORK or (since is not None and now - since >= POPUP_GRACE)

    def _settle_list(self, timeout: float = 15.0) -> np.ndarray:
        """等到商店列表没有弹窗、且列表区域停稳，返回那一帧。

        滑动、刷新后的飞入动画都在列表区域；左侧人物有待机动画，不参与判断。
        弹窗交给内置规则（网络异常重试、残留确认框点取消、未知弹窗返回键）。
        """
        ctl = self.ctl
        deadline = time.monotonic() + timeout
        prev: np.ndarray | None = None
        prev_at = still_since = popup_since = None
        while True:
            state = ctl.detect()
            now = time.monotonic()
            if state.is_(SCENE):
                popup_since = None
                thumb = _list_thumb(ctl.last_frame)
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
                if self._popup_overdue(state, popup_since, now):
                    ctl.wait_scene(SCENE, timeout=30)
                    popup_since = None
                    continue
            if now >= deadline:
                ctl.wait_scene(SCENE, timeout=30)
                return ctl.last_frame
            ctl.sleep(POLL)

    def _back_to_shop(self) -> None:
        """回到没有弹窗的商店列表：网络异常点重试，残留的确认框点取消，未知弹窗按返回键。"""
        self.ctl.wait_scene(SCENE, timeout=30)

    # ------------------------------------------------------------ 顶栏读数

    def _read_resources(self, frame) -> Resources:
        return page.read_resources(self.vision, frame)

    def _resources(self) -> Resources:
        """连续两帧读数一致才采用（金币数字有约 0.4 秒的滚动动画）。"""
        ctl = self.ctl
        prev: Resources | None = None
        for _ in range(8):
            res = self._read_resources(ctl.screenshot())
            if res == prev and res.skystone is not None and res.gold is not None:
                self._last_res = res
                return res
            prev = res
            ctl.sleep(0.15)
        raise StopShop(f"顶栏天空石/金币读不出或不稳定（最后一次：{prev}）")

    def _verify(self, spent_of: Callable[[Resources], int], expected: int) -> tuple[int, Resources]:
        """点确认后：轮询顶栏直到读数变化（或 VERIFY_TIMEOUT 秒），再读稳定值，返回（花费, 读数）。

        途中出现网络异常就点重试；确认框没关掉（点击被吞）则过 POPUP_GRACE 秒后点取消。
        """
        ctl = self.ctl
        deadline = time.monotonic() + VERIFY_TIMEOUT
        popup_since = None
        while True:
            state = ctl.detect()
            now = time.monotonic()
            if state.clear:
                popup_since = None
                res = self._read_resources(ctl.last_frame)
                if res.skystone is not None and res.gold is not None and spent_of(res) != 0:
                    break
            else:
                popup_since = popup_since or now
                if self._popup_overdue(state, popup_since, now):
                    ctl.wait_scene(SCENE, timeout=30)
                    popup_since = None
                    continue
            if now >= deadline:
                break
            ctl.sleep(POLL)
        if not ctl.last_state.clear:
            self._back_to_shop()
        after = self._resources()
        spent = spent_of(after)
        if spent not in (0, expected):
            self.log.warning("扣费读数异常：花费 %d，预期 %d（%s）", spent, expected, after)
        return spent, after

    # ------------------------------------------------------------ 计数

    def _ok(self, progress: bool = True) -> None:
        self._consecutive_failures = 0
        if progress:
            self.ctl.progress()

    def _fail(self, msg: str) -> None:
        self.run_stats.failures += 1
        self._consecutive_failures += 1
        n, limit = self._consecutive_failures, self.config.max_failures
        self.log.warning("失败（连续 %d/%d）：%s", n, limit, msg)
        if n >= limit:
            raise StopShop(f"连续失败 {n} 次，最后一次：{msg}")


def _target_str(t: Target) -> str:
    return t.name if t.price is None else f"{t.name}({t.price:,})"


__all__ = ["SecretShopConfig", "SecretShopModule", "ShopAnomaly", "StopShop", "Target"]
