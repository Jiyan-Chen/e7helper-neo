"""真机：runtime + 场景/弹窗的端到端测试。启用方式：E7_DEVICE_TESTS=1 uv run pytest -m device

前提：游戏停在大厅、没有弹窗（否则跳过）。全程只点入口、返回和「取消」，不会刷新或购买：
- 大厅按返回键 → 「确定要结束游戏吗？」 → dismiss_popups 点取消；
- 大厅 → 秘密商店 → 返回 → 大厅（不点立即更新）；
- 大厅 → 圣域 → 「?」说明弹窗 → 遮罩检测 + 返回键关闭 → 返回大厅；
- 竞技场 → 铃铛通知面板 → 返回键关闭 → 返回大厅。
途中如果网络超时弹出「点击重试」，wait_scene / tap_until 会自动重试。
"""

import os

import pytest

from e7helper.core.runtime import Humanize, Runtime

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(os.environ.get("E7_DEVICE_TESTS") != "1", reason="未设置 E7_DEVICE_TESTS=1"),
]

LOBBY_SANCTUARY = (70, 230)  # 大厅左侧「圣域」
LOBBY_ARENA = (1500, 487)  # 大厅右侧「竞技场」
SANCTUARY_HELP = (248, 42)  # 圣域标题旁的「?」
NOTICE_BELL = (1258, 40)  # 顶栏铃铛


@pytest.fixture(scope="module")
def ctl(tmp_path_factory):
    from e7helper.device import connect

    with connect() as device, Runtime(device, humanize=Humanize(delay=(0.3, 0.6)),
                                      debug_root=tmp_path_factory.mktemp("debug")) as rt:
        c = rt.make_controller()
        if not c.detect().is_("lobby"):
            pytest.skip("游戏不在大厅（或有弹窗），跳过")
        yield c
        # 无论成败都尽量回到大厅
        try:
            c.wait_scene("lobby", timeout=5)
        except Exception:
            for _ in range(3):
                state = c.detect()
                if state.is_("lobby"):
                    break
                if state.popup:
                    c.dismiss_popups(state=state)
                elif state.scene not in (None, "lobby"):
                    c.tap_until("back", "lobby")


def test_exit_dialog_cancelled(ctl):
    ctl.back()
    state = ctl.wait_until(lambda f: (s := ctl.detect(f)).popup and s, timeout=5, what="结束游戏确认框")
    assert state.popup == "confirm"
    assert ctl.dismiss_popups(state=state) == ["confirm"]
    assert ctl.wait_scene("lobby", timeout=5, dismiss=False).is_("lobby")


def test_secret_shop_round_trip(ctl):
    # 进秘密商店要等服务器响应，网络慢时会弹「网络连接异常 / 点击重试」，tap_until 会自动重试
    ctl.tap_until("lobby/secret_shop", "secret_shop")
    ctl.tap_until("back", "lobby")


def test_sanctuary_help_popup(ctl):
    ctl.tap_until(LOBBY_SANCTUARY, "sanctuary")
    ctl.tap(*SANCTUARY_HELP)
    state = ctl.wait_until(lambda f: (s := ctl.detect(f)).popup and s, timeout=5, what="说明弹窗")
    assert state.popup == "obscured"
    assert ctl.dismiss_popups(state=state) == ["obscured"]
    assert ctl.detect().is_("sanctuary")
    ctl.tap_until("back", "lobby")


def test_arena_notice_panel(ctl):
    ctl.tap_until(LOBBY_ARENA, "arena")
    ctl.tap(*NOTICE_BELL)
    state = ctl.wait_until(lambda f: (s := ctl.detect(f)).popup and s, timeout=5, what="通知面板")
    assert state.popup == "notice"
    assert ctl.dismiss_popups(state=state) == ["notice"]
    assert ctl.detect().is_("arena")
    ctl.tap_until("back", "lobby")
