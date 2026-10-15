"""B06 重复刷关：界面识别、托管设置核对、补行动力框核对、整个流程（用 fixtures + RbSim 离线模拟）。"""

import dataclasses
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from game_sim import load_fixture
from rb_sim import DANGER, HUNT_ROWS, TIER_CARDS, RbSim

from e7helper.core.geometry import Rect
from e7helper.core.runtime import Humanize, Runtime, TaskStatus
from e7helper.core.scene import default_detector
from e7helper.core.vision import Vision, normalize_text
from e7helper.modules.base import ModuleContext
from e7helper.modules.repeat_battle import RepeatBattleConfig, RepeatBattleModule, page
from e7helper.modules.repeat_battle.config import Hunt, Tier
from e7helper.modules.repeat_battle.page import AutoState, PrepMode


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(scope="module")
def vision():
    return Vision.for_module("repeat_battle")


@pytest.fixture(scope="module")
def detector(vision):
    det = default_detector(vision)
    ctx = ModuleContext(None, logging.getLogger("test"), Path("."), Path("."), vision=vision,
                        controller=SimpleNamespace(scenes=det))
    RepeatBattleModule(ctx)
    return det


def _frame(name, size=(1600, 900)):
    return load_fixture(name, size)


# ---------------------------------------------------------------- 场景识别


@pytest.mark.parametrize(("fixture", "scene", "popup"), [
    ("rb_lobby_no_auto", "lobby", None),
    ("rb_lobby_auto_running", "lobby", None),
    ("rb_lobby_auto_done", "lobby", None),
    ("rb_battle_menu", "rb_menu", None),
    ("rb_hunt_list", "rb_hunt", None),
    ("rb_hunt_list_golem", "rb_hunt", None),
    ("rb_hunt_list_end", "rb_hunt", None),
    ("rb_prep_quick", "rb_prep", None),
    ("rb_prep_quick_done", "rb_prep", None),
    ("rb_prep_battle", "rb_prep", None),
    ("rb_prep_battle_running", "rb_prep", None),
    ("rb_prep_norecord", "rb_prep", None),
    ("rb_auto_setup", None, "rb_auto_setup"),
    ("rb_auto_setup_checked", None, "rb_auto_setup"),
    ("rb_auto_setup_disabled", None, "rb_auto_setup"),
    ("rb_auto_sort", None, "rb_auto_setup"),
    ("rb_auto_confirm", None, "rb_auto_confirm"),  # 不能被内置 confirm 抢先（它也有 取消/确认）
    ("rb_auto_running", None, "rb_auto"),
    ("rb_auto_running_lobby", None, "rb_auto"),
    ("rb_auto_done", None, "rb_auto"),
    ("rb_auto_done_lobby", None, "rb_auto"),
    ("rb_auto_settling", None, "rb_auto"),
    ("rb_auto_settled", None, "rb_auto_settled"),
    ("rb_auto_claimed", None, "rb_auto"),
    ("rb_energy_low", None, "rb_energy"),
    ("rb_battle", "rb_battle", None),
    ("rb_clear", "rb_clear", None),
    ("rb_result", "rb_result", None),
    ("rb_after", "rb_after", None),
])
@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_scenes(detector, fixture, scene, popup, size):
    state = detector.detect(_frame(fixture, size))
    assert state.popup == popup, state
    if popup is None:
        assert state.scene == scene, state


# ---------------------------------------------------------------- 读数


@pytest.mark.parametrize(("fixture", "energy"), [
    ("rb_battle_menu", 82), ("rb_hunt_list", 102), ("rb_hunt_list_end", 23), ("rb_lobby_auto_done", 82),
    ("rb_lobby_auto_running", 7), ("rb_lobby_no_auto", 22), ("rb_prep_battle", 102), ("rb_prep_battle_running", 7),
    ("rb_prep_quick", 59),
])
def test_read_energy(vision, fixture, energy):
    assert page.read_energy(vision, _frame(fixture)) == energy


