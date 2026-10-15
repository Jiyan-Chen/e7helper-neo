"""重复刷关模拟器：在 GameSim 的基础上模拟 大厅 → 战斗 → 讨伐 → 准备界面、托管框（设置 / 进度 / 结算）、
手动战斗（战斗 → CLEAR → 结算 → 战后）、行动力不足框。

- 有消耗的按钮由策略决定，默认都是 "danger"（进入 DANGER，测试断言从没发生）：
    start：「战斗开始」（行动力够时）；"ok" 扣行动力并开打，"eat" 点击被吞
    auto_start：托管确认框的「确认」；"ok" 按设置扣行动力 / 叶子，托管进入进行中
    claim：托管框的「结算」；"ok" 结算
    refill：行动力不足框的「购买」；"ok" 按选中的选项扣叶子 / 天空石并加行动力
- 进行中的托管框里点到「中断」一律进入 DANGER。
- 截图上的数字是固定的，读数（行动力、天空石、准备界面消耗、设置框、补充框选中项、关卡名、讨伐列表）
  由测试用 monkeypatch 换成模拟器的值（见 test_repeat_battle._patch_reads）。
- 开了自动战斗后，自动图标每截一次图转 40°；battle_shots 次截图后出现 CLEAR。
- 战后界面的背景一直在动（每次截图亮度跳动，整屏帧差 > 静止阈值），模拟实机永远「不静止」。
- 托管确认框点「确认」、补充框点「购买」后，框还要淡出 linger 次截图才消失；淡出期间点到取消记在 late_cancels。
"""

from __future__ import annotations

import cv2
import numpy as np
from game_sim import DANGER, GameSim, load_fixture

from e7helper.core.geometry import Rect, Scaler

HUNT_TOP = ["双足飞龙", "魔像", "报丧妖"]  # 列表顶部可见的地下城（rb_hunt_list）
HUNT_END = ["阿吉玛纳克", "卡戴斯", "食人魔"]  # 翻到底后可见的（rb_hunt_list_end）
HUNT_ROWS = [Rect(1301, 336, 180, 36), Rect(1302, 592, 121, 35), Rect(1303, 847, 148, 35)]
TIERS = ["中级", "上级", "地狱级", "异界"]
TIER_CARDS = [Rect(962, 187, 278, 115), Rect(962, 322, 278, 115), Rect(962, 457, 278, 115), Rect(962, 592, 278, 115)]
ONLY_ABYSS = {"阿吉玛纳克", "卡戴斯", "食人魔"}  # 后出的地下城只有「讨伐异界」一张难度卡片（在第一张的位置）

BACK_BTN = Rect(28, 18, 38, 44)
LOBBY_BATTLE = Rect(1485, 388, 60, 34)
MENU_HUNT = Rect(802, 220, 350, 630)
TOGGLE = Rect(1515, 792, 70, 72)
PREP_START = Rect(1168, 790, 336, 75)
PREP_AUTO = Rect(765, 655, 115, 100)
DIALOG_BTN = Rect(630, 745, 338, 72)  # 托管进度框的 结算 / 中断 / 关闭
CLOSE_AREA = Rect(600, 845, 400, 45)  # 托管框底部「轻触后关闭」
RECOMMEND = Rect(655, 788, 250, 75)  # 准备界面「推荐配置」：会改队伍，本模块绝不该点到
SETTLED_AREA = Rect(600, 600, 400, 120)
SETUP_CHECK = Rect(697, 383, 38, 38)
SETUP_MIN, SETUP_MINUS, SETUP_PLUS = Rect(693, 515, 66, 44), Rect(765, 515, 66, 44), Rect(1093, 515, 64, 44)
SETUP_START = Rect(655, 752, 285, 62)
CONFIRM_CANCEL, CONFIRM_OK = Rect(542, 537, 246, 75), Rect(811, 537, 246, 75)
ENERGY_CANCEL, ENERGY_BUY = Rect(542, 650, 246, 74), Rect(810, 650, 246, 74)
ENERGY_LEFT, ENERGY_RIGHT = Rect(478, 385, 288, 160), Rect(835, 385, 288, 160)
RESULT_OK = Rect(1356, 790, 208, 75)
AFTER_RETRY, AFTER_LEAVE = Rect(1228, 790, 336, 75), Rect(32, 790, 207, 72)
AUTO_ICON = Rect(1382, 14, 54, 50)

