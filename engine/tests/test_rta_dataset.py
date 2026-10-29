"""B14b：训练数据快照（采集库 → 解析、过滤、编码 → npz → 切分）。"""

import json

import numpy as np
import pytest

from e7helper.core.rta import dataset as rds
from e7helper.core.rta import encode
from e7helper.core.rta.battle import strip
from e7helper.core.rta.crawl import connect
from rta_fakes import ENEMY, MY, battle

RULE = "rta_cs_dodge_down_desc"


def _insert(conn, server, raw):
    conn.execute("INSERT INTO battles (key, server, season, day, raw, added) VALUES (?, ?, ?, ?, ?, 0)",
                 (f"{server}:{raw['battle_seq']}", server, raw["season_code"], raw["battle_day"][:19],
                  json.dumps(strip(raw), ensure_ascii=False)))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    db = tmp_path_factory.mktemp("rta") / "crawl.sqlite"
    conn = connect(db)
    days = ["2026-10-01", "2026-10-05", "2026-10-10", "2026-10-15", "2026-10-17", "2026-10-20", "2026-10-23"]
    for i, d in enumerate(days):
        _insert(conn, "global", battle(f"g{i}", fmt="global", rule=RULE if i % 2 else None, day=f"{d} 12:00:00.0",
                                       iswin=1 + i % 2, grades=("champion", "legend") if i else ("gold", "legend")))
        _insert(conn, "cn", battle(f"c{i}", me_first=bool(i % 2), day=f"{d} 08:00:00.0"))
    _insert(conn, "cn", battle("bad", my_deck={"hero_list": [], "preban_list": []}, teamBettleInfo='"my_team":[]'))
    _insert(conn, "cn", battle("m", prebans=(("m8041_apr", "c3002"), ("c3001", "c3003"))))
    _insert(conn, "cn", battle("t0", turn=0))
    _insert(conn, "cn", battle("old", season="pvp_rta_ss20"))
    _insert(conn, "global", battle("late", fmt="global", day="2026-10-24 01:00:00.0"))
    conn.commit()
    conn.close()
    return rds.build(db, until="2026-10-23", workers=1)


def test_build_filters_and_sorts(built):
    ds = built
    assert len(ds) == 14 and ds.meta["read"] == 18 and ds.meta["kept"] == 14  # 以前赛季的那场不读
    assert ds.meta["dropped"] == {"解析失败：没有选秀": 1, "含 m 开头英雄": 1, "0 回合": 1, "截止日之后": 1}
    assert ds.meta["per_server"] == {"cn": 7, "global": 7}
    assert ds.meta["first_day"] == "2026-10-01" and ds.meta["last_day"] == "2026-10-23"
    assert (np.diff(ds.day) >= 0).all()
    assert ds.tokens.shape == (14, 17) and ds.tokens.dtype == np.int16
    assert (ds.tokens[:, 0] == -1).all() and (ds.tokens[:, 5:] >= 0).all()
    assert ds.rule_table == [(RULE, "rta_openingrule_category_1")]
    assert set(ds.codes) == set(MY) | set(ENEMY) | {"c3001", "c3002", "c3003"}
    cn = ds.server == 0
    assert (ds.rule[cn] == -2).all()  # 国服：不知道
    assert set(ds.rule[~cn].tolist()) == {-1, 0}  # 海外：没有 / 第 0 条
    # 国服里我方先手的那几场（i 为奇数）我方赢 → 先手赢；我方后手的 → 后手赢
    assert ds.first_wins[cn].tolist() == [0, 1, 0, 1, 0, 1, 0]


def test_save_load_roundtrip(built, tmp_path):
    path = tmp_path / "ds.npz"
    built.save(path)
    ds = rds.Dataset.load(path)
    assert ds.codes == built.codes and ds.rule_table == built.rule_table and ds.meta == built.meta
    for k in ("tokens", "grades", "rule", "server", "day", "first_wins", "turns"):
        assert np.array_equal(getattr(ds, k), getattr(built, k))


