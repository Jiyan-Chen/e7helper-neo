"""自定义流程（B11）：流程定义、存储、执行器（分支 / 循环 / 安全规则），用 GameSim 离线跑。"""

import json

import game_sim
import pytest
from game_sim import DANGER, GameSim, load_fixture
from pydantic import ValidationError

from e7helper.core import paths
from e7helper.core.flows import Flow, FlowNotFound, FlowStore, missing_templates, user_template_store
from e7helper.core.geometry import Rect
from e7helper.core.runtime import Humanize, Runtime, TaskStatus
from e7helper.core.scene import default_detector
from e7helper.core.vision import TemplateMeta
from e7helper.modules.custom_flow import CustomFlow, CustomFlowConfig, FlowBlocked
from e7helper.modules.custom_flow.runner import FlowRunner

SANCTUARY_ENTRY = Rect(40, 195, 62, 82)  # 大厅「圣域」可点区域（common:lobby/sanctuary 的 tap）
TITLE_BOX = Rect(82, 23, 69, 37)  # 圣域标题


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(autouse=True)
def _sanctuary_entry(monkeypatch):
    """模拟器里加上 大厅 → 圣域 的入口。"""
    t = dict(game_sim.TRANSITIONS)
    t["lobby"] = [(SANCTUARY_ENTRY, "sanctuary"), *t["lobby"]]
    monkeypatch.setattr(game_sim, "TRANSITIONS", t)


@pytest.fixture()
def detector():
    return default_detector()


def _runtime(sim, tmp_path, detector, **kw) -> Runtime:
    return Runtime(sim, scenes=detector, debug_root=tmp_path / "debug", seed=1, humanize=Humanize.off(), **kw)


def _flow(steps, **kw) -> Flow:
    flow = FlowStore().save(Flow.model_validate({"name": kw.pop("name", "测试流程"), "steps": steps, **kw}))
    return flow


def _run(sim, tmp_path, detector, flow: Flow, **kw):
    with _runtime(sim, tmp_path, detector, **kw) as rt:
        return rt.run_task(CustomFlow, CustomFlowConfig(flow=flow.id), timeout=60)


def _save_title_template(name="圣域标题"):
    frame = load_fixture("sanctuary")
    meta = TemplateMeta(region=TITLE_BOX.expand(40).clip(), box=TITLE_BOX)
    user_template_store().save(name, TITLE_BOX.crop(frame).copy(), meta)


def _history():
    path = paths.module_data_dir("custom_flow") / "history.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


NAV = [
    {"type": "tap_template", "template": "common:lobby/sanctuary"},
    {"type": "wait_scene", "scene": "sanctuary"},
    {"type": "back"},
    {"type": "wait_scene", "scene": "lobby"},
]


# ---------------------------------------------------------------- 定义


def test_flow_model_roundtrip_and_refs():
    flow = Flow.model_validate({
        "name": " 圣域往返 ",
        "steps": [
            *NAV,
            {"type": "if", "condition": {"templates": ["圣域标题"], "wait": 2},
             "then": [{"type": "back"}], "else": [{"type": "end", "success": False, "message": "不在圣域"}]},
            {"type": "repeat", "mode": "until", "count": 3, "condition": {"kind": "scene", "scene": "lobby"},
             "body": [{"type": "back"}, {"type": "break"}]},
        ],
    })
    assert flow.name == "圣域往返"
    data = flow.dump()
    assert "else" in data["steps"][4] and "else_" not in data["steps"][4]
    again = Flow.model_validate(json.loads(json.dumps(data)))
    assert again == flow
    assert flow.template_refs() == {"common:lobby/sanctuary", "圣域标题"}
    assert all(s["id"] for s in data["steps"])


