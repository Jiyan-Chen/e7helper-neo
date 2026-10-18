import json
import random
import threading
import time

import numpy as np
import pytest
import game_sim
from game_sim import DANGER, LOADING, GameSim

from e7helper.core.events import EventBus, Topic
from e7helper.core.geometry import Rect
from e7helper.core.runtime import (
    Humanize,
    PopupError,
    Runtime,
    RuntimeBusy,
    StuckConfig,
    StuckDetector,
    TaskStatus,
    WaitTimeout,
)
from e7helper.core.scene import Dismiss, Popup, default_detector
from e7helper.device import DeviceError
from e7helper.modules import AssistantModule, TaskModule, discover


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(scope="module")
def detector():
    return default_detector()


def _runtime(sim, tmp_path, detector, **kw) -> Runtime:
    kw.setdefault("humanize", Humanize.off())
    return Runtime(sim, scenes=detector, debug_root=tmp_path / "debug", seed=1, **kw)


# ---------------------------------------------------------------- 点击随机化


def test_point_in_rect_stays_inside_margin():
    h = Humanize()
    rng = random.Random(0)
    rect = Rect(100, 200, 200, 60)
    pts = [h.point_in(rect, rng) for _ in range(2000)]
    xs, ys = zip(*pts, strict=True)
    assert min(xs) >= 100 + 200 * 0.2 - 1 and max(xs) <= 300 - 200 * 0.2 + 1
    assert min(ys) >= 200 + 60 * 0.2 - 1 and max(ys) <= 260 - 60 * 0.2 + 1
    assert len(set(pts)) > 100  # 确实是随机的
    assert abs(np.mean(xs) - 200) < 3 and abs(np.mean(ys) - 230) < 2


def test_jitter_is_truncated():
    h = Humanize(jitter_px=3)
    rng = random.Random(0)
    pts = [h.jitter(800, 450, rng) for _ in range(1000)]
    assert all(abs(x - 800) <= 6 and abs(y - 450) <= 6 for x, y in pts)
    assert Humanize.off().jitter(800, 450, rng) == (800, 450)


# ---------------------------------------------------------------- Controller


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_tap_converts_base_to_device(tmp_path, detector, size):
    sim = GameSim("lobby", size)
    with _runtime(sim, tmp_path, detector) as rt:
        ctl = rt.make_controller()
        ctl.tap(800, 450)
        ctl.tap_rect(Rect(100, 100, 50, 50))
    sx = size[0] / 1600
    assert sim.taps[0][:2] == (round(800 * sx), round(450 * sx))
    assert sim.taps[1][:2] == (round(125 * sx), round(125 * sx))


def test_humanized_taps_vary_and_stay_in_match(tmp_path, detector):
    sim = GameSim("lobby")
    with Runtime(sim, scenes=detector, humanize=Humanize(delay=(0, 0))) as rt:
        ctl = rt.make_controller()
        m = ctl.find("lobby/shop")
        pts = {ctl.tap_match(m) for _ in range(30)}
        sim.screen = "lobby"
    assert len(pts) > 5
    assert all(m.rect.x <= x < m.rect.right and m.rect.y <= y < m.rect.bottom for x, y in pts)
    durations = {round(d, 4) for *_, d in sim.taps}
    assert len(durations) > 5 and all(0.04 <= d <= 0.09 for d in durations)


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
@pytest.mark.parametrize(("start", "target", "closed"), [
    ("secret_shop_refresh_confirm", "secret_shop", ["confirm"]),
    ("lobby_exit_confirm", "lobby", ["confirm"]),
    ("sanctuary_help", "sanctuary", ["obscured"]),
    ("arena_notice", "arena", ["notice"]),
    ("lobby_network_error", "lobby", ["network"]),
])
def test_dismiss_popups_closes_and_never_confirms(tmp_path, detector, size, start, target, closed):
    sim = GameSim(start, size)
    with _runtime(sim, tmp_path, detector) as rt:
        ctl = rt.make_controller()
        assert ctl.dismiss_popups() == closed
        assert ctl.detect().is_(target)
    assert DANGER not in sim.history
    assert sim.history == [start, target]


