"""API 层：路由、鉴权、WebSocket（离线，GameSim 提供画面，假模块不点游戏）。"""

import json

import cv2
import numpy as np
import pytest
from api_fakes import FAKE_MODULES, EchoAssistant, QuickTask, make_engine, wait_for
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from e7helper.api import create_app
from e7helper.api.auth import host_name
from e7helper.core.scene import default_detector
from e7helper.modules import ModuleRegistryError, TaskModule, discover

TOKEN = "test-token"
BASE = "http://127.0.0.1:47800"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))
    QuickTask.due = None
    _pending.clear()


@pytest.fixture(scope="module")
def detector():
    return default_detector()


def _client(engine, **kw) -> TestClient:
    kw.setdefault("token", TOKEN)
    kw.setdefault("start_scheduler", False)
    app = create_app(engine, **kw)
    return TestClient(app, base_url=BASE, headers=AUTH)


@pytest.fixture
def engine(tmp_path, detector):
    return make_engine(tmp_path, detector)


@pytest.fixture
def client(engine):
    with _client(engine) as c:
        wait_for(lambda: engine.runtime is not None)  # 启动时自动连接
        yield c


def _ws_url(path="/ws", token=TOKEN, **params):
    q = "&".join(f"{k}={v}" for k, v in {"token": token, **params}.items() if v is not None)
    url = "ws://127.0.0.1:47800" + path  # TestClient 默认用 ws://testserver，过不了 Host 校验
    return f"{url}?{q}" if q else url


_pending: dict[int, list] = {}


def _recv_until(ws, pred, limit=200):
    """取第一条满足 pred 的消息；不满足的留着给后面的调用（事件可能比回复先到）。"""
    buf = _pending.setdefault(id(ws), [])
    for i, msg in enumerate(buf):
        if pred(msg):
            return buf.pop(i)
    for _ in range(limit):
        msg = ws.receive_json()
        if pred(msg):
            return msg
        buf.append(msg)
    raise AssertionError("没有等到期望的消息")


# ---------------------------------------------------------------- 鉴权


def test_health_needs_no_token(engine):
    with _client(engine, autoconnect=False) as c:
        r = c.get("/api/health", headers={"Authorization": ""})
        assert r.status_code == 200
        assert r.json()["ok"] and r.json()["auth"] is True


def test_token_required(engine):
    with _client(engine, autoconnect=False) as c:
        assert c.get("/api/status", headers={"Authorization": ""}).status_code == 401
        assert c.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get(f"/api/status?token={TOKEN}", headers={"Authorization": ""}).status_code == 200
        assert c.get("/api/status").status_code == 200


def test_no_auth_mode(engine):
    with _client(engine, token=None, autoconnect=False) as c:
        assert c.get("/api/status", headers={"Authorization": ""}).status_code == 200