@pytest.mark.parametrize("steps, msg", [
    ([{"type": "break"}], "只能放在循环里"),
    ([{"type": "tap_template", "template": "common:dialog/confirm"}], "不能点确认框"),
    ([{"type": "repeat", "mode": "until", "body": []}], "需要条件"),
    ([{"type": "tap_point", "x": 1700, "y": 10}], "less than or equal"),
    ([{"type": "repeat", "count": 1000, "body": []}], "less than or equal"),
    ([{"type": "wait_scene", "scene": "battle"}], "不认识的界面"),
    ([{"type": "wait_template", "templates": ["../x"]}], "模板引用不合法"),
    ([{"type": "if", "condition": {"templates": []}}], "至少要选一个模板"),
])
def test_flow_validation_errors(steps, msg):
    with pytest.raises(ValidationError, match=msg):
        Flow.model_validate({"name": "x", "steps": steps})


def test_flow_depth_limit():
    inner: dict = {"type": "back"}
    for _ in range(7):
        inner = {"type": "repeat", "count": 1, "body": [inner]}
    with pytest.raises(ValidationError, match="嵌套"):
        Flow.model_validate({"name": "x", "steps": [inner]})


def test_store_crud(tmp_path):
    store = FlowStore()
    assert store.root == paths.flows_dir()
    f = store.save(Flow(name="甲", steps=[]))
    assert f.id.startswith("f") and f.created and f.updated
    assert store.get(f.id).name == "甲"
    f2 = store.save(store.get(f.id).model_copy(update={"name": "乙", "created": None}))
    assert f2.created == f.created and f2.id == f.id
    assert [x.name for x in store.list()] == ["乙"]
    (store.root / "broken.json").write_text("{", encoding="utf-8")
    assert any(isinstance(x, tuple) and x[0] == "broken" for x in store.list())
    store.delete(f.id)
    with pytest.raises(FlowNotFound):
        store.get(f.id)
    with pytest.raises(FlowNotFound):
        store.get("../secret")


def test_missing_templates():
    flow = Flow.model_validate({"name": "x", "steps": [
        {"type": "tap_template", "template": "common:back"},
        {"type": "tap_template", "template": "我的按钮"},
        {"type": "wait_template", "templates": ["common:不存在"]},
    ]})
    assert missing_templates(flow) == ["common:不存在", "我的按钮"]
    _save_title_template("我的按钮")
    assert missing_templates(flow) == ["common:不存在"]


def test_user_templates_live_in_data_dir():
    _save_title_template()
    assert (paths.data_dir() / "flows" / "templates" / "圣域标题.png").is_file()
    assert not (paths.ASSETS_DIR / "custom_flow").exists()


# ---------------------------------------------------------------- 运行


def test_lobby_sanctuary_round_trip(tmp_path, detector):
    sim = GameSim("lobby")
    flow = _flow(NAV, name="圣域往返")
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.history == ["lobby", "sanctuary", "lobby"]
    assert len(sim.taps) == 1 and sim.backs == 1
    (h,) = _history()
    assert h["flow"] == flow.id and h["name"] == "圣域往返" and h["status"] == "succeeded"
    assert h["steps"] == 4 and h["taps"] == 1
    stats = json.loads((paths.module_data_dir("custom_flow") / "stats.json").read_text(encoding="utf-8"))
    assert stats["runs"] == 1 and stats["succeeded"] == 1 and stats["flows"][flow.id]["runs"] == 1


@pytest.mark.parametrize("start, branch", [("sanctuary", "then"), ("lobby", "else")])
def test_if_branches_with_user_template(tmp_path, detector, start, branch):
    _save_title_template()
    sim = GameSim(start)
    flow = _flow([
        {"type": "if", "condition": {"templates": ["圣域标题"]},
         "then": [{"type": "back"}],
         "else": [{"type": "tap_point", "x": 800, "y": 120}]},
    ])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    if branch == "then":
        assert sim.backs == 1 and not sim.taps
    else:
        assert sim.backs == 0 and len(sim.taps) == 1