def test_transient_dim_is_not_treated_as_popup(tmp_path, detector):
    """界面切换的淡入淡出会让画面短暂变暗：画面在动时不能当成未知弹窗按返回键。"""
    sim = GameSim("sanctuary_help")
    sim.animating = 100
    sim.then = (3, "sanctuary")  # 3 帧后过渡结束
    with _runtime(sim, tmp_path, detector) as rt:
        assert rt.make_controller().dismiss_popups() == []
    assert sim.backs == 0


def test_static_dim_is_dismissed_with_back(tmp_path, detector):
    sim = GameSim("sanctuary_help")
    with _runtime(sim, tmp_path, detector) as rt:
        assert rt.make_controller().dismiss_popups() == ["obscured"]
    assert sim.backs == 1


def test_wait_scene_dismisses_popup_on_the_way(tmp_path, detector):
    sim = GameSim("secret_shop_refresh_confirm")
    with _runtime(sim, tmp_path, detector) as rt:
        state = rt.make_controller().wait_scene("secret_shop", timeout=3)
    assert state.is_("secret_shop")
    assert DANGER not in sim.history


def test_wait_scene_waits_for_animation(tmp_path, detector):
    """标题已经能识别，但画面还在动（列表飞入）时不返回，等静止 0.5 秒后才返回。"""
    sim = GameSim("secret_shop")
    sim.animating = 6
    with _runtime(sim, tmp_path, detector) as rt:
        ctl = rt.make_controller()
        t0 = time.monotonic()
        ctl.wait_scene("secret_shop", timeout=10, interval=0.05)
        elapsed = time.monotonic() - t0
    assert sim.animating == 0
    assert elapsed >= 0.5


def test_tap_uses_template_tap_area(tmp_path, detector):
    """大厅「秘密商店」识别的是文字，点击的是 json 里 tap 指定的图标区域。"""
    sim = GameSim("lobby")
    with Runtime(sim, scenes=detector, humanize=Humanize(delay=(0, 0))) as rt:
        ctl = rt.make_controller()
        pts = []
        for _ in range(30):
            sim.screen = "lobby"
            m = ctl.tap_template("lobby/secret_shop")
            pts.append(sim.taps[-1][:2])
    assert m.rect.y == 438
    assert all(40 <= x < 110 and 385 <= y < 447 for x, y in pts), pts


def test_tap_area_follows_match_offset():
    import numpy as np

    from e7helper.core.vision import Template, TemplateMeta

    meta = TemplateMeta.model_validate({"box": [26, 438, 92, 32], "tap": [40, 385, 70, 62]})
    tpl = Template("t", np.zeros((32, 92, 3), np.uint8), meta)
    assert tpl.tap_area(Rect(26, 438, 92, 32)) == Rect(40, 385, 70, 62)
    assert tpl.tap_area(Rect(36, 448, 92, 32)) == Rect(50, 395, 70, 62)  # 整体平移
    assert Template("u", tpl.image).tap_area(Rect(1, 2, 3, 4)) == Rect(1, 2, 3, 4)  # 没设 tap
    assert '"tap": [40, 385, 70, 62]' in meta.to_json()


def test_wait_scene_timeout(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector) as rt:
        with pytest.raises(WaitTimeout, match="arena"):
            rt.make_controller().wait_scene("arena", timeout=0.3, interval=0.05)


def test_non_auto_popup_raises(tmp_path):
    d = default_detector()
    d.add_popup(Popup("ask_user", ("dialog/cancel", "dialog/confirm"), Dismiss.none(), auto=False), first=True)
    sim = GameSim("secret_shop_refresh_confirm")
    with _runtime(sim, tmp_path, d) as rt:
        with pytest.raises(PopupError) as e:
            rt.make_controller().dismiss_popups()
    assert e.value.popup == "ask_user"
    assert sim.taps == [] and sim.backs == 0


# ---------------------------------------------------------------- 断线重进（B10a）

RELOGIN_HISTORY = ["lobby_disconnected", "title_announcement", "title_connecting", "title_start", LOADING, "lobby"]


