"""日常收取 · 竞技场（B05 的 arena_npc，B12 并入 daily）：界面识别、补旗框核对、自动战斗判定、
整个流程（用 fixtures + ArenaSim 离线模拟，日常收取只开竞技场这一项）。"""

import dataclasses
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from arena_sim import DANGER, ArenaSim
from game_sim import load_fixture

from e7helper.core.runtime import Humanize, Runtime, TaskStatus
from e7helper.core.scene import default_detector
from e7helper.core.vision import Vision
from e7helper.modules.base import ModuleContext
from e7helper.modules.daily import DailyConfig, DailyModule
from e7helper.modules.daily import arena_page as page
from e7helper.modules.daily.arena import AUTO_DIFF, Arena
from e7helper.modules.daily.arena_page import BuyDialog, PrepMode


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(scope="module")
def vision():
    return Vision.for_module("daily")


@pytest.fixture(scope="module")
def detector(vision):
    """带本模块场景和弹窗的识别器（setup 只需要 ctl.scenes）。"""
    det = default_detector(vision)
    ctx = ModuleContext(None, logging.getLogger("test"), Path("."), Path("."), vision=vision,
                        controller=SimpleNamespace(scenes=det))
    DailyModule(ctx)
    return det


def _frame(name, size=(1600, 900)):
    return load_fixture(name, size)


# ---------------------------------------------------------------- 场景识别


@pytest.mark.parametrize(("fixture", "scene", "popup"), [
    ("lobby", "lobby", None),
    ("arena", "arena", None),  # 模式选择
    ("arena_notice", "arena", "notice"),
    ("arena_defense_record", "arena_main", "arena_record"),
    ("arena_pvp", "arena_main", None),
    ("arena_npc", "arena_npc", None),
    ("arena_npc_selected", "arena_npc", None),
    ("arena_npc_3flags", "arena_npc", None),
    ("arena_prep_quick", "arena_prep", None),
    ("arena_prep_quick9", "arena_prep", None),
    ("arena_prep_battle", "arena_prep", None),
    ("arena_quick_cutin", None, "obscured"),
    ("arena_quick_victory", "arena_result", None),
    ("arena_battle_loading", None, None),
    ("arena_battle_manual", "arena_battle", None),
    ("arena_battle_auto", "arena_battle", None),
    ("arena_battle_victory", "arena_result", None),
    ("arena_buy_flags", "arena_npc", "arena_buy_flags"),
    ("arena_buy_flags_used", "arena_npc", "arena_buy_flags"),
    ("arena_prep_buy_flags", None, "arena_buy_flags"),  # 无旗时在准备界面点开始，弹出同一个补旗框
])
@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_scenes(detector, fixture, scene, popup, size):
    """有弹窗时只核对弹窗（被压暗的背景场景不重要）。"""
    state = detector.detect(_frame(fixture, size))
    assert state.popup == popup, state
    if popup is None:
        assert state.scene == scene, state


def test_builtin_arena_is_mode_select_only():
    """内置 arena 场景只认模式选择：竞技场里其他界面的标题也是「竞技场」。"""
    det = default_detector()
    assert det.detect(_frame("arena")).is_("arena")
    for name in ("arena_pvp", "arena_npc", "arena_prep_quick"):
        assert det.detect(_frame(name)).scene is None, name


# ---------------------------------------------------------------- 读数


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
@pytest.mark.parametrize(("fixture", "flags"), [
    ("arena_npc", 5), ("arena_npc_3flags", 3), ("arena_pvp", 5), ("arena_prep_quick9", 4),
    ("arena_prep_battle", 4), ("arena_buy_flags", 3), ("arena_defense_record", 5),
    ("arena_buy_flags_used", 4), ("arena_prep_buy_flags", 0),
])
def test_read_flags(vision, fixture, flags, size):
    assert page.read_flags(vision, _frame(fixture, size)) == flags


def test_read_flags_none_without_top_bar(vision):
    assert page.read_flags(vision, _frame("arena_battle_manual")) is None
    assert page.read_flags(vision, _frame("lobby")) is None


@pytest.mark.parametrize(("fixture", "mode", "left"), [
    ("arena_prep_quick", PrepMode.QUICK, 10),
    ("arena_prep_quick9", PrepMode.QUICK, 9),
    ("arena_prep_battle", PrepMode.BATTLE, None),
])
def test_read_prep(vision, fixture, mode, left):
    prep = page.read_prep(vision, _frame(fixture))
    assert (prep.mode, prep.quick_left) == (mode, left)