def test_condition_not_appear_and_wait(tmp_path, detector):
    _save_title_template()
    sim = GameSim("lobby")
    flow = _flow([
        {"type": "if", "condition": {"templates": ["圣域标题"], "appear": False}, "then": [{"type": "back"}]},
    ])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    # 大厅按返回键 → 结束游戏确认框；流程结束时框还在（没有下一步去处理），但绝不会点确认
    assert sim.backs == 1 and DANGER not in sim.history


def test_repeat_until_scene(tmp_path, detector):
    sim = GameSim("sanctuary_help")  # 说明弹窗 → 返回 → 圣域 → 返回 → 大厅
    flow = _flow([
        {"type": "repeat", "mode": "until", "count": 5, "condition": {"kind": "scene", "scene": "lobby"},
         "body": [{"type": "back"}, {"type": "wait", "seconds": 0.2}]},
    ])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    assert sim.backs == 2 and sim.history[-1] == "lobby"


@pytest.mark.parametrize("on_limit, status", [("stop", TaskStatus.FAILED), ("continue", TaskStatus.SUCCEEDED)])
def test_repeat_until_exhausted(tmp_path, detector, on_limit, status):
    sim = GameSim("sanctuary")
    flow = _flow([
        {"type": "repeat", "mode": "until", "count": 3, "on_limit": on_limit,
         "condition": {"kind": "scene", "scene": "shop"}, "body": [{"type": "wait", "seconds": 0.1}]},
    ])
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is status
    if status is TaskStatus.FAILED:
        assert "重复了 3 轮" in result.error and "Traceback" not in result.error
        assert result.debug_dir is not None


def test_repeat_times_and_break(tmp_path, detector):
    _save_title_template()
    sim = GameSim("lobby")
    # 重复 5 次：点圣域入口；到了圣域就跳出
    flow = _flow([
        {"type": "repeat", "count": 5, "body": [
            {"type": "if", "condition": {"templates": ["圣域标题"], "wait": 1}, "then": [{"type": "break"}]},
            {"type": "tap_template", "template": "common:lobby/sanctuary", "settle": False},
        ]},
        {"type": "back"},
    ])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    assert len(sim.taps) == 1 and sim.backs == 1 and sim.history == ["lobby", "sanctuary", "lobby"]


def test_repeat_while(tmp_path, detector):
    sim = GameSim("sanctuary_help")
    flow = _flow([
        {"type": "repeat", "mode": "while", "count": 5, "condition": {"kind": "scene", "scene": "lobby", "appear": False},
         "body": [{"type": "back"}, {"type": "wait", "seconds": 0.2}]},
    ])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    assert sim.history[-1] == "lobby" and sim.backs == 2


def test_end_step(tmp_path, detector):
    sim = GameSim("lobby")
    flow = _flow([{"type": "end", "success": False, "message": "故意结束"}, {"type": "back"}])
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is TaskStatus.FAILED and result.error == "故意结束"
    assert sim.backs == 0
    flow = _flow([{"type": "end"}, {"type": "back"}])
    assert _run(GameSim("lobby"), tmp_path, detector, flow).status is TaskStatus.SUCCEEDED


@pytest.mark.parametrize("on_missing, status", [("stop", TaskStatus.FAILED), ("skip", TaskStatus.SUCCEEDED)])
def test_tap_template_missing(tmp_path, detector, on_missing, status):
    sim = GameSim("shop")
    flow = _flow([
        {"type": "tap_template", "template": "common:lobby/sanctuary", "timeout": 0.5, "on_missing": on_missing},
        {"type": "back"},
    ])
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is status
    assert sim.backs == (1 if on_missing == "skip" else 0) and not sim.taps
    if status is TaskStatus.FAILED:
        assert "没找到「大厅左侧「圣域」文字」" in result.error


def test_wait_template_disappear(tmp_path, detector):
    _save_title_template()
    sim = GameSim("sanctuary")
    flow = _flow([
        {"type": "back"},
        {"type": "wait_template", "templates": ["圣域标题"], "appear": False, "timeout": 3},
        {"type": "wait_template", "templates": ["common:lobby/sanctuary"], "timeout": 3},
    ])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED


