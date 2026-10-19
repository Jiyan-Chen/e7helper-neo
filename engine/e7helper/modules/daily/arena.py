"""日常收取 · 竞技场：用掉现有的竞技场旗帜挑战 NPC；可选用友情点数补一次旗（每天限一次）后继续。

B05 是单独的 `arena_npc` 模块，B12 按用户意见并进日常收取，作为第 4 项（`DailyConfig.arena`）。

流程（详见 docs/reviews/B05.md）：
大厅 → 竞技场模式选择 → 普通竞技场（关掉「战斗记录」弹窗）→ NPC对战页 → 选第一行 → 挑战 → 准备界面
→ 快速对战（当天次数用完则切到普通战斗，并在战斗中开启自动）→ 结算点确认 → 回到 NPC 列表 → 循环。

安全规则：
- 只有确认后才计数：一场 = 看到结算界面 + 顶栏旗帜读数减少；补旗 = 旗帜读数增加 5。不按点击次数计。
- 读数差异常（一场少了 2 面以上、补旗后增加的不是 5）立即停止整个任务（`ArenaAnomaly`），任务记为失败。
- 补旗只用友情点数：点「购买」前核对左边是友情点数选项且被选中、天空石选项没被选中、消耗 100 换 5 面。
  任一项不符就点取消并结束这一项。补旗框自动关闭时一律点取消。
- dry_run 只导航到准备界面并决定用哪种模式，不点「快速对战」「战斗开始」「购买」。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np

from e7helper.core.geometry import Rect
from e7helper.core.runtime.stuck import thumb_diff, thumbnail
from e7helper.core.scene import Dismiss, Popup, Scene, SceneState

from . import arena_page as page
from . import stats
from .arena_page import BuyDialog, Prep, PrepMode
from .errors import DailyAnomaly, ItemFailed, StopItem

if TYPE_CHECKING:
    from e7helper.core.scene import SceneDetector

    from . import DailyModule
    from .config import DailyConfig

MODES = "arena"  # 内置场景：竞技场模式选择
MAIN = "arena_main"  # 交战对手页（进竞技场默认在这一页）
NPC = "arena_npc"  # NPC对战页
PREP = "arena_prep"  # 准备界面
BATTLE = "arena_battle"  # 普通战斗中
RESULT = "arena_result"  # 结算（快速对战和普通战斗两种布局）
POPUP_RECORD = "arena_record"  # 进竞技场时弹出的「战斗记录」
POPUP_BUY = "arena_buy_flags"  # 购买旗帜
POPUP_NETWORK = "network"
SCENES = (MODES, MAIN, NPC, PREP, RESULT)  # 可以从这些界面回到大厅（战斗中不行）

POLL = 0.15
POPUP_GRACE = 1.0  # 弹窗先等它自己消失，超过这个时间再交给内置规则
DIALOG_SETTLE = 0.15  # 确认框完全显示后再稍等，避免点在动画末尾
VERIFY_TIMEOUT = 6.0  # 补旗后等旗帜读数变化的时间
QUICK_TIMEOUT = 60.0  # 快速对战从点按钮到结算的最长时间（实测约 6 秒）
START_GRACE = 8.0  # 点了开始后还停在准备界面这么久，认为点击被吞
VICTORY_WAIT = 1.5  # 结算出现后等胜利字样（发光动画约 0.5 秒）
# 结算的「确认」刚出现时点击会被吞（实测普通战斗结算入场动画期间），确认不消耗东西，2 秒没反应就补点
RESULT_RETRY = 2.0
# 自动战斗：图标连续 AUTO_STILL 秒变化 < AUTO_DIFF 认为没开（开启后图标一直旋转，实测帧间差 20+；关闭时 < 1）
AUTO_DIFF = 3.0
AUTO_STILL = 0.6
AUTO_RETRY = 2.5  # 点了自动后至少等这么久再判断要不要重点
AUTO_MAX_TAPS = 4
MOVING_DIFF = 3.0  # 战斗画面在动（整屏缩略图帧差），用于清零卡死计数
FLAG_PLUS = (20, -5, 14, 14)  # 顶栏旗帜图标右上角的「+」，相对图标命中框
BUY_LEFT_OPTION = Rect(495, 400, 250, 130)  # 补旗框左边（友情点数）选项
BUY_COST, BUY_GAIN = 100, 5
MAX_FLAG_BUYS = 1  # 游戏每天限补一次


class StopArena(StopItem):
    """竞技场这一项正常结束（旗帜用完、dry-run 等）。"""


class ArenaAnomaly(DailyAnomaly):
    """旗帜读数变化与预期不符，立即停止整个任务，任务记为失败。"""


def register(sc: SceneDetector, q: str) -> None:
    """注册竞技场的场景和弹窗。q 是模板的模块前缀（"daily:"）。"""
    a = q + "arena/"
    for scene in (
        Scene(MAIN, ("title/arena", a + "tab/npc"), (a + "npc/header",), note="竞技场：交战对手页"),
        Scene(NPC, ("title/arena", a + "npc/header"), note="竞技场：NPC对战页"),
        Scene(PREP, ("title/arena", a + "prep/power"), note="竞技场：准备界面"),
        Scene(BATTLE, (a + "battle/pause", a + "battle/help"), note="战斗中"),
        Scene(RESULT, (a + "result/detail", a + "result/ok"), note="竞技场结算"),
    ):
        sc.add_scene(scene, replace=True, first=True)
    sc.add_popup(Popup(POPUP_BUY, (a + "buy/title", a + "buy/cancel"), Dismiss.tap(a + "buy/cancel"),
                       note="购买旗帜（自动关闭时点取消）"), replace=True, first=True)
    sc.add_popup(Popup(POPUP_RECORD, (a + "record/title", a + "record/close"), Dismiss.tap(a + "record/close"),
                       note="竞技场战斗记录（点击关闭）"), replace=True, first=True)


class Arena:
    """竞技场这一项。借用日常收取模块的 ctl / vision / log / 统计 / 账本 / 失败计数。"""

    def __init__(self, m: DailyModule):
        self.m = m
        self.ctl = m.ctl
        self.vision = m.vision
        self.log = m.log
        self.cfg: DailyConfig = m.config
        self.r: stats.RunStats = m.run_stats
        self._quick_exhausted = not self.cfg.arena_prefer_quick
        self._flags: int | None = None  # 最近一次核对过的旗帜读数
        self._buys = 0

    # ------------------------------------------------------------ 主流程

    def run(self) -> None:
        cfg = self.cfg
        self.log.info("竞技场：补旗 %s；最多 %s 场", "开" if cfg.arena_buy_flags else "关",
                      cfg.arena_max_battles or "不限")
        try:
            self._enter()
            self.r.flags_start = self._read_flags_stable()
            self.log.info("竞技场：旗帜 %d", self._flags)
            while True:
                self._step()
        finally:
            self.r.flags_end = self._flags

    def _step(self) -> None:
        cfg = self.cfg
        if cfg.arena_max_battles and len(self.r.battles) >= cfg.arena_max_battles:
            raise StopArena(f"达到最多场数 {cfg.arena_max_battles}（打了 {len(self.r.battles)} 场）")
        if self._flags >= 1:
            self._battle()
            return
        done = f"旗帜用完（打了 {len(self.r.battles)} 场）"
        if not cfg.arena_buy_flags:
            raise StopArena(done)
        if self._buys >= MAX_FLAG_BUYS:
            raise StopArena(f"{done}，本次已补旗 {self._buys} 次")
        if not cfg.force and self.m.ledger.is_done("arena_buy"):
            raise StopArena(f"{done}，今天已经补过旗（账本）")
        self._buy_flags()

    def _enter(self) -> None:
        """从大厅或竞技场里的任一界面走到 NPC 对战页。"""
        ctl = self.ctl
        state = ctl.wait_scene(("lobby", MODES, MAIN, NPC, PREP, RESULT), timeout=20)
        if state.is_("lobby"):
            self.log.info("从大厅进入竞技场")
            state = ctl.tap_until("lobby/arena", MODES)
        if state.is_(MODES):
            state = ctl.tap_until("arena/mode_arena", (MAIN, NPC))  # 途中「战斗记录」弹窗会被点击关闭
        self._to_npc(state)

    def _to_npc(self, state: SceneState | None = None) -> None:
        """在竞技场的交战对手页 / 准备界面 / 结算界面时回到 NPC 对战页。"""
        ctl = self.ctl
        state = state if state is not None and state.clear else ctl.wait_scene((MAIN, NPC, PREP, RESULT), timeout=30)
        if state.is_(MAIN):
            ctl.tap_until("arena/tab/npc", NPC)
        elif state.is_(PREP):
            ctl.tap_until("back", NPC)
        elif state.is_(RESULT):
            ctl.tap_until("arena/result/ok", NPC, retry_after=RESULT_RETRY)
        ctl.wait_scene(NPC, timeout=30)

    # ------------------------------------------------------------ 一场

    def _battle(self) -> None:
        ctl = self.ctl
        before = self._flags
        if not self._select_first():
            return
        ctl.tap_until("arena/npc/challenge", PREP, timeout=30)  # 挑战只打开准备界面，不消耗旗帜
        prep = self._choose_mode()
        if prep is None:
            self.m._fail("准备界面的开始按钮没认出来")
            self._to_npc()
            return
        label = "快速对战" if prep.mode is PrepMode.QUICK else "普通战斗（自动）"
        if self.cfg.dry_run:
            left = f"，本日快速对战剩余 {prep.quick_left}" if prep.mode is PrepMode.QUICK else ""
            msg = f"用{label}挑战第一个 NPC（旗帜 {before}{left}）"
            self.r.would.append(msg)
            self._to_npc()
            raise StopArena(f"dry-run，下一步会{msg}")

        self.log.info("开始第 %d 场：%s，旗帜 %d", len(self.r.battles) + 1, label, before)
        t0 = time.monotonic()
        ref = "arena/prep/quick" if prep.mode is PrepMode.QUICK else "arena/prep/start"
        ctl.tap_match(prep.button, ref=ref, delay=False)
        frame = self._wait_result(prep.mode)
        if frame is None:
            self.m._fail(f"点{label}后没有开始战斗")
            self._to_npc()
            self._check_spent(before, self._read_flags_stable(), counted=False)
            return
        victory = page.is_victory(self.vision, frame)
        seconds = time.monotonic() - t0
        ctl.tap_until("arena/result/ok", NPC, timeout=30, retry_after=RESULT_RETRY, max_taps=5)
        after = self._read_flags_stable()
        self._check_spent(before, after, counted=True)
        self.r.battles.append(stats.Battle(prep.mode.value, victory, after, round(seconds, 1)))
        self.log.info("✔ 第 %d 场%s，用时 %.0f 秒，旗帜 %d → %d", len(self.r.battles),
                      "胜利" if victory else "结束（没认出胜利）", seconds, before, after)
        self.m._ok()

    def _check_spent(self, before: int, after: int, *, counted: bool) -> None:
        """核对一场消耗的旗帜。counted=False 表示没看到结算（点击可能被吞），这时不应该少旗帜。"""
        spent = before - after
        expected = 1 if counted else 0
        if spent == expected:
            self.r.flags_spent += spent
            return
        if counted and spent == 0:
            # 旗帜每小时回复一面，恰好在这一场里回复时读数不变
            self.log.warning("打完一场旗帜读数没变（%d），可能刚好回复了一面", after)
            return
        if spent > 0:
            self.r.flags_spent += spent
        raise ArenaAnomaly(f"旗帜 {before} → {after}，预期减少 {expected}")

    def _select_first(self) -> bool:
        """选中 NPC 列表第一行，直到「挑战」按钮亮起。"""
        ctl = self.ctl
        ctl.wait_scene(NPC, timeout=30)
        for _ in range(2):
            if ctl.find("arena/npc/challenge") is not None:
                return True
            ctl.tap_rect(page.FIRST_ROW)
            if self.m._wait_for(lambda f: ctl.find("arena/npc/challenge", f), timeout=3.0) is not None:
                return True
        self.m._fail("选中第一个 NPC 后「挑战」按钮没有亮")
        return False

    def _choose_mode(self) -> Prep | None:
        """在准备界面切到要用的模式：优先快速对战，当天次数用完就用普通战斗。"""
        prep = self.m._wait_for(self._prep_probe, timeout=15.0)
        if prep is None:
            return None
        if not self._quick_exhausted:
            if prep.mode is PrepMode.BATTLE:
                prep = self._toggle(prep, PrepMode.QUICK)
            if prep.mode is PrepMode.QUICK and (prep.quick_left or 0) > 0:
                return prep
            self.log.info("本日快速对战次数已用完（读数 %s），改打普通战斗", prep.quick_left)
            self._quick_exhausted = True
        if prep.mode is PrepMode.QUICK:
            prep = self._toggle(prep, PrepMode.BATTLE)
        return prep if prep.mode is PrepMode.BATTLE else None

    def _prep_probe(self, frame: np.ndarray) -> Prep | None:
        return page.read_prep(self.vision, frame) if self.ctl.detect(frame).is_(PREP) else None

    def _toggle(self, prep: Prep, target: PrepMode) -> Prep:
        """点切换钮（快速对战 ⇄ 普通战斗），返回切换后的状态；没切过去就返回原状态。"""
        self.ctl.tap_rect(page.MODE_TOGGLE, delay=False)
        new = self.m._wait_for(lambda f: p if (p := self._prep_probe(f)) and p.mode is target else None, timeout=3.0)
        if new is None:
            self.log.warning("切换到%s没有生效", "快速对战" if target is PrepMode.QUICK else "普通战斗")
            return self.m._wait_for(self._prep_probe, timeout=3.0) or prep
        return new

    def _wait_result(self, mode: PrepMode) -> np.ndarray | None:
        """点开始后等结算界面，返回那一帧；一直停在准备界面（点击被吞）返回 None。

        普通战斗中检查自动战斗是否开启。战斗中的过场（压暗、闪白）不按返回键：返回键会打开暂停菜单。
        只有网络异常立即重试，其他弹窗持续 10 秒以上才交给内置规则。
        """
        ctl = self.ctl
        t0 = time.monotonic()
        deadline = t0 + (QUICK_TIMEOUT if mode is PrepMode.QUICK else self.cfg.arena_battle_timeout)
        self._auto_reset()
        prev_thumb = None
        popup_since = None
        while True:
            state = ctl.detect()
            now = time.monotonic()
            frame = ctl.last_frame
            thumb = thumbnail(frame)
            if prev_thumb is not None and thumb_diff(thumb, prev_thumb) >= MOVING_DIFF:
                ctl.progress()  # 战斗画面在动：正常进行，不算卡死
            prev_thumb = thumb
            if state.is_(RESULT):
                # 结算刚出现时胜利字样还在发光动画里，认不出；最多再看 VICTORY_WAIT 秒
                win = self.m._wait_for(lambda f: f if page.is_victory(self.vision, f) else None, timeout=VICTORY_WAIT)
                return frame if win is None else win
            if state.popup == POPUP_NETWORK:
                ctl.dismiss_popups(state=state)
                continue
            if state.popup == POPUP_BUY:
                ctl.dismiss_popups(state=state)  # 点取消
                raise StopArena("开始战斗时弹出了购买旗帜（旗帜不足）")
            if state.popup is not None:
                popup_since = popup_since or now
                if now - popup_since >= 10.0:
                    ctl.dismiss_popups(state=state)
                    popup_since = None
            else:
                popup_since = None
            if state.is_(BATTLE):
                self._ensure_auto(frame, now)
            elif state.is_(PREP) and now - t0 >= START_GRACE and page.read_prep(self.vision, frame) is not None:
                return None
            if now >= deadline:
                raise ItemFailed(f"等结算超时（{deadline - t0:.0f} 秒），当前：{state}")
            ctl.sleep(POLL)

    # ------------------------------------------------------------ 自动战斗

    def _auto_reset(self) -> None:
        self._auto_prev: np.ndarray | None = None
        self._auto_still_since: float | None = None
        self._auto_tapped_at = -1e9
        self._auto_taps = 0

    def _ensure_auto(self, frame: np.ndarray, now: float) -> None:
        """自动战斗图标连续 AUTO_STILL 秒不动就点一下开启（开启后图标一直旋转）。"""
        patch = page.auto_icon(self.vision, frame)
        prev, self._auto_prev = self._auto_prev, patch
        if patch is None or prev is None or page.patch_diff(patch, prev) >= AUTO_DIFF:
            self._auto_still_since = None
            return
        self._auto_still_since = self._auto_still_since or now
        if now - self._auto_still_since < AUTO_STILL or now - self._auto_tapped_at < AUTO_RETRY:
            return
        if self._auto_taps >= AUTO_MAX_TAPS:
            raise ItemFailed(f"点了 {AUTO_MAX_TAPS} 次自动战斗仍没有开启")
        m = self.vision.find(frame, "arena/battle/auto")
        if m is None:
            return
        self._auto_taps += 1
        self.log.info("自动战斗没开，点开（第 %d 次）", self._auto_taps)
        self.ctl.tap_match(m, ref="arena/battle/auto", delay=False)
        self._auto_tapped_at = now
        self._auto_still_since = None
        self._auto_prev = None

    # ------------------------------------------------------------ 补旗

    def _buy_flags(self) -> None:
        ctl = self.ctl
        before = self._flags
        dialog = self._open_buy_dialog()
        if dialog is None:
            return
        problem = self._check_dialog(dialog)
        if problem and dialog.friendship and not dialog.left_selected:
            self.log.info("补旗框没选中友情点数，点左边选项")
            ctl.tap_rect(BUY_LEFT_OPTION, delay=False)
            ctl.sleep(0.4)
            dialog = self.m._wait_for(self._buy_probe, timeout=3.0) or dialog
            problem = self._check_dialog(dialog)
        if problem:
            self._cancel_buy()
            if not dialog.friendship and not self.cfg.dry_run:
                self.m.ledger.mark_done("arena_buy", note="补旗框显示今天不能再用友情点数")
            raise StopArena(f"旗帜用完，不补旗：{problem}（{dialog}）")
        if self.cfg.dry_run:
            msg = f"用 {dialog.cost} 友情点数补 {dialog.gain} 面旗帜（持有 {dialog.hold}）"
            self.r.would.append(msg)
            self.log.info("[dry-run] 补旗框核对通过，下一步会%s；点取消", msg)
            self._cancel_buy()
            raise StopArena("dry-run 不补旗")

        self.log.info("补旗：%s", dialog)
        ctl.sleep(DIALOG_SETTLE)
        ctl.tap_match(dialog.ok, ref="arena/buy/ok", delay=False)
        after = self._verify_flags(before)
        gained = after - before
        if gained == BUY_GAIN:
            self._buys += 1
            self.r.flag_buys += 1
            self.r.friendship_spent += BUY_COST
            self.m.ledger.mark_done("arena_buy", friendship=BUY_COST)
            self.log.info("✔ 补旗成功，旗帜 %d → %d", before, after)
            self.m._ok()
            return
        if gained == 0:
            raise StopArena("点了购买但旗帜没有增加（可能今天已经补过）")
        raise ArenaAnomaly(f"补旗后旗帜 {before} → {after}，预期增加 {BUY_GAIN}")

    def _open_buy_dialog(self) -> BuyDialog | None:
        if self.cfg.dry_run and not self.cfg.arena_probe_dialogs:
            self.r.would.append("用友情点数补旗")
            self.log.info("[dry-run] 旗帜用完，下一步会打开补旗框（arena_probe_dialogs 时才实际打开并核对）")
            raise StopArena("dry-run 不补旗")
        ctl = self.ctl
        icon = ctl.wait("top/flag", timeout=5.0)
        dx, dy, w, h = FLAG_PLUS
        ctl.tap_rect(Rect(icon.rect.x + dx, icon.rect.y + dy, w, h), delay=False)
        dialog = self.m._wait_for(self._buy_probe, timeout=5.0)
        if dialog is None:
            self.m._fail(f"点旗帜旁的 + 后补旗框没出现（{ctl.last_state}）")
            self._to_npc()
        return dialog

    def _buy_probe(self, frame: np.ndarray) -> BuyDialog | None:
        state = self.ctl.detect(frame)
        return page.read_buy_dialog(self.vision, frame) if state.popup == POPUP_BUY else None

    def _check_dialog(self, d: BuyDialog) -> str | None:
        """返回不能购买的原因；可以买返回 None。"""
        keep = self.cfg.arena_friendship_keep
        if not d.friendship:
            # 今天补过后：左边变成「一天可购买1次 / N分后可购买」，游戏自动选中天空石，购买按钮仍然亮着（实测 B05）
            return "友情点数选项不可用（今天可能已经补过）"
        if d.right_selected:
            return "选中的是天空石"
        if not d.left_selected:
            return "没有选中友情点数"
        if d.cost != BUY_COST or d.gain != BUY_GAIN:
            return f"价格读数不符（预期 {BUY_COST} 换 {BUY_GAIN}）"
        if d.hold is None or d.hold - d.cost < keep:
            return f"友情点数不够（持有 {d.hold}，保底 {keep}）"
        return None

    def _cancel_buy(self) -> None:
        """点补旗框的取消，回到 NPC 列表（补旗框按规则也是点取消）。"""
        self.ctl.wait_scene(NPC, timeout=30)

    def _verify_flags(self, before: int) -> int:
        """点购买后：轮询旗帜读数直到变化（或 VERIFY_TIMEOUT 秒），返回稳定读数。"""
        ctl = self.ctl
        deadline = time.monotonic() + VERIFY_TIMEOUT
        popup_since = None
        while True:
            state = ctl.detect()
            now = time.monotonic()
            if state.is_(NPC):
                popup_since = None
                flags = self._read_flags(ctl.last_frame)
                if flags is not None and flags != before:
                    break
            else:
                popup_since = popup_since or now
                if state.popup == POPUP_NETWORK or now - popup_since >= POPUP_GRACE:
                    ctl.wait_scene(NPC, timeout=30)
                    popup_since = None
                    continue
            if now >= deadline:
                break
            ctl.sleep(POLL)
        ctl.wait_scene(NPC, timeout=30)
        return self._read_flags_stable()

    # ------------------------------------------------------------ 读数

    def _read_flags(self, frame: np.ndarray) -> int | None:
        return page.read_flags(self.vision, frame)

    def _read_flags_stable(self) -> int:
        """连续两帧读数一致才采用。"""
        ctl = self.ctl
        prev = None
        for _ in range(8):
            flags = self._read_flags(ctl.screenshot())
            if flags is not None and flags == prev:
                self._flags = flags
                return flags
            prev = flags
            ctl.sleep(0.15)
        raise ItemFailed(f"顶栏旗帜读不出或不稳定（最后一次：{prev}）")


__all__ = ["Arena", "ArenaAnomaly", "StopArena", "register"]
