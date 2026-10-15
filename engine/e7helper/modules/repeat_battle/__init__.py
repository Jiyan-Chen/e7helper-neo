"""重复刷关（讨伐）：托管战斗的结算与重开 + 手动反复刷同一关。

游戏把以前的「重复战斗」重做成了「托管战斗」：在准备界面设好份数（每份打 4 次，用行动力或生命之叶支付），
宠物在后台按最快通关记录自动打，打完后在托管框里「结算」领奖。托管在后台跑的同时还可以手动打关卡。

流程（详见 docs/reviews/B06.md）：
大厅 → 战斗 → 讨伐 → 选地下城 → 选难度 → 准备界面（或 start_here：从当前准备界面开始）
→ 托管：顶栏托管图标显示已完成就结算；没有托管就打开设置框，设份数、核对将使用的行动力和叶子后开始
→ 手动：切到普通战斗 → 战斗开始 → 战斗（检查自动战斗）→ CLEAR → 结算确认 → 重新进行 → 循环；
  每回到准备界面都看一眼托管图标，完成了就结算并重开。

安全规则：
- 手动一场 = 看到 CLEAR + 战后读数「持有行动力」的减少量不超过一场的消耗（讨伐会掉落行动力，减少量可能更小）。
  多扣立即停止，任务记为失败。不按点击次数计。
- 托管重开：设置框里「将使用」的行动力和叶子必须等于按配置算出的值（叶子不超过 auto_leaves），开始后顶栏
  行动力的减少量必须等于将使用的行动力，天空石不能变。确认框「是否开始托管战斗？」自动关闭时点取消。
- 进行中的托管框只点底部空白处关闭，绝不点「中断」。
- 补行动力：默认关闭。开启后先用叶子，再用天空石，各自不超过次数上限；点「购买」前核对选中的是要用的选项、
  价格（叶子 1 换 80、天空石 30 换 60）和持有量；购买后按行动力增加量和天空石读数差确认。补充框自动关闭时点取消。
- dry_run（默认开启）只导航、打开托管框读数（设置框会改份数，但不点开始），不点「结算」「开始」「战斗开始」「购买」。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from e7helper.core.runtime.stuck import thumb_diff, thumbnail
from e7helper.core.scene import Dismiss, Popup, Scene, SceneState
from e7helper.core.vision import normalize_text
from e7helper.modules.base import TaskModule

from . import page, stats
from .config import Hunt, RepeatBattleConfig, Tier
from .page import AutoProgress, AutoSetup, AutoState, EnergyDialog, Prep, PrepMode

MENU = "rb_menu"  # 战斗菜单（一般 / 赛季 / 事件）
HUNT = "rb_hunt"  # 讨伐：难度 + 地下城列表
PREP = "rb_prep"  # 准备战斗
BATTLE = "rb_battle"
CLEAR = "rb_clear"  # 胜利「CLEAR」，点一下继续
RESULT = "rb_result"  # 获得的道具 + 确认
AFTER = "rb_after"  # 离开 / 大厅 / 重新进行
POPUP_AUTO = "rb_auto"  # 托管进度框（进行中 / 已完成 / 已结算）
POPUP_SETUP = "rb_auto_setup"  # 托管设置框
POPUP_SETTLED = "rb_auto_settled"  # 结算完毕
POPUP_CONFIRM = "rb_auto_confirm"  # 是否开始托管战斗？
POPUP_ENERGY = "rb_energy"  # 行动力不足（购买行动力）
POPUP_NETWORK = "network"

POLL = 0.15
POPUP_GRACE = 1.0  # 弹窗先等它自己消失，超过这个时间再交给内置规则
DIALOG_WAIT = 6.0  # 点按钮后等框出现 / 消失
SETTLE_WAIT = 15.0  # 点「结算」后等「结算完毕」（中间有「结算中」）
VERIFY_TIMEOUT = 6.0  # 补充 / 开托管后等读数变化
START_GRACE = 8.0  # 点了开始后还停在准备界面这么久，认为点击被吞
UNKNOWN_POPUP = 4.0  # 点开始后出现认不出的弹窗（例如背包已满）超过这么久就停止
AUTO_REGEN = 2  # 核对时允许行动力自然回复的量
LEAF_COST, LEAF_GAIN = 1, 80
SKY_COST, SKY_GAIN = 30, 60
COUNT_TAP_WAIT = 1.5  # 点 +1 后等份数变化
AUTO_DOT_GAP = 0.6  # 判断托管是否完成时每帧间隔（3 帧跨 1.2 秒）
# 自动战斗：图标连续 AUTO_STILL 秒变化 < AUTO_DIFF 认为没开（开启后图标一直旋转；技能演出时图标会消失）
AUTO_DIFF = 3.0
AUTO_STILL = 0.6
AUTO_RETRY = 2.5
AUTO_MAX_TAPS = 4
MOVING_DIFF = 3.0
RESULT_RETRY = 2.0


class StopRepeat(Exception):
    """正常停止（次数到了、行动力用完、dry-run 等），任务仍算成功。"""


class RepeatAnomaly(RuntimeError):
    """读数与预期不符或出现认不出的情况，立即停止，任务记为失败（会保存调试截图）。"""


class RepeatBattleModule(TaskModule):
    id = "repeat_battle"
    name = "重复刷关（托管 + 手动）"
    description = "讨伐：结算并重开托管战斗；托管在后台跑的同时手动反复刷同一关，可选用叶子 / 天空石补行动力"
    config_model = RepeatBattleConfig

    def setup(self) -> None:
        if self.ctx.controller is None:
            return
        sc = self.ctl.scenes
        q = f"{self.id}:"
        for scene in (
            Scene(MENU, ("title/battle", q + "menu/hunt"), note="战斗菜单"),
            Scene(HUNT, ("title/battle", q + "hunt/header"), note="讨伐：地下城列表"),
            Scene(PREP, ("title/prep", q + "prep/auto"), note="准备战斗"),
            Scene(AFTER, (q + "after/retry", q + "after/leave"), note="战后：离开 / 大厅 / 重新进行"),
            Scene(BATTLE, (q + "battle/pause",), (q + "after/retry",), note="战斗中"),
            Scene(CLEAR, (q + "clear",), note="战斗胜利 CLEAR"),
            Scene(RESULT, (q + "result/items", q + "result/ok"), note="结算：获得的道具"),
        ):
            sc.add_scene(scene, replace=True, first=True)
        # first=True 插到最前，后加的优先判定：补充框 > 开始确认 > 结算完毕 > 设置框 > 进度框
        for popup in (
            Popup(POPUP_AUTO, (q + "auto/title",), Dismiss.at(*page.CLOSE_POINT),
                  note="托管进度框（点底部空白关闭，绝不点中断）"),
            Popup(POPUP_SETUP, (q + "auto/setup_title",), Dismiss.at(*page.CLOSE_POINT),
                  note="托管设置框（点底部空白关闭）"),
            Popup(POPUP_SETTLED, (q + "auto/settled",), Dismiss.at(*page.SETTLED_CLOSE), note="托管结算完毕"),
            Popup(POPUP_CONFIRM, (q + "auto/confirm_text", "dialog/cancel"), Dismiss.tap("dialog/cancel"),
                  note="是否开始托管战斗（自动关闭时点取消）"),
            Popup(POPUP_ENERGY, (q + "energy/title", q + "energy/cancel"), Dismiss.tap(q + "energy/cancel"),
                  note="行动力不足（自动关闭时点取消）"),
        ):
            sc.add_popup(popup, replace=True, first=True)

    # ------------------------------------------------------------ 主流程

    def run(self) -> None:
        cfg: RepeatBattleConfig = self.config
        self.run_stats = stats.RunStats(dry_run=cfg.dry_run)
        self._consecutive_failures = 0
        self._energy: int | None = None
        self._stage = ""
        mode = "dry-run（不点结算、开始和购买）" if cfg.dry_run else "实跑"
        target = "当前准备界面" if cfg.start_here else f"讨伐{cfg.hunt.value} {cfg.tier.value}"
        self.log.info("重复刷关：%s；目标 %s；托管 %s（叶子最多 %d）；手动 %s（%s 场）；补行动力 叶子 %s / 天空石 %s",
                      mode, target, "开" if cfg.auto_battle else "关", cfg.auto_leaves, "开" if cfg.manual else "关",
                      cfg.manual_runs or "不限", f"开 ×{cfg.max_leaf_refills}" if cfg.refill_leaf else "关",
                      f"开 ×{cfg.max_skystone_refills}" if cfg.refill_skystone else "关")
        try:
            self._enter()
            self.run_stats.energy_start = self._read_energy_stable()
            self.log.info("准备界面：%s，行动力 %d", self._stage, self._energy)
            if cfg.auto_battle:
                self._handle_auto()
            if not cfg.manual:
                raise StopRepeat("没有开启手动刷关")
            while True:
                self._manual_step()
        except StopRepeat as e:
            self.run_stats.stop_reason = str(e)
            self.log.info("停止：%s", e)
        except BaseException as e:
            self.run_stats.stop_reason = f"{type(e).__name__}：{e}"
            raise
        finally:
            r = self.run_stats
            r.stage = self._stage
            r.energy_end = self._energy
            r.ended = stats.now()
            stats.save(self.ctx.data_dir, r)
            self.log.info("统计：%s", r.summary())

    # ------------------------------------------------------------ 导航

    def _enter(self) -> None:
        """走到目标关卡的准备界面。"""
        cfg: RepeatBattleConfig = self.config
        ctl = self.ctl
        # 战后 / 结算界面一直有动画，先不等静止认出来；其他界面再等静止
        state = ctl.wait_scene(("lobby", MENU, HUNT, PREP, AFTER, RESULT), timeout=20, settle=False)
        if state.is_(RESULT, AFTER):
            state = self._after_to_prep(state)
        else:
            state = ctl.wait_scene(state.scene, timeout=20)
        if cfg.start_here:
            if not state.is_(PREP):
                raise StopRepeat(f"start_here 要求停在准备界面，当前：{state}")
            self._stage = " ".join(page.read_stage(self.vision, ctl.screenshot()))
            if "异界" in self._stage:
                raise StopRepeat(f"{self._stage} 消耗异界代币，暂不支持")
            return
        if state.is_(PREP):
            if self._stage_ok():
                return
            self.log.info("当前准备界面不是目标关卡（%s），返回讨伐列表", self._stage)
            state = ctl.tap_until("back", (HUNT, MENU, "lobby"))
        if state.is_("lobby"):
            self.log.info("从大厅进入战斗菜单")
            state = ctl.tap_until("lobby/battle", MENU)
        if state.is_(MENU):
            state = ctl.tap_until(f"{self.id}:menu/hunt", HUNT)
        if not state.is_(HUNT):
            raise StopRepeat(f"没有走到讨伐列表，当前：{state}")
        for attempt in range(2):
            self._select_hunt(cfg.hunt)
            ctl.wait_scene(HUNT, timeout=15)
            # 难度卡片在选中地下城后才刷新，多看几次
            card = self._wait_for(lambda f: page.find_tier(self.vision, f, cfg.tier), timeout=3.0)
            if card is None:
                raise StopRepeat(f"讨伐{cfg.hunt.value}没有「{cfg.tier.value}」难度（或没有解锁）")
            ctl.tap_until(card, PREP, timeout=30)
            if self._stage_ok():
                return
            self.log.warning("进入的关卡不对（%s），返回重选（第 %d 次）", self._stage, attempt + 1)
            ctl.tap_until("back", HUNT)
        raise StopRepeat(f"进不了 讨伐{cfg.hunt.value} {cfg.tier.value}（最后进入：{self._stage}）")

    def _stage_ok(self) -> bool:
        cfg: RepeatBattleConfig = self.config
        self.ctl.wait_scene(PREP, timeout=20)
        hunt, tier = page.read_stage(self.vision, self.ctl.screenshot())
        self._stage = f"{hunt} {tier}"
        return hunt == normalize_text(f"讨伐{cfg.hunt.value}") and tier == normalize_text(f"讨伐{cfg.tier.value}")

    def _select_hunt(self, hunt: Hunt) -> None:
        """在右侧列表里找到目标地下城并点它（选中后中间的难度卡片对应它）。找不到就向下翻，翻到底再回到顶部。"""
        ctl = self.ctl
        (x1, y1), (x2, y2) = page.HUNT_SWIPE
        for i in range(5):
            ctl.wait_scene(HUNT, timeout=15)
            rect = page.find_hunt(self.vision, ctl.last_frame, hunt)
            if rect is not None:
                self.log.info("选择 讨伐%s", hunt.value)
                ctl.tap_rect(rect)
                ctl.sleep(0.8)  # 列表滚动、难度卡片刷新
                return
            if i < 2:
                ctl.swipe(x1, y1, x2, y2, 0.5)  # 看下面的
            else:
                ctl.swipe(x2, y2, x1, y1, 0.5)  # 回到上面
            ctl.sleep(0.8)
        raise StopRepeat(f"讨伐列表里没找到「讨伐{hunt.value}」")

    def _after_to_prep(self, state: SceneState) -> SceneState:
        """在结算 / 战后界面时回到准备界面（「重新进行」只是回到准备界面，不消耗行动力）。"""
        ctl = self.ctl
        q = f"{self.id}:"
        if state.is_(RESULT):
            state = ctl.tap_until(q + "result/ok", AFTER, retry_after=RESULT_RETRY, max_taps=5, settle=False)
        return ctl.tap_until(q + "after/retry", PREP, timeout=30, retry_after=3.0)

    # ------------------------------------------------------------ 托管

    def _handle_auto(self) -> None:
        """在准备界面：托管完成了就结算，没有托管就重开；进行中什么都不做。"""
        cfg: RepeatBattleConfig = self.config
        ctl = self.ctl
        ctl.wait_scene(PREP, timeout=30)
        st = self._auto_icon_state()
        if st is AutoState.RUNNING:
            self.log.info("托管战斗进行中")
            return
        if st is AutoState.DONE:
            prog = self._open_auto_dialog()
            if not isinstance(prog, AutoProgress) or prog.state is not AutoState.DONE:
                self._close_dialog()
                self._fail(f"托管图标显示已完成，但托管框是 {prog}")
                return
            if cfg.dry_run:
                msg = f"结算托管（{prog.stage} {prog.done}/{prog.total}）并在 {self._stage} 重开"
                self.run_stats.would.append(msg)
                self.log.info("[dry-run] 下一步会%s；关闭托管框", msg)
                self._close_dialog()
                return
            self._claim(prog)
        self._start_auto()

    def _auto_icon_state(self) -> AutoState:
        """顶栏托管图标的状态。隔 AUTO_DOT_GAP 秒看 3 帧：都没有图标才是 NONE；
        都够红、且第一帧和最后一帧红点位置重合才是 DONE（进行中的光弧会扫过红点位置，但不会停住）；
        其余当作进行中（什么都不做最安全）。
        """
        states, dots = [], []
        for i in range(3):
            if i:
                self.ctl.sleep(AUTO_DOT_GAP)
            frame = self.ctl.screenshot()
            states.append(page.auto_state(self.vision, frame))
            dots.append(page.auto_dot(self.vision, frame))
        if all(s is AutoState.NONE for s in states):
            return AutoState.NONE
        if all(s is AutoState.DONE for s in states) and page.dots_match(dots[0], dots[-1]):
            return AutoState.DONE
        return AutoState.RUNNING

    def _open_auto_dialog(self) -> AutoProgress | AutoSetup | None:
        """点准备界面的「托管战斗」，返回进度框或设置框的内容；没打开（例如无记录）返回 None。"""
        ctl = self.ctl
        ctl.wait_scene(PREP, timeout=20)
        ctl.tap_template(f"{self.id}:prep/auto", timeout=5)
        return self._wait_for(lambda f: page.read_auto_progress(self.vision, f) or page.read_auto_setup(self.vision, f),
                              timeout=DIALOG_WAIT)

    def _close_dialog(self) -> None:
        """托管框（进度 / 设置）点底部空白处关闭，回到准备界面。"""
        ctl = self.ctl
        state = ctl.detect()
        if state.popup in (POPUP_AUTO, POPUP_SETUP):
            ctl.tap(*page.CLOSE_POINT)
            self._wait_popup_gone(state.popup)  # 淡出时不要再点一次
        ctl.wait_scene(PREP, timeout=20)

    def _claim(self, prog: AutoProgress) -> None:
        """结算已完成的托管：结算 → 结算完毕（点击关闭）→ 关闭。"""
        ctl = self.ctl
        q = f"{self.id}:"
        frame = ctl.screenshot()
        if self.vision.find(frame, q + "auto/abort") is not None or self.vision.find(frame, q + "auto/settle") is None:
            raise RepeatAnomaly("准备点结算时托管框不是已完成状态")
        self.log.info("结算托管：%s %s/%s", prog.stage, prog.done, prog.total)
        ctl.tap_match(prog.button, ref=q + "auto/settle", delay=False)
        if self._wait_for(lambda f: True if self.vision.find(f, q + "auto/settled") else None,
                          timeout=SETTLE_WAIT) is None:
            raise RepeatAnomaly(f"点结算后没有出现「结算完毕」（{ctl.last_state}）")
        ctl.sleep(0.5)
        ctl.tap(*page.SETTLED_CLOSE)
        closed = self._wait_for(lambda f: p if (p := page.read_auto_progress(self.vision, f)) and
                                p.state is AutoState.NONE else None, timeout=DIALOG_WAIT)
        if closed is None:
            raise RepeatAnomaly(f"结算完毕后托管框没有变成「关闭」（{ctl.last_state}）")
        ctl.tap_match(closed.button, ref=q + "auto/close", delay=False)
        self._wait_popup_gone(POPUP_AUTO)  # 淡出时交给弹窗规则会再点一次底部（B06 实跑发现）
        ctl.wait_scene(PREP, timeout=20)
        if self._auto_icon_state() is not AutoState.NONE:
            raise RepeatAnomaly("结算后顶栏仍有托管图标")
        self.run_stats.autos.append(stats.AutoRun("claimed", prog.stage, prog.done))
        self.log.info("✔ 托管已结算（%s 次）", prog.done)
        self._ok()

    def _start_auto(self) -> None:
        """打开托管设置框，按配置设份数并核对，然后开始（dry-run 只核对）。"""
        cfg: RepeatBattleConfig = self.config
        ctl = self.ctl
        ctl.wait_scene(PREP, timeout=20)
        prep = self._battle_mode()
        if prep is None:
            self._fail("准备界面没切到普通战斗，看不到有没有通关记录")
            return
        if prep.no_record:
            msg = f"{self._stage} 没有通关记录（无记录），开不了托管；先手动通关一次"
            self.log.warning(msg)
            if cfg.dry_run:
                self.run_stats.would.append(msg)
            return
        energy_before = self._read_energy_stable()
        sky_before = self._read_skystone_stable()
        setup = self._open_auto_dialog()
        if not isinstance(setup, AutoSetup):
            if setup is not None:
                self._close_dialog()
            self._fail(f"托管设置框没有打开（{setup or ctl.last_state}）")
            return
        if setup.run_energy is None or setup.energy is None or setup.leaves is None:
            self._close_dialog()
            self._fail(f"托管设置框读数不全：{setup}")
            return
        count, use_energy, use_leaves = page.plan_auto(setup.energy, setup.run_energy,
                                                       min(cfg.auto_leaves, setup.leaves), cfg.auto_prefer_energy,
                                                       cfg.auto_max_units)
        if count == 0:
            self._close_dialog()
            msg = (f"行动力 {setup.energy} 不够 1 份（{setup.run_energy * page.RUNS_PER_UNIT}），"
                   f"也不允许用叶子（auto_leaves={cfg.auto_leaves}），不开托管")
            self.log.info(msg)
            if cfg.dry_run:
                self.run_stats.would.append(msg)
            return
        setup = self._configure_setup(setup, count)
        problem = self._check_setup(setup, count, use_energy, use_leaves)
        if problem:
            self._close_dialog()
            raise StopRepeat(f"不开托管：{problem}（{setup}）")
        runs = count * page.RUNS_PER_UNIT
        msg = f"在 {self._stage} 开托管 {count} 份（约 {runs} 次），用行动力 {use_energy}、叶子 {use_leaves}"
        if cfg.dry_run:
            self.run_stats.would.append(msg)
            self.log.info("[dry-run] 托管设置核对通过，下一步会%s；关闭设置框", msg)
            self._close_dialog()
            return
        self.log.info("开托管：%s", setup)
        ctl.tap_match(setup.start, ref=f"{self.id}:auto/start", delay=False)
        confirm = self._wait_for(lambda f: ctl.find("dialog/confirm", f) if ctl.detect(f).popup == POPUP_CONFIRM
                                 else None, timeout=DIALOG_WAIT)
        if confirm is None:
            raise RepeatAnomaly(f"点开始后没有出现「是否开始托管战斗」（{ctl.last_state}）")
        ctl.sleep(0.2)
        ctl.tap_match(confirm, ref="dialog/confirm", delay=False)
        # 确认框淡出期间不能交给弹窗规则（会点取消）：等它自己消失
        self._wait_popup_gone(POPUP_CONFIRM)
        ctl.wait_scene(PREP, timeout=20)
        if self._wait_for(lambda f: True if page.auto_state(self.vision, f) is AutoState.RUNNING else None,
                          timeout=VERIFY_TIMEOUT) is None:
            raise RepeatAnomaly("确认开始后顶栏没有出现进行中的托管图标")
        energy_after = self._read_energy_stable()
        sky_after = self._read_skystone_stable()
        spent = energy_before - energy_after
        if not (use_energy - AUTO_REGEN <= spent <= use_energy) or sky_after != sky_before:
            raise RepeatAnomaly(f"开托管后行动力 {energy_before} → {energy_after}（预期减少 {use_energy}），"
                                f"天空石 {sky_before} → {sky_after}")
        r = self.run_stats
        r.autos.append(stats.AutoRun("started", self._stage, runs, spent, use_leaves))
        r.leaves_spent += use_leaves
        self.log.info("✔ 托管已开始：%s；行动力 %d → %d", msg, energy_before, energy_after)
        self._ok()

    def _configure_setup(self, setup: AutoSetup, count: int) -> AutoSetup:
        """设置框：按配置勾选「优先使用持有的行动力」，把份数调到 count，返回调整后的读数。"""
        cfg: RepeatBattleConfig = self.config
        ctl = self.ctl
        want_checked = cfg.auto_prefer_energy and setup.check_enabled
        if setup.checked != want_checked and setup.check_enabled:
            ctl.tap_rect(page.SETUP_CHECK, delay=False)
            setup = self._wait_for(lambda f: s if (s := self._setup_probe(f)) and s.checked == want_checked else None,
                                   timeout=COUNT_TAP_WAIT) or self._read_setup()
        if setup.count != 1:
            ctl.tap_rect(page.SETUP_MIN, delay=False)
            setup = self._wait_for(lambda f: s if (s := self._setup_probe(f)) and s.count == 1 else None,
                                   timeout=COUNT_TAP_WAIT) or self._read_setup()
        misses = 0
        while setup.count is not None and setup.count != count and misses < 5:
            before = setup.count
            ctl.tap_rect(page.SETUP_PLUS if before < count else page.SETUP_MINUS, delay=False)
            new = self._wait_for(lambda f: s if (s := self._setup_probe(f)) and s.count != before else None,
                                 timeout=COUNT_TAP_WAIT)
            if new is None:
                misses += 1
                continue
            setup = new
        ctl.sleep(0.3)  # 下方「将使用」的数字跟着份数变化
        return self._read_setup()

    def _setup_probe(self, frame: np.ndarray) -> AutoSetup | None:
        return page.read_auto_setup(self.vision, frame)

    def _read_setup(self) -> AutoSetup:
        """连续两帧读数一致的设置框。"""
        prev = None
        for _ in range(8):
            s = self._setup_probe(self.ctl.screenshot())
            if s is not None and prev is not None and (s.count, s.use_energy, s.use_leaves, s.checked) == \
                    (prev.count, prev.use_energy, prev.use_leaves, prev.checked):
                return s
            prev = s
            self.ctl.sleep(0.15)
        if prev is None:
            raise RepeatAnomaly(f"托管设置框不见了（{self.ctl.last_state}）")
        return prev

    def _check_setup(self, s: AutoSetup, count: int, use_energy: int, use_leaves: int) -> str | None:
        cfg: RepeatBattleConfig = self.config
        if s.count != count:
            return f"份数没调到 {count}"
        if s.use_energy != use_energy or s.use_leaves != use_leaves:
            return f"将使用的行动力 / 叶子不符（预期 {use_energy} / {use_leaves}）"
        if s.use_leaves is None or s.use_leaves > cfg.auto_leaves:
            return f"将使用叶子 {s.use_leaves}，超过上限 {cfg.auto_leaves}"
        if s.checked != (cfg.auto_prefer_energy and s.check_enabled):
            return "「优先使用持有的行动力」勾选状态不对"
        return None

    # ------------------------------------------------------------ 手动刷关

    def _manual_step(self) -> None:
        cfg: RepeatBattleConfig = self.config
        if cfg.manual_runs and len(self.run_stats.battles) >= cfg.manual_runs:
            raise StopRepeat(f"手动已打 {cfg.manual_runs} 场")
        prep = self._ready_prep()
        if prep is None:
            return
        if not prep.enough:
            self._refill(prep)
            return
        if cfg.dry_run:
            msg = f"手动刷 {self._stage}：行动力 {prep.held}，每场 {prep.cost}，够打 {prep.held // max(1, prep.cost)} 场"
            self.run_stats.would.append(msg)
            self.log.info("[dry-run] 下一步会%s；不点战斗开始", msg)
            raise StopRepeat("dry-run 停在准备界面")
        self._battle(prep)

    def _ready_prep(self) -> Prep | None:
        """回到准备界面后：托管完成了就处理；切到普通战斗；返回准备界面读数。"""
        cfg: RepeatBattleConfig = self.config
        ctl = self.ctl
        ctl.wait_scene(PREP, timeout=30)
        if cfg.auto_battle and not cfg.dry_run and self._auto_icon_state() is AutoState.DONE:
            self._handle_auto()
        prep = self._battle_mode()
        if prep is None or prep.cost is None or prep.held is None:
            self._fail(f"准备界面没切到普通战斗或读不出行动力（{prep}）")
            return None
        return prep

    def _battle_mode(self) -> Prep | None:
        """准备界面切到普通战斗（游戏每次回到准备界面默认是快速战斗）；切不过去返回 None。

        「无记录」只在普通战斗模式显示，判断能不能开托管前也要先切过来。
        """
        ctl = self.ctl
        prep = self._wait_for(self._prep_probe, timeout=10)
        if prep is not None and prep.mode is PrepMode.QUICK:
            ctl.tap_rect(page.MODE_TOGGLE, delay=False)
            prep = self._wait_for(lambda f: p if (p := self._prep_probe(f)) and p.mode is PrepMode.BATTLE else None,
                                  timeout=3.0)
        return prep if prep is not None and prep.mode is PrepMode.BATTLE else None

    def _prep_probe(self, frame: np.ndarray) -> Prep | None:
        return page.read_prep(self.vision, frame) if self.ctl.detect(frame).is_(PREP) else None

    def _battle(self, prep: Prep) -> None:
        ctl = self.ctl
        before = prep.held
        n = len(self.run_stats.battles) + 1
        self.log.info("开始第 %d 场：%s，行动力 %d（每场 %d）", n, self._stage, before, prep.cost)
        t0 = time.monotonic()
        ctl.tap_match(prep.button, ref=f"{self.id}:prep/start", delay=False)
        if not self._wait_clear():
            self._fail("点战斗开始后没有开始战斗")
            self._check_spent(before, self._read_energy_stable(), 0)
            return
        self._finish_battle()
        after = self._read_after_stable()
        self._check_spent(before, after, prep.cost)
        seconds = time.monotonic() - t0
        r = self.run_stats
        r.battles.append(stats.Battle(self._stage, before, after, round(seconds, 1)))
        self.log.info("✔ 第 %d 场完成，用时 %.0f 秒，行动力 %d → %d", n, seconds, before, after)
        self._ok()
        ctl.tap_until(f"{self.id}:after/retry", PREP, timeout=30, retry_after=3.0)

    def _check_spent(self, before: int, after: int, cost: int) -> None:
        """一场最多扣 cost（讨伐会掉落行动力，实际减少量可能更小甚至增加）；cost=0 表示没开打，不应该减少。"""
        self._energy = after
        spent = before - after
        if spent > cost:
            raise RepeatAnomaly(f"行动力 {before} → {after}，减少 {spent}，超过一场的消耗 {cost}")
        self.run_stats.energy_spent += max(0, spent)

    def _wait_clear(self) -> bool:
        """点开始后等到 CLEAR / 结算，返回 True；一直停在准备界面（点击被吞）返回 False。

        战斗中检查自动战斗；不按返回键（会打开暂停菜单）。只有网络异常立即重试；
        还没进战斗就出现认不出的弹窗（例如背包已满）持续 UNKNOWN_POPUP 秒就停止。
        """
        cfg: RepeatBattleConfig = self.config
        ctl = self.ctl
        t0 = time.monotonic()
        deadline = t0 + cfg.battle_timeout
        self._auto_reset()
        prev_thumb = None
        popup_since = None
        fought = False
        while True:
            state = ctl.detect()
            now = time.monotonic()
            frame = ctl.last_frame
            thumb = thumbnail(frame)
            moving = prev_thumb is not None and thumb_diff(thumb, prev_thumb) >= MOVING_DIFF
            if moving:
                ctl.progress()
            prev_thumb = thumb
            if state.is_(CLEAR, RESULT, AFTER):
                return True
            if state.popup == POPUP_NETWORK:
                ctl.dismiss_popups(state=state)
                continue
            if state.popup == POPUP_ENERGY:
                ctl.dismiss_popups(state=state)  # 点取消
                raise StopRepeat("点战斗开始时弹出了「行动力不足」")
            if state.popup is not None:
                # 过场（压暗的演出）在动，不算弹窗；静止的认不出的框才计时
                popup_since = None if moving else (popup_since or now)
                if popup_since is not None and not fought and now - popup_since >= UNKNOWN_POPUP:
                    raise RepeatAnomaly(f"点战斗开始后出现认不出的弹窗（可能背包已满）：{state}")
                if popup_since is not None and now - popup_since >= 10.0:
                    ctl.dismiss_popups(state=state)
                    popup_since = None
            else:
                popup_since = None
            if state.is_(BATTLE):
                fought = True
                self._ensure_auto(frame, now)
            elif state.is_(PREP) and not fought and now - t0 >= START_GRACE:
                return False
            if now >= deadline:
                raise RepeatAnomaly(f"等战斗结束超时（{cfg.battle_timeout:.0f} 秒），当前：{state}")
            ctl.sleep(POLL)

    def _finish_battle(self) -> None:
        """CLEAR（点一下继续）→ 结算（确认）→ 战后界面。确认不消耗东西，没反应就补点。"""
        ctl = self.ctl
        state = ctl.detect()
        if not state.is_(RESULT, AFTER):
            state = ctl.tap_until(page.CLEAR_TAP, (RESULT, AFTER), timeout=30, retry_after=RESULT_RETRY, max_taps=6,
                                  settle=False)
        if state.is_(RESULT):
            ctl.tap_until(f"{self.id}:result/ok", AFTER, timeout=30, retry_after=RESULT_RETRY, max_taps=5,
                          settle=False)

    def _read_after_stable(self) -> int:
        """战后界面「重新进行」旁的持有行动力，连续两帧一致才采用。"""
        prev = None
        for _ in range(8):
            frac = page.read_after_energy(self.vision, self.ctl.screenshot())
            held = None if frac is None else frac[1]
            if held is not None and held == prev:
                return held
            prev = held
            self.ctl.sleep(0.15)
        raise RepeatAnomaly(f"战后界面的行动力读不出或不稳定（最后一次：{prev}）")

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
            raise RepeatAnomaly(f"点了 {AUTO_MAX_TAPS} 次自动战斗仍没有开启")
        m = self.vision.find(frame, "battle/auto")
        if m is None:
            return
        self._auto_taps += 1
        self.log.info("自动战斗没开，点开（第 %d 次）", self._auto_taps)
        self.ctl.tap_match(m, ref=f"{self.id}:battle/auto", delay=False)
        self._auto_tapped_at = now
        self._auto_still_since = None
        self._auto_prev = None

    # ------------------------------------------------------------ 补行动力

    def _refill(self, prep: Prep) -> None:
        """行动力不够一场：按配置用叶子 / 天空石补一次（在「行动力不足」框里买），然后回到循环。"""
        cfg: RepeatBattleConfig = self.config
        ctl = self.ctl
        r = self.run_stats
        leaf_ok = cfg.refill_leaf and r.leaf_refills < cfg.max_leaf_refills
        sky_ok = cfg.refill_skystone and r.skystone_refills < cfg.max_skystone_refills
        short = f"行动力不够（{prep.held}/{prep.cost}）"
        if not (leaf_ok or sky_ok):
            used = f"，本次已补 叶子 {r.leaf_refills} 次 / 天空石 {r.skystone_refills} 次" if \
                (r.leaf_refills or r.skystone_refills) else ""
            raise StopRepeat(f"{short}{used}")
        top = self._read_energy_stable()
        if top >= prep.cost:
            self._fail(f"按钮上的行动力 {prep.held} 和顶栏 {top} 不一致")
            return
        if cfg.dry_run and not cfg.probe_dialogs:
            msg = f"{short}，用{'叶子' if leaf_ok else '天空石'}补行动力"
            r.would.append(msg)
            self.log.info("[dry-run] 下一步会%s（probe_dialogs 时才实际打开补充框核对）", msg)
            raise StopRepeat("dry-run 不补行动力")
        sky_before = self._read_skystone_stable()
        # 行动力不够时「战斗开始」只会弹出「行动力不足」框（按钮读数和顶栏读数都已核对不够）
        ctl.tap_match(prep.button, ref=f"{self.id}:prep/start", delay=False)
        dialog = self._wait_for(self._energy_probe, timeout=DIALOG_WAIT)
        if dialog is None:
            raise RepeatAnomaly(f"行动力不够时点战斗开始，没有出现「行动力不足」框（{ctl.last_state}）")
        use_leaf = leaf_ok and dialog.leaf and (dialog.leaf_hold or 0) >= LEAF_COST
        if not use_leaf and not sky_ok:
            self._cancel_energy()
            raise StopRepeat(f"{short}，叶子不够（持有 {dialog.leaf_hold}），也没开天空石补充")
        dialog = self._select_option(dialog, use_leaf)
        problem = self._check_energy_dialog(dialog, use_leaf)
        if problem:
            self._cancel_energy()
            raise StopRepeat(f"不补行动力：{problem}（{dialog}）")
        what = "叶子" if use_leaf else "天空石"
        cost, gain = (LEAF_COST, LEAF_GAIN) if use_leaf else (SKY_COST, SKY_GAIN)
        if cfg.dry_run:
            msg = f"用 {cost} {what}补 {gain} 行动力（{dialog}）"
            r.would.append(msg)
            self.log.info("[dry-run] 补充框核对通过，下一步会%s；点取消", msg)
            self._cancel_energy()
            raise StopRepeat("dry-run 不补行动力")
        self.log.info("补行动力：%s", dialog)
        ctl.sleep(0.15)
        ctl.tap_match(dialog.buy, ref=f"{self.id}:energy/buy", delay=False)
        self._wait_popup_gone(POPUP_ENERGY)  # 淡出期间不能交给弹窗规则（会点取消）
        after = self._verify_refill(top, gain)
        sky_after = self._read_skystone_stable()
        gained = after - top
        sky_spent = sky_before - sky_after
        if not (gain <= gained <= gain + AUTO_REGEN) or sky_spent != (0 if use_leaf else SKY_COST):
            raise RepeatAnomaly(f"用{what}补行动力后：行动力 {top} → {after}（预期 +{gain}），"
                                f"天空石 {sky_before} → {sky_after}")
        if use_leaf:
            r.leaf_refills += 1
            r.leaves_spent += LEAF_COST
        else:
            r.skystone_refills += 1
            r.skystone_spent += sky_spent
        self.log.info("✔ 用%s补了行动力：%d → %d", what, top, after)
        self._ok()

    def _energy_probe(self, frame: np.ndarray) -> EnergyDialog | None:
        return page.read_energy_dialog(self.vision, frame) if self.ctl.detect(frame).popup == POPUP_ENERGY else None

    def _select_option(self, dialog: EnergyDialog, leaf: bool) -> EnergyDialog:
        """选中要用的付款选项（左：叶子，右：天空石），返回选中后的读数。"""
        if (leaf and dialog.left_selected and not dialog.right_selected) or \
                (not leaf and dialog.right_selected and not dialog.left_selected):
            return dialog
        self.ctl.tap_rect(page.LEFT_OPTION if leaf else page.RIGHT_OPTION, delay=False)
        self.ctl.sleep(0.3)
        want = (lambda d: d.left_selected and not d.right_selected) if leaf else \
            (lambda d: d.right_selected and not d.left_selected)
        return self._wait_for(lambda f: d if (d := self._energy_probe(f)) and want(d) else None,
                              timeout=3.0) or self._wait_for(self._energy_probe, timeout=3.0) or dialog

    def _check_energy_dialog(self, d: EnergyDialog, leaf: bool) -> str | None:
        """返回不能购买的原因；可以买返回 None。"""
        if leaf:
            if not d.leaf:
                return "左边不是生命之叶选项"
            if not d.left_selected or d.right_selected:
                return "选中的不是生命之叶"
            if d.leaf_cost != LEAF_COST or d.leaf_gain != LEAF_GAIN:
                return f"叶子价格读数不符（预期 {LEAF_COST} 换 {LEAF_GAIN}）"
            if d.leaf_hold is None or d.leaf_hold < LEAF_COST:
                return f"叶子不够（持有 {d.leaf_hold}）"
            return None
        if not d.skystone:
            return "右边不是天空石选项"
        if not d.right_selected or d.left_selected:
            return "选中的不是天空石"
        if d.sky_cost != SKY_COST or d.sky_gain != SKY_GAIN:
            return f"天空石价格读数不符（预期 {SKY_COST} 换 {SKY_GAIN}）"
        keep = self.config.skystone_keep
        if d.sky_hold is None or d.sky_hold - SKY_COST < keep:
            return f"天空石不够（持有 {d.sky_hold}，保底 {keep}）"
        return None

    def _cancel_energy(self) -> None:
        """点「行动力不足」框的取消（按弹窗规则），回到准备界面。"""
        self.ctl.wait_scene(PREP, timeout=30)

    def _verify_refill(self, before: int, gain: int) -> int:
        """点购买后：等框关闭、回到准备界面，轮询顶栏行动力直到变化（或 VERIFY_TIMEOUT 秒），返回稳定读数。"""
        ctl = self.ctl
        deadline = time.monotonic() + VERIFY_TIMEOUT
        popup_since = None
        while True:
            state = ctl.detect()
            now = time.monotonic()
            if state.is_(PREP):
                popup_since = None
                energy = page.read_energy(self.vision, ctl.last_frame)
                if energy is not None and energy != before:
                    break
            elif state.is_(BATTLE):
                raise RepeatAnomaly("补行动力后游戏直接开始了战斗（没见过，停止核对）")
            else:
                popup_since = popup_since or now
                if state.popup == POPUP_NETWORK or now - popup_since >= POPUP_GRACE:
                    ctl.wait_scene(PREP, timeout=30)
                    popup_since = None
                    continue
            if now >= deadline:
                break
            ctl.sleep(POLL)
        ctl.wait_scene(PREP, timeout=30)
        return self._read_energy_stable()

    # ------------------------------------------------------------ 读数 / 等待 / 计数

    def _read_stable(self, read: Callable[[np.ndarray], int | None], what: str) -> int:
        ctl = self.ctl
        prev = None
        for _ in range(8):
            value = read(ctl.screenshot())
            if value is not None and value == prev:
                return value
            prev = value
            ctl.sleep(0.15)
        raise RepeatAnomaly(f"顶栏{what}读不出或不稳定（最后一次：{prev}）")

    def _read_energy_stable(self) -> int:
        """顶栏行动力，连续两帧一致才采用（数字有滚动动画）。"""
        self._energy = self._read_stable(lambda f: page.read_energy(self.vision, f), "行动力")
        return self._energy

    def _read_skystone_stable(self) -> int:
        return self._read_stable(lambda f: page.read_skystone(self.vision, f), "天空石")

    def _wait_popup_gone(self, popup: str) -> None:
        """点了弹窗的确认 / 购买 / 关闭之后，等它自己消失（不交给弹窗规则，避免在淡出时又点一次）。"""
        if self._wait_for(lambda f: True if self.ctl.detect(f).popup != popup else None,
                          timeout=DIALOG_WAIT) is None:
            raise RepeatAnomaly(f"点了 {popup} 的按钮后它一直没有消失")

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

    def _ok(self) -> None:
        self._consecutive_failures = 0
        self.ctl.progress()

    def _fail(self, msg: str) -> None:
        self.run_stats.failures += 1
        self._consecutive_failures += 1
        n, limit = self._consecutive_failures, self.config.max_failures
        self.log.warning("失败（连续 %d/%d）：%s", n, limit, msg)
        if n >= limit:
            raise StopRepeat(f"连续失败 {n} 次，最后一次：{msg}")


__all__ = ["Hunt", "RepeatAnomaly", "RepeatBattleConfig", "RepeatBattleModule", "StopRepeat", "Tier"]