def test_disconnected_relogins_to_lobby(tmp_path, detector):
    """断线框 → 公告窗 → 标题「连接中」→ 轻触画面开始 → 黑屏 → 大厅，全程只点屏幕。"""
    sim = GameSim("lobby_disconnected")
    with _runtime(sim, tmp_path, detector) as rt:
        ctl = rt.make_controller()
        assert ctl.dismiss_popups() == ["disconnected", "announcement", "title_start"]
        assert ctl.detect().is_("lobby")
        assert ctl.reloads == 3
    assert sim.history == RELOGIN_HISTORY
    # 标题画面只点了「轻触画面开始」那行字，没碰下面的协议链接
    start_taps = [(x, y) for x, y, _ in sim.taps if 700 < y < 800]
    assert len(start_taps) == 1 and 728 <= start_taps[0][0] < 872 and 730 <= start_taps[0][1] < 760


def test_wait_scene_survives_slow_relogin(tmp_path, detector):
    """重进游戏比 wait_scene 的超时还久：重进后重新计时，不算超时。"""
    sim = GameSim("lobby_disconnected")
    with _runtime(sim, tmp_path, detector) as rt:
        t0 = time.monotonic()
        state = rt.make_controller().wait_scene("lobby", timeout=1.5)
        assert time.monotonic() - t0 > 1.5
    assert state.is_("lobby")
    assert sim.history == RELOGIN_HISTORY


def test_tap_until_retaps_after_relogin(tmp_path, detector):
    """导航途中断线：重进回到大厅（点击前的场景）后补点，继续进目标界面。"""
    sim = GameSim("lobby", drop_taps=1)
    sim.then = (2, "lobby_disconnected")
    with _runtime(sim, tmp_path, detector) as rt:
        state = rt.make_controller().tap_until("lobby/secret_shop", "secret_shop", timeout=1.0, retry_after=0.3)
    assert state.is_("secret_shop")
    assert sim.history == ["lobby", *RELOGIN_HISTORY, "secret_shop"]


def test_relogin_timeout_raises(tmp_path, detector, monkeypatch):
    """一直黑屏进不去：超时抛 PopupError，交给任务失败处理。"""
    import e7helper.core.runtime.controller as controller

    monkeypatch.setattr(controller, "RELOAD_TIMEOUT", 1.0)
    monkeypatch.delitem(game_sim.AUTO, LOADING)
    sim = GameSim("title_start")
    with _runtime(sim, tmp_path, detector) as rt:
        with pytest.raises(PopupError, match="仍未加载完") as e:
            rt.make_controller().dismiss_popups()
    assert e.value.popup == "title_start"
    assert sim.screen == LOADING and len(sim.taps) == 1


def test_navigation_flow(tmp_path, detector):
    """大厅 → 秘密商店 → 返回大厅，全程用场景等待。"""
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector) as rt:
        ctl = rt.make_controller()
        ctl.wait_scene("lobby")
        ctl.tap_template("lobby/secret_shop")
        ctl.wait_scene("secret_shop", timeout=2)
        ctl.tap_template("back")
        ctl.wait_scene("lobby", timeout=2)
    assert sim.history == ["lobby", "secret_shop", "lobby"]


def test_tap_until_retries_dropped_tap(tmp_path, detector):
    sim = GameSim("lobby", drop_taps=1)
    with _runtime(sim, tmp_path, detector) as rt:
        state = rt.make_controller().tap_until("lobby/secret_shop", "secret_shop", timeout=5, retry_after=0.3)
    assert state.is_("secret_shop")
    assert len(sim.taps) == 2


def test_tap_until_gives_up_after_max_taps(tmp_path, detector):
    sim = GameSim("lobby", drop_taps=10)
    with _runtime(sim, tmp_path, detector) as rt:
        with pytest.raises(WaitTimeout, match="点了 2 次"):
            rt.make_controller().tap_until((70, 230), "sanctuary", timeout=5, retry_after=0.2, max_taps=2)
    assert len(sim.taps) == 2


def test_tap_until_does_not_retap_when_screen_changed(tmp_path, detector):
    """点击后画面变了（例如进了别的界面/在加载），不再重复点击。"""
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector) as rt:
        with pytest.raises(WaitTimeout):
            # 点商店入口会进 shop，而我们等的是 arena：不能在 shop 里继续乱点
            rt.make_controller().tap_until("lobby/shop", "arena", timeout=1.0, retry_after=0.3)
    assert len(sim.taps) == 1 and sim.screen == "shop"