def test_host_check(engine):
    with _client(engine, autoconnect=False) as c:
        r = c.get("/api/health", headers={"Host": "evil.example.com"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_host"
        assert c.get("/api/health", headers={"Host": "localhost:47800"}).status_code == 200
        with pytest.raises(WebSocketDisconnect), c.websocket_connect(_ws_url(), headers={"Host": "evil.com"}) as ws:
            ws.receive_json()


def test_redact_token_filter():
    import logging

    from e7helper.api.auth import RedactTokenFilter

    rec = logging.LogRecord("uvicorn.error", logging.INFO, "", 0, '%s - "WebSocket %s" [accepted]',
                            ("127.0.0.1:1", "/ws?token=abc-123&fps=2"), None)
    RedactTokenFilter().filter(rec)
    assert rec.getMessage() == '127.0.0.1:1 - "WebSocket /ws?token=***&fps=2" [accepted]'


def test_quiet_connection_lost(caplog):
    """对端已断开时关连接的 ConnectionResetError 不记 ERROR（不出现在 GUI「动态」）；别的异常照常记。"""
    import asyncio

    from e7helper.api.app import quiet_connection_lost

    msg = "Exception in callback _ProactorBasePipeTransport._call_connection_lost()"
    loop = asyncio.new_event_loop()
    try:
        loop.set_exception_handler(quiet_connection_lost)
        with caplog.at_level("DEBUG", logger="asyncio"):
            loop.call_exception_handler({"message": msg, "exception": ConnectionResetError(10054, "reset")})
            loop.call_exception_handler({"message": msg, "exception": ConnectionAbortedError(10053, "aborted")})
            assert not [r for r in caplog.records if r.levelname == "ERROR"]
            loop.call_exception_handler({"message": msg, "exception": ValueError("别的错")})
            loop.call_exception_handler({"message": "Exception in callback other()",
                                         "exception": ConnectionResetError(10054, "reset")})
    finally:
        loop.close()
    errors = [r for r in caplog.records if r.levelname == "ERROR" and r.name == "asyncio"]
    assert len(errors) == 2


def test_server_uses_selector_loop_and_graceful_timeout(engine):
    """`e7helper serve` 用 Selector 事件循环（Windows 的 Proactor 在客户端断开太快时会关掉监听 socket、
    关服务时卡在 wait_closed，B12 反馈 7），关服务最多等 GRACEFUL_SHUTDOWN 秒。"""
    import asyncio

    from e7helper.cli import GRACEFUL_SHUTDOWN, server_config

    cfg = server_config(create_app(engine, token=TOKEN))
    assert cfg.get_loop_factory() is asyncio.SelectorEventLoop
    assert cfg.timeout_graceful_shutdown == GRACEFUL_SHUTDOWN and 0 < GRACEFUL_SHUTDOWN <= 8  # GUI 退出 8 秒后强杀
    assert cfg.ws == "websockets-sansio" and cfg.lifespan == "on"


def test_lifespan_installs_loop_exception_handler(engine):
    import asyncio

    from e7helper.api.app import quiet_connection_lost

    async def handler():
        return asyncio.get_running_loop().get_exception_handler()

    with _client(engine) as c:
        assert c.portal.call(handler) is quiet_connection_lost


def test_host_name_parsing():
    assert host_name("127.0.0.1:47800") == "127.0.0.1"
    assert host_name("[::1]:47800") == "::1"
    assert host_name("LocalHost") == "localhost"
    assert host_name("::1") == "::1"


def test_ws_requires_token(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(_ws_url(token="bad")) as ws:
        ws.receive_json()
    no_header = {"Authorization": ""}
    with (pytest.raises(WebSocketDisconnect),
          client.websocket_connect(_ws_url("/ws/frames", token=None), headers=no_header) as ws):
        ws.receive_bytes()
    with client.websocket_connect(_ws_url(token=None)) as ws:  # 也接受 Authorization 头
        assert ws.receive_json()["type"] == "hello"


# ---------------------------------------------------------------- 设备


def test_device_connect_screenshot_scene(client, engine):
    d = client.get("/api/device").json()
    assert d["connected"] and d["resolution"] == [1600, 900]

    r = client.get("/api/device/screenshot")
    assert r.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape == (900, 1600, 3)
    r = client.get("/api/device/screenshot?format=jpeg&scale=0.5")
    assert r.headers["content-type"] == "image/jpeg"
    assert cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR).shape == (450, 800, 3)

    s = client.get("/api/scene").json()
    assert s["scene"] == "lobby" and s["popup"] is None and s["clear"]
    assert engine.sims[0].taps == []  # 只读

    assert client.post("/api/device/disconnect").json()["connected"] is False
    assert client.get("/api/scene").status_code == 503
    assert client.post("/api/device/connect", json={}).json()["connected"] is True
    assert len(engine.sims) == 2


def test_device_lost_reports_503(client, engine):
    def broken():
        raise OSError("IPC 断开")

    engine.sims[0].screenshot = broken
    r = client.get("/api/device/screenshot")
    assert r.status_code == 503 and r.json()["error"]["code"] == "device_error"
    assert client.get("/api/scene").status_code == 503


def test_device_connect_failure(tmp_path, detector):
    engine = make_engine(tmp_path, detector, fail_connect=True)
    with _client(engine, autoconnect=False) as c:
        r = c.post("/api/device/connect")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "no_device" and "MuMu 没开" in r.json()["error"]["message"]
        assert c.get("/api/device").json() == {"connected": False, "error": "MuMu 没开", "index": None}
        assert c.post("/api/tasks", json={"module": "quick"}).status_code == 503


def test_disconnect_refused_while_task_running(client):
    assert client.post("/api/tasks", json={"module": "slow"}).status_code == 202
    r = client.post("/api/device/disconnect")
    assert r.status_code == 409 and r.json()["error"]["code"] == "busy"
    client.post("/api/tasks/stop")


# ---------------------------------------------------------------- 模块


def test_modules_and_config(client, engine):
    mods = {m["id"]: m for m in client.get("/api/modules").json()}
    assert set(mods) == set(FAKE_MODULES)
    assert mods["quick"]["kind"] == "task" and mods["quick"]["has_routes"] and mods["quick"]["supports_next_due"]
    assert mods["slow"]["supports_next_due"] is False and mods["echo"]["kind"] == "assistant"

    m = client.get("/api/modules/slow").json()
    assert m["config_schema"]["properties"]["seconds"]["default"] == 30.0
    assert m["config"] == {"seconds": 30.0}
    assert client.get("/api/modules/nope").status_code == 404

    r = client.put("/api/modules/slow/config", json={"seconds": -1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_config"
    assert r.json()["error"]["detail"][0]["loc"] == ["seconds"]
    assert client.put("/api/modules/slow/config", json={"seconds": 2}).json() == {"seconds": 2.0}
    assert client.get("/api/modules/slow/config").json() == {"seconds": 2.0}
    assert json.loads(engine.config_path("slow").read_text(encoding="utf-8")) == {"seconds": 2.0}


def test_stats_and_timers(client):
    from e7helper.core.paths import module_data_dir

    d = module_data_dir("quick")
    (d / "stats.json").write_text(json.dumps({"runs": 3}), encoding="utf-8")
    (d / "history.jsonl").write_text("\n".join(json.dumps({"n": i}) for i in range(5)) + "\n", encoding="utf-8")
    s = client.get("/api/modules/quick/stats?limit=2").json()
    assert s == {"module": "quick", "stats": {"runs": 3}, "history": [{"n": 3}, {"n": 4}]}
    assert client.get("/api/modules/slow/stats").json() == {"module": "slow", "stats": None, "history": []}
    assert client.get("/api/modules/quick/timers").json() == [
        {"key": "next", "label": "下次", "at": None, "note": "测试"}]
    assert client.get("/api/modules/slow/timers").json() == []


def test_module_routes_mounted_with_auth(client):
    assert client.get("/api/modules/quick/ping").json() == {"module": "quick", "pong": True}
    assert client.get("/api/modules/quick/ping", headers={"Authorization": ""}).status_code == 401


def test_module_routes_cannot_shadow_core(tmp_path, detector):
    class Bad(TaskModule):
        id = "bad"
        name = "坏路由"

        def run(self):
            pass

        @classmethod
        def routes(cls):
            r = APIRouter()
            r.get("/config")(lambda: {})
            return r

    engine = make_engine(tmp_path, detector, modules={"bad": Bad})
    with pytest.raises(ModuleRegistryError):
        create_app(engine, token=TOKEN)
    engine.close()


def test_real_modules_daily_routes(tmp_path, detector):
    engine = make_engine(tmp_path, detector, modules=discover())
    with _client(engine, autoconnect=False) as c:
        led = c.get("/api/modules/daily/ledger").json()
        assert set(led) == {"day", "done", "week", "week_done", "forest_next", "forest_due"}
        assert led["forest_due"] is True
        keys = [t["key"] for t in c.get("/api/modules/daily/timers").json()]
        assert keys == ["reset", "weekly", "forest", "covenant"]
        mods = {m["id"]: m for m in c.get("/api/modules").json()}
        assert mods["daily"]["supports_next_due"] and not mods["repeat_battle"]["supports_next_due"]
        # 真实模块的默认配置都是 dry-run
        for mid in ("daily", "repeat_battle", "secret_shop"):
            assert c.get(f"/api/modules/{mid}/config").json()["dry_run"] is True


# ---------------------------------------------------------------- 任务


def test_task_lifecycle(client, engine):
    r = client.post("/api/tasks", json={"module": "slow", "config": {"seconds": 30}})
    assert r.status_code == 202
    task = r.json()
    assert task["module"] == "slow" and task["status"] == "running" and task["source"] == "api"

    r = client.post("/api/tasks", json={"module": "quick"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "busy"
    cur = client.get("/api/tasks/current").json()
    assert cur["id"] == task["id"] and cur["elapsed"] >= 0

    assert client.post("/api/tasks/stop").json() == {"stopped": True}
    rec = engine.wait_task(5)
    assert rec["status"] == "stopped"
    assert client.get("/api/tasks/current").json() is None
    assert client.post("/api/tasks/stop").json() == {"stopped": False}

    hist = client.get("/api/tasks/history").json()
    assert hist[0]["id"] == task["id"] and hist[0]["status"] == "stopped" and hist[0]["duration"] > 0
    lines = engine.tasks_file.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["id"] == task["id"]


def test_task_uses_saved_config_and_records_failure(client, engine):
    client.put("/api/modules/quick/config", json={"fail": True})
    task = client.post("/api/tasks", json={"module": "quick"}).json()
    assert task["config"] == {"fail": True, "dry_run": True}
    rec = engine.wait_task(5)
    assert rec["status"] == "failed" and "故意失败" in rec["error"]
    assert client.get("/api/tasks/history?module=quick").json()[0]["status"] == "failed"
    assert client.get("/api/tasks/history?module=slow").json() == []


def test_task_errors(client):
    assert client.post("/api/tasks", json={"module": "nope"}).status_code == 404
    r = client.post("/api/tasks", json={"module": "echo"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_task"
    r = client.post("/api/tasks", json={"module": "slow", "config": {"seconds": "abc"}})
    assert r.status_code == 422
    assert client.post("/api/tasks", json={"module": "slow", "timeout": -1}).status_code == 422


def test_task_timeout(client, engine):
    client.post("/api/tasks", json={"module": "slow", "timeout": 0.3})
    assert engine.wait_task(5)["status"] == "timeout"


def test_history_survives_restart(tmp_path, detector):
    e1 = make_engine(tmp_path, detector)
    with _client(e1) as c:
        wait_for(lambda: e1.runtime is not None)
        c.post("/api/tasks", json={"module": "quick"})
        e1.wait_task(5)
    e2 = make_engine(tmp_path, detector)
    assert e2.task_history()[0]["module"] == "quick"
    e2.close()


def test_assistant_attach_detach(client, engine):
    assert client.post("/api/assistants/echo").json() == {"id": "echo", "name": "回声助手"}
    assert client.get("/api/assistants").json() == [{"id": "echo", "name": "回声助手"}]
    assert client.post("/api/assistants/echo").status_code == 409
    module = engine.runtime.assistants["echo"].module
    assert module.got.wait(3)  # 帧泵给助手发帧
    assert client.delete("/api/assistants/echo").json() == {"detached": True}
    assert client.get("/api/assistants").json() == []
    assert client.post("/api/assistants/slow").status_code == 400


def test_logs_endpoint(client, engine, caplog):
    caplog.set_level("INFO")
    client.post("/api/tasks", json={"module": "quick", "config": {"dry_run": False}})
    engine.wait_task(5)
    msgs = [r["message"] for r in client.get("/api/logs?limit=50").json()]
    assert "快任务：fail=False dry_run=False" in msgs
    assert all(r["level"] != "DEBUG" for r in client.get("/api/logs").json())


def test_status(client):
    s = client.get("/api/status").json()
    assert s["device"]["connected"] and s["task"] is None
    assert s["scheduler"] == {"paused": False, "schedules": 0, "next": None}


# ---------------------------------------------------------------- WebSocket


def test_ws_control_start_stop(client, engine):
    with client.websocket_connect(_ws_url()) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["data"]["device"]["connected"]

        ws.send_json({"id": 1, "op": "subscribe", "topics": ["task", "log", "stats"], "log_level": "info"})
        r = _recv_until(ws, lambda m: m["type"] == "reply")
        assert r == {"type": "reply", "id": 1, "ok": True,
                     "data": {"topics": ["log", "stats", "task"], "log_level": "INFO"}}

        ws.send_json({"id": 2, "op": "start_task", "module": "slow", "config": {"seconds": 30}})
        r = _recv_until(ws, lambda m: m["type"] == "reply" and m["id"] == 2)
        assert r["ok"] and r["data"]["source"] == "ws"
        ev = _recv_until(ws, lambda m: m["type"] == "event" and m["topic"] == "task")
        assert ev["data"] == {"module": "slow", "status": "running"}

        ws.send_json({"id": 3, "op": "start_task", "module": "quick"})
        r = _recv_until(ws, lambda m: m["type"] == "reply" and m["id"] == 3)
        assert r["ok"] is False and r["error"]["code"] == "busy"

        ws.send_json({"id": 4, "op": "stop_task"})
        r = _recv_until(ws, lambda m: m["type"] == "reply" and m["id"] == 4)
        assert r["data"] == {"stopped": True}
        ev = _recv_until(ws, lambda m: m["type"] == "event" and m["topic"] == "task"
                         and m["data"]["status"] != "running")
        assert ev["data"]["status"] == "stopped" and ev["data"]["module"] == "slow"
        ev = _recv_until(ws, lambda m: m["type"] == "event" and m["topic"] == "stats")
        assert ev["data"]["module"] == "slow"


def test_ws_log_filter_and_errors(client):
    with client.websocket_connect(_ws_url()) as ws:
        ws.receive_json()
        ws.send_text("not json")
        assert ws.receive_json()["error"]["code"] == "bad_json"
        ws.send_json({"id": 1, "op": "fly"})
        assert ws.receive_json()["error"]["code"] == "unknown_op"
        ws.send_json({"id": 2, "op": "start_task"})
        assert ws.receive_json()["error"]["code"] == "bad_request"
        ws.send_json({"id": 3, "op": "subscribe", "topics": ["log"], "log_level": "loud"})
        assert ws.receive_json()["error"]["code"] == "bad_request"
        ws.send_json({"id": 4, "op": "subscribe", "topics": ["log"], "log_level": "WARNING"})
        assert ws.receive_json()["ok"]
        ws.send_json({"id": 5, "op": "start_task", "module": "quick", "config": {"fail": True}})
        _recv_until(ws, lambda m: m.get("id") == 5)
        # INFO 级的「任务开始」被过滤，ERROR 级的「任务结束：failed」推过来
        ev = _recv_until(ws, lambda m: m["type"] == "event")
        assert ev["topic"] == "log" and ev["data"]["level"] in ("WARNING", "ERROR")
        ws.send_json({"id": 6, "op": "ping"})
        assert _recv_until(ws, lambda m: m.get("id") == 6)["ok"]


def test_ws_wildcard_gets_device_and_schedule_events(client, engine):
    with client.websocket_connect(_ws_url()) as ws:
        ws.receive_json()
        ws.send_json({"id": 1, "op": "subscribe", "topics": ["*"], "log_level": "ERROR"})
        ws.receive_json()
        client.post("/api/device/disconnect")
        ev = _recv_until(ws, lambda m: m.get("topic") == "device")
        assert ev["data"]["connected"] is False
        ws.send_json({"id": 2, "op": "pause_scheduler"})
        ev = _recv_until(ws, lambda m: m.get("topic") == "schedule")
        assert ev["data"] == {"action": "paused"}
        assert _recv_until(ws, lambda m: m.get("id") == 2)["data"]["paused"] is True


def test_ws_frames_idle_and_task(client, engine):
    with client.websocket_connect(_ws_url("/ws/frames", fps=10, scale=0.25)) as ws:
        data = ws.receive_bytes()  # 空闲：自己截图
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        assert img.shape == (225, 400, 3)
        client.post("/api/tasks", json={"module": "slow", "config": {"seconds": 30}})
        for _ in range(3):  # 任务中：转发任务的截图
            assert ws.receive_bytes()[:2] == b"\xff\xd8"
        client.post("/api/tasks/stop")
    assert engine.sims[0].taps == []


def test_ws_frames_without_device(tmp_path, detector):
    engine = make_engine(tmp_path, detector, fail_connect=True)
    with _client(engine, autoconnect=False) as c, c.websocket_connect(_ws_url("/ws/frames")) as ws:
        assert json.loads(ws.receive_text()) == {"type": "status", "connected": False}


def test_assistant_module_is_listed_as_not_task():
    assert not issubclass(EchoAssistant, TaskModule)
