"""秘密商店模拟器：在 GameSim 的基础上模拟两份商品列表、滑动、购买/刷新确认框和扣费。

- 列表 A：secret_shop / secret_shop_scrolled；列表 B：secret_shop_relist / secret_shop_relist_scrolled
- 刷新成功后在 A、B 之间切换，回到列表顶部
- 购买确认框只有 B 的第一行（灿烂精髓长袍 360,000）的截图，所以只有那一行能打开确认框
- confirm 决定点「确认」后的行为：
    "danger"（默认）：进入 DANGER，测试断言从没发生
    "ok"：扣费并完成操作
    "eat"：点击被吞，确认框关闭但没有扣费
    "network"：先出现网络异常弹窗，点重试后扣费并完成
    "double"：扣两次费（模拟重试导致请求重复）
- 天空石/金币不画在截图上，测试用 resources() 替换模块的读数函数
- 聊天（B12 换世界频道）：列表右上的聊天图标 → 聊天面板（chat_tab="guild" 时停在骑士团页签）→ ⇆ →
  「变更频道」框 → 点输入框 → input_text → 点框里的「输入」→ 频道变了；返回键关掉整个面板回到列表。
  截图是实机的：频道只有 69 和 70 两个（69 → 70 → 69）。type_text=False 时打字没进输入框。
  点到底部发消息的输入框 / 「输入」进入 DANGER。
"""

from __future__ import annotations

from game_sim import BACK, DANGER, GameSim

from e7helper.core.geometry import Rect, Scaler
from e7helper.modules.secret_shop.page import Resources

LISTS = {"A": ("secret_shop", "secret_shop_scrolled"), "B": ("secret_shop_relist", "secret_shop_relist_scrolled")}
REFRESH_CONFIRM = "secret_shop_refresh_confirm"
BUY_CONFIRM = "secret_shop_buy_confirm"
NETWORK = "lobby_network_error"

ENTRY = Rect(26, 400, 92, 70)
REFRESH_BTN = Rect(85, 790, 375, 75)
BUY_ROW1 = Rect(1330, 172, 225, 66)  # 列表顶部第一行的购买按钮
REFRESH_CANCEL, REFRESH_OK = Rect(565, 545, 200, 60), Rect(833, 545, 200, 60)
BUY_CANCEL, BUY_OK = Rect(480, 600, 245, 72), Rect(750, 600, 375, 72)
NETWORK_RETRY = Rect(748, 538, 104, 32)
CHAT_ICON = Rect(1452, 16, 54, 52)
CHAT_TAB_CHANNEL = Rect(910, 78, 185, 50)
CHAT_SWITCH = Rect(1356, 12, 62, 54)
CHAT_FIELD = Rect(948, 203, 326, 50)
CHAT_OK = Rect(1296, 198, 182, 58)
CHAT_SEND = Rect(966, 810, 620, 70)  # 底部发消息的输入框和「输入」
# (聊天状态, 频道) -> 截图
CHAT_SCREENS = {
    ("panel", 69): "shop_chat_channel", ("panel", 70): "shop_chat_switched",
    ("change", 69): "shop_chat_change", ("change", 70): "shop_chat_change70",
    ("focus", 69): "shop_chat_change_focus", ("focus", 70): "shop_chat_change70",
}
TYPED_SCREENS = {"70": "shop_chat_typed", "69": "shop_chat_typed69"}
BUY_PRICE = 360_000  # 灿烂精髓长袍


def _hit(r: Rect, x: int, y: int) -> bool:
    return r.x <= x < r.right and r.y <= y < r.bottom