def test_screenshot_publishes_frame_and_scene_events(tmp_path, detector):
    bus = EventBus()
    frames, scenes = [], []
    bus.subscribe(Topic.FRAME, lambda e: frames.append(e.data.shape))
    bus.subscribe(Topic.SCENE, lambda e: scenes.append(e.data["scene"]))
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector, bus=bus) as rt:
        ctl = rt.make_controller()
        ctl.detect()
        ctl.detect()  # 场景没变，不重复发
        sim.screen = "shop"
        ctl.detect()
    assert frames == [(900, 1600, 3)] * 3
    assert scenes == ["lobby", "shop"]


# ---------------------------------------------------------------- 卡死检测


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_stuck_on_still_frames():
    clock = FakeClock()
    det = StuckDetector(StuckConfig(still_frames=5, still_seconds=10), clock)
    frame = np.full((90, 160, 3), 100, np.uint8)
    for _ in range(6):
        det.feed_frame(frame)
        clock.t += 1
    assert det.reason is None  # 帧数够了，时间不够
    clock.t += 10
    assert "没有变化" in det.reason
    det.reset()
    assert det.reason is None


def test_changing_frames_are_not_stuck():
    clock = FakeClock()
    det = StuckDetector(StuckConfig(still_frames=3, still_seconds=0), clock)
    for i in range(20):
        det.feed_frame(np.full((90, 160, 3), (i * 10) % 250, np.uint8))
    assert det.reason is None


def test_stuck_on_same_scene():
    clock = FakeClock()
    det = StuckDetector(StuckConfig(scene_checks=3, scene_seconds=5), clock)
    for _ in range(4):
        det.feed_scene("lobby|None")
        clock.t += 2
    assert "lobby" in det.reason
    det.feed_scene("shop|None")
    assert det.reason is None


def test_stuck_disabled():
    det = StuckDetector(StuckConfig(enabled=False, still_frames=0, still_seconds=0))
    det.feed_frame(np.zeros((90, 160, 3), np.uint8))
    det.feed_frame(np.zeros((90, 160, 3), np.uint8))
    assert det.reason is None


# ---------------------------------------------------------------- 任务调度


class BlockingTask(TaskModule):
    id = "test_blocking"
    name = "阻塞任务"

    def run(self):
        while True:
            self.ctl.screenshot()
            self.ctl.sleep(0.02)


class SwallowingTask(TaskModule):
    """用 except Exception 包住一切的模块，也不能吞掉急停。"""

    id = "test_swallow"
    name = "吞异常任务"

    def run(self):
        while True:
            try:
                self.ctl.screenshot()
                self.ctl.sleep(0.02)
            except Exception:
                pass


class FailingTask(TaskModule):
    id = "test_failing"
    name = "失败任务"

    def run(self):
        self.ctl.detect()
        raise ValueError("模块内部错误")


class PollingTask(TaskModule):
    """不用 ctl，只轮询 self.stopped 的老式写法。"""

    id = "test_polling"
    name = "轮询任务"

    def run(self):
        while not self.stopped:
            time.sleep(0.01)


class AssistantProbe(AssistantModule):
    id = "test_assistant"
    name = "收帧助手"

    def setup(self):
        self.frames = 0
        self.threads = set()
        self.tap_error = None

    def on_frame(self, frame):
        self.frames += 1
        self.threads.add(threading.current_thread().name)
        try:
            self.device.tap(1, 1)
        except DeviceError as e:
            self.tap_error = str(e)


def test_task_mutex_and_stop(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector) as rt:
        h = rt.start_task(BlockingTask)
        with pytest.raises(RuntimeBusy):
            rt.start_task(BlockingTask)
        assert rt.current_task is h
        h.stop()
        result = h.wait(3)
        assert result.status is TaskStatus.STOPPED
        assert result.debug_dir is None  # 用户急停不存调试信息
        assert rt.current_task is None
        # 结束后可以再启动
        h2 = rt.start_task(BlockingTask)
        h2.stop()
        assert h2.wait(3).status is TaskStatus.STOPPED


def test_one_runtime_per_device(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector):
        with pytest.raises(RuntimeBusy):
            _runtime(sim, tmp_path, detector)
    _runtime(sim, tmp_path, detector).close()  # 关闭后释放


