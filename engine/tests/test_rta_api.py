"""B14c：RTA 选秀推荐接口（/api/rta/*）。推荐器换成假模型（rta_fakes.FakeModel），不读随包模型。"""

import pytest
from api_fakes import make_engine
from fastapi.testclient import TestClient

from e7helper.api import create_app
from e7helper.core.rta import search
from rta_fakes import FakeModel, fake_priors

TOKEN = "test-token"
BASE = "http://127.0.0.1:47800"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CODES = [f"c{i:02d}" for i in range(30)]
PRE = {"F": [["c00", "c01", 50], ["c02", "c03", 30]], "S": [["c00", "c01", 60], ["c04", "c05", 40]]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    model = FakeModel({c: 1.0 - 0.03 * i for i, c in enumerate(CODES)}, {c: 0.0 for c in CODES}, preban=0.5)
    adv = search.Advisor(model, fake_priors({c: 5000 for c in CODES}, preban=PRE))
    monkeypatch.setattr(search, "available", lambda: True)
    monkeypatch.setattr(search, "load", lambda: adv)
    engine = make_engine(tmp_path, detector=None)
    app = create_app(engine, token=TOKEN, start_scheduler=False, autoconnect=False)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        yield c


def _state(f=(), s=()):
    return {"prebans": {"F": ["c25", "c26"], "S": ["c27", "c28"]}, "picks": {"F": list(f), "S": list(s)},
            "grades": ["emperor", "legend"], "rule": "unknown"}


def test_needs_token(client):
    assert client.post("/api/rta/advise", json={"side": "F"}, headers={"Authorization": ""}).status_code == 401


def test_model_info(client):
    d = client.get("/api/rta/model").json()
    assert d["model"]["kind"] == "fake" and d["second"] is None and d["rare_picks"] == 1000


def test_advise_my_turn(client):
    d = client.post("/api/rta/advise", json={"side": "S", "state": _state(["c00"])}).json()
    assert d["phase"] == "pick" and d["turn"] == "mine" and d["slots"] == 2
    assert len(d["recommend"]) == 8 and set(d["recommend"][0]["heroes"]) == {"c01", "c02"}
    assert d["heroes"] and d["stats"]["depth"] >= 2


def test_advise_their_turn_and_ban(client):
    d = client.post("/api/rta/advise", json={"side": "F", "state": _state(["c00"])}).json()
    assert d["turn"] == "theirs" and d["opponent"]["likely"]
    picks = {"F": ["c00", "c03", "c04", "c07", "c08"], "S": ["c01", "c02", "c05", "c06", "c09"]}
    d = client.post("/api/rta/advise", json={"side": "F", "state": _state(picks["F"], picks["S"])}).json()
    assert d["phase"] == "ban" and len(d["ban"]["matrix"]) == 4 and d["ban"]["recommend"] in picks["S"]


def test_advise_with_pool_and_top(client):
    d = client.post("/api/rta/advise", json={"side": "F", "state": _state(), "pool": ["c05", "c06", "c07"], "top": 2}).json()
    assert [r["heroes"][0] for r in d["recommend"]] == ["c05", "c06"]


def test_advise_invalid_state(client):
    r = client.post("/api/rta/advise", json={"side": "S", "state": _state(["c25"])})  # 选了被预禁的
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_state" and any("预禁" in p for p in err["detail"])
    assert client.post("/api/rta/advise", json={"side": "X"}).status_code == 422  # 请求体校验


def test_preban(client):
    d = client.post("/api/rta/preban", json={"side": "F", "grades": ["emperor", "legend"]}).json()
    assert d["phase"] == "preban" and d["recommend"][0]["heroes"] == ["c00", "c01"]
    d = client.post("/api/rta/preban", json={"fixed": "c02"}).json()
    assert d["side"] is None and all("c02" in r["heroes"] for r in d["recommend"])


def test_no_model(client, monkeypatch):
    monkeypatch.setattr(search, "available", lambda: False)
    r = client.get("/api/rta/model")
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_model"