class ShopSim(GameSim):
    def __init__(self, screen: str = "lobby", first_list: str = "B", confirm: str = "danger",
                 skystone: int = 1000, gold: int = 10_000_000, refresh_cost: int = 3, chat_tab: str = "channel",
                 type_text: bool = True, **kw):
        super().__init__(screen, **kw)
        self.list = first_list
        self.scrolled = False
        self.confirm = confirm
        self.skystone = skystone
        self.gold = gold
        self.refresh_cost = refresh_cost
        self.confirms = 0  # 点「确认」的次数
        self.pending: str | None = None  # 网络异常时挂起的操作
        self.chat_tab = chat_tab
        self.type_text = type_text
        self.chat: str | None = None  # None / panel / change / focus / typed
        self.channel = 69
        self.typed = ""
        self.channel_history: list[int] = []  # 换过去的频道
        if screen == "shop":
            self._show_list()

    def resources(self) -> Resources:
        return Resources(self.skystone, self.gold)

    def _show_list(self) -> None:
        self._go(LISTS[self.list][1 if self.scrolled else 0])

    @property
    def in_list(self) -> bool:
        return self.screen in LISTS["A"] + LISTS["B"]

    def _show_chat(self) -> None:
        if self.chat == "panel" and self.chat_tab == "guild":
            self._go("shop_chat_guild")
        elif self.chat == "typed":
            self._go(TYPED_SCREENS[self.typed])
        else:
            self._go(CHAT_SCREENS[(self.chat, self.channel)])

    def _tap_chat(self, bx: int, by: int) -> None:
        if _hit(CHAT_SEND, bx, by):
            self._go(DANGER)
        elif self.chat == "panel":
            if self.chat_tab == "guild":
                if _hit(CHAT_TAB_CHANNEL, bx, by):
                    self.chat_tab = "channel"
            elif _hit(CHAT_SWITCH, bx, by):
                self.chat = "change"
        elif self.chat == "change" and _hit(CHAT_FIELD, bx, by):
            self.chat = "focus"
        elif self.chat == "typed" and _hit(CHAT_OK, bx, by):
            self.channel = int(self.typed)
            self.channel_history.append(self.channel)
            self.chat, self.typed = "panel", ""
        if self.screen != DANGER:
            self._show_chat()

    def input_text(self, text: str) -> None:
        if self.chat == "focus" and self.type_text:
            self.chat, self.typed = "typed", text
            self._show_chat()

    def _complete(self, action: str) -> None:
        times = 2 if self.confirm == "double" else 1
        if action == "refresh":
            self.skystone -= self.refresh_cost * times
            self.list = "A" if self.list == "B" else "B"
            self.scrolled = False
        else:
            self.gold -= BUY_PRICE * times
        self._show_list()

    def _confirm(self, action: str) -> None:
        self.confirms += 1
        mode = self.confirm
        if mode == "danger":
            self._go(DANGER)
        elif mode == "eat":
            self._show_list()
        elif mode == "network":
            self.pending = action
            self._go(NETWORK)
        else:
            self._complete(action)

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        self.taps.append((x, y, duration))
        if self.drop_taps > 0:
            self.drop_taps -= 1
            return
        bx, by = Scaler(*self.size).to_base(x, y)
        s = self.screen
        if self.chat is not None:
            self._tap_chat(bx, by)
        elif s == "lobby" and _hit(ENTRY, bx, by):
            self._show_list()
        elif self.in_list:
            if _hit(CHAT_ICON, bx, by):
                self.chat = "panel"
                self._show_chat()
            elif _hit(REFRESH_BTN, bx, by):
                self._go(REFRESH_CONFIRM)
            elif _hit(BUY_ROW1, bx, by) and s == "secret_shop_relist":
                self._go(BUY_CONFIRM)
        elif s == REFRESH_CONFIRM:
            if _hit(REFRESH_CANCEL, bx, by):
                self._show_list()
            elif _hit(REFRESH_OK, bx, by):
                self._confirm("refresh")
        elif s == BUY_CONFIRM:
            if _hit(BUY_CANCEL, bx, by):
                self._show_list()
            elif _hit(BUY_OK, bx, by):
                self._confirm("buy")
        elif s == NETWORK and _hit(NETWORK_RETRY, bx, by):
            action, self.pending = self.pending, None
            self._complete(action)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        self.swipes.append((x1, y1, x2, y2, duration))
        if self.in_list:
            self.scrolled = y2 < y1
            self._show_list()

    def back(self) -> None:
        self.backs += 1
        if self.chat is not None:  # 一次关掉整个聊天面板
            self.chat, self.typed = None, ""
            self._show_list()
        elif self.in_list:
            self._go("lobby")
        elif self.screen in (REFRESH_CONFIRM, BUY_CONFIRM):
            self._show_list()


__all__ = ["BACK", "DANGER", "ShopSim"]
