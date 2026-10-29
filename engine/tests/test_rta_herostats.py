"""B14d1：官方英雄分析快照（假客户端，不联网）和读有开局行动条的对局。"""

import json

from e7helper.core.rta import herostats
from e7helper.core.rta.battle import strip
from e7helper.core.rta.crawl import connect
from e7helper.core.rta.official import OfficialError
from rta_fakes import MY, battle, gauge

SEASON = "pvp_rta_ss21"
SPEED = "0,1,2,3,4,5,6,7,8,9"


class FakeClient:
    server = "cn"

    def __init__(self):
        self.calls = []

    def hero_analysis(self, hero, season, grade):
        self.calls.append((hero, grade))
        if hero == "none":
            raise OfficialError("getHeroAnalysis 返回码 -10002", code=-10002)
        if hero == "broken":
            raise OfficialError("HTTP 500", status=500)
        return {"heroCode": hero, "seasonTierCode": grade, "abillity": {"speed": SPEED, "cri": "1,2"}}


def test_histogram():
    assert herostats.histogram({"abillity": {"speed": SPEED}}) == list(range(10))
    assert herostats.histogram({"abillity": {"speed": "1,2"}}) is None  # 不是 10 档
    assert herostats.histogram({"abillity": {"speed": "a,b"}}) is None
    assert herostats.histogram({}) is None
    assert herostats.SCALES["speed"] == (110, 310)


def test_snapshot_and_read(tmp_path):
    db = tmp_path / "crawl.sqlite"
    clock = [1_000_000.0]
    client = FakeClient()
    counts = herostats.snapshot(client, SEASON, ["c1", "none", "broken"], grades=["legend", "champion"], db_path=db,
                                now=lambda: clock[0])
    assert counts == {"jobs": 6, "skipped": 0, "fetched": 2, "no_data": 2, "errors": 2}
    assert herostats.speed_histograms(SEASON, db_path=db) == {"c1": {"legend": list(range(10)),
                                                                     "champion": list(range(10))}}
    # 72 小时内取过的（含官方没有数据的）跳过，出错的重取
    client = FakeClient()
    clock[0] += 3600
    counts = herostats.snapshot(client, SEASON, ["c1", "none", "broken"], grades=["legend"], db_path=db,
                                now=lambda: clock[0])
    assert client.calls == [("broken", "legend")] and counts["skipped"] == 2
    # 过期了重取
    client = FakeClient()
    clock[0] += 80 * 3600
    herostats.snapshot(client, SEASON, ["c1"], grades=["legend"], db_path=db, now=lambda: clock[0])
    assert client.calls == [("c1", "legend")]


def test_energy_matches(tmp_path):
    db = tmp_path / "crawl.sqlite"
    conn = connect(db)
    rows = [battle(2, energyGauge=gauge(), day="2026-10-20 10:00:00.0"),
            battle(1, energyGauge=gauge(), day="2026-10-19 10:00:00.0"), battle(3)]
    rows[2].pop("energyGauge")
    for raw in rows + [battle(4, energyGauge=gauge(), season="pvp_rta_ss20")]:
        conn.execute("INSERT INTO battles (key, server, season, day, raw, added) VALUES (?, 'cn', ?, ?, ?, 0)",
                     (f"cn:{raw['battle_seq']}", raw["season_code"], raw["battle_day"][:19], json.dumps(strip(raw))))
    conn.commit()
    conn.close()
    ms = herostats.energy_matches(SEASON, db_path=db)
    assert len(ms) == 2 and all(len(u) == 8 for u in ms)  # 没有行动条的、别的赛季的不要
    first = next(u for u in ms[0] if u.energy == 100)
    assert first.code == MY[0] and first.side == "F" and first.grade == "legend"
    assert herostats.energy_matches(SEASON, db_path=db, limit=1) == ms[-1:]
