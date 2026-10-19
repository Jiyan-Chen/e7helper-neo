"""自定义流程的安全规则（B11，用户确认：遇到确认框一律点取消，禁止点确认）。

1. 流程运行时只自动处理这几类弹窗（其余弹窗、遮罩都不碰，免得打断玩家自己的流程）：
   - 断线重进（disconnected / announcement / title_start）、网络重试（network）；
   - 「取消 / 确认」二次确认框和各内置模块认识的消耗框：一律点取消（GUARD_POPUPS，排在最前判定）。
2. 每次点击 / 滑动之前，在当前画面上找已知的「确认 / 购买」按钮（FORBIDDEN_BUTTONS），
   落点碰到就拦下并停止流程，绝不点下去。
"""

from __future__ import annotations

from e7helper.core.scene import Dismiss, Popup

# 自动处理的内置弹窗：断线重进三件套 + 网络重试
SAFE_POPUPS = ("disconnected", "announcement", "title_start", "network")

GUARD_POPUPS: tuple[Popup, ...] = (
    Popup("flow_guard_shop_buy", ("secret_shop:dialog/buy_title", "dialog/cancel"), Dismiss.tap("dialog/cancel"),
          note="秘密商店购买框（自定义流程：点取消）"),
    Popup("flow_guard_arena_buy", ("daily:arena/buy/title", "daily:arena/buy/cancel"), Dismiss.tap("daily:arena/buy/cancel"),
          note="竞技场购买旗帜（自定义流程：点取消）"),
    Popup("flow_guard_energy", ("repeat_battle:energy/title", "repeat_battle:energy/cancel"),
          Dismiss.tap("repeat_battle:energy/cancel"), note="行动力不足 / 购买行动力（自定义流程：点取消）"),
    Popup("flow_guard_core", ("repeat_battle:core/title", "repeat_battle:core/cancel"),
          Dismiss.tap("repeat_battle:core/cancel"), note="购买光谱核心（自定义流程：点取消）"),
    Popup("flow_guard_auto_start", ("repeat_battle:auto/confirm_text", "dialog/cancel"), Dismiss.tap("dialog/cancel"),
          note="是否开始托管战斗（自定义流程：点取消）"),
    # 通用二次确认框（结束游戏、天空石立即更新、各种购买确认……）
    Popup("flow_guard_confirm", ("dialog/cancel", "dialog/confirm"), Dismiss.tap("dialog/cancel"),
          note="取消 / 确认框（自定义流程：一律点取消）"),
)

HANDLED_POPUPS = frozenset(SAFE_POPUPS) | {p.name for p in GUARD_POPUPS}

# 流程绝不能点的按钮（模板用限定引用，在内置识别器里找）
FORBIDDEN_BUTTONS: dict[str, str] = {
    "common:dialog/confirm": "确认框的「确认」",
    "secret_shop:dialog/buy_ok": "秘密商店的「购买」",
    "daily:arena/buy/ok": "竞技场补旗的「购买」",
    "repeat_battle:energy/buy": "行动力的「购买」",
    "repeat_battle:core/buy": "光谱核心的「购买」",
    "daily:summon/again": "召唤结果的「再召唤一次」",
}