def test_read_prep_none_elsewhere(vision):
    for name in ("arena_npc_selected", "arena_battle_loading", "arena_quick_victory"):
        assert page.read_prep(vision, _frame(name)) is None


@pytest.mark.parametrize(("fixture", "victory"), [
    ("arena_quick_victory", True), ("arena_battle_victory", True), ("arena_npc", False), ("arena_battle_auto", False),
])
def test_is_victory(vision, fixture, victory):
    assert page.is_victory(vision, _frame(fixture)) is victory


# ---------------------------------------------------------------- 补旗框


def test_read_buy_dialog(vision):
    d = page.read_buy_dialog(vision, _frame("arena_buy_flags"))
    assert d.friendship and d.left_selected and not d.right_selected
    assert (d.cost, d.gain, d.hold) == (100, 5, 193_789)


def test_read_buy_dialog_on_prep(vision):
    """无旗时在准备界面点「快速对战」弹出的补旗框，内容一样。"""
    d = page.read_buy_dialog(vision, _frame("arena_prep_buy_flags"))
    assert d.friendship and d.left_selected and not d.right_selected and (d.cost, d.gain) == (100, 5)


def test_read_buy_dialog_used_today(vision):
    """今天补过后：友情点数不可选，游戏自动选中天空石，购买按钮仍然亮着——必须拒绝。"""
    d = page.read_buy_dialog(vision, _frame("arena_buy_flags_used"))
    assert not d.friendship and d.right_selected and not d.left_selected
    reason = Arena._check_dialog(SimpleNamespace(cfg=DailyConfig()), d)
    assert reason and "今天" in reason


def test_read_buy_dialog_none_elsewhere(vision):
    for name in ("arena_npc", "arena_defense_record", "secret_shop_buy_confirm", "lobby_exit_confirm"):
        assert page.read_buy_dialog(vision, _frame(name)) is None


def _swap_selection(frame):
    """合成图：把左边选项的亮边框挪到右边选项（同样的相对位置），模拟选中的是天空石。"""
    img = frame.copy()
    band = img[370:560, 470:772].copy()
    left_plain = img[370:560, 825:1127].copy()  # 右边选项没有边框的样子
    img[370:560, 825:1127] = band
    img[370:560, 470:772] = left_plain
    return img


def test_read_buy_dialog_skystone_selected(vision):
    d = page.read_buy_dialog(vision, _swap_selection(_frame("arena_buy_flags")))
    assert d.right_selected and not d.left_selected


def _dialog(**kw):
    m = SimpleNamespace(rect=None)
    base = dict(friendship=True, left_selected=True, right_selected=False, cost=100, gain=5, hold=1000, ok=m, cancel=m)
    return BuyDialog(**{**base, **kw})


@pytest.mark.parametrize(("kw", "keep", "ok"), [
    ({}, 0, True),
    ({"friendship": False}, 0, False),
    ({"right_selected": True}, 0, False),
    ({"left_selected": False}, 0, False),
    ({"cost": 30}, 0, False),
    ({"gain": 1}, 0, False),
    ({"hold": None}, 0, False),
    ({"hold": 99}, 0, False),
    ({"hold": 600}, 500, True),
    ({"hold": 599}, 500, False),
])
def test_check_dialog(kw, keep, ok):
    item = SimpleNamespace(cfg=DailyConfig(arena_friendship_keep=keep))
    assert (Arena._check_dialog(item, _dialog(**kw)) is None) is ok


# ---------------------------------------------------------------- 自动战斗图标


def test_auto_icon_still_vs_rotating(vision):
    """没开自动：图标静止、模板命中、帧差 0。开了自动：图标在转，转过的角度要么认不出（None），
    要么和静止图标相差 ≥ AUTO_DIFF——都不会被当成「静止」去点。"""
    manual = _frame("arena_battle_manual")
    still = page.auto_icon(vision, manual)
    assert still is not None and page.patch_diff(still, page.auto_icon(vision, manual.copy())) == 0
    sim = ArenaSim("arena_battle_auto", battle_shots=100)  # 模拟器每截一次图把图标转 40°
    for _ in range(8):  # 40°..320°
        p = page.auto_icon(vision, sim.screenshot())
        assert p is None or page.patch_diff(p, still) >= AUTO_DIFF, sim._angle
    # 实机录屏（B05）：开启后模板偶尔在某些角度命中，相邻两帧的差 20 以上；关闭时 0.3–0.7


