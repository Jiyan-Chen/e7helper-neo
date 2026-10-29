"""B14a：官方战绩站的对局 → Match（国服 / 海外两种格式）。"""

import json

import pytest

from e7helper.core.rta.battle import STORE_KEYS, BadBattle, parse_battle, strip
from rta_fakes import ENEMY, MY, battle


@pytest.mark.parametrize("fmt,server", [("cn", "cn"), ("global", "global")])
def test_parse_me_first(fmt, server):
    m = parse_battle(battle(42, fmt=fmt), server)
    assert m.key == f"{server}:42"
    assert m.first.codes == list(MY) and m.second.codes == list(ENEMY)
    assert m.winner == "F"  # 我方先手、我方赢
    assert m.first.banned == MY[4] and m.second.banned == ENEMY[3]
    assert m.first.prebans == ["c3001", "c3002"] and m.second.prebans == ["c3001", "c3003"]
    assert m.first.grade == "legend" and m.second.grade == "emperor"
    assert m.sequence()[:3] == [("F", MY[0]), ("S", ENEMY[0]), ("S", ENEMY[1])]
    assert m.day == "2026-10-19 10:35:59" and m.season == "pvp_rta_ss21"
    assert m.score == 3007 and m.turns == 5 and m.seconds == 53
    banned = m.first.picks[4]
    assert banned.position == 0 and banned.sets == [] and banned.dealt == 0
    assert [p.position for p in m.first.picks[:4]] == [1, 2, 3, 4]
    assert m.first.picks[0].sets == ["set_speed", "set_immune"] and m.first.picks[1].dealt == 2000


def test_parse_enemy_first_and_loss():
    m = parse_battle(battle(me_first=False, iswin=2), "cn")
    assert m.first.codes == list(ENEMY) and m.second.codes == list(MY)
    assert m.winner == "F"  # 对方先手、我方输
    m = parse_battle(battle(me_first=False, iswin=1), "cn")
    assert m.winner == "S"


def test_parse_rule():
    assert parse_battle(battle(), "cn").rule is None
    m = parse_battle(battle(fmt="global", rule="rta_cs_dodge_down_desc"), "global")
    assert m.rule == "rta_cs_dodge_down_desc" and m.rule_category == "rta_openingrule_category_1"
    # 有一方低于优胜者时是占位符「_」
    m = parse_battle(battle(fmt="global", opening_rule_title="_", opening_rule_desc_tid="_"), "global")
    assert m.rule is None and m.rule_category is None


def test_team_info_order_is_used():
    """对局详情里英雄的顺序是乱的，按 pick_order 排。"""
    raw = battle()
    team = json.loads("{" + raw["teamBettleInfo"] + "}")["my_team"]
    raw["teamBettleInfo"] = '"my_team":' + json.dumps(list(reversed(team)))
    assert parse_battle(raw, "cn").first.codes == list(MY)


def _break(raw, key, fn):
    raw = dict(raw)
    raw[key] = fn(raw[key])
    return raw


@pytest.mark.parametrize("raw,reason", [
    (battle(battle_seq=""), "缺对局编号"),
    (battle(iswin=0), "胜负不明"),
    (battle(teamBettleInfo=""), "缺对局详情"),
    (battle(my_deck="{bad json"), "字段格式不对"),
    (battle(my_deck={"preban_list": []}), "缺牌组"),
    (battle(my_deck={"hero_list": [], "preban_list": []}, teamBettleInfo='"my_team":[]', turn=0), "没有选秀"),
    (battle(my_banned=2), "不符合选秀规则"),  # 后禁了保护位
    (battle(my=("c1001", "c1002", "c1003", "c1004", "c2001")), "不符合选秀规则"),  # 双方选了同一名
    (battle(prebans=(("c2001", "c3002"), ("c3001", "c3003"))), "不符合选秀规则"),  # 选了被预禁的
    (_break(battle(), "teamBettleInfo", lambda s: s.replace('"pick_order" : 5', '"pick_order" : 4')), "选人顺序不对"),
])
def test_bad_battles(raw, reason):
    with pytest.raises(BadBattle) as e:
        parse_battle(raw, "cn")
    assert e.value.reason == reason