def test_read_skystone(vision):
    assert page.read_skystone(vision, _frame("rb_prep_battle")) == 19728


def test_read_energy_none_without_top_bar(vision):
    assert page.read_energy(vision, _frame("rb_battle")) is None


@pytest.mark.parametrize(("fixture", "mode", "cost", "held", "no_record"), [
    ("rb_prep_battle", PrepMode.BATTLE, 20, 102, False),
    ("rb_prep_battle_running", PrepMode.BATTLE, 20, 7, False),
    ("rb_prep_quick", PrepMode.QUICK, 200, 59, False),
    ("rb_prep_norecord", PrepMode.BATTLE, 20, 82, True),
])
@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_read_prep(vision, fixture, mode, cost, held, no_record, size):
    p = page.read_prep(vision, _frame(fixture, size))
    assert (p.mode, p.cost, p.held, p.no_record) == (mode, cost, held, no_record)
    assert p.enough == (held >= cost)


def test_read_prep_none_under_dialog(vision):
    assert page.read_prep(vision, _frame("rb_energy_low")) is None  # 按钮被压暗，max_diff 不通过


@pytest.mark.parametrize(("fixture", "hunt"), [("rb_prep_battle", "讨伐双足飞龙"), ("rb_prep_norecord", "讨伐魔像")])
def test_read_stage(vision, fixture, hunt):
    assert page.read_stage(vision, _frame(fixture)) == (hunt, "讨伐地狱级")


@pytest.mark.parametrize(("fixture", "state"), [
    ("rb_lobby_auto_done", AutoState.DONE), ("rb_prep_quick_done", AutoState.DONE),
    ("rb_prep_norecord", AutoState.DONE), ("rb_lobby_auto_running", AutoState.RUNNING),
    ("rb_prep_battle_running", AutoState.RUNNING), ("rb_lobby_no_auto", AutoState.NONE),
    ("rb_prep_battle", AutoState.NONE), ("rb_hunt_list", AutoState.NONE),
])
@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_auto_state(vision, fixture, state, size):
    assert page.auto_state(vision, _frame(fixture, size)) is state


def test_auto_state_dim_icon_done(vision):
    """从「重新进行」回到准备界面时顶栏托管图标变灰：红点也变暗，仍然认成完成（B06 实跑发现）。"""
    f = _frame("rb_prep_battle_done_dim")
    assert page.auto_state(vision, f) is AutoState.DONE
    assert page.dots_match(page.auto_dot(vision, f), page.auto_dot(vision, f))


def test_running_arc_needs_several_frames(vision):
    """进行中的光弧扫过红点位置时单帧会认成完成，但隔 1 秒的帧红点位置对不上（不会同时够红）。"""
    arc = [_frame(n) for n in ("rb_lobby_auto_running_arc0", "rb_lobby_auto_running_arc",
                               "rb_lobby_auto_running_arc2")]
    assert page.auto_state(vision, arc[1]) is AutoState.DONE  # 单帧误判
    states = [page.auto_state(vision, f) for f in arc]
    dots = [page.auto_dot(vision, f) for f in arc]
    assert not (all(s is AutoState.DONE for s in states) and page.dots_match(dots[0], dots[-1]))
    done = [page.auto_dot(vision, _frame(n)) for n in ("rb_lobby_auto_done", "rb_prep_battle_done_dim")]
    assert page.dots_match(*done)  # 平时和变灰时红点位置一样


@pytest.mark.parametrize(("fixture", "hunt", "found"), [
    ("rb_hunt_list", Hunt.WYVERN, True), ("rb_hunt_list", Hunt.BANSHEE, True), ("rb_hunt_list", Hunt.GOLEM, True),
    ("rb_hunt_list_golem", Hunt.GOLEM, True), ("rb_hunt_list_end", Hunt.WYVERN, False),
    ("rb_hunt_list_end", Hunt.BANSHEE, False),
])
def test_find_hunt(vision, fixture, hunt, found):
    r = page.find_hunt(vision, _frame(fixture), hunt)
    assert (r is not None) == found
    if found:
        assert page.HUNT_LIST.x <= r.x and r.right <= page.HUNT_LIST.right