def test_swipe_and_wait_still(tmp_path, detector):
    sim = GameSim("lobby")
    sim.animating = 4
    flow = _flow([
        {"type": "wait_still", "timeout": 5},
        {"type": "swipe", "x1": 1200, "y1": 450, "x2": 400, "y2": 450, "duration": 0.3},
    ])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    assert len(sim.swipes) == 1 and sim.animating == 0


# ---------------------------------------------------------------- 安全


def test_confirm_dialog_is_cancelled(tmp_path, detector):
    """大厅按返回键弹出「结束游戏」确认框：下一步之前自动点取消，绝不点确认。"""
    sim = GameSim("lobby")
    flow = _flow([{"type": "back"}, *NAV])
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert DANGER not in sim.history
    assert sim.history[:3] == ["lobby", "lobby_exit_confirm", "lobby"]
    assert _history()[0]["popups"] == 1


def test_tap_on_confirm_position_cancels_first(tmp_path, detector):
    """确认框开着时，点确认按钮位置的坐标：先点取消关掉框，确认按钮不会被点到。"""
    sim = GameSim("secret_shop_refresh_confirm")
    flow = _flow([{"type": "tap_point", "x": 933, "y": 575}])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    assert DANGER not in sim.history and sim.history[1] == "secret_shop"


def test_guard_blocks_confirm_buttons(tmp_path, detector):
    sim = GameSim("secret_shop_refresh_confirm")
    flow = Flow(name="x")
    with _runtime(sim, tmp_path, detector) as rt:
        runner = FlowRunner(rt.make_controller(), flow)
        frame = load_fixture("secret_shop_refresh_confirm")
        with pytest.raises(FlowBlocked, match="确认"):
            runner._guard(frame, Rect(933, 575, 1, 1), "1")
        runner._guard(frame, Rect(665, 575, 1, 1), "1")  # 取消按钮可以点


def test_guard_popups_cover_module_dialogs(detector):
    """各模块的消耗框排在最前、自动关闭时点取消。"""
    from e7helper.modules.custom_flow.guard import GUARD_POPUPS, HANDLED_POPUPS

    for p in GUARD_POPUPS:
        assert "cancel" in p.dismiss.target
        detector.add_popup(p, replace=True, first=True)
    state = detector.detect(load_fixture("secret_shop_refresh_confirm"))
    assert state.popup in HANDLED_POPUPS
    assert detector.vision.template("secret_shop:dialog/buy_title") is not None


def test_max_taps(tmp_path, detector):
    sim = GameSim("shop")
    flow = _flow([{"type": "repeat", "count": 10, "body": [{"type": "tap_point", "x": 800, "y": 120}]}],
                 limits={"max_taps": 3})
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is TaskStatus.FAILED and "最多点击次数" in result.error
    assert len(sim.taps) == 3


def test_max_minutes_times_out(tmp_path, detector, monkeypatch):
    flow = _flow([{"type": "wait", "seconds": 30}])

    class ShortStore(FlowStore):
        def get(self, flow_id):
            f = super().get(flow_id)
            f.limits.max_minutes = 0.01  # 0.6 秒（正常最少 0.5 分钟）
            return f

    monkeypatch.setattr(CustomFlow, "store_factory", ShortStore)
    sim = GameSim("lobby")
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is TaskStatus.TIMEOUT
    assert result.duration < 5
    assert _history()[0]["status"] == "timeout"


def test_stop_flow(tmp_path, detector):
    sim = GameSim("lobby")
    flow = _flow([{"type": "wait", "seconds": 30}])
    with _runtime(sim, tmp_path, detector) as rt:
        handle = rt.start_task(CustomFlow, CustomFlowConfig(flow=flow.id))
        assert handle.wait(0.5) is None
        handle.stop()
        result = handle.wait(5)
    assert result.status is TaskStatus.STOPPED
    assert _history()[0]["status"] == "stopped"


