"""B11：流程和玩家模板接口（离线：GameSim 提供画面，数据目录用临时目录）。"""

import game_sim
import pytest
from api_fakes import FAKE_MODULES, make_engine, wait_for
from fastapi.testclient import TestClient

from e7helper.api import create_app
from e7helper.core import paths
from e7helper.core.geometry import Rect
from e7helper.core.scene import default_detector
from e7helper.modules.custom_flow import CustomFlow

TOKEN = "test-token"
BASE = "http://127.0.0.1:47800"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SANCTUARY_BOX = [44, 241, 53, 34]  # 大厅「圣域」文字（同 common/lobby/sanctuary.json）
SANCTUARY_TAP = [40, 195, 62, 82]


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))
    t = dict(game_sim.TRANSITIONS)
    t["lobby"] = [(Rect(*SANCTUARY_TAP), "sanctuary"), *t["lobby"]]
    monkeypatch.setattr(game_sim, "TRANSITIONS", t)


@pytest.fixture(scope="module")
def detector():
    return default_detector()


@pytest.fixture
def engine(tmp_path, detector):
    return make_engine(tmp_path, detector, modules={**FAKE_MODULES, CustomFlow.id: CustomFlow})


@pytest.fixture
def client(engine):
    app = create_app(engine, token=TOKEN, start_scheduler=False)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        wait_for(lambda: engine.runtime is not None)
        yield c


def _freeze(client) -> str:
    r = client.post("/api/capture/frames")
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _save_tpl(client, name="圣域入口", **kw):
    body = {"frame": _freeze(client), "name": name, "box": SANCTUARY_BOX, "tap": SANCTUARY_TAP, **kw}
    return client.post("/api/user-templates", json=body)


FLOW = {
    "name": "圣域往返",
    "description": "大厅 → 圣域 → 返回",
    "steps": [
        {"type": "tap_template", "template": "圣域入口"},
        {"type": "wait_scene", "scene": "sanctuary"},
        {"type": "back"},
        {"type": "wait_scene", "scene": "lobby"},
    ],
}


def test_needs_token(engine):
    app = create_app(engine, token=TOKEN, start_scheduler=False, autoconnect=False)
    with TestClient(app, base_url=BASE) as c:
        assert c.get("/api/flows").status_code == 401
        assert c.get("/api/user-templates").status_code == 401


def test_flow_crud(client):
    assert client.get("/api/flows").json() == []
    r = client.post("/api/flows", json=FLOW)
    assert r.status_code == 201, r.text
    flow = r.json()
    fid = flow["id"]
    assert flow["missing"] == ["圣域入口"] and flow["steps"][0]["id"]
    (summary,) = client.get("/api/flows").json()
    assert summary["id"] == fid and summary["steps"] == 4 and summary["missing"] == ["圣域入口"]
    assert summary["last_run"] is None

    changed = {**flow, "name": "改名了", "id": "别的", "limits": {"max_minutes": 3, "max_taps": 20}}
    r = client.put(f"/api/flows/{fid}", json=changed)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == fid and r.json()["name"] == "改名了" and r.json()["created"] == flow["created"]
    assert client.get(f"/api/flows/{fid}").json()["limits"]["max_taps"] == 20

    r = client.post(f"/api/flows/{fid}/copy")
    assert r.status_code == 201 and r.json()["name"] == "改名了 副本" and r.json()["id"] != fid
    assert len(client.get("/api/flows").json()) == 2

    assert client.delete(f"/api/flows/{fid}").status_code == 204
    assert client.get(f"/api/flows/{fid}").status_code == 404
    assert client.get("/api/flows/..%2Fx").status_code == 404


