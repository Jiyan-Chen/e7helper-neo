"""B14c：RTA 选秀推荐接口（/api/rta/*）。推荐器换成假模型（rta_fakes.FakeModel），不读随包模型。
B14d1：英雄池、先动概率（速度表换成合成的，英雄池存在临时目录）。"""

import pytest
from api_fakes import make_engine
from fastapi.testclient import TestClient

from e7helper.api import create_app
from e7helper.core.rta import pool as rpool
from e7helper.core.rta import search, speed
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
    monkeypatch.setattr(rpool, "default_path", lambda: tmp_path / "pool.json")
    monkeypatch.setattr(speed, "load", lambda path=None: None)  # 默认没有速度表，用到的测试自己换
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
    rules = d["options"]["rules"]  # B14e1：准备这一步的开战规则按钮
    assert {r["label"] for r in rules} == {"攻击", "防御", "抵抗", "特殊"} and all(r["tid"] and r["desc"] for r in rules)


def test_priors(client, monkeypatch):
    adv = search.Advisor(FakeModel({c: 1.0 for c in CODES}, {c: 0.0 for c in CODES}),
                         fake_priors({"c00": 5000, "c01": 300}, preban=PRE, postban={"c00": [50, 200], "c01": [1, 10]}))
    monkeypatch.setattr(search, "load", lambda: adv)
    d = client.get("/api/rta/priors").json()
    assert d["rare_picks"] == 1000 and set(d["heroes"]) == {"c00", "c01"}
    c00, c01 = d["heroes"]["c00"], d["heroes"]["c01"]
    assert c00["picks"] == 5000 and not c00["rare"] and c00["ban_rate"] == 0.25
    assert c01["rare"] and c01["ban_rate"] is None  # 可被禁不到 100 次
    # c00 在先手方 50 / 80、后手方 60 / 100 的预禁组合里 → 平均 (0.625 + 0.6) / 2
    assert c00["preban"] == pytest.approx(0.6125) and c01["preban"] == pytest.approx(0.6125)
    assert "c04" not in d["heroes"]  # 没出现过的不列


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


# —— 英雄池、先动概率（B14d1） ——

def _table():
    """c00 最快（290 以上），c01 250–270，其余 190–210。"""
    def one(k):
        h = [0] * 10
        h[k] = 100
        return h
    return speed.SpeedTable.from_hists({c: {"legend": one(9 if c == "c00" else 7 if c == "c01" else 4)} for c in CODES},
                                       season="pvp_rta_ss21")


def test_pool_roundtrip_and_validation(client):
    assert client.get("/api/rta/pool").json()["heroes"] == []
    d = client.put("/api/rta/pool", json={"heroes": [{"code": "c05", "speed": 280}, {"code": "c06"},
                                                     {"code": "c05", "speed": 300}]}).json()
    assert d["heroes"] == [{"code": "c06", "speed": None}, {"code": "c05", "speed": 300}] and d["updated"]
    assert client.get("/api/rta/pool").json()["heroes"][1] == {"code": "c05", "speed": 300}
    assert client.put("/api/rta/pool", json={"heroes": [{"code": "c05", "speed": 999}]}).status_code == 422


def test_advise_uses_saved_pool(client):
    client.put("/api/rta/pool", json={"heroes": [{"code": c} for c in ("c05", "c06", "c07")]})
    d = client.post("/api/rta/advise", json={"side": "F", "state": _state(), "top": 2}).json()
    assert [r["heroes"][0] for r in d["recommend"]] == ["c05", "c06"] and d["pool"] == ["c05", "c06", "c07"]
    d = client.post("/api/rta/advise", json={"side": "F", "state": _state(), "top": 2, "use_saved_pool": False}).json()
    assert [r["heroes"][0] for r in d["recommend"]] == ["c00", "c01"] and d["pool"] is None
    assert d["first"] is None  # 没有速度表


def test_advise_first_mover(client, monkeypatch):
    table = _table()
    monkeypatch.setattr(speed, "load", lambda path=None: table)
    # 轮到后手方（我方）选两名：先手方已选 c00（最快）
    d = client.post("/api/rta/advise", json={"side": "S", "state": _state(["c00"])}).json()
    assert d["first"] is None  # 我方还没有英雄
    assert all(r["first"] == 0.0 for r in d["recommend"])
    # 英雄池里给我方的 c02 填了 400 速
    client.put("/api/rta/pool", json={"heroes": [{"code": "c02", "speed": 400}]})
    d = client.post("/api/rta/advise", json={"side": "S", "state": _state(["c00"]), "use_saved_pool": False}).json()
    with_c02 = [r for r in d["recommend"] if "c02" in r["heroes"]]
    assert with_c02 and all(r["first"] == 1.0 for r in with_c02)
    # 后禁矩阵：每格 4 打 4
    picks = {"F": ["c00", "c03", "c04", "c07", "c08"], "S": ["c01", "c02", "c05", "c06", "c09"]}
    d = client.post("/api/rta/advise", json={"side": "F", "state": _state(picks["F"], picks["S"])}).json()
    b = d["ban"]
    assert d["first"]["partial"] and d["first"]["mine"] == 1.0
    # 行 = 我方禁对方哪名，列 = 对方禁我方哪名。c02 是对方的，用不到英雄池里的速度
    for i, row in enumerate(b["rows"]):
        for j, col in enumerate(b["cols"]):
            if col != "c00":
                assert b["first"][i][j] == 1.0  # 我方 c00 在场就先动
            elif row != "c01":
                assert b["first"][i][j] == 0.0  # c00 被禁、对方 c01 在场
            else:
                assert 0.3 < b["first"][i][j] < 0.7  # 双方最快的都被禁了，剩下的一样快


def test_first_endpoint(client, monkeypatch):
    r = client.post("/api/rta/first", json={"mine": ["c01"], "theirs": ["c02"]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_speed_data"
    table = _table()
    monkeypatch.setattr(speed, "load", lambda path=None: table)
    d = client.post("/api/rta/first", json={"mine": ["c01", "c03"], "theirs": ["c00"], "grades": ["legend", "legend"]}).json()
    assert d["mine"] == 0.0 and d["theirs"] == 1.0 and d["season"] == "pvp_rta_ss21" and len(d["heroes"]) == 3
    d = client.post("/api/rta/first", json={"mine": ["c03"], "theirs": ["c00"], "speeds": {"c03": 400}}).json()
    assert d["mine"] == 1.0
    assert client.post("/api/rta/first", json={"mine": [], "theirs": ["c00"]}).status_code == 422
    assert client.get("/api/rta/model").json()["speed"]["heroes"] == 30