@pytest.mark.parametrize(("fixture", "state", "done", "total", "button"), [
    ("rb_auto_done", AutoState.DONE, 4, 4, "settle"),
    ("rb_auto_done_lobby", AutoState.DONE, 4, 4, "settle"),
    ("rb_auto_running", AutoState.RUNNING, 0, 4, None),
    ("rb_auto_running_lobby", AutoState.RUNNING, 1, 4, None),
    ("rb_auto_claimed", AutoState.NONE, 4, 4, "close"),
])
def test_read_auto_progress(vision, fixture, state, done, total, button):
    p = page.read_auto_progress(vision, _frame(fixture))
    assert (p.state, p.done, p.total, p.stage) == (state, done, total, "讨伐地狱级")
    if button is None:
        assert p.button is None  # 进行中只有「中断」，绝不返回可点的按钮
    else:
        assert vision.find(_frame(fixture), f"auto/{button}").rect == p.button.rect


def test_read_auto_progress_none(vision):
    assert page.read_auto_progress(vision, _frame("rb_auto_settling")) is None  # 「结算中」
    assert page.read_auto_progress(vision, _frame("rb_prep_battle")) is None


@pytest.mark.parametrize(("fixture", "energy", "use", "checked", "enabled"), [
    ("rb_auto_setup", 87, (0, 1), False, True),
    ("rb_auto_setup_checked", 87, (80, 0), True, True),
    ("rb_auto_setup_disabled", 60, (0, 1), False, False),
])
def test_read_auto_setup(vision, fixture, energy, use, checked, enabled):
    s = page.read_auto_setup(vision, _frame(fixture))
    assert (s.energy, s.leaves, s.run_energy, s.count, s.count_max) == (energy, 291, 20, 1, 100)
    assert (s.use_energy, s.use_leaves, s.checked, s.check_enabled) == (*use, checked, enabled)
    assert "约4次" in s.estimate


def test_read_auto_setup_none(vision):
    assert page.read_auto_setup(vision, _frame("rb_auto_sort")) is None  # 装备自动整理页签
    assert page.read_auto_setup(vision, _frame("rb_auto_confirm")) is None  # 被确认框压暗


@pytest.mark.parametrize(("energy", "run", "leaves", "prefer", "plan"), [
    (87, 20, 0, True, (1, 80, 0)),
    (87, 20, 2, True, (3, 80, 2)),
    (60, 20, 0, True, (0, 0, 0)),  # 不够一份、不许用叶子：不开
    (60, 20, 1, True, (1, 0, 1)),
    (360, 20, 0, True, (4, 320, 0)),
    (360, 20, 3, False, (3, 0, 3)),  # 不勾优先行动力：全用叶子
    (360, 10, 0, True, (9, 360, 0)),
    (10000, 20, 100, True, (100, 8000, 0)),  # 份数上限 100
])
def test_plan_auto(energy, run, leaves, prefer, plan):
    assert page.plan_auto(energy, run, leaves, prefer) == plan


@pytest.mark.parametrize(("energy", "leaves", "max_units", "plan"), [
    (263, 0, 1, (1, 80, 0)),
    (263, 2, 4, (4, 240, 1)),  # 先用行动力，叶子少用
    (60, 2, 1, (1, 0, 1)),
])
def test_plan_auto_max_units(energy, leaves, max_units, plan):
    assert page.plan_auto(energy, 20, leaves, True, max_units) == plan


def test_read_energy_dialog(vision):
    d = page.read_energy_dialog(vision, _frame("rb_energy_low"))
    assert (d.leaf, d.skystone, d.left_selected, d.right_selected) == (True, True, True, False)
    assert (d.leaf_cost, d.leaf_gain, d.leaf_hold) == (1, 80, 291)
    assert (d.sky_cost, d.sky_gain, d.sky_hold) == (30, 60, 19728)