def test_invalid_flow(client):
    r = client.post("/api/flows", json={"name": "x", "steps": [{"type": "break"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_flow"
    r = client.post("/api/flows", json={"name": "x", "steps": [{"type": "tap_template", "template": "common:dialog/confirm"}]})
    assert r.status_code == 422
    assert any("确认" in d["msg"] for d in r.json()["error"]["detail"])


def test_template_save_list_test_delete(client):
    r = _save_tpl(client, dim_check=True)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["ref"] == "圣域入口" and saved["quality"] == "good" and saved["dim_check"] and saved["has_tap"]
    assert (paths.data_dir() / "flows" / "templates" / "圣域入口.png").is_file()
    assert _save_tpl(client).status_code == 409
    assert _save_tpl(client, overwrite=True, moving=True).json()["moving"] is True
    assert _save_tpl(client, name="a/b").status_code == 422

    lst = client.get("/api/user-templates").json()
    assert [t["ref"] for t in lst["mine"]] == ["圣域入口"]
    common = {t["ref"] for t in lst["common"]}
    assert "common:back" in common and "common:lobby/sanctuary" in common
    assert not any(ref.startswith("common:popup/") for ref in common)

    img = client.get("/api/user-templates/image", params={"ref": "圣域入口"})
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert client.get("/api/user-templates/image", params={"ref": "common:back"}).status_code == 200
    assert client.get("/api/user-templates/image", params={"ref": "没有"}).status_code == 404

    res = client.post("/api/user-templates/test", json={"templates": ["圣域入口", "common:title/sanctuary", "没有"]})
    assert res.status_code == 200, res.text
    by = {x["ref"]: x for x in res.json()["results"]}
    assert by["圣域入口"]["hit"] is True and by["common:title/sanctuary"]["hit"] is False
    assert by["没有"]["error"]

    fid = client.post("/api/flows", json=FLOW).json()["id"]
    r = client.delete("/api/user-templates/圣域入口")
    assert r.status_code == 409 and r.json()["error"]["detail"] == [{"id": fid, "name": "圣域往返"}]
    assert client.get("/api/user-templates").json()["mine"][0]["used_by"] == [{"id": fid, "name": "圣域往返"}]
    assert client.delete("/api/user-templates/圣域入口", params={"force": True}).status_code == 204
    assert client.get(f"/api/flows/{fid}").json()["missing"] == ["圣域入口"]
    assert client.delete("/api/user-templates/圣域入口").status_code == 404


def test_template_too_small_or_flat(client):
    r = client.post("/api/user-templates", json={"frame": _freeze(client), "name": "小", "box": [10, 10, 4, 4]})
    assert r.status_code == 422


def test_builtin_templates_are_read_only(client):
    """玩家接口只写数据目录；内置模板没有修改 / 删除的路由。"""
    assert client.delete("/api/user-templates/common:back").status_code == 404
    assert (paths.ASSETS_DIR / "common" / "cn" / "back.png").is_file()


def test_run_flow_via_tasks(client, engine):
    assert _save_tpl(client).status_code == 200
    fid = client.post("/api/flows", json=FLOW).json()["id"]
    schema = client.get("/api/modules/custom_flow").json()["config_schema"]
    assert schema["properties"]["flow"]["x-enum-labels"] == {fid: "圣域往返"}

    r = client.post("/api/tasks", json={"module": "custom_flow", "config": {"flow": fid}})
    assert r.status_code == 202, r.text
    rec = wait_for(lambda: (t := client.get("/api/tasks/history").json()) and t[0], timeout=30)
    assert rec["status"] == "succeeded", rec
    assert engine.sims[0].history == ["lobby", "sanctuary", "lobby"]
    (summary,) = client.get("/api/flows").json()
    assert summary["last_run"]["status"] == "succeeded" and summary["last_run"]["taps"] == 1
    stats = client.get("/api/modules/custom_flow/stats").json()
    assert stats["stats"]["flows"][fid]["runs"] == 1


def test_run_missing_template_fails_fast(client):
    fid = client.post("/api/flows", json=FLOW).json()["id"]
    r = client.post("/api/tasks", json={"module": "custom_flow", "config": {"flow": fid}})
    assert r.status_code == 500 and "圣域入口" in r.json()["error"]["message"]


def test_delete_flow_used_by_schedule(client):
    fid = client.post("/api/flows", json=FLOW).json()["id"]
    r = client.post("/api/schedules", json={"module": "custom_flow", "name": "每小时圣域",
                                            "trigger": {"type": "interval", "minutes": 60},
                                            "config": {"flow": fid}, "enabled": False})
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]
    r = client.delete(f"/api/flows/{fid}")
    assert r.status_code == 409 and r.json()["error"]["detail"] == [{"id": sid, "name": "每小时圣域"}]
    assert client.delete(f"/api/flows/{fid}", params={"force": True}).status_code == 204
    assert client.get(f"/api/schedules/{sid}").status_code == 404