# ---------------------------------------------------------------- 流程（ArenaSim）


ENTER = ["lobby", "arena", "arena_defense_record", "arena_pvp", "arena_npc"]  # 大厅 → NPC 页（首次进入有战斗记录）
LEAVE = ["arena", "lobby"]  # NPC 页 → 返回 → 模式选择 → 返回 → 大厅


@pytest.fixture(autouse=True)
def _fast_waits(monkeypatch):
    """模拟器的画面是静止的，等待时间缩短不影响流程，只为让测试快一些。"""
    import e7helper.core.runtime.controller as controller
    import e7helper.modules.daily.arena as arena

    monkeypatch.setattr(controller, "SETTLE_TIME", 0.1)
    monkeypatch.setattr(controller, "POPUP_SETTLE", 0.1)
    monkeypatch.setattr(arena, "VERIFY_TIMEOUT", 1.0)
    monkeypatch.setattr(arena, "POPUP_GRACE", 0.3)
    monkeypatch.setattr(arena, "START_GRACE", 1.0)
    monkeypatch.setattr(arena, "VICTORY_WAIT", 0.3)


def _config(**cfg):
    """日常收取只开竞技场这一项。"""
    return DailyConfig(**{"mail": False, "forest": False, "covenant": False, "shop": False, **cfg})


def _run(sim, tmp_path, monkeypatch, *, timeout=120, **cfg):
    """旗帜数和快速对战剩余次数取模拟器的值（截图上画的是固定数字）。"""
    import e7helper.modules.daily.arena as arena

    monkeypatch.setattr(Arena, "_read_flags", lambda self, frame: sim.flags)
    orig = page.read_prep

    def read_prep(vision, frame):
        p = orig(vision, frame)
        if p is not None and p.mode is PrepMode.QUICK:
            p = dataclasses.replace(p, quick_left=sim.quick_left)
        return p

    monkeypatch.setattr(arena.page, "read_prep", read_prep)
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off(), debug_root=tmp_path / "debug",
                 seed=1) as rt:
        return rt.run_task(DailyModule, _config(**cfg), timeout=timeout)


def _data(tmp_path):
    return tmp_path / "data" / "modules" / "daily"


def _history(tmp_path):
    path = _data(tmp_path) / "history.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _totals(tmp_path):
    path = _data(tmp_path) / "stats.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _ledger_done(tmp_path):
    path = _data(tmp_path) / "ledger.json"
    return json.loads(path.read_text(encoding="utf-8"))["done"] if path.exists() else {}


def test_dry_run_from_lobby_stops_at_prep(tmp_path, monkeypatch):
    """dry-run（默认）：大厅 → 模式选择 → 关战斗记录 → NPC页 → 选第一行 → 挑战 → 准备界面 → 返回大厅；不点开始。"""
    sim = ArenaSim("lobby")
    result = _run(sim, tmp_path, monkeypatch)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert DANGER not in sim.history and sim.starts == 0 and sim.buys == 0
    assert sim.history == ENTER + ["arena_npc_selected", "arena_prep_quick", "arena_npc_selected"] + LEAVE
    run = _history(tmp_path)[-1]
    assert run["dry_run"] and run["battles"] == [] and run["flags_start"] == 5
    assert "快速对战" in run["would"][0] and "dry-run" in run["items"]["arena"]
    assert _totals(tmp_path) is None  # dry-run 不计入累计


def test_dry_run_reads_real_numbers(tmp_path):
    """不替换读数：真的 OCR 顶栏旗帜和快速对战剩余次数。"""
    sim = ArenaSim("arena_npc")
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off(), debug_root=tmp_path / "debug") as rt:
        result = rt.run_task(DailyModule, _config(), timeout=60)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    run = _history(tmp_path)[-1]
    assert run["flags_start"] == 5 and "剩余 10" in run["would"][0]
    assert sim.starts == 0 and sim.screen == "lobby"


def test_dry_run_quick_exhausted_switches_to_battle(tmp_path, monkeypatch):
    sim = ArenaSim("arena_npc", quick_left=0)
    result = _run(sim, tmp_path, monkeypatch)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.mode == "battle" and sim.starts == 0
    assert "普通战斗" in _history(tmp_path)[-1]["would"][0]


