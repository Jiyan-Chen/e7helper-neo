"""竞技场模拟器：在 GameSim 的基础上模拟竞技场导航、NPC 列表、准备界面、快速对战/普通战斗、结算和补旗框。

- 大厅 → 模式选择 →（第一次进入时弹出「战斗记录」）→ 交战对手页 → NPC对战页 → 选第一行 → 挑战 → 准备界面
- 准备界面的切换钮在 快速对战 / 普通战斗 之间切换
- start 决定点「快速对战」「战斗开始」后的行为：
    "danger"（默认）：进入 DANGER，测试断言从没发生
    "ok"：扣一面旗帜并开始战斗（快速对战：过场 → 结算；普通战斗：加载 → 战斗中，开了自动才会打完）
    "eat"：点击被吞，什么都不发生
- buy 决定补旗框点「购买」后的行为："danger"（默认）/ "ok"（旗帜 +5）/ "eat"（框关闭但没加旗帜）
- bought_today=True 时补旗框是「今天已补过」的样子：友情点数不可选，游戏自动选中天空石（点购买会花天空石）
- 普通战斗开了自动后，自动图标每截一次图转 40°（模拟旋转）；没开自动战斗就一直停着
- 旗帜数和快速对战剩余次数不画在截图上，测试用 flags / quick_left 替换模块的读数
"""

from __future__ import annotations

import cv2
import numpy as np
from game_sim import DANGER, GameSim, load_fixture

from e7helper.core.geometry import Rect, Scaler

NPC_LIST, NPC_SELECTED = "arena_npc", "arena_npc_selected"
PREP = {"quick": "arena_prep_quick", "battle": "arena_prep_battle"}
BATTLE_MANUAL, BATTLE_AUTO = "arena_battle_manual", "arena_battle_auto"
RESULT = {"quick": "arena_quick_victory", "battle": "arena_battle_victory"}
BUY, BUY_USED = "arena_buy_flags", "arena_buy_flags_used"

BACK_BTN = Rect(28, 18, 38, 44)
LOBBY_ARENA = Rect(1456, 470, 88, 32)
MODE_ARENA = Rect(430, 700, 320, 170)
RECORD_CLOSE = Rect(700, 640, 200, 100)
TAB_NPC = Rect(1262, 214, 336, 112)
FIRST_ROW = Rect(372, 213, 860, 135)
CHALLENGE = Rect(648, 792, 302, 70)
FLAG_PLUS = Rect(706, 12, 26, 26)
TOGGLE = Rect(1157, 791, 72, 75)
START = Rect(845, 792, 300, 72)
AUTO = Rect(1382, 14, 54, 50)
RESULT_OK = {"quick": Rect(808, 760, 246, 72), "battle": Rect(1357, 790, 208, 75)}
BUY_CANCEL, BUY_OK = Rect(542, 650, 246, 74), Rect(810, 650, 246, 74)
AUTO_ICON = Rect(1382, 14, 54, 50)


def _hit(r: Rect, x: int, y: int) -> bool:
    return r.x <= x < r.right and r.y <= y < r.bottom