def test_disconnect_during_flow_reloads(tmp_path, detector):
    """断线重进照常自动处理（B10a 的规则），流程接着跑。"""
    sim = GameSim("lobby_disconnected")
    flow = _flow([{"type": "wait_scene", "scene": "lobby", "timeout": 20}, *NAV])
    result = _run(sim, tmp_path, detector, flow)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.history[-3:] == ["lobby", "sanctuary", "lobby"]


def test_obscured_is_not_dismissed(tmp_path, detector):
    """遮罩兜底（按返回键）在流程里不生效：说明弹窗留给流程自己处理。"""
    sim = GameSim("sanctuary_help")
    flow = _flow([{"type": "wait", "seconds": 0.2}, {"type": "wait_still", "timeout": 1},
                  {"type": "tap_point", "x": 800, "y": 120}])
    assert _run(sim, tmp_path, detector, flow).status is TaskStatus.SUCCEEDED
    assert sim.backs == 0 and sim.history == ["sanctuary_help"]


def test_setup_errors(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector) as rt:
        with pytest.raises(ValueError, match="没有选择"):
            rt.start_task(CustomFlow, CustomFlowConfig())
        with pytest.raises(ValueError, match="流程不存在"):
            rt.start_task(CustomFlow, CustomFlowConfig(flow="fnope"))
        empty = _flow([])
        with pytest.raises(ValueError, match="还没有步骤"):
            rt.start_task(CustomFlow, CustomFlowConfig(flow=empty.id))
        bad = _flow([{"type": "tap_template", "template": "没采集的"}])
        with pytest.raises(ValueError, match="没采集的"):
            rt.start_task(CustomFlow, CustomFlowConfig(flow=bad.id))


def test_config_schema_lists_flows():
    assert "enum" not in CustomFlow.config_schema()["properties"]["flow"]
    f = _flow(NAV, name="圣域往返")
    prop = CustomFlow.config_schema()["properties"]["flow"]
    assert prop["enum"] == [f.id] and prop["x-enum-labels"] == {f.id: "圣域往返"}


def test_step_events(tmp_path, detector):
    sim = GameSim("lobby")
    flow = _flow(NAV)
    seen = []
    with _runtime(sim, tmp_path, detector) as rt:
        rt.bus.subscribe("custom_flow.step", lambda e: seen.append(e.data["path"]))
        assert rt.run_task(CustomFlow, CustomFlowConfig(flow=flow.id)).ok
    assert seen == ["1", "2", "3", "4"]


def test_step_numbering_in_logs(tmp_path, detector, caplog):
    sim = GameSim("lobby")
    flow = _flow([
        {"type": "if", "condition": {"kind": "scene", "scene": "lobby"},
         "then": [{"type": "wait", "seconds": 0.1}], "else": [{"type": "back"}]},
        {"type": "if", "condition": {"kind": "scene", "scene": "shop"},
         "then": [{"type": "wait", "seconds": 0.1}], "else": [{"type": "wait", "seconds": 0.1}]},
    ])
    with caplog.at_level("INFO"):
        assert _run(sim, tmp_path, detector, flow).ok
    text = caplog.text
    assert "第 1.1 步：等待 0.1 秒" in text and "第 2.2 步：等待 0.1 秒" in text


def test_log_uses_friendly_template_names(tmp_path, detector, caplog):
    _save_title_template()
    flow = _flow([*NAV[:2], {"type": "wait_template", "templates": ["圣域标题", "common:back"]}])
    with caplog.at_level("INFO"):
        assert _run(GameSim("lobby"), tmp_path, detector, flow).ok
    assert "第 1 步：点击模板「大厅左侧「圣域」文字」" in caplog.text
    assert "第 3 步：等模板「圣域标题」或「左上角返回」出现" in caplog.text