def test_split_by_days(built):
    parts = built.split(test_days=7, val_days=7)
    day = lambda rows: sorted({built.day_str(d) for d in built.day[rows]})  # noqa: E731
    assert day(parts["test"]) == ["2026-10-17", "2026-10-20", "2026-10-23"]
    assert day(parts["val"]) == ["2026-10-10", "2026-10-15"]
    assert day(parts["train"]) == ["2026-10-01", "2026-10-05"]
    full = built.split(test_days=0)
    assert len(full["train"]) == 14 and not len(full["test"])


def test_encode(built):
    parts = built.split()
    vocab = built.vocab(parts["train"], min_picks=1)
    assert set(vocab.heroes) == set(MY) | set(ENEMY)  # 预禁的 c300x 没被选过
    x = built.encode(vocab)
    assert x["heroes"].shape == (14, 17) and x["ctx"].shape == (14, 3) and x["y"].dtype == np.float32
    assert (x["heroes"][:, 0] == encode.PAD).all()
    assert (x["heroes"][:, 1] == encode.UNK).all()  # c3001 预禁、不在词表
    cn = built.server == 0
    assert (x["ctx"][cn, 2] == encode.RULE_UNKNOWN).all()
    assert set(x["ctx"][~cn, 2].tolist()) == {encode.RULE_NONE, 2}
    assert x["ctx"][~cn][0, 0] == encode.grade_id("gold")
    # 和直接编码 DraftState 的结果一致
    from e7helper.core.rta.battle import parse_battle
    m = parse_battle(battle("g1", fmt="global", rule=RULE, iswin=2, grades=("champion", "legend")), "global")
    st = encode.encode_states([encode.DraftState.from_match(m)], vocab)
    row = np.flatnonzero((built.server == 1) & (built.day == built.day[built.server == 1][1]))[0]
    assert np.array_equal(st["heroes"][0], x["heroes"][row]) and np.array_equal(st["ctx"][0], x["ctx"][row])


def test_summary(built):
    info = rds.summary(built, min_picks=1)
    assert info["splits"]["test"]["matches"] == 6 and info["splits"]["train"]["matches"] == 4
    assert info["vocab"] == 10 and info["rules"] == [RULE]
    assert info["splits"]["test"]["champion_plus"] == 6  # 国服默认传说 / 王者，海外优胜者 / 传说
    assert info["splits"]["train"]["champion_plus"] == 3  # 海外第一场有一方是金牌


def test_energy_in_snapshot(tmp_path):
    """B14d1：快照带上 10 手各自的开局行动条（按选秀顺序）和谁先动；旧快照读出来是 -1。"""
    from rta_fakes import gauge

    db = tmp_path / "crawl.sqlite"
    conn = connect(db)
    _insert(conn, "cn", battle("e1", energyGauge=gauge()))  # 我方先手，我方第 1 手先动
    _insert(conn, "cn", battle("e2", me_first=False, energyGauge=gauge()))  # 对方先手，我方（后手方）先动
    raw = battle("e3")
    raw.pop("energyGauge")
    _insert(conn, "cn", raw)
    conn.commit()
    conn.close()
    ds = rds.build(db, workers=1)
    rows = {k: i for i, k in enumerate(sorted(["e1", "e2", "e3"]))}  # 同一天，按 key 排
    # 选秀顺序 F S S F F S S F F S；e1 我方是 F
    assert ds.energy[rows["e1"]].tolist() == [100, 90, 75, 80, 70, 65, 0, 60, 0, 55]
    assert ds.first_mover.tolist() == [1, 0, -1] and ds.meta["with_energy"] == 2
    assert ds.energy[rows["e3"]].tolist() == [-1] * 10
    path = tmp_path / "s.npz"
    ds.save(path)
    again = rds.Dataset.load(path)
    assert (again.energy == ds.energy).all() and (again.first_mover == ds.first_mover).all()
    # 旧快照（没有这两项）
    old = rds.Dataset(codes=ds.codes, rule_table=ds.rule_table, tokens=ds.tokens, grades=ds.grades, rule=ds.rule,
                      server=ds.server, day=ds.day, first_wins=ds.first_wins, turns=ds.turns)
    assert (old.first_mover == -1).all() and old.energy.shape == (3, 10)
