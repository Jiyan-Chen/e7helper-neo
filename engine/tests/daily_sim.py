"""日常收取模拟器：在 GameSim 的基础上模拟大厅、邮件、圣域 / 精灵之森、召唤 / 誓约召唤。

- 大厅 → 邮件：mail_top2（11 封）→ 领第一行 → 物品提示 → mail_after_claim（10 封）。
  mail="ok"（默认）按上面的链走；"eat"：点领取没反应。链走完后再点领取也没反应。
  mail_detail=True：点领取先弹出邮件详情框（淡入 1 帧），点「收信」才算领取；点「点击关闭」/ 返回键回到列表。
- 大厅 → 圣域 → 精灵之森：forest="ready"（两张卡可领）/ "after"（只有精灵之泉可领）/ "waiting"（都在倒计时）。
  点可领的卡 → 奖励框淡入（先 1 帧淡入，再静止）→ 点「点击关闭」→ 框淡出 1 帧 → 下一状态。
  forest_claim="eat" 时点卡片没反应。
- 大厅 → 召唤（限时池）→ 誓约召唤：covenant 是誓约页的 fixture 序列，每完成一次召唤前进一个。
  点「免费」按钮：summon="ok" → 召唤动画（书 → 跳过）→ 十连：英雄展示 → 结果入场 → 召唤结果；
  单抽：没有「跳过」，动画播完直接是单抽结果卡片。"eat"：没反应。结果页点「返回」回到序列里的下一个誓约页。
- 危险按钮（DANGER）：邮件「全部领取」；不是免费的召唤按钮（限时池、誓约页上没显示免费的那个）；
  结果页「再召唤一次」。
- 照料：care_ready=True 时把照料的倒计时涂掉（看起来可照料）；点照料按钮记在 care_taps，画面不变。
"""

from __future__ import annotations

import numpy as np
from game_sim import DANGER, GameSim

from e7helper.core.geometry import Rect, Scaler

LOBBY = "daily_lobby_ready"
SANCTUARY = "daily_sanctuary_night_dot"
FOREST = {"ready": "daily_forest_ready", "after": "daily_forest_after_claim", "waiting": "daily_forest_waiting"}
FOREST_POPUP, FOREST_FADEIN = "daily_forest_popup", "daily_forest_popup_fadein"
MAIL_CHAIN = ("daily_mail_top2", "daily_mail_after_claim")
MAIL_TOAST = "daily_mail_toast"
MAIL_DETAIL, MAIL_DETAIL_FADEIN = "daily_mail_detail", "daily_mail_detail_fadein"
SUMMON_MAIN = "daily_summon_main_free"
SKIP, HERO = "daily_summon_skip", "daily_summon_hero"
RESULTS, RESULTS_ANIM = "daily_summon_results", "daily_summon_results_anim"
RESULT_SINGLE = "daily_summon_result_single"
# 誓约页 → 哪些按钮是免费的（1 = 1次召唤，10 = 召唤10次）
FREE = {"daily_covenant_free": (1, 10), "daily_covenant_free11": (1, 10), "daily_covenant_free1": (1,)}

BACK_BTN = Rect(28, 18, 38, 44)
LOBBY_SANCTUARY = Rect(40, 195, 62, 82)
LOBBY_MAIL = Rect(1380, 20, 56, 45)
LOBBY_SUMMON = Rect(1462, 540, 100, 55)
SANCTUARY_FOREST = Rect(1410, 190, 170, 55)
CARDS = {"penguin": Rect(1145, 258, 415, 110), "well": Rect(1145, 403, 415, 110)}
FOREST_CLOSE = Rect(700, 620, 200, 80)
CARE_BTN = Rect(1340, 665, 210, 55)
CARE_TIMER = Rect(1170, 668, 145, 48)
MAIL_CLAIM_ROW1 = Rect(1312, 152, 238, 66)
MAIL_CLAIM = Rect(1312, 152, 238, 600)  # 各行的「领取」
MAIL_CLAIM_ALL = Rect(1306, 800, 250, 65)
MAIL_RECEIVE = Rect(628, 654, 346, 66)
MAIL_DETAIL_CLOSE = Rect(735, 845, 130, 40)
TAB_COVENANT = Rect(20, 505, 235, 92)
BTN_1, BTN_10 = Rect(948, 788, 304, 80), Rect(1268, 788, 306, 80)
SKIP_BTN = Rect(1470, 20, 110, 52)
NEXT_BTN = Rect(1270, 790, 300, 75)
RESULTS_BACK = Rect(45, 788, 295, 75)
RESULTS_AGAIN = Rect(1155, 790, 410, 78)


