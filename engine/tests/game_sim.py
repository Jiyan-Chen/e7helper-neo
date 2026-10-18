"""测试用的「游戏模拟器」：用 fixtures 截图当画面，按点击位置 / 返回键切换画面。

点击了危险按钮（确认刷新、确认退出）会进入 DANGER 画面并记录下来，测试据此断言从没点过。
"""

from __future__ import annotations

import itertools
from pathlib import Path

import cv2
import numpy as np

from e7helper.core.geometry import Rect, Scaler
from e7helper.core.imageio import read_image
from e7helper.device import Device

FIXTURES = Path(__file__).parent / "fixtures"
DANGER = "DANGER"
BACK = "back"
LOADING = "LOADING"  # 进游戏时的黑屏加载

CANCEL = Rect(565, 545, 200, 60)
CONFIRM = Rect(833, 545, 200, 60)
LOBBY_EXIT_CANCEL = Rect(543, 538, 246, 74)
LOBBY_EXIT_CONFIRM = Rect(812, 538, 246, 74)

# 画面 -> [(点击区域 或 "back", 目标画面)]
TRANSITIONS: dict[str, list[tuple[Rect | str, str]]] = {
    "lobby": [(Rect(26, 400, 92, 70), "secret_shop"), (Rect(1480, 629, 70, 41), "shop"), (BACK, "lobby_exit_confirm")],
    "lobby_exit_confirm": [(LOBBY_EXIT_CANCEL, "lobby"), (LOBBY_EXIT_CONFIRM, DANGER), (BACK, "lobby")],
    "secret_shop": [(Rect(28, 18, 38, 44), "lobby"), (Rect(270, 800, 130, 48), "secret_shop_refresh_confirm"),
                    (BACK, "lobby")],
    "secret_shop_refresh_confirm": [(CANCEL, "secret_shop"), (CONFIRM, DANGER), (BACK, "secret_shop")],
    "sanctuary": [(Rect(28, 18, 38, 44), "lobby"), (Rect(225, 20, 46, 46), "sanctuary_help"), (BACK, "lobby")],
    "sanctuary_help": [(BACK, "sanctuary")],
    "lobby_network_error": [(Rect(748, 538, 104, 32), "lobby")],
    "arena": [(Rect(28, 18, 38, 44), "lobby"), (BACK, "lobby")],
    "arena_notice": [(BACK, "arena")],
    "shop": [(Rect(28, 18, 38, 44), "lobby"), (BACK, "lobby")],
    # 断线重进（B10a）：断线框 → 公告窗 → 标题「连接中」→ 轻触画面开始 → 黑屏 → 大厅
    "lobby_disconnected": [(Rect(748, 540, 106, 30), "title_announcement")],
    "title_announcement": [(Rect(1394, 66, 62, 62), "title_connecting")],
    "title_start": [(Rect(728, 730, 144, 30), LOADING)],
    "title_start_forest": [(Rect(728, 730, 144, 30), LOADING)],
}

# 不用点击、截这么多次图后自己切换的画面（加载）
AUTO: dict[str, tuple[int, str]] = {
    "title_connecting": (4, "title_start"),
    LOADING: (4, "lobby"),
}

_counter = itertools.count()
_cache: dict[tuple[str, tuple[int, int]], np.ndarray] = {}


def load_fixture(name: str, size: tuple[int, int] = (1600, 900)) -> np.ndarray:
    key = (name, size)
    if key not in _cache:
        img = read_image(FIXTURES / f"{name}.png")
        if size != (1600, 900):
            img = cv2.resize(img, size, interpolation=cv2.INTER_AREA if size[0] < 1600 else cv2.INTER_CUBIC)
        _cache[key] = img
    return _cache[key]


class GameSim(Device):
    def __init__(self, screen: str = "lobby", size: tuple[int, int] = (1600, 900), drop_taps: int = 0):
        self.screen = screen
        self.drop_taps = drop_taps  # 前 N 次点击不生效（模拟网络慢 / 点击被吞）
        self.size = size
        self._name = f"sim-{next(_counter)}"
        self.taps: list[tuple[int, int, float]] = []  # 设备坐标
        self.swipes: list[tuple[int, int, int, int, float]] = []
        self.backs = 0
        self.history = [screen]
        self.screenshots = 0
        self.animating = 0  # 接下来这么多次截图带「动画」（整体亮度跳动），模拟界面切换后的飞入动画
        self.then: tuple[int, str] | None = None  # (n, screen)：再截 n 次图后自动切到 screen（模拟过渡结束）

    @property
    def name(self) -> str:
        return self._name

    @property
    def resolution(self) -> tuple[int, int]:
        return self.size

    def screenshot(self) -> np.ndarray:
        self.screenshots += 1
        if self.then is None and self.screen in AUTO:
            self.then = AUTO[self.screen]
        if self.then is not None:
            n, target = self.then
            if n <= 0:
                self._go(target)
                self.then = None
            else:
                self.then = (n - 1, target)
        if self.screen in (DANGER, LOADING):
            return np.zeros((self.size[1], self.size[0], 3), np.uint8)
        img = load_fixture(self.screen, self.size).copy()
        if self.animating > 0:
            self.animating -= 1
            img = cv2.add(img, np.full_like(img, 20 * (self.animating % 2)))
        return img

    def _go(self, target: str) -> None:
        self.screen = target
        self.history.append(target)

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        self.taps.append((x, y, duration))
        if self.drop_taps > 0:
            self.drop_taps -= 1
            return
        bx, by = Scaler(*self.size).to_base(x, y)
        for area, target in TRANSITIONS.get(self.screen, []):
            if isinstance(area, Rect) and area.x <= bx < area.right and area.y <= by < area.bottom:
                self._go(target)
                return

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        self.swipes.append((x1, y1, x2, y2, duration))

    def back(self) -> None:
        self.backs += 1
        for area, target in TRANSITIONS.get(self.screen, []):
            if area == BACK:
                self._go(target)
                return