def test_read_energy_dialog_skystone_selected(vision):
    """把左边选项的亮边框挪到右边，模拟选中天空石。"""
    f = _frame("rb_energy_low").copy()
    left, right = Rect(478, 376, 290, 24), Rect(834, 376, 290, 24)
    f[right.y:right.bottom, right.x:right.right] = f[left.y:left.bottom, left.x:left.right]
    f[left.y:left.bottom, left.x:left.right] = 30
    d = page.read_energy_dialog(vision, f)
    assert (d.left_selected, d.right_selected) == (False, True)


def test_read_energy_dialog_none_elsewhere(vision):
    assert page.read_energy_dialog(vision, _frame("rb_prep_battle")) is None


def test_read_after_energy(vision):
    assert page.read_after_energy(vision, _frame("rb_after")) == (20, 94)
    assert page.read_after_energy(vision, _frame("rb_result")) is None


def test_auto_icon_still_vs_rotating(vision):
    f = _frame("rb_battle")
    a = page.auto_icon(vision, f)
    assert a is not None and page.patch_diff(a, page.auto_icon(vision, f)) == 0
    sim = RbSim("rb_battle", battle_shots=99)
    b = page.auto_icon(vision, sim.screenshot())
    c = page.auto_icon(vision, sim.screenshot())
    if b is not None and c is not None:
        assert page.patch_diff(b, c) >= 3.0


def test_config_schema_only_user_fields():
    props = RepeatBattleConfig.model_json_schema()["properties"]
    assert set(props) == {"hunt", "tier", "start_here", "auto_battle", "auto_leaves", "manual", "manual_runs",
                          "refill_leaf", "max_leaf_refills", "refill_skystone", "max_skystone_refills", "dry_run"}
    cfg = RepeatBattleConfig()
    assert cfg.dry_run and not cfg.refill_leaf and not cfg.refill_skystone and cfg.auto_leaves == 0
    assert cfg.auto_prefer_energy  # 用户要求：开托管时勾选「优先使用持有的行动力」


# ---------------------------------------------------------------- 流程（RbSim）


@pytest.fixture(autouse=True)
def _fast_waits(monkeypatch):
    """模拟器画面是静止的，等待时间缩短不影响流程，只为让测试快一些。"""
    import e7helper.core.runtime.controller as controller
    import e7helper.modules.repeat_battle as rb

    monkeypatch.setattr(controller, "SETTLE_TIME", 0.1)
    monkeypatch.setattr(controller, "POPUP_SETTLE", 0.1)
    monkeypatch.setattr(rb, "VERIFY_TIMEOUT", 1.0)
    monkeypatch.setattr(rb, "POPUP_GRACE", 0.3)
    monkeypatch.setattr(rb, "START_GRACE", 1.0)
    monkeypatch.setattr(rb, "UNKNOWN_POPUP", 1.0)
    monkeypatch.setattr(rb, "COUNT_TAP_WAIT", 0.5)
    monkeypatch.setattr(rb, "AUTO_DOT_GAP", 0.05)


TOP_BAR = {"rb_lobby_no_auto", "rb_lobby_auto_running", "rb_lobby_auto_done", "rb_battle_menu", "rb_hunt_list",
           "rb_hunt_list_end", "rb_prep_quick", "rb_prep_battle"}