def test_dry_run_switches_back_to_quick(tmp_path, monkeypatch):
    sim = ArenaSim("arena_npc", mode="battle", quick_left=3)
    result = _run(sim, tmp_path, monkeypatch)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.mode == "quick" and sim.starts == 0


def test_dry_run_no_flags_does_not_open_buy_dialog(tmp_path, monkeypatch):
    sim = ArenaSim("lobby", flags=0)
    result = _run(sim, tmp_path, monkeypatch, arena_buy_flags=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.history == ENTER + LEAVE
    assert _history(tmp_path)[-1]["would"] == ["用友情点数补旗"]


def test_dry_run_probe_buy_dialog_only_cancels(tmp_path, monkeypatch):
    sim = ArenaSim("lobby", flags=0)
    result = _run(sim, tmp_path, monkeypatch, arena_buy_flags=True, arena_probe_dialogs=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.history == ENTER + ["arena_buy_flags", "arena_npc"] + LEAVE and sim.buys == 0
    assert "100 友情点数补 5 面旗帜" in _history(tmp_path)[-1]["would"][0]
    assert _ledger_done(tmp_path) == {}


def test_no_flags_without_buy_stops(tmp_path, monkeypatch):
    sim = ArenaSim("lobby", flags=0, start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.history == ENTER + LEAVE
    assert _history(tmp_path)[-1]["items"]["arena"] == "旗帜用完（打了 0 场）"


def test_live_quick_battles_until_flags_run_out(tmp_path, monkeypatch):
    sim = ArenaSim("lobby", flags=3, start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.starts == 3 and sim.flags == 0 and sim.quick_left == 7 and sim.auto_taps == 0
    assert sim.screen == "lobby"
    run = _history(tmp_path)[-1]
    assert [b["mode"] for b in run["battles"]] == ["quick"] * 3 and all(b["victory"] for b in run["battles"])
    assert run["flags_spent"] == 3 and run["flags_end"] == 0 and run["items"]["arena"] == "旗帜用完（打了 3 场）"
    assert _totals(tmp_path)["battles"] == 3 and _totals(tmp_path)["wins"] == 3


def test_live_quick_then_battle_with_auto(tmp_path, monkeypatch):
    """快速对战只剩 1 次：第 1 场快速，之后改打普通战斗；第一次普通战斗点开自动，之后游戏记住了自动。"""
    sim = ArenaSim("arena_npc", flags=3, quick_left=1, start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.battles == ["quick", "battle", "battle"] and sim.auto_taps == 1 and sim.flags == 0
    run = _history(tmp_path)[-1]
    assert [b["mode"] for b in run["battles"]] == ["quick", "battle", "battle"]
    assert _totals(tmp_path)["quick_battles"] == 1


def test_live_buy_flags_once(tmp_path, monkeypatch):
    sim = ArenaSim("arena_npc", flags=1, start="ok", buy="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, arena_buy_flags=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.buys == 1 and sim.starts == 6 and sim.flags == 0
    run = _history(tmp_path)[-1]
    assert run["flag_buys"] == 1 and run["friendship_spent"] == 100 and len(run["battles"]) == 6
    assert "本次已补旗 1 次" in run["items"]["arena"]
    assert _totals(tmp_path)["last_flag_buy"] is not None
    assert "arena_buy" in _ledger_done(tmp_path)


def test_bought_today_ledger_skips_buy_dialog(tmp_path, monkeypatch):
    """账本记了今天补过旗：旗帜用完就结束，不再打开补旗框。"""
    sim = ArenaSim("arena_npc", flags=1, start="ok", buy="ok")
    _run(sim, tmp_path, monkeypatch, dry_run=False, arena_buy_flags=True)
    sim = ArenaSim("arena_npc", flags=1, start="ok", buy="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, arena_buy_flags=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.buys == 0 and sim.starts == 1 and "arena_buy_flags" not in sim.history
    assert "今天已经补过旗" in _history(tmp_path)[-1]["items"]["arena"]


def test_live_buy_not_applied_stops(tmp_path, monkeypatch):
    sim = ArenaSim("arena_npc", flags=0, buy="eat")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, arena_buy_flags=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.buys == 1 and "没有增加" in _history(tmp_path)[-1]["items"]["arena"]


def test_live_wrong_selection_never_buys(tmp_path, monkeypatch):
    """补旗框选中的是天空石：点左边选项后仍不对，就点取消并结束，从不点购买。"""
    import e7helper.modules.daily.arena as arena

    sim = ArenaSim("arena_npc", flags=0, buy="danger")
    orig = page.read_buy_dialog
    monkeypatch.setattr(arena.page, "read_buy_dialog",
                        lambda v, f: (d := orig(v, f)) and dataclasses.replace(d, left_selected=False,
                                                                               right_selected=True))
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, arena_buy_flags=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.buys == 0 and DANGER not in sim.history and sim.screen == "lobby"
    assert "选中的是天空石" in _history(tmp_path)[-1]["items"]["arena"]
    assert _ledger_done(tmp_path) == {}  # 友情点数选项可用，只是没选中：不记「今天补过」


def test_live_bought_today_never_buys(tmp_path, monkeypatch):
    """今天已补过：补旗框里选中的是天空石，点取消并结束，从不点购买；账本记下今天不用再看。"""
    sim = ArenaSim("arena_npc", flags=0, buy="danger", bought_today=True)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, arena_buy_flags=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.buys == 0 and DANGER not in sim.history and sim.screen == "lobby"
    assert "今天可能已经补过" in _history(tmp_path)[-1]["items"]["arena"]
    assert "arena_buy" in _ledger_done(tmp_path)


def test_live_max_battles(tmp_path, monkeypatch):
    sim = ArenaSim("arena_npc", flags=5, start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, arena_max_battles=2)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.starts == 2 and sim.flags == 3


def test_live_swallowed_start_is_not_counted(tmp_path, monkeypatch):
    """点开始连续被吞 3 次：这一项算失败（任务失败），没有计场次，回到大厅。"""
    sim = ArenaSim("arena_npc", flags=3, start="eat")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.FAILED and "竞技场" in result.error
    run = _history(tmp_path)[-1]
    assert sim.starts == 3 and run["battles"] == [] and run["failures"] == 3
    assert "连续失败 3 次" in run["items"]["arena"] and sim.screen == "lobby"


def test_live_double_flag_spend_is_anomaly(tmp_path, monkeypatch):
    sim = ArenaSim("arena_npc", flags=3, start="ok")
    orig = sim._start

    def start_twice():
        orig()
        sim.flags -= 1

    sim._start = start_twice
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.FAILED and "ArenaAnomaly" in result.error
    assert sim.starts == 1 and _history(tmp_path)[-1]["flags_spent"] == 2


def test_live_manual_battle_gets_auto(tmp_path, monkeypatch):
    sim = ArenaSim("arena_npc", flags=1, mode="battle", quick_left=0, start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.auto_taps == 1 and sim.battles == ["battle"]


def test_start_from_prep_and_result(tmp_path, monkeypatch):
    """从竞技场里的任一界面开始：先回到大厅，再按日常收取的顺序进竞技场。"""
    for screen in ("arena_prep_quick", "arena_quick_victory", "arena_pvp", "arena"):
        sim = ArenaSim(screen, record_popup=False)
        result = _run(sim, tmp_path, monkeypatch)
        assert result.status is TaskStatus.SUCCEEDED, (screen, result.error)
        assert sim.starts == 0 and "arena_npc_selected" in sim.history and sim.screen == "lobby", screen


def test_arena_runs_after_other_items(tmp_path, monkeypatch):
    """五项都开：竞技场排在最后（ArenaSim 没有邮件 / 圣域 / 召唤 / 商店界面，前四项换成只记顺序）。"""
    from e7helper.modules.daily import StopItem

    order = []

    def fake(key):
        def run(self):
            order.append(key)
            raise StopItem("跳过")
        return run

    for key in ("mail", "forest", "covenant", "shop"):
        monkeypatch.setattr(DailyModule, f"_{key}", fake(key))
    sim = ArenaSim("lobby", flags=1, start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, mail=True, forest=True, covenant=True, shop=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    run = _history(tmp_path)[-1]
    assert order == ["mail", "forest", "covenant", "shop"]
    assert list(run["items"]) == ["mail", "forest", "covenant", "shop", "arena"]
    assert run["items"]["arena"] == "旗帜用完（打了 1 场）" and sim.starts == 1


def test_rotated_icon_helper_changes_pixels():
    sim = ArenaSim("arena_battle_auto")
    a, b = sim.screenshot(), sim.screenshot()
    assert cv2.absdiff(a[14:64, 1382:1436], b[14:64, 1382:1436]).mean() > 1
    assert np.array_equal(a[200:800, 200:1200], b[200:800, 200:1200])
