"""B09：模板采集接口和 /api/shutdown（离线：GameSim 提供大厅画面，模板写进临时 assets 目录）。"""

import cv2
import numpy as np
import pytest
from api_fakes import make_engine, wait_for
from fastapi.testclient import TestClient

from e7helper.api import create_app
from e7helper.core import paths
from e7helper.core.imageio import read_image
from e7helper.core.scene import default_detector

TOKEN = "test-token"
BASE = "http://127.0.0.1:47800"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SHOP_BOX = [1480, 629, 70, 41]  # 大厅右侧「商店」（同 common/lobby/shop.json）


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))
    assets = tmp_path / "assets"
    assets.mkdir()
    monkeypatch.setattr(paths, "ASSETS_DIR", assets)
    return assets


@pytest.fixture(scope="module")
def detector():
    return default_detector()


@pytest.fixture
def engine(tmp_path, detector):
    return make_engine(tmp_path, detector)


@pytest.fixture
def client(engine):
    app = create_app(engine, token=TOKEN, start_scheduler=False)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        wait_for(lambda: engine.runtime is not None)
        yield c


def _freeze(client) -> str:
    r = client.post("/api/capture/frames")
    assert r.status_code == 200, r.text
    assert (r.json()["width"], r.json()["height"]) == (1600, 900)
    return r.json()["id"]


def test_needs_token(engine):
    app = create_app(engine, token=TOKEN, start_scheduler=False, autoconnect=False)
    with TestClient(app, base_url=BASE) as c:
        assert c.post("/api/capture/frames").status_code == 401
        assert c.get("/api/capture/stores").status_code == 401


def test_freeze_and_get_frame(client):
    fid = _freeze(client)
    r = client.get(f"/api/capture/frames/{fid}")
    assert r.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape == (900, 1600, 3)
    assert client.get("/api/capture/frames/nope").json()["error"]["code"] == "unknown_frame"


def test_upload_frame_resizes_to_base(client):
    small = cv2.resize(read_image("tests/fixtures/lobby.png"), (800, 450))
    ok, buf = cv2.imencode(".png", small)
    r = client.post("/api/capture/frames/upload", content=buf.tobytes(), headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    assert client.post("/api/capture/frames/upload", content=b"not an image",
                       headers={"Content-Type": "application/octet-stream"}).status_code == 422


def test_save_verify_match_delete(client, _dirs):
    fid = _freeze(client)
    body = {"frame": fid, "name": "lobby/shop_test", "box": SHOP_BOX, "max_diff": 30, "note": "测试"}
    r = client.post("/api/capture/templates/mymod", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (_dirs / "mymod" / "cn" / "lobby" / "shop_test.png").is_file()
    assert data["meta"]["box"] == SHOP_BOX
    assert data["meta"]["region"] == [1440, 589, 150, 121]  # 默认外扩 40
    assert data["verify"]["own"]["score"] > 0.99 and data["verify"]["own"]["hit"]

    # 重复保存要勾选覆盖
    assert client.post("/api/capture/templates/mymod", json=body).json()["error"]["code"] == "exists"
    assert client.post("/api/capture/templates/mymod", json={**body, "overwrite": True, "full": True}).json()["meta"]["region"] is None

    listed = client.get("/api/capture/templates", params={"module": "mymod"}).json()
    assert [t["name"] for t in listed] == ["lobby/shop_test"]
    assert any(s["module"] == "mymod" and s["count"] == 1 for s in client.get("/api/capture/stores").json())
    assert client.get("/api/capture/templates/mymod/image/lobby/shop_test").headers["content-type"] == "image/png"

    hits = client.post("/api/capture/match", json={"frame": fid, "module": "mymod"}).json()
    assert hits[0]["name"] == "lobby/shop_test" and hits[0]["hit"] and hits[0]["rect"] == SHOP_BOX

    assert client.delete("/api/capture/templates/mymod/lobby/shop_test").status_code == 204
    assert client.get("/api/capture/templates", params={"module": "mymod"}).json() == []
    assert client.delete("/api/capture/templates/mymod/lobby/shop_test").status_code == 404


def test_save_rejects_bad_input(client):
    fid = _freeze(client)
    bad_name = client.post("/api/capture/templates/mymod", json={"frame": fid, "name": "../x", "box": SHOP_BOX})
    assert bad_name.status_code == 422
    outside = client.post("/api/capture/templates/mymod", json={"frame": fid, "name": "x", "box": [2000, 0, 10, 10]})
    assert outside.json()["error"]["code"] == "bad_rect"
    region = client.post("/api/capture/templates/mymod",
                         json={"frame": fid, "name": "x", "box": SHOP_BOX, "region": [0, 0, 100, 100]})
    assert region.json()["error"]["code"] == "bad_region"
    assert client.get("/api/capture/templates", params={"module": "../etc"}).json()["error"]["code"] == "bad_module"


def test_shutdown(engine):
    app = create_app(engine, token=TOKEN, start_scheduler=False, autoconnect=False)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        assert c.post("/api/shutdown").json()["error"]["code"] == "not_supported"
        called = []
        app.state.request_shutdown = lambda: called.append(True)
        assert c.post("/api/shutdown").status_code == 202
        assert called == [True]
