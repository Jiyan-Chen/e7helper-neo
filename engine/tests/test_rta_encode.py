"""B14b：RTA 模型的特征编码。"""

import numpy as np
import pytest

from e7helper.core.rta import encode, rules
from e7helper.core.rta.battle import parse_battle
from rta_fakes import ENEMY, MY, battle

RULE = "rta_cs_dodge_down_desc"


def _match(**kw):
    return parse_battle(battle(**kw), kw.get("fmt", "cn"))


def _vocab():
    return encode.Vocab(heroes=list(MY) + list(ENEMY[:4]) + ["c3001", "c3002"],
                        rules=[(RULE, "rta_openingrule_category_6"), ("rta_cs_soulburn_dmg_up_desc", "rta_openingrule_category_1")])


def test_layout():
    assert encode.SEQ_LEN == 17 and encode.N_STATES == 12
    assert encode.TOKEN_TYPES.tolist() == [0, 1, 1, 2, 2, 3, 4, 4, 3, 3, 4, 4, 3, 3, 4, 5, 6]
    assert encode.STATE_POS.tolist() == [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16]
    assert encode.POSITION_IDS.tolist()[:5] == [0, 1, 1, 2, 2] and encode.N_POSITIONS == 15
    mask = encode.attention_mask()
    assert mask[1, 4] and mask[4, 1] and mask[0, 3]  # 预禁互相可见
    assert not mask[4, 5] and mask[5, 4] and mask[9, 5] and not mask[5, 9]  # 选秀之后因果
    assert mask[16, 15] and not mask[15, 16] and mask[16].all()


def test_pick_targets():
    assert encode.pick_targets(0) == [(5, 1.0)]
    assert encode.pick_targets(1) == [(6, 0.5), (7, 0.5)]  # 后手连选 2 名
    assert encode.pick_targets(2) == [(7, 1.0)]  # 这一轮的第二名
    assert encode.pick_targets(9) == [(14, 1.0)]
    assert encode.pick_targets(10) == [] and encode.pick_targets(11) == []
    # 每个局面的标签都是下一手轮到的那一方
    for n in range(10):
        for pos, _ in encode.pick_targets(n):
            assert rules.PICK_ORDER[pos - encode.PICK_POS] == rules.mover(n)


def test_match_tokens():
    m = _match(me_first=False, prebans=(("c3001", "c3002"), ("c3001", "c3003")))
    t = encode.match_tokens(m)
    assert t[0] is None
    assert t[1:5] == ["c3001", "c3003", "c3001", "c3002"]  # 先手方是对手
    assert [c for _, c in m.sequence()] == t[5:15]
    assert t[5] == ENEMY[0] and t[6:8] == list(MY[:2])
    assert t[15] == ENEMY[3] and t[16] == MY[4]  # 默认 enemy_banned=3、my_banned=4


def test_vocab():
    v = encode.Vocab.build({"c1": 50, "c2": 80, "c3": 29, "c4": 30}, [(RULE, "cat6"), ("unknown", None), (RULE, "cat6")])
    assert v.heroes == ["c2", "c1", "c4"] and v.size == 5
    assert v.hero("c2") == 2 and v.hero("c3") == encode.UNK and v.hero(None) == encode.PAD
    assert v.code(2) == "c2" and v.code(encode.UNK) is None
    assert v.rules == [(RULE, "cat6")] and v.n_rules == 3
    assert v.rule(None) == encode.RULE_NONE and v.rule(encode.UNKNOWN_RULE) == encode.RULE_UNKNOWN
    assert v.rule(RULE) == 2
    assert v.rule("rta_cs_new_desc", "cat6") == 2  # 没见过的规则按类别找同类的
    assert v.rule("rta_cs_new_desc", "cat9") == encode.RULE_UNKNOWN
    assert encode.Vocab.from_dict(v.to_dict()) == v
    assert v.lut(["c1", "c3", "c2"]).tolist() == [encode.PAD, 3, encode.UNK, 2]


def test_match_rule():
    assert encode.match_rule(_match()) == encode.UNKNOWN_RULE  # 国服没有这个字段
    assert encode.match_rule(_match(fmt="global")) is None
    assert encode.match_rule(_match(fmt="global", rule=RULE)) == RULE


@pytest.mark.parametrize("n", range(12))
def test_draft_state_matches_match_tokens(n):
    m = _match(fmt="global", rule=RULE)
    st = encode.DraftState.from_match(m, n)
    full = encode.match_tokens(m)
    t = st.tokens()
    picks = min(n, 10)
    assert st.state == n and st.n_picks == picks and not st.problems()
    assert t[:encode.PICK_POS + picks] == full[:encode.PICK_POS + picks]
    assert all(c is None for c in t[encode.PICK_POS + picks:15])
    assert t[15:] == (full[15:] if n == 11 else [None, None])
    assert st.mover() == rules.mover(picks)


def test_encode_states_and_mask():
    v = _vocab()
    m = _match(fmt="global", rule=RULE, grades=("legend", "gold"))
    states = [encode.DraftState.from_match(m, n) for n in (0, 3, 11)]
    states.append(encode.DraftState(grades=("champion", None), rule=None))  # 空局面、没有规则
    x = encode.encode_states(states, v)
    assert x["heroes"].shape == (4, 17) and x["heroes"].dtype == np.int64
    assert x["state"].tolist() == [0, 3, 11, 0]
    legend, gold, champ = (encode.grade_id(g) for g in ("legend", "gold", "champion"))
    assert x["ctx"].tolist()[0] == [legend, gold, 2] and x["ctx"].tolist()[3] == [champ, 0, encode.RULE_NONE]
    assert x["heroes"][0, 1:5].tolist() == [v.hero("c3001"), v.hero("c3002"), v.hero("c3001"), encode.UNK]  # c3003 不在词表
    assert x["heroes"][1, 5:9].tolist() == [v.hero(MY[0]), v.hero(ENEMY[0]), v.hero(ENEMY[1]), encode.PAD]
    assert x["heroes"][2, 15] == v.hero(MY[4]) and x["heroes"][2, 16] == v.hero(ENEMY[3])  # 双方被禁的
    assert (x["heroes"][:2, 15:] == encode.PAD).all()
    mask = encode.pick_mask(x["heroes"], x["state"], v.size)
    assert not mask[:, :encode.FIRST_HERO].any()
    assert not mask[0, v.hero("c3001")] and not mask[0, v.hero("c3002")] and mask[0, v.hero(MY[0])]
    assert not mask[1, v.hero(MY[0])] and not mask[1, v.hero(ENEMY[1])] and mask[1, v.hero(MY[1])]
    assert mask[3, encode.FIRST_HERO:].all()


def test_grade_id():
    assert encode.grade_id("bronze") == encode.grade_id("gold") == 1
    assert encode.grade_id("legend") == len(rules.GRADE_BUCKETS)
    assert encode.grade_id(None) == encode.grade_id("??") == encode.GRADE_UNKNOWN


def test_pick_counts():
    tokens = np.full((2, 17), -1, dtype=np.int16)
    tokens[:, 5:15] = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [0, 1, 2, 3, 4, 5, 6, 7, 8, 10]]
    tokens[:, 1] = 11  # 预禁不算
    codes = [f"c{i}" for i in range(12)]
    counts = encode.pick_counts(tokens, codes)
    assert counts["c0"] == 2 and counts["c9"] == 1 and counts["c10"] == 1 and "c11" not in counts
