"""场景识别与弹窗判定（fixtures：MuMu 1600x900 国服实机截图，2026-10-14 采集）。

- lobby / secret_shop / secret_shop_scrolled / shop / arena / sanctuary：普通场景
- lobby_exit_confirm：大厅按返回键弹出的「确定要结束游戏吗？」（取消/确认，遮罩盖住了大厅入口）
- secret_shop_refresh_confirm：立即更新的确认框（取消/确认）
- sanctuary_help：圣域「?」说明弹窗（没有关闭按钮，返回键关闭）——用遮罩检测兜底
- arena_notice：铃铛打开的通知中心面板（不压暗背景）
- lobby_network_error：大厅点秘密商店时网络超时弹出的「网络连接异常，请重新连接。/ 点击重试」
"""

import pytest
from game_sim import load_fixture

from e7helper.core.geometry import Rect
from e7helper.core.scene import (
    OBSCURED,
    Dismiss,
    DismissKind,
    Popup,
    Scene,
    SceneDetector,
    default_detector,
)
from e7helper.core.vision import Vision

# fixture -> (scene, popup)
EXPECTED = {
    "lobby": ("lobby", None),
    "lobby_exit_confirm": (None, "confirm"),
    "lobby_network_error": (None, "network"),
    "secret_shop": ("secret_shop", None),
    "secret_shop_scrolled": ("secret_shop", None),
    "secret_shop_refresh_confirm": ("secret_shop", "confirm"),
    "shop": ("shop", None),
    "arena": ("arena", None),
    "arena_notice": ("arena", "notice"),
    "sanctuary": ("sanctuary", None),
    "sanctuary_help": (None, OBSCURED),
}

OBSCURED_FIXTURES = {"secret_shop_refresh_confirm", "sanctuary_help"}


@pytest.fixture(scope="module")
def detector() -> SceneDetector:
    return default_detector()


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720), (1920, 1080)], ids=["1600x900", "1280x720", "1920x1080"])
@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_detect_fixture(detector, fixture, size):
    state = detector.detect(load_fixture(fixture, size))
    assert (state.scene, state.popup) == EXPECTED[fixture], str(state)
    assert state.obscured == (fixture in OBSCURED_FIXTURES)
    assert state.clear == (EXPECTED[fixture][1] is None)


def test_is_requires_no_popup(detector):
    state = detector.detect(load_fixture("secret_shop_refresh_confirm"))
    assert state.scene == "secret_shop"
    assert not state.is_("secret_shop")
    assert detector.detect(load_fixture("secret_shop")).is_("lobby", "secret_shop")


def test_confirm_popup_dismisses_with_cancel(detector):
    popup = detector.popup("confirm")
    assert popup.dismiss.kind is DismissKind.TAP and popup.dismiss.target == "dialog/cancel"
    assert detector.popup(OBSCURED).dismiss.kind is DismissKind.BACK


def test_detect_is_fast_enough(detector):
    frame = load_fixture("secret_shop_refresh_confirm")
    detector.detect(frame)
    assert detector.detect(frame).elapsed_ms < 200


def test_registration_rules():
    d = SceneDetector(Vision.for_module("common"), [Scene("a", "title/shop")])
    with pytest.raises(ValueError):
        d.add_scene(Scene("a", "title/arena"))
    d.add_scene(Scene("a", "title/arena"), replace=True)
    assert d.scene("a").all_of == ("title/arena",)
    d.add_scene(Scene("b", "title/shop"), first=True)
    assert [s.name for s in d.scenes] == ["b", "a"]
    with pytest.raises(ValueError):
        d.add_popup(Popup(OBSCURED, ("dialog/cancel",), Dismiss.back()))
    with pytest.raises(ValueError):
        Scene("empty", ())
    with pytest.raises(ValueError):
        Popup("p", ("dialog/cancel",), Dismiss.none())  # 不能自动关闭的必须 auto=False
    with pytest.raises(ValueError):
        Popup("p", ("dialog/cancel",), Dismiss.back(), text="x")  # text 需要 text_region


def test_none_of_excludes():
    v = Vision.for_module("common")
    d = SceneDetector(v, [Scene("not_secret", "top/skystone", none_of="title/secret_shop")], dim_probes=())
    assert d.detect(load_fixture("secret_shop")).scene is None
    assert d.detect(load_fixture("lobby")).scene == "not_secret"


def test_qualified_template_ref():
    """模块注册场景时用 module_id:name 引用自己的模板。"""
    d = SceneDetector(Vision.for_module("common"), [Scene("shop_by_module", "secret_shop:title")])
    assert d.detect(load_fixture("secret_shop")).scene == "shop_by_module"
    assert d.detect(load_fixture("lobby")).scene is None
    # 压暗检测也要能用限定引用找到模板
    state = d.detect(load_fixture("secret_shop_refresh_confirm"))
    assert state.scene == "shop_by_module" and state.obscured


def test_popup_text_condition_distinguishes_dialogs():
    """按钮相同的确认框，用 OCR 文字区分（结束游戏 vs 消耗天空石）。"""
    d = default_detector()
    d.add_popup(Popup("exit_game", ("dialog/cancel", "dialog/confirm"), Dismiss.tap("dialog/cancel"),
                      text="确定要结束游戏吗", text_region=Rect(500, 360, 600, 90)), first=True)
    assert d.detect(load_fixture("lobby_exit_confirm")).popup == "exit_game"
    assert d.detect(load_fixture("secret_shop_refresh_confirm")).popup == "confirm"