def _hit(r: Rect, x: int, y: int) -> bool:
    return r.x <= x < r.right and r.y <= y < r.bottom


class DailySim(GameSim):
    def __init__(self, screen: str = LOBBY, *, mail: str = "ok", forest: str = "ready", forest_claim: str = "ok",
                 summon: str = "ok",
                 covenant: tuple[str, ...] = ("daily_covenant_free", "daily_covenant_free11", "daily_covenant_free1",
                                              "daily_covenant_done"),
                 care_ready: bool = False, mail_detail: bool = False, **kw):
        super().__init__(screen, **kw)
        self.mail = mail
        self.mail_idx = 0
        self.forest = forest
        self.forest_claim = forest_claim
        self.summon = summon
        self.covenant = list(covenant)
        self.cov_idx = 0
        self.care_ready = care_ready
        self.mail_detail = mail_detail
        self.detail_closes = 0
        self.mail_claims = 0
        self.forest_claims: list[str] = []
        self.care_taps = 0
        self.summons = 0  # 点免费按钮且开始召唤的次数
        self.summon_times: list[int] = []  # 每次召唤是单抽（1）还是十连（10）
        self._after_popup: str | None = None
        self._fade_out = 0

    # ------------------------------------------------------------ 画面

    def screenshot(self) -> np.ndarray:
        if self._fade_out > 0:
            # 奖励框淡出：还显示 1 帧弹窗
            self._fade_out -= 1
            if self._fade_out == 0:
                self._go(self._after_popup)
        img = super().screenshot()
        if self.care_ready and self.screen in FOREST.values():
            s = Scaler(*self.size)
            r = s.rect_to_device(CARE_TIMER)
            img = img.copy()
            img[r.y:r.bottom, r.x:r.right] = img[r.y, r.x]  # 用左上角的底色涂掉倒计时
        return img

    @property
    def cov_screen(self) -> str:
        return self.covenant[min(self.cov_idx, len(self.covenant) - 1)]

    # ------------------------------------------------------------ 输入

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        self.taps.append((x, y, duration))
        if self.drop_taps > 0:
            self.drop_taps -= 1
            return
        bx, by = Scaler(*self.size).to_base(x, y)
        s = self.screen
        if s == LOBBY:
            if _hit(LOBBY_SANCTUARY, bx, by):
                self._go(SANCTUARY)
            elif _hit(LOBBY_MAIL, bx, by):
                self._go(MAIL_CHAIN[self.mail_idx])
            elif _hit(LOBBY_SUMMON, bx, by):
                self._go(SUMMON_MAIN)
        elif s == SANCTUARY:
            if _hit(BACK_BTN, bx, by):
                self._go(LOBBY)
            elif _hit(SANCTUARY_FOREST, bx, by):
                self._go(FOREST[self.forest])
        elif s in FOREST.values():
            self._tap_forest(bx, by)
        elif s in (FOREST_POPUP, FOREST_FADEIN):
            if s == FOREST_POPUP and _hit(FOREST_CLOSE, bx, by) and self._fade_out == 0:
                self._fade_out = 2
        elif s in MAIL_CHAIN or s == MAIL_TOAST:
            self._tap_mail(bx, by)
        elif s == MAIL_DETAIL:
            if _hit(MAIL_RECEIVE, bx, by):
                self._claim_mail()
            elif _hit(MAIL_DETAIL_CLOSE, bx, by):
                self.detail_closes += 1
                self._go(MAIL_CHAIN[self.mail_idx])
        elif s == SUMMON_MAIN:
            if _hit(BACK_BTN, bx, by):
                self._go(LOBBY)
            elif _hit(TAB_COVENANT, bx, by):
                self._go(self.cov_screen)
            elif _hit(BTN_1, bx, by) or _hit(BTN_10, bx, by):
                self._go(DANGER)  # 限时池不免费
        elif s in self.covenant:
            self._tap_covenant(s, bx, by)
        elif s == SKIP:
            if _hit(SKIP_BTN, bx, by):
                self._go(HERO)
        elif s == HERO:
            if _hit(SKIP_BTN, bx, by) or _hit(NEXT_BTN, bx, by):
                self._go(RESULTS_ANIM)
                self.then = (1, RESULTS)
        elif s in (RESULTS, RESULT_SINGLE):
            if s == RESULTS and _hit(RESULTS_AGAIN, bx, by):
                self._go(DANGER)
            elif _hit(RESULTS_BACK, bx, by):
                self.cov_idx += 1
                self._go(self.cov_screen)

    def _tap_forest(self, bx: int, by: int) -> None:
        if _hit(BACK_BTN, bx, by):
            self._go(SANCTUARY)
            return
        if _hit(CARE_BTN, bx, by):
            self.care_taps += 1
            return
        ready = {"ready": ("penguin", "well"), "after": ("well",), "waiting": ()}[self.forest]
        for name in ready:
            if _hit(CARDS[name], bx, by):
                if self.forest_claim == "eat" or (name == "well" and "penguin" in ready):
                    return  # 模拟器只按顺序领：企鹅巢穴可领时点精灵之泉不处理
                self.forest_claims.append(name)
                self.forest = "after" if name == "penguin" else "waiting"
                self._after_popup = FOREST[self.forest]
                self._go(FOREST_FADEIN)
                self.then = (1, FOREST_POPUP)
                return

    def _tap_mail(self, bx: int, by: int) -> None:
        if _hit(BACK_BTN, bx, by):
            self._go(LOBBY)
        elif _hit(MAIL_CLAIM_ALL, bx, by):
            self._go(DANGER)
        elif _hit(MAIL_CLAIM, bx, by):
            if not _hit(MAIL_CLAIM_ROW1, bx, by):
                self._go(DANGER)  # 模块应该只领最上面那封（列表按剩余时间排序）
                return
            if self.mail == "eat" or self.mail_idx + 1 >= len(MAIL_CHAIN):
                return
            if self.mail_detail:
                self._go(MAIL_DETAIL_FADEIN)
                self.then = (1, MAIL_DETAIL)
                return
            self._claim_mail()

    def _claim_mail(self) -> None:
        self.mail_idx += 1
        self.mail_claims += 1
        self._go(MAIL_TOAST)
        self.then = (2, MAIL_CHAIN[self.mail_idx])

    def _tap_covenant(self, s: str, bx: int, by: int) -> None:
        if _hit(BACK_BTN, bx, by):
            self._go(LOBBY)
            return
        times = 1 if _hit(BTN_1, bx, by) else 10 if _hit(BTN_10, bx, by) else None
        if times is None:
            return
        if times not in FREE.get(s, ()):
            self._go(DANGER)
        elif self.summon == "ok":
            self.summons += 1
            self.summon_times.append(times)
            self._go("daily_summon_book")
            # 十连：动画右上有「跳过」；单抽：没有跳过，动画自己播完直接出卡片（实跑约 9 秒）
            self.then = (2, SKIP) if times == 10 else (4, RESULT_SINGLE)

    def back(self) -> None:
        self.backs += 1
        s = self.screen
        if s == MAIL_DETAIL:
            self.detail_closes += 1
            self._go(MAIL_CHAIN[self.mail_idx])
        elif s in (SANCTUARY, SUMMON_MAIN) or s in MAIL_CHAIN or s in self.covenant:
            self._go(LOBBY)
        elif s in FOREST.values():
            self._go(SANCTUARY)


__all__ = ["DANGER", "DailySim"]