def _patch_reads(sim, monkeypatch):
    """截图上的数字是固定的：读数换成模拟器的值（模板判定仍然用真实截图）。"""
    orig_prep, orig_setup = page.read_prep, page.read_auto_setup
    orig_progress, orig_dialog = page.read_auto_progress, page.read_energy_dialog

    def read_prep(vision, frame):
        p = orig_prep(vision, frame)
        if p is None:
            return None
        cost = sim.cost * (10 if p.mode is PrepMode.QUICK else 1)
        # 「无记录」只在普通战斗模式显示（实测 B06）
        return dataclasses.replace(p, cost=cost, held=sim.energy,
                                   no_record=sim.no_record and p.mode is PrepMode.BATTLE)

    def read_auto_setup(vision, frame):
        s = orig_setup(vision, frame)
        if s is None:
            return None
        use_e, use_l = sim.setup_use()
        return dataclasses.replace(s, energy=sim.energy, leaves=sim.leaves, run_energy=sim.cost, count=sim.count,
                                   count_max=100, use_energy=use_e, use_leaves=use_l, checked=sim.checked,
                                   check_enabled=sim.check_enabled)

    def read_auto_progress(vision, frame):
        p = orig_progress(vision, frame)
        return None if p is None else dataclasses.replace(p, done=sim.auto_done_runs, total=sim.auto_done_runs)

    def read_energy_dialog(vision, frame):
        d = orig_dialog(vision, frame)
        if d is None:
            return None
        return dataclasses.replace(d, left_selected=sim.option == "leaf", right_selected=sim.option == "skystone",
                                   leaf_hold=sim.leaves, sky_hold=sim.skystone)

    def find_hunt(vision, frame, hunt):
        names = sim.visible_hunts()
        return HUNT_ROWS[names.index(hunt.value)] if hunt.value in names else None

    def find_tier(vision, frame, tier):
        tiers = sim.tiers()
        return TIER_CARDS[tiers.index(tier.value)] if tier.value in tiers else None

    top = lambda v: (lambda vision, frame: v() if sim.screen in TOP_BAR else None)  # noqa: E731
    monkeypatch.setattr(page, "read_energy", top(lambda: sim.energy))
    monkeypatch.setattr(page, "read_skystone", top(lambda: sim.skystone))
    monkeypatch.setattr(page, "auto_state", top(lambda: AutoState(sim.auto)))
    monkeypatch.setattr(page, "auto_dot", top(lambda: np.full((16, 16), sim.auto == "done")))
    monkeypatch.setattr(page, "read_prep", read_prep)
    monkeypatch.setattr(page, "read_auto_setup", read_auto_setup)
    monkeypatch.setattr(page, "read_auto_progress", read_auto_progress)
    monkeypatch.setattr(page, "read_energy_dialog", read_energy_dialog)
    monkeypatch.setattr(page, "find_hunt", find_hunt)
    monkeypatch.setattr(page, "find_tier", find_tier)
    monkeypatch.setattr(page, "read_stage", lambda vision, frame: (normalize_text(f"讨伐{sim.selected}"),
                                                                    normalize_text(f"讨伐{sim.tier}")))
    monkeypatch.setattr(page, "read_after_energy", lambda vision, frame: (sim.cost, sim.energy)
                        if sim.screen == "rb_after" else None)


def _run(sim, tmp_path, monkeypatch, *, timeout=120, **cfg):
    _patch_reads(sim, monkeypatch)
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off(), debug_root=tmp_path / "debug",
                 seed=1) as rt:
        return rt.run_task(RepeatBattleModule, RepeatBattleConfig(**cfg), timeout=timeout)


def _history(tmp_path):
    path = tmp_path / "data" / "modules" / "repeat_battle" / "history.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _totals(tmp_path):
    path = tmp_path / "data" / "modules" / "repeat_battle" / "stats.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _assert_safe(sim):
    assert DANGER not in sim.history, sim.history
    assert sim.late_cancels == 0  # 确认 / 购买后框淡出时没有再点取消（B06 实跑发现）


