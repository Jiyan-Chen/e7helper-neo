"""内置的通用场景和弹窗（模板都在 assets/common/cn/）。

模块要识别自己的界面时，在 setup() 里 `self.ctl.scenes.add_scene(Scene(...), replace=True)`
（识别器由 Runtime 共享、每次启动任务都会调 setup），模板用限定引用 `<module_id>:<name>`。
"""

from __future__ import annotations

from .model import Dismiss, Popup, Scene

SCENES: tuple[Scene, ...] = (
    Scene("lobby", ("lobby/shop", "lobby/secret_shop"), note="大厅"),
    Scene("secret_shop", ("title/secret_shop",), note="秘密商店"),
    Scene("shop", ("title/shop",), note="商店"),
    # 竞技场里的模式选择、交战对手列表、准备界面标题都是「竞技场」，所以另加普通竞技场卡片的文字（B05）
    Scene("arena", ("title/arena", "arena/mode_arena"), note="竞技场（模式选择）"),
    Scene("sanctuary", ("title/sanctuary",), note="圣域"),
)

POPUPS: tuple[Popup, ...] = (
    # 断线时压在当前界面上，只有「点击关闭」一个选项，关闭后游戏回到标题画面。
    # 重新进游戏只需要点屏幕、不用输入账号（B10a），所以自动关闭；reload=True 让 Controller 等游戏重新加载完。
    Popup("disconnected", ("popup/disconnected", "popup/tap_close"), Dismiss.tap("popup/tap_close"),
          reload=True, note="与服务器的连接中断，将返回游戏初始界面。/ 点击关闭"),
    # 回到标题画面（或冷启动）时自动弹出的公告窗。关掉后标题画面还要「连接中」十几秒，所以也是 reload
    Popup("announcement", ("popup/announce_close", "popup/announce_faq"), Dismiss.tap("popup/announce_close"),
          reload=True, note="登录公告窗（最新消息 / 活动专区 / 常见问答）"),
    # 游戏标题画面。协议勾选框保持游戏记住的状态，只点「轻触画面开始」这行字（下面一行是协议链接，不能点）
    Popup("title_start", ("title/start",), Dismiss.tap("title/start"),
          reload=True, note="游戏标题画面：轻触画面开始"),
    # 请求超时/断网时出现，只有「点击重试」一个选项。重试会重发刚才那个请求（进商店、刷新、购买……），
    # 也就是任务已经决定要做的操作，所以自动重试是安全的；需要精确计数的任务应在重试后重新核对状态。
    Popup("network", ("popup/network_error", "popup/network_retry"), Dismiss.tap("popup/network_retry"),
          note="网络连接异常，请重新连接。/ 点击重试"),
    Popup("notice", ("popup/notice",), Dismiss.back(), note="右上角铃铛打开的通知中心面板（不压暗背景）"),
    # 通用二次确认框：结束游戏、消耗天空石立即更新、购买等都长这样。
    # 自动处理一律点「取消」：任务自己打开的确认框必须在调用 dismiss_popups 之前自行处理。
    Popup("confirm", ("dialog/cancel", "dialog/confirm"), Dismiss.tap("dialog/cancel"),
          note="取消/确认 二次确认框，自动关闭时点取消"),
)
