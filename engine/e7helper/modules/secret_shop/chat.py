"""换世界频道（B12 用户意见：连续几次刷不出目标就换个频道，玩家的玄学）。

游戏里的做法（B12 实机）：顶栏聊天图标 → 聊天面板（停在「骑士团」页签时先点左边的「频道」）
→ 标题「★频道#69」→ 右上 ⇆ → 「变更频道」框 → 点输入框 → 输入频道号（1–9999）→ 点框里的「输入」
→ 标题变成「频道#70」→ 返回键关掉聊天（一次就关掉整个面板）。

规则：换到当前频道号 +1（9999 之后回到 1，用户选）。只点上面这些位置；底部发消息的输入框和「输入」
绝不碰。输入框里的数字核对过才点「输入」，标题变成新频道号才算换好。不花任何资源。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from e7helper.core.geometry import Rect
from e7helper.core.runtime import Controller
from e7helper.core.scene import Dismiss, Popup, SceneDetector
from e7helper.core.vision import Vision

POPUP_CHAT = "shop_chat"  # 聊天面板
POPUP_CHANGE = "shop_chat_change"  # 「变更频道」框

TITLE = Rect(895, 14, 190, 56)  # 聊天面板标题「★频道#69」/「骑士团频道」
TAB_CHANNEL = Rect(910, 78, 185, 50)  # 「频道」页签
FIELD = Rect(948, 203, 326, 50)  # 「变更频道」框的输入框
MAX_CHANNEL = 9999
WAIT = 5.0
POLL = 0.15

_CHANNEL = re.compile(r"频道\s*#\s*(\d{1,4})")


class ChannelError(RuntimeError):
    """换频道没换成（界面没出现、数字没输对、标题没变）。不影响刷商店，调用方记一次失败。"""


@dataclass(frozen=True)
class ChatTitle:
    guild: bool  # 停在「骑士团」页签
    channel: int | None  # 「频道」页签的频道号


def register(sc: SceneDetector) -> None:
    """聊天面板 / 变更频道框登记成弹窗：任务意外停在这里时按返回键关掉（一次关掉整个面板）。"""
    sc.add_popup(Popup(POPUP_CHAT, ("secret_shop:chat/settings",), Dismiss.back(), note="聊天面板（返回键关闭）"),
                 replace=True, first=True)
    sc.add_popup(Popup(POPUP_CHANGE, ("secret_shop:chat/change_title",), Dismiss.back(),
                       note="变更频道（返回键关闭，不换频道）"), replace=True, first=True)


def read_title(vision: Vision, frame: np.ndarray) -> ChatTitle | None:
    text = vision.ocr.read_line(frame, TITLE).text.replace(" ", "")
    if "骑士团" in text:
        return ChatTitle(True, None)
    m = _CHANNEL.search(text)
    return ChatTitle(False, int(m.group(1))) if m else None


def next_channel(n: int) -> int:
    return n % MAX_CHANNEL + 1


def read_field(vision: Vision, frame: np.ndarray) -> str:
    return vision.ocr.read_line(frame, FIELD).text.replace(" ", "")


class ChannelSwitcher:
    def __init__(self, ctl: Controller, vision: Vision, log):
        self.ctl, self.vision, self.log = ctl, vision, log

    def switch(self, target: int | None = None) -> tuple[int, int]:
        """在商店（或大厅）里打开聊天，换到 target（默认当前 +1），关掉聊天。返回（原频道, 新频道）。

        出错时也会尽量关掉聊天面板（返回键），再抛 ChannelError。
        """
        try:
            current = self._open_channel_tab()
            new = target if target is not None else next_channel(current)
            self._change(new)
            return current, new
        finally:
            self._close()

    # ------------------------------------------------------------ 步骤

    def _open_channel_tab(self) -> int:
        ctl = self.ctl
        icon = self._wait(lambda f: ctl.find("chat/open", f), timeout=3.0)
        if icon is None:
            raise ChannelError("没找到顶栏的聊天图标")
        ctl.tap_match(icon, ref="chat/open", delay=False)
        title = self._wait(lambda f: t if ctl.find("chat/settings", f)
                           and (t := read_title(self.vision, f)) else None)
        if title is None:
            raise ChannelError("点了聊天图标，聊天面板没出现")
        if title.guild:
            self.log.info("聊天停在骑士团页签，切到频道")
            ctl.tap_rect(TAB_CHANNEL, delay=False)
            title = self._wait(lambda f: t if (t := read_title(self.vision, f)) and not t.guild else None)
            if title is None:
                raise ChannelError("点了「频道」页签，没有切过去")
        if title.channel is None:
            raise ChannelError("读不出当前频道号")
        return title.channel

    def _change(self, new: int) -> None:
        ctl = self.ctl
        switch = self._wait(lambda f: ctl.find("chat/switch", f))
        if switch is None:
            raise ChannelError("没找到换频道的图标")
        ctl.tap_match(switch, ref="chat/switch", delay=False)
        if self._wait(lambda f: ctl.find("chat/change_title", f)) is None:
            raise ChannelError("「变更频道」框没出现")
        ctl.tap_rect(FIELD, delay=False)
        ctl.sleep(0.4)
        ctl.input_text(str(new), delay=False)
        typed = self._wait(lambda f: s if (s := read_field(self.vision, f)) == str(new) else None)
        if typed is None:
            raise ChannelError(f"输入框里不是 {new}（读到「{read_field(self.vision, ctl.screenshot())}」），不提交")
        ok = ctl.find("chat/change_ok", ctl.last_frame)
        if ok is None:
            raise ChannelError("没找到「变更频道」框里的「输入」")
        ctl.tap_match(ok, ref="chat/change_ok", delay=False)
        if self._wait(lambda f: True if (t := read_title(self.vision, f)) and t.channel == new else None) is None:
            raise ChannelError(f"点了「输入」，标题没变成频道#{new}")

    def _close(self) -> None:
        """聊天还开着就按一次返回键（一次关掉整个面板，包括变更频道框）。"""
        ctl = self.ctl
        frame = ctl.screenshot()
        if ctl.find("chat/settings", frame) or ctl.find("chat/change_title", frame):
            ctl.back(delay=False)
            self._wait(lambda f: None if ctl.find("chat/settings", f) else True)

    def _wait(self, probe: Callable[[np.ndarray], object], timeout: float = WAIT):
        ctl = self.ctl
        deadline = time.monotonic() + timeout
        while True:
            result = probe(ctl.screenshot())
            if result:
                return result
            if time.monotonic() >= deadline:
                return None
            ctl.sleep(POLL)