def test_dry_run_from_lobby(tmp_path, monkeypatch):
    """dry-run（默认）：大厅 → 战斗 → 讨伐 → 飞龙 → 地狱级 → 准备界面；托管设置框核对后关闭；切普通战斗后停下。"""
    sim = RbSim("lobby", energy=100)
    result = _run(sim, tmp_path, monkeypatch)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.starts == 0 and sim.auto_starts == [] and sim.claims == 0
    assert "rb_auto_setup" in sim.history and sim.screen == "rb_prep_battle"
    assert sim.count == 1 and sim.checked  # 份数和「优先使用持有的行动力」按配置调好（不点开始）
    rec = _history(tmp_path)[-1]
    assert rec["dry_run"] and rec["stage"] == "讨伐双足飞龙 讨伐地狱级"
    assert any("开托管 1 份" in w and "行动力 80、叶子 0" in w for w in rec["would"]), rec["would"]
    assert any("够打 5 场" in w for w in rec["would"]), rec["would"]
    assert rec["stop_reason"] == "dry-run 停在准备界面"
    assert _totals(tmp_path) is None


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_dry_run_scrolls_to_other_hunt(tmp_path, monkeypatch, size):
    """列表停在底部（上次选的是后面的地下城）：往下翻找不到，再翻回顶部找到。"""
    sim = RbSim("lobby", energy=100, size=size)
    sim.scrolled = True
    result = _run(sim, tmp_path, monkeypatch, hunt=Hunt.GOLEM, tier=Tier.HIGH, auto_battle=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert (sim.selected, sim.tier) == ("魔像", "上级") and len(sim.swipes) == 3
    assert _history(tmp_path)[-1]["stage"] == "讨伐魔像 讨伐上级"


def test_missing_tier_stops(tmp_path, monkeypatch):
    """选中的地下城没有该难度（例如食人魔只有异界，实测 B06）：停止。"""
    sim = RbSim("lobby", energy=100)
    sim.tiers = lambda: ["异界"]
    result = _run(sim, tmp_path, monkeypatch, tier=Tier.MID, auto_battle=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.screen == "rb_hunt_list"
    assert _history(tmp_path)[-1]["stop_reason"] == "讨伐双足飞龙没有「中级」难度（或没有解锁）"


def test_start_here_abyss_not_supported(tmp_path, monkeypatch):
    sim = RbSim("prep", tier="异界")
    result = _run(sim, tmp_path, monkeypatch, start_here=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert _history(tmp_path)[-1]["stop_reason"] == "讨伐双足飞龙 讨伐异界 消耗异界代币，暂不支持"


@pytest.mark.parametrize(("fixture", "tier", "y"), [
    ("rb_hunt_list", Tier.MID, 211), ("rb_hunt_list", Tier.HIGH, 346), ("rb_hunt_list", Tier.HELL, 481),
    ("rb_hunt_list_ogre", Tier.HELL, None), ("rb_hunt_list_ogre", Tier.MID, None),
])
def test_find_tier(vision, fixture, tier, y):
    r = page.find_tier(vision, _frame(fixture), tier)
    assert (r is None) if y is None else abs(r.y - y) <= 4


def test_dry_run_auto_done_only_reports(tmp_path, monkeypatch):
    """托管已完成：dry-run 打开进度框读数后关闭，不点结算。"""
    sim = RbSim("lobby", auto="done", auto_done_runs=48)
    result = _run(sim, tmp_path, monkeypatch, manual=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.claims == 0 and sim.auto == "done" and "rb_auto_done" in sim.history
    rec = _history(tmp_path)[-1]
    assert any("结算托管（讨伐地狱级 48/48）" in w for w in rec["would"]), rec["would"]
    assert rec["stop_reason"] == "没有开启手动刷关"


def test_dry_run_auto_running_does_nothing(tmp_path, monkeypatch):
    sim = RbSim("lobby", auto="running")
    result = _run(sim, tmp_path, monkeypatch, manual=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert "rb_auto_running" not in sim.history and "rb_auto_setup" not in sim.history


def test_dry_run_not_enough_energy_for_auto(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=60)
    result = _run(sim, tmp_path, monkeypatch, manual=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    rec = _history(tmp_path)[-1]
    assert any("不够 1 份" in w for w in rec["would"]), rec["would"]


def test_live_auto_start_then_manual_until_energy_out(tmp_path, monkeypatch):
    """实跑：托管用 80 行动力开 1 份；剩下 20 手动打 1 场；行动力不够、没开补充就停。"""
    sim = RbSim("lobby", energy=100, auto_start="ok", start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.auto_starts == [(1, 80, 0)] and sim.auto == "running"
    assert sim.battles == 1 and sim.energy == 0
    rec = _history(tmp_path)[-1]
    assert len(rec["battles"]) == 1 and rec["energy_spent"] == 20
    assert rec["stop_reason"].startswith("行动力不够（0/20）")
    assert [a["action"] for a in rec["autos"]] == ["started"] and rec["autos"][0]["energy"] == 80
    totals = _totals(tmp_path)
    assert totals["battles"] == 1 and totals["auto_started"] == 1 and totals["energy_spent"] == 100


def test_live_claims_then_restarts_auto(tmp_path, monkeypatch):
    sim = RbSim("lobby", auto="done", energy=170, claim="ok", auto_start="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, manual=False, auto_leaves=1)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.claims == 1 and sim.auto_starts == [(3, 160, 1)]
    rec = _history(tmp_path)[-1]
    assert [a["action"] for a in rec["autos"]] == ["claimed", "started"]
    assert rec["autos"][0]["runs"] == 4 and rec["leaves_spent"] == 1


def test_live_claims_when_auto_finishes_between_battles(tmp_path, monkeypatch):
    """手动刷关时托管跑完了：回到准备界面后结算并重开。"""
    sim = RbSim("prep", auto="running", energy=200, start="ok", claim="ok", auto_start="ok")
    orig = sim._go

    def go(target):
        if target == "rb_clear" and sim.battles == 0:
            sim.auto = "done"
        orig(target)

    sim._go = go
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, start_here=True, manual_runs=2)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.claims == 1 and sim.battles == 2
    assert sim.auto_starts == [(2, 160, 0)]  # 200 - 20 = 180 → 2 份


def test_live_manual_only(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=100, start="ok", drop_energy=11)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False, manual_runs=2)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.battles == 2 and sim.toggles >= 2  # 每次回到准备界面都要从快速战斗切回普通战斗
    rec = _history(tmp_path)[-1]
    assert rec["stop_reason"] == "手动已打 2 场" and rec["energy_spent"] == 18  # 掉落的行动力抵掉一部分


def test_live_refill_with_leaf(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=10, start="ok", refill="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False, refill_leaf=True,
                  refill_skystone=True, manual_runs=1)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.refills == ["leaf"] and sim.skystone == 19728 and sim.battles == 1
    rec = _history(tmp_path)[-1]
    assert rec["leaf_refills"] == 1 and rec["skystone_refills"] == 0


def test_live_refill_with_skystone_selects_right_option(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=10, start="ok", refill="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False, refill_skystone=True,
                  manual_runs=1)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.refills == ["skystone"] and sim.skystone == 19698
    rec = _history(tmp_path)[-1]
    assert rec["skystone_refills"] == 1 and rec["skystone_spent"] == 30


def test_live_refill_limit_then_stop(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=10, start="ok", refill="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False, refill_leaf=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.refills == ["leaf"] and sim.battles == 4  # 10 + 80 = 90 → 4 场后剩 10
    assert _history(tmp_path)[-1]["stop_reason"] == "行动力不够（10/20），本次已补 叶子 1 次 / 天空石 0 次"


def test_no_refill_never_opens_dialog(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=10)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert "rb_energy_low" not in sim.history and sim.starts == 0


def test_dry_run_probe_refill_only_cancels(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=10)
    result = _run(sim, tmp_path, monkeypatch, auto_battle=False, refill_skystone=True, probe_dialogs=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert "rb_energy_low" in sim.history and sim.refills == [] and sim.option == "skystone"
    rec = _history(tmp_path)[-1]
    assert any("用 30 天空石补 60 行动力" in w for w in rec["would"]), rec["would"]


def test_live_refill_wrong_amount_is_anomaly(tmp_path, monkeypatch):
    """补完行动力只加了 40：读数不符，立即停止并记为失败。"""
    sim = RbSim("lobby", energy=10, refill="ok")
    orig = sim.tap

    def tap(x, y, duration=0.05):
        before = sim.energy
        orig(x, y, duration)
        if sim.refills and sim.energy == before + 80:
            sim.energy -= 40

    sim.tap = tap
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False, refill_leaf=True)
    assert result.status is TaskStatus.FAILED, result.error
    assert "预期 +80" in result.error
    assert sim.starts == 0


def test_live_double_energy_spend_is_anomaly(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=100, start="ok")
    orig = sim._go

    def go(target):
        if target == "rb_battle_start":
            sim.energy -= sim.cost  # 多扣一次
        orig(target)

    sim._go = go
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False)
    assert result.status is TaskStatus.FAILED, result.error
    assert "超过一场的消耗" in result.error and sim.battles == 1


def test_live_swallowed_start_is_not_counted(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=100, start="eat")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.starts == 3 and sim.battles == 0
    rec = _history(tmp_path)[-1]
    assert rec["battles"] == [] and rec["failures"] == 3 and rec["stop_reason"].startswith("连续失败 3 次")


def test_live_unknown_popup_after_start_stops(tmp_path, monkeypatch):
    """点战斗开始后出现认不出的静止弹窗（例如背包已满，还没采到截图）：停止并记为失败，不乱点。"""
    sim = RbSim("lobby", energy=100, start="ok")
    orig = sim.tap

    def tap(x, y, duration=0.05):
        orig(x, y, duration)
        if sim.screen == "rb_battle_start":
            sim.then = None
            sim._go("secret_shop_buy_confirm")

    sim.tap = tap
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False)
    assert result.status is TaskStatus.FAILED, result.error
    assert "认不出的弹窗" in result.error
    assert sim.screen == "secret_shop_buy_confirm" and sim.backs == 0


def test_live_turns_on_auto_battle(tmp_path, monkeypatch):
    sim = RbSim("lobby", energy=20, start="ok", auto_on=False, battle_shots=40)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, auto_battle=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.auto_taps == 1 and sim.battles == 1


def test_no_record_skips_auto(tmp_path, monkeypatch):
    """准备界面默认是快速战斗，看不到「无记录」：先切到普通战斗再判断，不去点托管战斗。"""
    sim = RbSim("prep", no_record=True, energy=100)
    result = _run(sim, tmp_path, monkeypatch, start_here=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert "rb_auto_setup" not in sim.history
    rec = _history(tmp_path)[-1]
    assert rec["failures"] == 0 and any("无记录" in w for w in rec["would"]), rec


def test_auto_setup_mismatch_does_not_start(tmp_path, monkeypatch):
    """设置框「将使用」的叶子和算出来的不一样（例如游戏规则变了）：不点开始。"""
    sim = RbSim("lobby", energy=100, auto_start="ok")
    orig = sim.setup_use
    sim.setup_use = lambda: (orig()[0], orig()[1] + 1)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, manual=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.auto_starts == [] and "rb_auto_confirm" not in sim.history
    assert "将使用的行动力 / 叶子不符" in _history(tmp_path)[-1]["stop_reason"]


def test_start_here_requires_prep(tmp_path, monkeypatch):
    sim = RbSim("lobby")
    result = _run(sim, tmp_path, monkeypatch, start_here=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert _history(tmp_path)[-1]["stop_reason"].startswith("start_here 要求停在准备界面")


def test_wrong_prep_goes_back_and_reselects(tmp_path, monkeypatch):
    sim = RbSim("prep", hunt="魔像", tier="上级")
    result = _run(sim, tmp_path, monkeypatch, auto_battle=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert (sim.selected, sim.tier) == ("双足飞龙", "地狱级")

