"""定时调度（离线）：时钟可注入，手动调用 tick()，任务用不点游戏的假模块。"""

from datetime import UTC, datetime, timedelta

import pytest
from api_fakes import QuickTask, make_engine, wait_for

from e7helper.api import ApiError, Scheduler, ScheduleSpec
from e7helper.api.scheduler import BEIJING, next_daily
from e7helper.core.events import Topic
from e7helper.core.scene import default_detector
from e7helper.modules.daily import DailyModule
from e7helper.modules.daily import ledger as ledger_mod
from e7helper.modules.daily.config import DailyConfig
from e7helper.modules.daily.ledger import Ledger, next_reset


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))
    QuickTask.due = None
    QuickTask.due_calls = []


@pytest.fixture(scope="module")
def detector():
    return default_detector()


class Clock:
    """以真实时间为起点、可以拨快的时钟（任务记录用的是真实时间，两者要对得上）。"""

    def __init__(self):
        self.offset = timedelta()

    def __call__(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def advance(self, **kw) -> None:
        self.offset += timedelta(**kw)


@pytest.fixture
def env(tmp_path, detector):
    engine = make_engine(tmp_path, detector)
    engine.connect()
    clock = Clock()
    sched = Scheduler(engine, clock=clock)
    events = []
    engine.bus.subscribe(Topic.SCHEDULE, lambda e: events.append(e.data))
    yield engine, sched, clock, events
    sched.stop()
    engine.close()


def _spec(**kw) -> ScheduleSpec:
    kw.setdefault("module", "quick")
    kw.setdefault("trigger", {"type": "interval", "minutes": 30})
    return ScheduleSpec.model_validate(kw)


def _settle(engine, sched, sid):
    """等这条计划的任务跑完、回调处理完。"""
    engine.wait_task(5)
    wait_for(lambda: sched.schedules[sid].state.running_task is None)


def _actions(events, sid=None):
    return [e["action"] for e in events if sid is None or e.get("id") == sid]


# ---------------------------------------------------------------- 时间计算


def test_next_daily_beijing_time():
    # 北京时间 10-18 02:00 → 当天 03:05
    t = datetime(2026, 10, 18, 2, 0, tzinfo=BEIJING)
    assert next_daily("03:05", t) == datetime(2026, 10, 17, 19, 5, tzinfo=UTC)
    # 正好 03:05 → 第二天
    t = datetime(2026, 10, 18, 3, 5, tzinfo=BEIJING)
    assert next_daily("03:05", t).astimezone(BEIJING) == datetime(2026, 10, 19, 3, 5, tzinfo=BEIJING)
    # UTC 时间输入也一样
    assert next_daily("23:30", datetime(2026, 10, 18, 16, 0, tzinfo=UTC)) == datetime(2026, 10, 19, 15, 30,
                                                                                        tzinfo=UTC)


def test_next_reset():
    assert next_reset(datetime(2026, 10, 18, 18, 59, tzinfo=UTC)) == datetime(2026, 10, 18, 19, 0, tzinfo=UTC)
    assert next_reset(datetime(2026, 10, 18, 19, 0, tzinfo=UTC)) == datetime(2026, 10, 19, 19, 0, tzinfo=UTC)


# ---------------------------------------------------------------- 创建 / 校验


def test_create_copies_saved_config_and_validates(env):
    engine, sched, clock, _ = env
    engine.save_config(QuickTask, {"dry_run": False})
    s = sched.create(_spec())
    assert s["config"] == {"fail": False, "dry_run": False} and s["module_name"] == "快任务"
    s2 = sched.create(_spec(config={"dry_run": True}))
    assert s2["config"] == {"fail": False, "dry_run": True}  # 调度器不改 dry_run

    with pytest.raises(ApiError) as e:
        sched.create(_spec(config={"fail": "x"}))
    assert e.value.code == "invalid_config"
    with pytest.raises(ApiError) as e:
        sched.create(_spec(module="slow", trigger={"type": "module"}))
    assert e.value.code == "trigger_unsupported"
    with pytest.raises(ApiError) as e:
        sched.create(_spec(module="echo"))
    assert e.value.code == "not_task"
    with pytest.raises(ValueError):
        _spec(trigger={"type": "daily", "at": "25:00"})
    with pytest.raises(ValueError):
        _spec(trigger={"type": "interval", "minutes": 0.5})
    with pytest.raises(ValueError):
        _spec(bogus=1)


def test_update_and_delete(env):
    engine, sched, clock, events = env
    sid = sched.create(_spec())["id"]
    s = sched.update(sid, {"enabled": False, "name": "托管"})
    assert s["enabled"] is False and s["name"] == "托管" and s["state"]["next_run"] is None
    with pytest.raises(ApiError) as e:
        sched.update(sid, {"trigger": {"type": "daily", "at": "nope"}})
    assert e.value.code == "invalid_schedule"
    with pytest.raises(ApiError):
        sched.update(sid, {"id": "x"})
    sched.delete(sid)
    with pytest.raises(ApiError) as e:
        sched.get(sid)
    assert e.value.status == 404
    assert _actions(events, sid) == ["created", "updated", "deleted"]


# ---------------------------------------------------------------- 触发


def test_interval_runs_immediately_then_after_end(env):
    engine, sched, clock, events = env
    sid = sched.create(_spec(trigger={"type": "interval", "minutes": 30}))["id"]
    sched.tick()
    _settle(engine, sched, sid)
    st = sched.schedules[sid].state
    assert st.last_status == "succeeded" and st.last_success is not None
    assert st.next_run == st.last_ended + timedelta(minutes=30)
    assert engine.task_history()[0]["source"] == f"schedule:{sid}"

    clock.advance(minutes=29)
    sched.tick()
    assert not engine.busy and len(engine.task_history()) == 1
    clock.advance(minutes=2)
    sched.tick()
    _settle(engine, sched, sid)
    assert len(engine.task_history()) == 2
    assert _actions(events, sid) == ["created", "started", "finished", "started", "finished"]


def test_daily_trigger_and_catch_up_once(env):
    engine, sched, clock, _ = env
    s = sched.create(_spec(trigger={"type": "daily", "at": "03:05"}))
    sid = s["id"]
    first = datetime.fromisoformat(s["state"]["next_run"])
    assert first == next_daily("03:05", clock())
    sched.tick()
    assert not engine.busy  # 还没到点

    # 服务「关了」两天：只补跑一次
    clock.advance(days=2)
    sched.tick()
    _settle(engine, sched, sid)
    sched.tick()
    assert not engine.busy and len(engine.task_history()) == 1
    nxt = sched.schedules[sid].state.next_run
    assert nxt > clock() and nxt.astimezone(BEIJING).strftime("%H:%M") == "03:05"


def test_busy_queues_then_runs(env):
    engine, sched, clock, events = env
    engine.start_task("slow", {"seconds": 30})
    sid = sched.create(_spec())["id"]
    sched.tick()
    assert sched.schedules[sid].state.queued_since is not None
    assert _actions(events, sid)[-1] == "queued"
    sched.tick()  # 还在排队，不重复入队
    assert _actions(events, sid).count("queued") == 1

    engine.stop_task()
    engine.wait_task(5)
    sched.tick()
    _settle(engine, sched, sid)
    assert sched.schedules[sid].state.last_status == "succeeded"
    assert sched.schedules[sid].state.queued_since is None


def test_queue_expires(env):
    engine, sched, clock, events = env
    engine.start_task("slow", {"seconds": 30})
    sid = sched.create(_spec(max_wait_minutes=5))["id"]
    sched.tick()
    clock.advance(minutes=6)
    sched.tick()
    st = sched.schedules[sid].state
    assert st.queued_since is None and "排队超过" in st.last_skip
    assert st.next_run == st.last_attempt + timedelta(minutes=30)
    engine.stop_task()
    engine.wait_task(5)


def test_on_busy_skip(env):
    engine, sched, clock, events = env
    engine.start_task("slow", {"seconds": 30})
    sid = sched.create(_spec(on_busy="skip"))["id"]
    sched.tick()
    st = sched.schedules[sid].state
    assert st.queued_since is None and st.last_skip == "有任务在运行"
    assert _actions(events, sid)[-1] == "skipped"
    engine.stop_task()
    engine.wait_task(5)


def test_queued_run_in_fifo_order(env):
    engine, sched, clock, events = env
    engine.start_task("slow", {"seconds": 30})
    b = sched.create(_spec(name="b", trigger={"type": "interval", "minutes": 30}))["id"]
    clock.advance(seconds=1)
    sched.tick()
    a = sched.create(_spec(name="a"))["id"]
    clock.advance(seconds=1)
    sched.tick()
    assert sched.schedules[b].state.queued_since < sched.schedules[a].state.queued_since
    engine.stop_task()
    engine.wait_task(5)
    for _ in range(3):
        sched.tick()
        engine.wait_task(5)
        wait_for(lambda: not any(s.state.running_task for s in sched.schedules.values()))
    started = [e["id"] for e in events if e["action"] == "started"]
    assert started == [b, a]  # 先入队的先跑


def test_no_device_tries_connect_then_skips(tmp_path, detector):
    engine = make_engine(tmp_path, detector, fail_connect=True)
    sched = Scheduler(engine, clock=Clock())
    sid = sched.create(_spec())["id"]
    sched.tick()
    st = sched.schedules[sid].state
    assert "连接设备失败" in st.last_skip and st.failures == 0
    engine.close()


def test_failures_disable_after_three(env):
    engine, sched, clock, events = env
    sid = sched.create(_spec(config={"fail": True}, trigger={"type": "interval", "minutes": 1}))["id"]
    for _ in range(3):
        sched.tick()
        _settle(engine, sched, sid)
        clock.advance(minutes=2)
    s = sched.schedules[sid]
    assert s.enabled is False and s.state.failures == 3 and s.state.next_run is None
    wait_for(lambda: "disabled" in _actions(events, sid))
    sched.tick()
    assert not engine.busy
    # 重新启用：失败计数清零
    sched.update(sid, {"enabled": True, "config": {"fail": False}})
    assert sched.schedules[sid].state.failures == 0


def test_stopped_is_not_a_failure(env):
    engine, sched, clock, _ = env
    sid = sched.create(_spec(module="slow", config={"seconds": 30}))["id"]
    sched.tick()
    wait_for(lambda: engine.busy)
    engine.stop_task()
    _settle(engine, sched, sid)
    st = sched.schedules[sid].state
    assert st.last_status == "stopped" and st.failures == 0 and st.last_success is None


def test_pause_blocks_triggers(env):
    engine, sched, clock, events = env
    sched.set_paused(True)
    sid = sched.create(_spec())["id"]
    sched.tick()
    assert not engine.busy and sched.schedules[sid].state.next_run is not None  # 仍然显示下次时间
    sched.set_paused(False)
    sched.tick()
    _settle(engine, sched, sid)
    assert sched.schedules[sid].state.last_status == "succeeded"


def test_run_now(env):
    engine, sched, clock, _ = env
    sid = sched.create(_spec(module="slow", config={"seconds": 30}, trigger={"type": "daily", "at": "03:05"}))["id"]
    rec = sched.run_now(sid)
    assert rec["source"] == f"schedule:{sid}"
    with pytest.raises(ApiError) as e:
        sched.run_now(sid)
    assert e.value.code == "busy"
    other = sched.create(_spec(trigger={"type": "daily", "at": "03:05"}))["id"]
    with pytest.raises(ApiError) as e:
        sched.run_now(other)  # 别的任务在跑
    assert e.value.code == "busy"
    engine.stop_task()
    _settle(engine, sched, sid)
    assert sched.schedules[sid].state.last_status == "stopped"


def test_module_trigger_uses_next_due_and_min_interval(env):
    engine, sched, clock, _ = env
    QuickTask.due = clock() - timedelta(minutes=1)
    sid = sched.create(_spec(trigger={"type": "module", "min_interval_minutes": 10}))["id"]
    sched.tick()
    _settle(engine, sched, sid)
    st = sched.schedules[sid].state
    assert QuickTask.due_calls[-1] == st.last_success  # 把上次成功时间传给模块
    # 模块说「已经到了」，但离上次结束不到 10 分钟
    assert st.next_run == st.last_attempt + timedelta(minutes=10)
    QuickTask.due = None
    sched.tick()
    assert sched.schedules[sid].state.next_run is None  # 模块说暂时不用跑
    QuickTask.due = clock() + timedelta(hours=3)
    sched.tick()
    assert sched.schedules[sid].state.next_run == QuickTask.due


def test_module_trigger_failure_backoff(env):
    engine, sched, clock, _ = env
    QuickTask.due = clock()
    sid = sched.create(_spec(config={"fail": True}, trigger={"type": "module", "min_interval_minutes": 10}))["id"]
    sched.tick()
    _settle(engine, sched, sid)
    st = sched.schedules[sid].state
    assert st.failures == 1 and st.next_run == st.last_attempt + timedelta(minutes=20)


def test_persistence(env, tmp_path, detector):
    engine, sched, clock, _ = env
    sid = sched.create(_spec(name="持久化"))["id"]
    sched.tick()
    _settle(engine, sched, sid)
    sched.set_paused(True)
    again = Scheduler(engine, clock=clock)
    assert again.paused is True
    s = again.schedules[sid]
    assert s.name == "持久化" and s.state.last_status == "succeeded" and s.state.running_task is None


def test_scheduler_thread_runs(env):
    engine, sched, clock, _ = env
    sched.tick_interval = 0.05
    sid = sched.create(_spec())["id"]
    sched.start()
    wait_for(lambda: sched.schedules[sid].state.last_status == "succeeded")
    sched.stop()


# ---------------------------------------------------------------- daily 的计时 / 下次时间


@pytest.fixture
def daily_clock(monkeypatch):
    now = {"t": datetime(2026, 10, 18, 4, 0, tzinfo=UTC)}  # 北京时间 12:00
    monkeypatch.setattr(ledger_mod, "utcnow", lambda: now["t"])
    return now


def test_daily_next_due(tmp_path, daily_clock):
    d = tmp_path / "daily"
    d.mkdir()
    cfg = DailyConfig()
    now = daily_clock["t"]
    # 从没成功过 / 上次成功在前一个游戏日 → 马上
    assert DailyModule.next_due(cfg, d, None) == now
    assert DailyModule.next_due(cfg, d, datetime(2026, 10, 17, 18, 0, tzinfo=UTC)) == now
    # 今天跑过、精灵之森没记时间 → 下一次重置（北京时间 10-19 03:00）
    last = now - timedelta(hours=1)
    assert DailyModule.next_due(cfg, d, last) == datetime(2026, 10, 18, 19, 0, tzinfo=UTC)
    # 精灵之森 2 小时后 → 2 小时后
    lg = Ledger.open(d, clock=lambda: now)
    lg.set_forest_next(7200)
    assert DailyModule.next_due(cfg, d, last) == now + timedelta(hours=2)
    # 关了精灵之森 → 不看 forest_next
    assert DailyModule.next_due(DailyConfig(forest=False), d, last) == datetime(2026, 10, 18, 19, 0, tzinfo=UTC)
    # forest_next 早于上次成功（上次没更新它）→ 不作数
    assert DailyModule.next_due(cfg, d, now + timedelta(hours=3)) == datetime(2026, 10, 18, 19, 0, tzinfo=UTC)


def test_daily_timers(tmp_path, daily_clock):
    d = tmp_path / "daily"
    d.mkdir()
    now = daily_clock["t"]
    t = {x.key: x for x in DailyModule.timers(d)}
    assert t["reset"].at == datetime(2026, 10, 18, 19, 0, tzinfo=UTC)
    assert t["forest"].at is None and t["forest"].note == "下次运行时查看"
    assert t["covenant"].note == "今天还没用完"
    lg = Ledger.open(d, clock=lambda: now)
    lg.set_forest_next(-60)
    lg.mark_done("covenant", summons=10)
    t = {x.key: x for x in DailyModule.timers(d)}
    assert t["forest"].note == "已到时间" and t["covenant"].note == "今天已用完"