class ArenaSim(GameSim):
    def __init__(self, screen: str = "lobby", *, flags: int = 5, quick_left: int = 10, mode: str = "quick",
                 start: str = "danger", buy: str = "danger", record_popup: bool = True,
                 bought_today: bool = False, battle_shots: int = 8, **kw):
        super().__init__(screen, **kw)
        self.flags = flags
        self.quick_left = quick_left
        self.mode = mode  # 准备界面当前模式
        self.start = start
        self.buy = buy
        self.record_popup = record_popup
        self.bought_today = bought_today
        self.battle_shots = battle_shots  # 开了自动后再截这么多次图打完
        self.starts = 0  # 点开始（快速对战 / 战斗开始）的次数
        self.buys = 0  # 点「购买」的次数
        self.auto_taps = 0
        self.battles: list[str] = []  # 完成的场次（模式）
        self._fight: str | None = None  # 进行中的战斗模式
        self._auto = False
        self._angle = 0

    # ------------------------------------------------------------ 画面

    def screenshot(self) -> np.ndarray:
        img = super().screenshot()
        if self.screen == BATTLE_AUTO:
            self._angle += 40
            self.battle_shots -= 1
            if self.battle_shots <= 0:
                self._finish()
            return self._rotated_icon(img)
        return img

    def _rotated_icon(self, img: np.ndarray) -> np.ndarray:
        """把手动模式截图里的自动图标转一个角度贴上去，模拟开启后的旋转。"""
        s = Scaler(*self.size)
        r = s.rect_to_device(AUTO_ICON)
        icon = s.rect_to_device(AUTO_ICON).crop(load_fixture(BATTLE_MANUAL, self.size))
        m = cv2.getRotationMatrix2D((icon.shape[1] / 2, icon.shape[0] / 2), self._angle, 1.0)
        img = img.copy()
        img[r.y:r.bottom, r.x:r.right] = cv2.warpAffine(icon, m, (icon.shape[1], icon.shape[0]),
                                                        borderMode=cv2.BORDER_REPLICATE)
        return img

    def _finish(self) -> None:
        mode, self._fight = self._fight, None
        self.battles.append(mode)
        self._go(RESULT[mode])

    # ------------------------------------------------------------ 输入

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        self.taps.append((x, y, duration))
        if self.drop_taps > 0:
            self.drop_taps -= 1
            return
        bx, by = Scaler(*self.size).to_base(x, y)
        s = self.screen
        if s == "lobby" and _hit(LOBBY_ARENA, bx, by):
            self._go("arena")
        elif s == "arena" and _hit(MODE_ARENA, bx, by):
            self._go("arena_defense_record" if self.record_popup else "arena_pvp")
            self.record_popup = False
        elif s == "arena_defense_record" and _hit(RECORD_CLOSE, bx, by):
            self._go("arena_pvp")
        elif s == "arena_pvp" and _hit(TAB_NPC, bx, by):
            self._go(NPC_LIST)
        elif s in (NPC_LIST, NPC_SELECTED):
            if _hit(FIRST_ROW, bx, by):
                self._go(NPC_SELECTED)
            elif s == NPC_SELECTED and _hit(CHALLENGE, bx, by):
                self._go(PREP[self.mode])
            elif _hit(FLAG_PLUS, bx, by):
                self._go(BUY_USED if self.bought_today else BUY)
            elif _hit(BACK_BTN, bx, by):
                self._go("arena")
        elif s in PREP.values():
            if _hit(TOGGLE, bx, by):
                self.mode = "battle" if self.mode == "quick" else "quick"
                self._go(PREP[self.mode])
            elif _hit(START, bx, by):
                self._start()
            elif _hit(BACK_BTN, bx, by):
                self._go(NPC_SELECTED)
        elif s == BATTLE_MANUAL and _hit(AUTO, bx, by):
            self.auto_taps += 1
            self._auto = True
            self._go(BATTLE_AUTO)
        elif s in RESULT.values():
            mode = "quick" if s == RESULT["quick"] else "battle"
            if _hit(RESULT_OK[mode], bx, by):
                self._go(NPC_LIST)
        elif s in (BUY, BUY_USED):
            if _hit(BUY_CANCEL, bx, by):
                self._go(NPC_LIST)
            elif _hit(BUY_OK, bx, by):
                self.buys += 1
                if self.buy == "danger" or s == BUY_USED:
                    self._go(DANGER)
                else:
                    if self.buy == "ok":
                        self.flags += 5
                    self._go(NPC_LIST)

    def _start(self) -> None:
        self.starts += 1
        if self.start == "danger":
            self._go(DANGER)
            return
        if self.start == "eat":
            return
        self.flags -= 1
        self._fight = self.mode
        if self.mode == "quick":
            self.quick_left -= 1
            self._go("arena_quick_cutin")
            self.then = (3, RESULT["quick"])
            self.battles.append("quick")
            self._fight = None
        else:
            self._go("arena_battle_loading")
            self.then = (2, BATTLE_AUTO if self._auto else BATTLE_MANUAL)

    def back(self) -> None:
        self.backs += 1
        s = self.screen
        if s == "arena_defense_record":
            self._go("arena_pvp")
        elif s in (BUY, BUY_USED):
            self._go(NPC_LIST)
        elif s in PREP.values():
            self._go(NPC_SELECTED)
        elif s in (NPC_LIST, NPC_SELECTED, "arena_pvp"):
            self._go("arena")
        elif s == "arena":
            self._go("lobby")


__all__ = ["DANGER", "ArenaSim"]