def test_first_pick_flags():
    raw = battle()
    deck = dict(raw["enemy_deck"])
    deck["hero_list"] = [dict(h, first_pick=1 if i == 0 else 0) for i, h in enumerate(deck["hero_list"])]
    with pytest.raises(BadBattle, match="双方都是"):
        parse_battle(dict(raw, enemy_deck=deck), "cn")
    deck = dict(raw["my_deck"])
    deck["hero_list"] = [dict(h, first_pick=0) for h in deck["hero_list"]]
    with pytest.raises(BadBattle, match="双方都不是"):
        parse_battle(dict(raw, my_deck=deck), "cn")


def test_strip_removes_personal_fields():
    kept = strip(battle(fmt="global", rule="rta_cs_dodge_down_desc"))
    assert set(kept) <= set(STORE_KEYS)
    text = json.dumps(kept, ensure_ascii=False)
    assert "昵称" not in text and "1100100000002" not in text
    assert "nicknameno" not in kept and "matchPlayerNicknameno" not in kept and "enemy_nick_no" not in kept
    assert parse_battle(kept, "global").rule == "rta_cs_dodge_down_desc"


# —— 开局行动条（B14d1） ——

def test_energy_parsed():
    from rta_fakes import gauge

    m = parse_battle(battle(energyGauge=gauge()), "cn")
    assert [p.energy for p in m.first.picks] == [100, 80, 70, 60, 0]  # 我方先手，第 5 手被禁
    assert [p.energy for p in m.second.picks] == [90, 75, 65, 0, 55]
    assert m.first_mover == "F" and m.first_hero == MY[0]
    # 对方先选，但我方的英雄先动 → 后手方先动
    m = parse_battle(battle(me_first=False, energyGauge=gauge()), "cn")
    assert m.first_mover == "S" and m.first_hero == MY[0] and m.second.picks[0].energy == 100
    # 对方英雄先动
    m = parse_battle(battle(energyGauge=gauge(mine=(90, 80, 70, 60, 0), theirs=(50, 75, 100, 0, 55))), "cn")
    assert m.first_mover == "S" and m.first_hero == ENEMY[2]


@pytest.mark.parametrize("value,reason", [
    (None, "缺行动条"),
    ('"energy_gauge":[]', "行动条条数不对"),
    ("{bad", "行动条格式不对"),
    ("gauge:two_firsts", "先动者不唯一"),
    ("gauge:banned_nonzero", "行动条为 0 的不是两名"),
    ("gauge:wrong_banned", "行动条和选秀对不上"),
    ("gauge:other_hero", "行动条和选秀对不上"),
])
def test_energy_problems_keep_match(value, reason):
    """行动条不合格时对局照常解析，只是没有行动条；数据报告按原因计数。"""
    from e7helper.core.rta.battle import energy_issue
    from rta_fakes import gauge

    values = {
        "gauge:two_firsts": gauge(theirs=(100, 75, 65, 0, 55)),
        "gauge:banned_nonzero": gauge(mine=(100, 80, 70, 60, 5)),
        "gauge:wrong_banned": gauge(mine=(100, 80, 70, 0, 60)),  # 0 的不是被禁的那名
        "gauge:other_hero": gauge(my=("c1001", "c1002", "c1003", "c1004", "c9999")),
    }
    raw = battle()
    raw.pop("energyGauge")
    if value is not None:
        raw["energyGauge"] = values.get(value, value)
    m = parse_battle(raw, "cn")
    assert m.first_mover is None and m.first_hero is None
    assert all(p.energy is None for side in (m.first, m.second) for p in side.picks)
    assert energy_issue(raw, m) == reason


def test_strip_keeps_energy():
    from rta_fakes import gauge

    kept = strip(battle(energyGauge=gauge()))
    assert "energyGauge" in kept and parse_battle(kept, "cn").first_mover == "F"
