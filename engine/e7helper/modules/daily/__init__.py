"""日常收取：邮件（只领快过期的）、精灵之森（领取 + 照料）、誓约召唤的免费次数、商店日常购买、竞技场 NPC。

五项各有开关，按 邮件 → 精灵之森 → 誓约召唤 → 商店 → 竞技场 的顺序做，每项做完回到大厅。从大厅开始（也能从这几项的界面开始）。
流程和核对规则详见 docs/reviews/B07.md；竞技场（B05 的 `arena_npc` 模块，B12 并入）见 arena.py 和 docs/reviews/B05.md；
商店（B12b）见 shop.py 和 docs/reviews/B12b.md。

安全规则：
- 只有画面核对通过才计数：邮件 = 底部邮件数减少 1；精灵之森 = 卡片从「领取奖励」变回倒计时；
  照料 = 「照料(n/3)」的 n 加 1；召唤 = 看到召唤结果、回到誓约页后顶栏货币区域画面不变。
- 誓约召唤只点显示「免费」的按钮（模板带亮度校验）；召唤结果页只点「返回」，绝不点「再召唤一次」。
  点了之后顶栏货币变了、或剩余免费次数没有按预期减少，立即停止，任务记为失败。
- 邮件只领剩余时间小于 mail_max_hours（默认 24 小时）的，逐封点「领取」，绝不点「全部领取」；
  列表必须是按剩余时间排序（左下角显示「剩余时间」），否则不领。有些邮件点领取后会弹出详情框，
  框里的剩余时间和那一行一致才点「收信」。
- dry_run（默认开启）只导航和识别，不点领取、照料、召唤、开始战斗、购买。
- 按天记账（ledger.json）只用来省导航：誓约召唤当天用完就不再进去；精灵之森按倒计时决定下次什么时候进去。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import numpy as np

from e7helper.core.runtime.stuck import thumb_diff, thumbnail
from e7helper.core.scene import Dismiss, Popup, Scene
from e7helper.modules.base import ModuleTimer, TaskModule

from . import arena as arena_mod
from . import ledger as ledger_mod
from . import page, stats
from . import shop as shop_mod
from .config import DailyConfig
from .errors import DailyAnomaly, ItemFailed, StopItem
from .ledger import Ledger
from .page import Card, Covenant

LOBBY = "lobby"
SANCTUARY = "sanctuary"  # 内置场景
MAIL = "daily_mail"
FOREST = "daily_forest"
SUMMON = "daily_summon"  # 召唤页（选中的不是誓约召唤）
COVENANT = "daily_covenant"  # 召唤页，选中誓约召唤
ANIM = "daily_summon_anim"  # 召唤动画（右上有「跳过」）
HERO = "daily_summon_hero"  # 召唤到的英雄展示（「下一页」）
RESULTS = "daily_summon_results"  # 召唤结果（左下「返回」）
POPUP_FOREST = "daily_forest_reward"  # 精灵之森领取后的奖励框（「点击关闭」）
POPUP_MAIL = "daily_mail_detail"  # 有些邮件点「领取」后先弹出详情框，要再点「收信」
POPUP_NETWORK = "network"
KNOWN = (LOBBY, SANCTUARY, MAIL, FOREST, SUMMON, COVENANT, RESULTS) + arena_mod.SCENES + shop_mod.SCENES

POLL = 0.15
STILL_DIFF = 2.0  # 弹窗 / 结果页完全显示：连续两帧缩略图差小于这个值
POPUP_WAIT = 5.0  # 等弹窗出现 / 消失
MAIL_WAIT = 5.0  # 点了领取后等邮件数变化
TOAST_WAIT = 1.5  # 领取邮件后顶部的物品提示约 2 秒淡出，等一会再扫描
SUMMON_TIMEOUT = 90.0  # 点免费召唤到召唤结果的最长时间（实测十连约 13 秒，有跳过）
SUMMON_EATEN = 8.0  # 点了召唤后还停在誓约页这么久，认为点击被吞
SKIP_INTERVAL = 1.5  # 「跳过」/「下一页」两次点击的最小间隔
UNKNOWN_LIMIT = 10.0  # 召唤过程中认不出的画面持续静止这么久就停止
MOVING_DIFF = 3.0
RESULTS_RETRY = 2.0  # 召唤结果的「返回」入场动画期间点了可能被吞


class DailyModule(TaskModule):
    id = "daily"
    name = "日常收取"
    description = "每天要做的事一键做完：邮件、精灵之森、誓约免费召唤、商店、竞技场"
    config_model = DailyConfig

    def setup(self) -> None:
        if self.ctx.controller is None:
            return
        sc = self.ctl.scenes
        q = f"{self.id}:"
        for scene in (
            Scene(MAIL, ("title/mail", q + "mail/claim_all"), note="邮件"),
            Scene(FOREST, ("title/forest",), note="精灵之森"),
            Scene(COVENANT, ("title/summon", q + "summon/wishlist"), note="召唤：誓约召唤"),
            Scene(SUMMON, ("title/summon",), (q + "summon/wishlist",), note="召唤（其他召唤）"),
            # 十连的结果页有「召唤结果」标题；单抽的结果是一张英雄 / 神器卡片，只有左下「返回」（B07 实跑）
            Scene(RESULTS, (q + "summon/back",), note="召唤结果（十连列表 / 单抽卡片）"),
            Scene(HERO, (q + "summon/next",), note="召唤到的英雄展示"),
            Scene(ANIM, (q + "summon/skip",), (q + "summon/next",), note="召唤动画"),
        ):
            sc.add_scene(scene, replace=True, first=True)
        # 「点击关闭」在别的弹窗里也有（竞技场战斗记录、托管结算完毕），所以要求背景是精灵之森
        sc.add_popup(Popup(POPUP_MAIL, ("title/mail", q + "mail/receive"), Dismiss.tap(q + "mail/detail_close"),
                           note="邮件详情（自动关闭时点「点击关闭」，不收信）"), replace=True, first=True)
        sc.add_popup(Popup(POPUP_FOREST, ("title/forest", q + "forest/close"), Dismiss.tap(q + "forest/close"),
                           note="精灵之森领取奖励（点击关闭）"), replace=True, first=True)
        arena_mod.register(sc, q)
        shop_mod.register(sc, q)

    # ------------------------------------------------------------ 计时与调度（B08）

    @classmethod
    def timers(cls, data_dir: Path) -> list[ModuleTimer]:
        lg = Ledger.open(data_dir, clock=lambda: ledger_mod.utcnow())
        now = lg.clock()
        forest_note = "" if lg.forest_next else "下次运行时查看"
        if lg.forest_next and lg.forest_next <= now:
            forest_note = "已到时间"
        return [
            ModuleTimer("reset", "每日重置", ledger_mod.next_reset(now)),
            ModuleTimer("weekly", "每周重置", ledger_mod.next_week_reset(now)),
            ModuleTimer("forest", "精灵之森", lg.forest_next, forest_note),
            ModuleTimer("covenant", "誓约免费召唤", None, "今天已用完" if lg.is_done("covenant") else "今天还没用完"),
        ]

    @classmethod
    def next_due(cls, config: DailyConfig, data_dir: Path, last_success: datetime | None) -> datetime | None:
        """持续收菜：本游戏日还没成功跑过就马上跑；之后等下一次重置，或精灵之森到时间（取较早的）。"""
        lg = Ledger.open(data_dir, clock=lambda: ledger_mod.utcnow())
        now = lg.clock()
        if last_success is None or ledger_mod.game_day(last_success) != ledger_mod.game_day(now):
            return now
        due = [ledger_mod.next_reset(now)]
        # forest_next 早于上次成功运行，说明上次没更新它（例如这一项失败了），不作数
        if config.forest and lg.forest_next is not None and lg.forest_next > last_success:
            due.append(lg.forest_next)
        return min(due)

    @classmethod
    def routes(cls):
        from fastapi import APIRouter

        from e7helper.core.paths import module_data_dir

        router = APIRouter()

        @router.get("/ledger", summary="日常收取的账本（游戏日、当天做完的项、本周买完的商店商品、精灵之森下次时间）")
        def get_ledger() -> dict:
            lg = Ledger.open(module_data_dir(cls.id), clock=lambda: ledger_mod.utcnow())
            return {
                "day": lg.day,
                "done": lg.done,
                "week": lg.week,
                "week_done": lg.week_done,
                "forest_next": lg.forest_next.isoformat() if lg.forest_next else None,
                "forest_due": lg.forest_due(),
            }

        return router

    # ------------------------------------------------------------ 主流程

    def run(self) -> None:
        cfg: DailyConfig = self.config
        self.run_stats = stats.RunStats(dry_run=cfg.dry_run)
        self.ledger = Ledger.open(self.ctx.data_dir, clock=lambda: ledger_mod.utcnow())
        items: list[tuple[str, str, Callable[[], None]]] = [
            (key, label, fn) for key, label, fn, on in (
                ("mail", "邮件", self._mail, cfg.mail),
                ("forest", "精灵之森", self._forest, cfg.forest),
                ("covenant", "誓约召唤", self._covenant, cfg.covenant),
                ("shop", "商店", self._shop, cfg.shop),
                ("arena", "竞技场", self._arena, cfg.arena),
            ) if on
        ]
        mode = "dry-run（不点领取、照料、召唤、开始战斗、购买）" if cfg.dry_run else "实跑"
        self.log.info("日常收取：%s；%s；游戏日 %s", mode, "、".join(label for _, label, _ in items) or "什么都没开",
                      self.ledger.day)
        failed: list[str] = []
        try:
            for key, label, fn in items:
                self._failures = 0
                try:
                    self._to_lobby()
                    fn()
                    self.run_stats.items[key] = "完成"
                except StopItem as e:
                    self.run_stats.items[key] = str(e)
                    self.log.info("%s：%s", label, e)
                except DailyAnomaly:
                    raise
                except Exception as e:  # noqa: BLE001 —— 一项失败不影响其他项（急停 TaskAborted 不是 Exception）
                    if not getattr(e, "counted", False):
                        self.run_stats.failures += 1
                    self.run_stats.items[key] = f"失败：{type(e).__name__}：{e}"
                    self.log.warning("%s 失败：%s：%s", label, type(e).__name__, e)
                    failed.append(label)
            if items:
                self._to_lobby()
        except BaseException as e:
            self.run_stats.items.setdefault("stopped", f"{type(e).__name__}：{e}")
            raise
        finally:
            r = self.run_stats
            r.ended = stats.now()
            stats.save(self.ctx.data_dir, r)
            self.log.info("统计：%s", r.summary())
        if failed:
            raise ItemFailed(f"没做成：{'、'.join(failed)}（详见日志）")

    def _to_lobby(self) -> None:
        """从这几项的任一界面回到大厅（只点返回 / 跳过 / 下一页）。"""
        ctl = self.ctl
        for _ in range(8):
            state = ctl.wait_scene(KNOWN + (ANIM, HERO), timeout=30)
            if state.is_(LOBBY):
                return
            if state.is_(ANIM):
                ctl.tap_template("summon/skip")
            elif state.is_(HERO):
                ctl.tap_template("summon/skip" if ctl.exists("summon/skip") else "summon/next")
            elif state.is_(RESULTS):
                ctl.tap_until("summon/back", (COVENANT, SUMMON), retry_after=RESULTS_RETRY)
            elif state.is_(arena_mod.RESULT):
                ctl.tap_until("arena/result/ok", arena_mod.NPC, retry_after=arena_mod.RESULT_RETRY)
            else:
                ctl.tap_until("back", tuple(s for s in KNOWN if s != state.scene))
        raise ItemFailed(f"回不到大厅，当前：{ctl.last_state}")

    # ------------------------------------------------------------ 邮件

    def _mail(self) -> None:
        cfg: DailyConfig = self.config
        ctl = self.ctl
        ctl.tap_until("top/mail", MAIL)
        if not ctl.exists("mail/sort_remain"):
            raise ItemFailed("邮件列表不是按剩余时间排序（左下角不是「剩余时间」），不领")
        count = self._mail_count()
        claimed = 0
        logged = False
        while True:
            rows = page.scan_mail(self.vision, ctl.screenshot())
            if not logged:
                self.log.info("邮箱 %d 封；当前屏：%s", count, "，".join(r.text or "?" for r in rows) or "无")
                logged = True
            if rows and rows[0].hours is None:
                raise StopItem(f"第一封邮件的剩余时间认不出（「{rows[0].text}」），不领")
            # 列表按剩余时间从短到长排，快过期的都在最上面
            target = next((r for r in rows if r.hours is not None and r.hours < cfg.mail_max_hours), None)
            if target is None:
                raise StopItem(f"没有剩余不到 {cfg.mail_max_hours:g} 小时的邮件（已领 {claimed} 封）")
            if cfg.mail_max_claims and claimed >= cfg.mail_max_claims:
                raise StopItem(f"达到每次最多 {cfg.mail_max_claims} 封")
            if cfg.dry_run:
                msg = f"领取「{target.text}」的邮件"
                self.run_stats.would.append(msg)
                raise StopItem(f"dry-run，下一步会{msg}")
            self.log.info("领取「%s」的邮件（邮箱 %d 封）", target.text, count)
            ctl.tap_match(target.claim, ref="mail/claim", delay=False)
            after = self._wait_mail_count(count, target)
            if after == count - 1:
                claimed += 1
                count = after
                self.run_stats.mails.append(stats.Mail(target.text, after))
                self.log.info("✔ 已领取（邮箱 %d → %d）", after + 1, after)
                self._ok()
                ctl.sleep(TOAST_WAIT)
                ctl.wait_scene(MAIL, timeout=10)
                continue
            if after == count:
                self._fail(f"点了领取，邮件数没变（{count}）")
                ctl.wait_scene(MAIL, timeout=10)
                continue
            raise DailyAnomaly(f"领取一封邮件后邮件数 {count} → {after}")

    def _mail_count(self) -> int:
        """邮件数（连续两帧一致才采用）。"""
        value = self._stable(lambda f: page.read_mail_count(self.vision, f))
        if value is None:
            raise ItemFailed("底部邮件数读不出")
        return value

    def _wait_mail_count(self, before: int, target: page.MailRow) -> int:
        """点了领取后：等邮件数变化（最多 MAIL_WAIT 秒），返回稳定读数。

        有些邮件会先弹出详情框（用户确认）：核对框里的剩余时间和要领的那行一致后点「收信」。
        出现其他弹窗就按弹窗规则关掉（确认框点取消），停止这一项。
        """
        ctl = self.ctl
        deadline = time.monotonic() + MAIL_WAIT
        received = False
        while time.monotonic() < deadline:
            state = ctl.detect()
            if state.popup == POPUP_NETWORK:
                ctl.dismiss_popups(state=state)
                continue
            if state.popup == POPUP_MAIL and not received:
                self._receive(target)
                received = True
                deadline = time.monotonic() + MAIL_WAIT
                continue
            if state.popup is not None and state.popup != "obscured":
                ctl.wait_scene(MAIL, timeout=15)  # 按弹窗规则关闭（确认框点取消、详情框点关闭）
                raise ItemFailed(f"领取后弹出了 {state.popup}，不再继续领")
            n = page.read_mail_count(self.vision, ctl.last_frame) if state.is_(MAIL) else None
            if n is not None and n != before:
                break
            ctl.sleep(POLL)
        ctl.wait_scene(MAIL, timeout=15)
        return self._mail_count()

    def _receive(self, target: page.MailRow) -> None:
        """邮件详情框：剩余时间和列表里那行一致才点「收信」，否则点关闭并停止这一项。"""
        ctl = self.ctl
        if not self._wait_popup_still(POPUP_MAIL):
            raise ItemFailed("邮件详情框没有完全显示")
        frame = ctl.last_frame
        text = page.read_mail_detail_remaining(self.vision, frame)
        if page.parse_remaining(text) != target.hours:
            ctl.wait_scene(MAIL, timeout=15)  # 规则：点「点击关闭」
            raise ItemFailed(f"详情框里的剩余时间「{text}」和要领的「{target.text}」不一致，不收信")
        self.log.info("邮件详情框（剩余「%s」）：点收信", text)
        ctl.tap_template("mail/receive")
        self._wait_popup_gone(POPUP_MAIL)

    # ------------------------------------------------------------ 精灵之森

    def _forest(self) -> None:
        cfg: DailyConfig = self.config
        ctl = self.ctl
        lg = self.ledger
        if not cfg.force and not lg.forest_due():
            local = lg.forest_next.astimezone()
            raise StopItem(f"还没到时间（下次 {local:%m-%d %H:%M}），不进去")
        ctl.tap_until("lobby/sanctuary", SANCTUARY)
        ctl.tap_until("sanctuary/forest", FOREST)
        forest = self._read_forest()
        would_from = len(self.run_stats.would)
        self.log.info("精灵之森：%s；照料：%s", "，".join(_card_str(c) for c in forest.cards),
                      _care_str(forest.care))
        try:
            for card in forest.ready:
                if cfg.dry_run:
                    self.run_stats.would.append(f"领取{card.name}")
                    continue
                self._claim_card(card)
            forest = self._read_forest()
            care = forest.care
            if care is not None and care.available:
                if cfg.dry_run:
                    self.run_stats.would.append(f"照料魔罗戈拉（{care.done}/{care.total}）")
                else:
                    self._care(care)
                    forest = self._read_forest()
        finally:
            nxt = forest.next_seconds()
            if not cfg.dry_run or nxt:
                lg.set_forest_next(nxt)
        if cfg.dry_run:
            raise StopItem(f"dry-run，会做：{'；'.join(self.run_stats.would[would_from:]) or '没有可领的'}")
        nxt = forest.next_seconds()
        when = "不知道" if nxt is None else f"{_hms(nxt)} 后"
        raise StopItem(f"领取 {len(self.run_stats.forest_claims)} 次，照料 {self.run_stats.cares} 次；下次 {when}")

    def _read_forest(self) -> page.Forest:
        self.ctl.wait_scene(FOREST, timeout=15)
        return page.read_forest(self.vision, self.ctl.screenshot())

    def _claim_card(self, card: Card) -> None:
        ctl = self.ctl
        self.log.info("领取%s", card.name)
        for _ in range(2):
            ctl.tap_rect(card.rect, delay=False)
            if self._wait_popup_still(POPUP_FOREST):
                break
            if not self._card_ready(card):
                break  # 没有弹框但已经领了（不太可能），下面按卡片状态核对
        else:
            raise ItemFailed(f"点了{card.name}，奖励框没出现")
        if ctl.detect().popup == POPUP_FOREST:
            ctl.tap_template("forest/close")
            self._wait_popup_gone(POPUP_FOREST)
        if self._card_ready(card):
            raise ItemFailed(f"{card.name}领取后仍显示「领取奖励」")
        self.run_stats.forest_claims.append(card.name)
        self.log.info("✔ %s已领取", card.name)
        self._ok()

    def _card_ready(self, card: Card) -> bool:
        self.ctl.wait_scene(FOREST, timeout=15)
        return self.vision.find(self.ctl.screenshot(), "forest/claim", card.rect) is not None

    def _care(self, care: page.Care) -> None:
        """照料（不花资源，用户确认）。可照料时按钮的样子还没见过：点了之后按次数核对。"""
        ctl = self.ctl
        self.log.info("照料魔罗戈拉（%d/%d）", care.done, care.total)
        ctl.tap_match(care.button, ref="forest/care", delay=False)
        if self._wait_popup_still(POPUP_FOREST, timeout=2.0):
            ctl.tap_template("forest/close")
            self._wait_popup_gone(POPUP_FOREST)
        new = self._read_forest().care
        if new is not None and new.done == care.done + 1:
            self.run_stats.cares += 1
            self.log.info("✔ 已照料（%d/%d）", new.done, new.total)
            self._ok()
            return
        raise ItemFailed(f"点了照料，次数没变（{_care_str(new)}）")

    # ------------------------------------------------------------ 誓约召唤

    def _covenant(self) -> None:
        cfg: DailyConfig = self.config
        ctl = self.ctl
        if not cfg.force and self.ledger.is_done("covenant"):
            raise StopItem("今天的免费召唤已经用完（账本）")
        state = ctl.tap_until("lobby/summon", (SUMMON, COVENANT))
        if state.is_(SUMMON):
            ctl.tap_until("summon/tab_covenant", COVENANT)
        done = 0
        while True:
            ctl.wait_scene(COVENANT, timeout=15)
            frame = ctl.screenshot()
            cov = page.read_covenant(self.vision, frame)
            if not done:
                self.log.info("誓约召唤：1次 %s，10次 %s，剩余免费 %s", _free(cov.free_1), _free(cov.free_10),
                              _frac(cov.left))
            if cov.free is None:
                if not cfg.dry_run:
                    self.ledger.mark_done("covenant", summons=done)
                raise StopItem(f"免费次数用完（这次召唤 {done} 次）")
            if cfg.covenant_max and done >= cfg.covenant_max:
                raise StopItem(f"达到每次最多 {cfg.covenant_max} 次")
            times = 10 if cov.free_10 is not None else 1
            if cfg.dry_run:
                msg = f"免费召唤 {times} 次（剩余免费 {_frac(cov.left)}）"
                self.run_stats.would.append(msg)
                raise StopItem(f"dry-run，下一步会{msg}")
            done += self._summon_once(cov, times, frame)

    def _summon_once(self, cov: Covenant, times: int, frame: np.ndarray) -> int:
        """点一次免费召唤，走完动画回到誓约页并核对。返回这次召唤的次数（点击被吞返回 0）。"""
        ctl = self.ctl
        before = self._currency_patches(frame)
        self.log.info("免费召唤 %d 次（剩余免费 %s；顶栏 %s）", times, _frac(cov.left),
                      page.read_currency_text(self.vision, frame))
        t0 = time.monotonic()
        ref = "summon/free_10" if times == 10 else "summon/free_1"
        ctl.tap_match(cov.free, ref=ref, delay=False)
        if not self._wait_results():
            self._fail("点了免费召唤，没有开始召唤")
            return 0
        seconds = time.monotonic() - t0
        ctl.tap_until("summon/back", COVENANT, timeout=30, retry_after=RESULTS_RETRY, max_taps=5)
        ctl.wait_scene(COVENANT, timeout=15)
        after_frame = self._still_frame()
        changed = page.changed_pixels_all(before, self._currency_patches(after_frame))
        text = page.read_currency_text(self.vision, after_frame)
        if changed > page.CURRENCY_CHANGED_PIXELS:
            raise DailyAnomaly(f"免费召唤后顶栏货币变了（{changed} 个像素；现在 {text}）")
        new = page.read_covenant(self.vision, after_frame)
        if cov.left is not None:
            expected = cov.left[0] - times
            got = new.left[0] if new.left else (0 if new.free is None else None)
            if got != expected:
                raise DailyAnomaly(f"免费次数 {cov.left[0]} → {got}，预期 {expected}")
        self.run_stats.summons.append(stats.Summon(times, new.left[0] if new.left else None, round(seconds, 1)))
        self.log.info("✔ 免费召唤 %d 次完成，用时 %.0f 秒，剩余免费 %s，顶栏没变（%s）", times, seconds,
                      _frac(new.left), text)
        self._ok()
        return times

    def _currency_patches(self, frame: np.ndarray) -> list[np.ndarray]:
        """顶栏货币区域：这一帧 + CURRENCY_FRAMES_GAP 秒后的一帧（用来排除背景光效）。"""
        self.ctl.sleep(page.CURRENCY_FRAMES_GAP)
        return [page.currency_patch(frame), page.currency_patch(self.ctl.screenshot())]

    def _wait_results(self) -> bool:
        """点了召唤后：一路点「跳过」/「下一页」，直到召唤结果完全显示。一直停在誓约页返回 False。

        只点这两个按钮。出现确认框（可能要花东西）立即停止；认不出的画面静止太久也停止。
        """
        ctl = self.ctl
        t0 = time.monotonic()
        last_tap = -1e9
        prev = None
        unknown_since = None
        while True:
            state = ctl.detect()
            now = time.monotonic()
            thumb = thumbnail(ctl.last_frame)
            moving = prev is not None and thumb_diff(thumb, prev) >= MOVING_DIFF
            prev = thumb
            if moving:
                ctl.progress()
            if state.is_(RESULTS):
                self._still_frame()
                return True
            if state.popup == POPUP_NETWORK:
                ctl.dismiss_popups(state=state)
                continue
            if state.popup == "confirm":
                ctl.dismiss_popups(state=state)  # 点取消
                raise DailyAnomaly("点了免费召唤后弹出了确认框（可能要花东西），已点取消")
            if state.is_(COVENANT) and now - t0 >= SUMMON_EATEN:
                return False
            if state.is_(ANIM, HERO) and now - last_tap >= SKIP_INTERVAL:
                m = ctl.find("summon/skip", ctl.last_frame) or ctl.find("summon/next", ctl.last_frame)
                if m is not None:
                    ctl.tap_match(m, delay=False)
                    last_tap = now
            if state.scene is None and not moving:
                unknown_since = unknown_since or now
                if now - unknown_since >= UNKNOWN_LIMIT:
                    raise DailyAnomaly(f"召唤过程中出现认不出的画面（{state}），停止")
            else:
                unknown_since = None
            if now - t0 >= SUMMON_TIMEOUT:
                raise DailyAnomaly(f"召唤 {SUMMON_TIMEOUT:.0f} 秒没有出结果，当前：{state}")
            ctl.sleep(POLL)

    # ------------------------------------------------------------ 商店（B12b）

    def _shop(self) -> None:
        shop_mod.Shop(self).run()

    # ------------------------------------------------------------ 竞技场

    def _arena(self) -> None:
        arena_mod.Arena(self).run()

    # ------------------------------------------------------------ 通用

    def _still_frame(self, timeout: float = 5.0) -> np.ndarray:
        """等画面静止（连续两帧差 < STILL_DIFF），返回最后一帧；超时返回当前帧。"""
        ctl = self.ctl
        deadline = time.monotonic() + timeout
        prev = None
        while True:
            frame = ctl.screenshot()
            thumb = thumbnail(frame)
            if prev is not None and thumb_diff(thumb, prev) < STILL_DIFF:
                return frame
            if time.monotonic() >= deadline:
                return frame
            prev = thumb
            ctl.sleep(POLL)

    def _wait_popup_still(self, popup: str, timeout: float = POPUP_WAIT) -> bool:
        """等弹窗出现并完全显示（淡入结束）。"""
        ctl = self.ctl
        deadline = time.monotonic() + timeout
        prev = None
        while time.monotonic() < deadline:
            state = ctl.detect()
            thumb = thumbnail(ctl.last_frame)
            if state.popup == popup and prev is not None and thumb_diff(thumb, prev) < STILL_DIFF:
                return True
            prev = thumb if state.popup == popup else None
            ctl.sleep(POLL)
        return False

    def _wait_popup_gone(self, popup: str) -> None:
        """点了弹窗的关闭之后，等它自己消失（不交给弹窗规则，避免在淡出时又点一次）。"""
        if self._wait_for(lambda f: True if self.ctl.detect(f).popup != popup else None, POPUP_WAIT) is None:
            raise ItemFailed(f"点了 {popup} 的关闭后它一直没有消失")

    def _stable(self, read: Callable[[np.ndarray], object], tries: int = 8):
        """连续两帧读数一致才采用；读不出返回 None。"""
        prev = None
        for _ in range(tries):
            value = read(self.ctl.screenshot())
            if value is not None and value == prev:
                return value
            prev = value
            self.ctl.sleep(POLL)
        return None

    def _wait_for(self, probe: Callable[[np.ndarray], object], timeout: float = 5.0):
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
        self._failures = 0
        self.ctl.progress()

    def _fail(self, msg: str) -> None:
        self.run_stats.failures += 1
        self._failures += 1
        limit = self.config.max_failures
        self.log.warning("失败（连续 %d/%d）：%s", self._failures, limit, msg)
        if self._failures >= limit:
            e = ItemFailed(f"连续失败 {self._failures} 次，最后一次：{msg}")
            e.counted = True  # 已经计入 failures
            raise e


def _card_str(c: Card) -> str:
    if c.ready:
        return f"{c.name} 可领"
    return f"{c.name} {_hms(c.seconds)}" if c.seconds is not None else f"{c.name} ?"


def _care_str(c: page.Care | None) -> str:
    if c is None:
        return "无"
    timer = f"，{_hms(c.seconds)} 后" if c.seconds is not None else ""
    return f"{c.done}/{c.total}{timer}{'（可照料）' if c.available else ''}"


def _hms(seconds: int) -> str:
    """秒数 → 「149:05:06」（和游戏里的倒计时同样写法）。"""
    h, rest = divmod(int(seconds), 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}"


def _free(m) -> str:
    return "免费" if m is not None else "不免费"


def _frac(f: tuple[int, int] | None) -> str:
    return f"{f[0]}/{f[1]}" if f else "?"


__all__ = ["DailyAnomaly", "DailyConfig", "DailyModule", "ItemFailed", "StopItem"]