LOBBY = {"none": "rb_lobby_no_auto", "running": "rb_lobby_auto_running", "done": "rb_lobby_auto_done"}
PREP = {"quick": "rb_prep_quick", "battle": "rb_prep_battle"}
AUTO_DIALOG = {"running": "rb_auto_running", "done": "rb_auto_done"}
PREP_SCREENS = set(PREP.values())


def _hit(r: Rect, x: int, y: int) -> bool:
    return r.x <= x < r.right and r.y <= y < r.bottom


class RbSim(GameSim):
    def __init__(self, screen: str = "lobby", *, energy: int = 100, cost: int = 20, leaves: int = 291,
                 skystone: int = 19728, auto: str = "none", auto_done_runs: int = 4, no_record: bool = False,
                 start: str = "danger", auto_start: str = "danger", claim: str = "danger", refill: str = "danger",
                 battle_shots: int = 4, drop_energy: int = 0, auto_on: bool = True, checked: bool = False,
                 hunt: str = "双足飞龙", tier: str = "地狱级", **kw):
        if screen == "lobby":
            screen = LOBBY[auto]
        elif screen == "prep":
            screen = PREP["quick"]
        super().__init__(screen, **kw)
        self.energy, self.cost, self.leaves, self.skystone = energy, cost, leaves, skystone
        self.auto = auto  # none / running / done
        self.auto_done_runs = auto_done_runs
        self.no_record = no_record
        self.start, self.auto_start, self.claim, self.refill = start, auto_start, claim, refill
        self.battle_shots = battle_shots
        self.drop_energy = drop_energy  # 每场掉落的行动力
        self.auto_on = auto_on
        self.checked = checked  # 托管设置框「优先使用持有的行动力」
        self.count = 1  # 托管份数
        self.mode = "quick"
        self.scrolled = False
        self.selected, self.tier = hunt, tier  # 讨伐列表当前选中的地下城、进入的难度
        self.option = "leaf"  # 行动力不足框选中的选项
        self.starts = 0
        self.battles = 0
        self.auto_starts: list[tuple[int, int, int]] = []  # (份数, 行动力, 叶子)
        self.claims = 0
        self.refills: list[str] = []
        self.toggles = 0
        self.auto_taps = 0
        self.linger = 2
        self.late_cancels = 0  # 确认 / 购买之后、框淡出期间又点了取消
        self._shots_left = 0
        self._angle = 0

    # ------------------------------------------------------------ 读数（测试替换识别函数时用）

    @property
    def check_enabled(self) -> bool:
        return self.energy >= self.cost * 4

    def setup_use(self) -> tuple[int, int]:
        """设置框「将使用」的行动力和叶子（模拟游戏：勾选后先用行动力凑整份）。"""
        unit = self.cost * 4
        energy_units = self.energy // unit if self.checked and self.check_enabled else 0
        e = min(self.count, energy_units)
        return e * unit, self.count - e

    def visible_hunts(self) -> list[str]:
        return HUNT_END if self.scrolled else HUNT_TOP

    def tiers(self) -> list[str]:
        """当前选中的地下城的难度卡片（按位置）。"""
        return ["异界"] if self.selected in ONLY_ABYSS else TIERS

    # ------------------------------------------------------------ 画面

    def screenshot(self) -> np.ndarray:
        img = super().screenshot()
        if self.screen == "rb_after":
            return cv2.add(img, np.full_like(img, 12 * (self.screenshots % 2)))
        if self.screen == "rb_battle":
            self._shots_left -= 1
            if self._shots_left <= 0:
                self._go("rb_clear")
            if self.auto_on:
                self._angle += 40
                return self._rotated_icon(img)
        return img

    def _rotated_icon(self, img: np.ndarray) -> np.ndarray:
        s = Scaler(*self.size)
        r = s.rect_to_device(AUTO_ICON)
        icon = r.crop(load_fixture("rb_battle", self.size))
        m = cv2.getRotationMatrix2D((icon.shape[1] / 2, icon.shape[0] / 2), self._angle, 1.0)
        img = img.copy()
        img[r.y:r.bottom, r.x:r.right] = cv2.warpAffine(icon, m, (icon.shape[1], icon.shape[0]),
                                                        borderMode=cv2.BORDER_REPLICATE)
        return img

    def _prep(self) -> None:
        self._go(PREP[self.mode])

    def _close_dialog(self) -> None:
        """托管框关闭要淡出 linger 次截图。"""
        self.then = (self.linger, PREP[self.mode])

    # ------------------------------------------------------------ 输入

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        self.taps.append((x, y, duration))
        if self.drop_taps > 0:
            self.drop_taps -= 1
            return
        bx, by = Scaler(*self.size).to_base(x, y)
        s = self.screen
        if s in LOBBY.values():
            if _hit(LOBBY_BATTLE, bx, by):
                self._go("rb_battle_menu")
        elif s == "rb_battle_menu":
            if _hit(MENU_HUNT, bx, by):
                self._go("rb_hunt_list_end" if self.scrolled else "rb_hunt_list")
            elif _hit(BACK_BTN, bx, by):
                self._go(LOBBY[self.auto])
        elif s in ("rb_hunt_list", "rb_hunt_list_end"):
            for name, row in zip(self.visible_hunts(), HUNT_ROWS, strict=True):
                if _hit(row, bx, by):
                    self.selected = name
            for tier, card in zip(self.tiers(), TIER_CARDS, strict=False):
                if _hit(card, bx, by):
                    self.tier = tier
                    self.mode = "quick"
                    self._prep()
            if _hit(BACK_BTN, bx, by):
                self._go("rb_battle_menu")
        elif s in PREP_SCREENS:
            self._tap_prep(bx, by)
        elif s == "rb_auto_setup":
            self._tap_setup(bx, by)
        elif s == "rb_auto_confirm":
            if self.then is not None and _hit(CONFIRM_CANCEL, bx, by):
                self.late_cancels += 1  # 已经确认了，框在淡出
            elif self.then is not None:
                pass
            elif _hit(CONFIRM_CANCEL, bx, by):
                self._go("rb_auto_setup")
            elif _hit(CONFIRM_OK, bx, by):
                if self.auto_start != "ok":
                    self._go(DANGER)
                    return
                use_e, use_l = self.setup_use()
                self.energy -= use_e
                self.leaves -= use_l
                self.auto_starts.append((self.count, use_e, use_l))
                self.auto = "running"
                self.then = (self.linger, PREP[self.mode])  # 确认框淡出
        elif s in ("rb_auto_running", "rb_auto_done", "rb_auto_claimed", "rb_auto_setup") and self.then is not None:
            self.late_cancels += 1  # 框在淡出，又点了一次
        elif s in ("rb_auto_running", "rb_auto_done", "rb_auto_claimed"):
            if _hit(DIALOG_BTN, bx, by):
                if s == "rb_auto_running":
                    self._go(DANGER)  # 中断
                elif s == "rb_auto_done":
                    if self.claim != "ok":
                        self._go(DANGER)
                        return
                    self.claims += 1
                    self._go("rb_auto_settling")
                    self.then = (1, "rb_auto_settled")
                else:
                    self._close_dialog()
            elif _hit(CLOSE_AREA, bx, by):
                self._close_dialog()
        elif s == "rb_auto_settled":
            if _hit(SETTLED_AREA, bx, by):
                self.auto = "none"
                self._go("rb_auto_claimed")
        elif s == "rb_energy_low":
            if self.then is not None:
                self.late_cancels += _hit(ENERGY_CANCEL, bx, by)
            elif _hit(ENERGY_CANCEL, bx, by):
                self._prep()
            elif _hit(ENERGY_LEFT, bx, by):
                self.option = "leaf"
            elif _hit(ENERGY_RIGHT, bx, by):
                self.option = "skystone"
            elif _hit(ENERGY_BUY, bx, by):
                if self.refill != "ok":
                    self._go(DANGER)
                    return
                if self.option == "leaf":
                    self.leaves -= 1
                    self.energy += 80
                else:
                    self.skystone -= 30
                    self.energy += 60
                self.refills.append(self.option)
                self.then = (self.linger, PREP[self.mode])  # 补充框淡出
        elif s == "rb_battle":
            if _hit(AUTO_ICON, bx, by):
                self.auto_taps += 1
                self.auto_on = True
        elif s == "rb_clear":
            self._go("rb_result")
        elif s == "rb_result":
            if _hit(RESULT_OK, bx, by):
                self._go("rb_after")
        elif s == "rb_after":
            if _hit(AFTER_RETRY, bx, by):
                self.mode = "quick"  # 回到准备界面时游戏默认是快速战斗
                self._prep()
            elif _hit(AFTER_LEAVE, bx, by):
                self._go("rb_hunt_list")

    def _tap_prep(self, bx: int, by: int) -> None:
        if _hit(RECOMMEND, bx, by):
            self._go(DANGER)
        elif _hit(TOGGLE, bx, by):
            self.toggles += 1
            self.mode = "battle" if self.mode == "quick" else "quick"
            self._prep()
        elif _hit(PREP_AUTO, bx, by):
            if self.auto == "none":
                if not self.no_record:
                    self._go("rb_auto_setup")
            else:
                self._go(AUTO_DIALOG[self.auto])
        elif _hit(PREP_START, bx, by):
            if self.mode == "quick":
                self._go(DANGER)  # 本模块不用快速战斗
            elif self.energy < self.cost:
                self.option = "leaf"
                self._go("rb_energy_low")
            else:
                self.starts += 1
                if self.start == "eat":
                    return
                if self.start != "ok":
                    self._go(DANGER)
                    return
                self.energy -= self.cost
                self._shots_left = self.battle_shots
                self._go("rb_battle_start")
                self.then = (1, "rb_battle")
        elif _hit(BACK_BTN, bx, by):
            self._go("rb_hunt_list_end" if self.scrolled else "rb_hunt_list")

    def _tap_setup(self, bx: int, by: int) -> None:
        if _hit(SETUP_CHECK, bx, by):
            if self.check_enabled:
                self.checked = not self.checked
        elif _hit(SETUP_MIN, bx, by):
            self.count = 1
        elif _hit(SETUP_MINUS, bx, by):
            self.count = max(1, self.count - 1)
        elif _hit(SETUP_PLUS, bx, by):
            self.count = min(100, self.count + 1)
        elif _hit(SETUP_START, bx, by):
            self._go("rb_auto_confirm")
        elif _hit(CLOSE_AREA, bx, by):
            self._close_dialog()

    def _go(self, target: str) -> None:
        if target == "rb_clear":
            self.battles += 1
            self.energy += self.drop_energy
        super()._go(target)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        super().swipe(x1, y1, x2, y2, duration)
        if self.screen in ("rb_hunt_list", "rb_hunt_list_end"):
            self.scrolled = y2 < y1
            self._go("rb_hunt_list_end" if self.scrolled else "rb_hunt_list")

    def back(self) -> None:
        self.backs += 1
        s = self.screen
        if s in ("rb_auto_setup", "rb_auto_running", "rb_auto_done", "rb_auto_claimed", "rb_energy_low"):
            self._prep()
        elif s == "rb_auto_confirm":
            self._go("rb_auto_setup")
        elif s in PREP_SCREENS:
            self._go("rb_hunt_list")
        elif s in ("rb_hunt_list", "rb_hunt_list_end"):
            self._go("rb_battle_menu")
        elif s == "rb_battle_menu":
            self._go(LOBBY[self.auto])


__all__ = ["DANGER", "RbSim"]