def test_timeout_saves_debug_info(tmp_path, detector, caplog):
    sim = GameSim("secret_shop")
    # 日志环形缓冲只收到已通过 logger 级别过滤的记录；CLI 里是 INFO，这里显式设置
    with _runtime(sim, tmp_path, detector) as rt, caplog.at_level("INFO"):
        result = rt.run_task(BlockingTask, timeout=0.3)
    assert result.status is TaskStatus.TIMEOUT
    assert 0.25 < result.duration < 3
    d = result.debug_dir
    assert d is not None and d.parent == tmp_path / "debug"
    for f in ("last_frame.png", "screen.png", "info.json", "error.txt", "log.txt"):
        assert (d / f).is_file(), f
    info = json.loads((d / "info.json").read_text(encoding="utf-8"))
    assert info["module"] == "test_blocking" and info["status"] == "timeout"
    assert "任务开始" in (d / "log.txt").read_text(encoding="utf-8")


def test_abort_is_not_swallowed_by_except_exception(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector) as rt:
        assert rt.run_task(SwallowingTask, timeout=0.2).status is TaskStatus.TIMEOUT


def test_failure_saves_traceback(tmp_path, detector):
    sim = GameSim("lobby")
    events = []
    bus = EventBus()
    bus.subscribe(Topic.TASK, lambda e: events.append(e.data["status"]))
    with _runtime(sim, tmp_path, detector, bus=bus) as rt:
        result = rt.run_task(FailingTask)
    assert result.status is TaskStatus.FAILED
    assert "模块内部错误" in result.error
    assert "ValueError" in (result.debug_dir / "error.txt").read_text(encoding="utf-8")
    info = json.loads((result.debug_dir / "info.json").read_text(encoding="utf-8"))
    assert info["scene"] == "lobby"
    assert events == ["running", "failed"]


def test_stuck_task(tmp_path, detector):
    sim = GameSim("secret_shop")  # 静态画面
    with _runtime(sim, tmp_path, detector, stuck=StuckConfig(still_frames=5, still_seconds=0)) as rt:
        result = rt.run_task(BlockingTask, timeout=5)
    assert result.status is TaskStatus.STUCK
    assert "没有变化" in result.error
    assert (result.debug_dir / "last_frame.png").is_file()


def test_polling_task_stopped_by_timeout(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector) as rt:
        assert rt.run_task(PollingTask, timeout=0.2).status is TaskStatus.TIMEOUT


def test_hello_via_runtime(tmp_path, detector, caplog):
    cls = discover(include_entry_points=False)["hello"]
    sim = GameSim("arena")
    with _runtime(sim, tmp_path, detector) as rt, caplog.at_level("INFO"):
        result = rt.run_task(cls, cls.config_model(screenshots=2))
    assert result.ok
    assert sum("场景：arena" in r.message for r in caplog.records) == 2


def test_assistant_gets_frames_in_parallel_and_cannot_tap(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector, frame_interval=0.05) as rt:
        h = rt.attach_assistant(AssistantProbe)
        probe = h.module
        task = rt.start_task(BlockingTask)  # 助手和任务并行
        deadline = time.monotonic() + 3
        while probe.frames < 5 and time.monotonic() < deadline:
            time.sleep(0.02)
        task.stop()
        task.wait(3)
        with pytest.raises(RuntimeBusy):
            rt.attach_assistant(AssistantProbe)
        h.detach()
        assert "test_assistant" not in rt.assistants
    assert probe.frames >= 5
    assert probe.threads == {"events:assistant:test_assistant"}
    assert "不能操作" in probe.tap_error
    assert sim.taps == []


def test_frame_pump_feeds_assistant_without_task(tmp_path, detector):
    sim = GameSim("lobby")
    with _runtime(sim, tmp_path, detector, frame_interval=0.05) as rt:
        probe = rt.attach_assistant(AssistantProbe).module
        deadline = time.monotonic() + 3
        while probe.frames < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
    assert probe.frames >= 3


def test_start_task_rejects_non_task(tmp_path, detector):
    with _runtime(GameSim(), tmp_path, detector) as rt:
        with pytest.raises(TypeError):
            rt.start_task(AssistantProbe)
        with pytest.raises(TypeError):
            rt.attach_assistant(BlockingTask)
