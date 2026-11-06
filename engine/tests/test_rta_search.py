"""B14c：选秀推荐搜索。逻辑用 rta_fakes.FakeModel（胜率 = σ(双方强度差)，能手算）测；最后几个用随包模型测速度和输出。"""

import time

import numpy as np
import pytest

from e7helper.core.rta import encode, rules, search
from e7helper.core.rta.encode import DraftState
from rta_fakes import FakeModel, fake_priors

CODES = [f"c{i:02d}" for i in range(30)]
RARE = "c29"  # 很强，但几乎没人选、训练数据里只有 100 次
STRENGTH = {c: round(1.0 - 0.03 * i, 2) for i, c in enumerate(CODES[:29])} | {RARE: 3.0}
POP = {c: 0.0 for c in CODES[:29]} | {RARE: -10.0}
PICKS = {c: 5000 for c in CODES[:29]} | {RARE: 100}
PREBANS = {"F": ["c25", "c26"], "S": ["c27", "c28"]}


def sig(x):
    return 1 / (1 + np.exp(-x))


def advisor(model=None, second=None, **priors):
    return search.Advisor(model or FakeModel(STRENGTH, POP), fake_priors(PICKS, **priors), second)


def state(picks_in_order: list[str], banned=None) -> DraftState:
    st = DraftState(prebans={s: list(v) for s, v in PREBANS.items()}, grades=("emperor", "emperor"))
    for k, code in enumerate(picks_in_order):
        st.picks[rules.mover(k)].append(code)
    if banned:
        st.banned = dict(banned)
    return st


# —— 小函数 ——
def test_correction_only_removes_the_movers_gain():
    assert search.correction(0.5, 0.1, True) == pytest.approx(-0.05)
    assert search.correction(0.5, -0.1, True) == 0
    assert search.correction(0.5, -0.1, False) == pytest.approx(0.05)  # 对手的回应：我方胜率变小 = 对手有利
    assert search.correction(0.5, 0.1, False) == 0
    assert search.correction(1.0, 0.3, True) == 0


@pytest.mark.parametrize("n,k,expected", [(0, 1, None), (1, 2, None), (3, 2, 1), (4, 1, 0), (5, 2, 0), (6, 1, None),
                                          (7, 2, None), (9, 1, None), (10, 0, None)])
def test_protected_index(n, k, expected):
    assert search.protected_index(n, k) == expected


def test_nash():
    x, y, v = search.nash(np.array([[1.0, 0.0], [0.0, 1.0]]))  # 猜硬币
    assert x == pytest.approx([0.5, 0.5]) and y == pytest.approx([0.5, 0.5]) and v == pytest.approx(0.5)
    x, y, v = search.nash(np.array([[0.6, 0.7], [0.4, 0.9]]))  # 鞍点：行 0、列 0
    assert x == pytest.approx([1, 0]) and y == pytest.approx([1, 0]) and v == pytest.approx(0.6)
    rps = np.array([[0.5, 0.0, 1.0], [1.0, 0.5, 0.0], [0.0, 1.0, 0.5]])
    x, y, v = search.nash(rps)
    assert x == pytest.approx([1 / 3] * 3, abs=1e-6) and v == pytest.approx(0.5)
    m = np.random.default_rng(0).random((4, 4))
    x, y, v = search.nash(m)
    assert (m @ y <= v + 1e-6).all() and (x @ m >= v - 1e-6).all()  # 谁都不能单方面变好


# —— 轮到我方 ——
def test_first_pick_takes_the_strongest_common_hero():
    out = advisor().advise(state([]), "F")
    assert out["phase"] == "pick" and out["turn"] == "mine" and out["slots"] == 1
    recs = out["recommend"]
    assert 5 <= len(recs) <= 8 and recs[0]["heroes"] == ["c00"]
    assert all(RARE not in r["heroes"] for r in recs)  # 很强但没人选的不推荐
    assert [r["score"] for r in recs] == sorted((r["score"] for r in recs), reverse=True)
    assert recs[0]["depth"] == 3 and out["stats"]["depth"] == 3 and not out["stats"]["truncated"]
    r = recs[0]
    assert r["gap"] == 0 and recs[1]["gap"] < 0 and r["worst"] <= r["win"]
    assert r["threat"]["heroes"] and "reply" in r["threat"] and len(r["responses"]) == 3
    assert out["win"] == pytest.approx(0.5)  # 预禁在假模型里不算分，空局面五五开


def test_pair_round_and_per_hero_ranking():
    out = advisor().advise(state(["c00"]), "S")
    assert out["slots"] == 2
    best = out["recommend"][0]
    assert set(best["heroes"]) == {"c01", "c02"} and best["protected"] is None
    heroes = out["heroes"]
    assert {h["code"] for h in heroes[:2]} == {"c01", "c02"} and heroes[0]["partner"] in ("c01", "c02")
    assert len({h["code"] for h in heroes}) == len(heroes)


def test_protected_round_picks_the_better_order():
    # 位置越靠后权重越大：先手第 4–5 手里第 5 手是保护位，强的那名放第 5 手更好
    m = FakeModel(STRENGTH, POP, order=0.5)
    out = advisor(m).advise(state(["c10", "c11", "c12"]), "F")
    best = out["recommend"][0]
    assert best["protected"] == best["heroes"][1]
    assert STRENGTH[best["heroes"][1]] >= STRENGTH[best["heroes"][0]]


def test_pool_limits_candidates_and_discounts_rare_heroes():
    pool = [f"c{i:02d}" for i in range(5, 11)]
    out = advisor().advise(state([]), "F", pool=pool + [RARE, "c99"])
    codes = [r["heroes"][0] for r in out["recommend"]]
    assert set(codes) <= set(pool) | {RARE} and codes[0] == "c05"
    assert RARE in codes  # 池里的冷门英雄也算候选，但排不到前面
    rare = next(r for r in out["recommend"] if r["heroes"] == [RARE])
    assert rare["rare"] == [RARE] and rare["pool_only"] == [RARE] and rare["trust"] < 0.01
    assert out["unknown"] == ["c99"]


def test_pool_short_round_is_not_limited():
    # B14e2：这一轮要选 2 名，英雄池里能选的只剩 1 名（c00 已被先手选走）→ 这一轮推荐全部英雄
    out = advisor().advise(state(["c00"]), "S", pool=["c00", "c05"])
    assert out["pool_short"] and out["recommend"]
    assert set(out["recommend"][0]["heroes"]) == {"c01", "c02"}
    assert all(r["pool_only"] == [] for r in out["recommend"])
    # 预禁掉的也不算能选的：池里只有被预禁的英雄
    out = advisor().advise(state([]), "F", pool=["c25", "c26"])
    assert out["pool_short"] and out["recommend"][0]["heroes"] == ["c00"]
    # 池里全是模型没见过的英雄 = 能选的 0 名
    out = advisor().advise(state([]), "F", pool=["c99"])
    assert out["pool_short"] and out["recommend"][0]["heroes"] == ["c00"] and out["unknown"] == ["c99"]


def test_pool_enough_round_is_limited():
    out = advisor().advise(state(["c00"]), "S", pool=["c05", "c06"])
    assert not out["pool_short"]
    assert [sorted(r["heroes"]) for r in out["recommend"]] == [["c05", "c06"]]
    out = advisor().advise(state([]), "F", pool=["c05", "c06", "c07"])
    assert not out["pool_short"] and {r["heroes"][0] for r in out["recommend"]} == {"c05", "c06", "c07"}
    assert advisor().advise(state([]), "F")["pool_short"] is False  # 没有英雄池


def test_pool_short_later_round_is_not_limited():
    # 先手第 1 手在池里选；第 3 层我方再回应要选 2 名，池里只剩 1 名 → 那一轮也不限制（还能算到第 3 层）
    out = advisor().advise(state([]), "F", pool=["c05", "c06"])
    assert not out["pool_short"]
    best = out["recommend"][0]
    assert best["heroes"][0] in ("c05", "c06") and best["depth"] == 3
    reply = best["threat"]["reply"]
    assert len(reply) == 2 and not set(reply) <= {"c05", "c06"}


def test_unknown_heroes_in_state_are_listed():
    # B14h：快照里去掉的新英雄选进局面时按 UNK 算，也要列出来（和英雄池里的合在一起，不重复）
    out = advisor().advise(state(["c98"]), "S", pool=["c05", "c99", "c98"])
    assert out["unknown"] == ["c98", "c99"]
    assert advisor().advise(state(["c00"]), "S")["unknown"] == []


def test_trust_discounts_gain_by_commonness():
    # 一名常见度低的强英雄：自己那一手的提升被打折，排不到第一
    pop = dict(POP) | {"c03": -6.0}  # c03 比 c00 弱一点，但这里让它很少见
    strength = dict(STRENGTH) | {"c03": 1.5}
    out = advisor(FakeModel(strength, pop)).advise(state([]), "F")
    assert out["recommend"][0]["heroes"] == ["c00"]
    c03 = [r for r in out["recommend"] if r["heroes"] == ["c03"]]
    assert not c03 or c03[0]["trust"] < 0.2


def test_last_pick_searches_to_the_ban_stage():
    picks = CODES[3:12]  # 9 手，轮到后手最后一手
    out = advisor().advise(state(picks), "S")
    r = out["recommend"][0]
    assert r["end"] and r["depth"] == 1 and out["slots"] == 1
    assert r["heroes"] == ["c00"]


# —— 轮到对手 ——
def test_their_turn_lists_likely_picks_and_threats():
    out = advisor().advise(state(["c00"]), "F")
    assert out["turn"] == "theirs" and "recommend" not in out
    likely, threats = out["opponent"]["likely"], out["opponent"]["threats"]
    assert all(len(x["heroes"]) == 2 for x in likely)
    assert [x["prob"] for x in likely] == sorted((x["prob"] for x in likely), reverse=True)
    assert [x["win"] for x in threats] == sorted(x["win"] for x in threats)
    assert sum(x["prob"] for x in likely) <= 1.0 + 1e-9


def test_their_turn_uses_our_reading_with_the_pool():
    # B14e2 审核（用户意见：始终用我方的读数）：对手每种选法之后的胜率 = 我方从英雄池里挑的最好回应的预期
    weak = [f"c{i:02d}" for i in range(18, 25)]
    out = advisor().advise(state(["c00"]), "F", pool=weak)
    opp = out["opponent"]
    assert opp["win"] is not None and not out["stats"]["truncated"]
    assert all(x["win"] < x["now"] for x in opp["likely"])  # 池里都是弱的：比不知道英雄池的模型读数低
    wins = [x["win"] for x in opp["likely"]]
    assert min(wins + [t["win"] for t in opp["threats"]]) - 1e-9 <= opp["win"] <= max(wins) + 1e-9
    free = advisor().advise(state(["c00"]), "F")["opponent"]  # 不限英雄
    assert free["win"] > opp["win"]
    assert [x["win"] for x in opp["threats"]] == sorted(x["win"] for x in opp["threats"])
    # 和之后轮到我方时推荐第 1 名的预期是一个口径：对方真的选了最可能的那组，我方那一轮的推荐第 1 名
    top = opp["likely"][0]["heroes"]
    mine = advisor().advise(state(["c00"] + top), "F", pool=weak)["recommend"][0]
    assert set(mine["heroes"]) <= set(weak)


def test_their_last_pick_reads_the_ban_game():
    # 对手选最后一手（我方先手、已选 9 手）：之后直接后禁，胜率 = 后禁推荐行的预期
    picks = CODES[3:12]
    m = FakeModel(STRENGTH, POP | {"c01": 8.0})  # 对手几乎一定选 c01：可信度接近 1，修正很小
    out = advisor(m).advise(state(picks), "F")
    assert out["turn"] == "theirs"
    opp = out["opponent"]
    assert opp["win"] is not None and all(len(x["heroes"]) == 1 for x in opp["likely"])
    assert opp["likely"][0]["heroes"] == ["c01"]
    ban = advisor(m).advise(state(picks + ["c01"]), "F")["ban"]
    row = ban["row_stats"][ban["rows"].index(ban["recommend"])]
    assert opp["likely"][0]["win"] == pytest.approx(row["win"], abs=0.005)
    # 少见的选法加上修正（对手的回应只往我方有利的方向修），不会比后禁推荐行的预期低
    for x in opp["likely"][1:4]:
        b = advisor(m).advise(state(picks + x["heroes"]), "F")["ban"]
        assert x["win"] >= b["row_stats"][b["rows"].index(b["recommend"])]["win"] - 1e-9


# —— 后禁 ——
def test_ban_turn_matrix():
    picks = CODES[:10]
    out = advisor().advise(state(picks), "F")
    assert out["phase"] == "ban"
    b = out["ban"]
    f_picks = [c for k, c in enumerate(picks) if rules.PICK_ORDER[k] == "F"]
    s_picks = [c for k, c in enumerate(picks) if rules.PICK_ORDER[k] == "S"]
    assert b["rows"] == [c for i, c in enumerate(s_picks) if i != rules.PROTECTED_SLOT]  # 我方禁后手方的，保护位除外
    assert b["cols"] == [c for i, c in enumerate(f_picks) if i != rules.PROTECTED_SLOT]
    base = sum(STRENGTH[c] for c in f_picks) - sum(STRENGTH[c] for c in s_picks)
    expect = sig(base + np.array([[STRENGTH[r] - STRENGTH[c] for c in b["cols"]] for r in b["rows"]]))
    assert np.array(b["matrix"]) == pytest.approx(expect)
    assert out["win"] == pytest.approx(sig(base))
    q = np.ones(4) / 4  # 没有后禁率数据：都按平均
    score = 0.5 * expect.min(axis=1) + 0.5 * expect @ q
    assert b["recommend"] == b["rows"][int(np.argmax(score))]
    assert expect.min() - 1e-9 <= b["nash"]["value"] <= expect.max() + 1e-9


def test_ban_matrix_keeps_unknown_heroes():
    # B14h：模型没见过的英雄（按 UNK 算）在后禁矩阵里也要给出编号，页面才能记下禁了谁
    picks = ["c98"] + CODES[1:10]  # c98 是先手方第 1 手
    out = advisor().advise(state(picks), "S")
    assert out["ban"]["rows"][0] == "c98" and None not in out["ban"]["rows"] + out["ban"]["cols"]
    assert out["unknown"] == ["c98"]


def test_ban_rates_weight_the_expectation():
    picks = CODES[:10]
    f_picks = [c for k, c in enumerate(picks) if rules.PICK_ORDER[k] == "F"]
    hot = f_picks[0]
    out = advisor(postban={hot: [900, 1000]} | {c: [100, 1000] for c in f_picks[1:]}).advise(state(picks), "F")
    likely = {x["code"]: x["prob"] for x in out["ban"]["their_likely"]}
    assert likely[hot] == pytest.approx(0.9 / (0.9 + 0.1 * 3))


def test_done_state():
    picks = CODES[:10]
    out = advisor().advise(state(picks, banned={"F": "c00", "S": "c01"}), "S")
    assert out["phase"] == "done"
    f = sum(STRENGTH[c] for k, c in enumerate(picks) if rules.PICK_ORDER[k] == "F") - STRENGTH["c00"]
    s = sum(STRENGTH[c] for k, c in enumerate(picks) if rules.PICK_ORDER[k] == "S") - STRENGTH["c01"]
    assert out["win"] == pytest.approx(1 - sig(f - s))


# —— 截止时间、缓存、第二个模型、错误 ——
def test_deadline_truncates_but_still_answers():
    out = advisor().advise(state(["c00"]), "S", budget=0.0)
    assert out["stats"]["truncated"] and out["stats"]["depth"] == 1
    assert len(out["recommend"]) == 8 and out["recommend"][0]["depth"] == 1


def test_cache():
    adv = advisor()
    a = adv.advise(state([]), "F")
    b = adv.advise(state([]), "F")
    assert not a["stats"]["cached"] and b["stats"]["cached"]
    assert a["recommend"] == b["recommend"]
    c = adv.advise(state([]), "F", budget=0.0)  # 预算更少：用缓存
    assert c["stats"]["cached"]


def test_second_model_with_its_own_vocab():
    # 第二个模型的词表顺序不一样、少一名英雄：编号要换对，强度一样时两个模型的结果一样
    codes2 = list(reversed(CODES[:28]))
    second = FakeModel({c: STRENGTH[c] for c in codes2}, {c: POP[c] for c in codes2})
    out = advisor(second=second).advise(state([]), "F")
    assert out["second_win"] == pytest.approx(out["win"])
    for r in out["recommend"]:
        assert r["second"]["depth"] == 2 and r["uncertain"] is False
        assert abs(r["second"]["spread"]) < 0.05


def test_invalid_state():
    with pytest.raises(ValueError) as e:
        advisor().advise(state(["c00", "c00"]), "S")
    assert any("两次" in p for p in e.value.args[0])
    with pytest.raises(ValueError):
        advisor().advise(state([]), "X")


# —— 预禁 ——
PRE = {"F": [["c00", "c01", 50], ["c02", "c03", 30], ["c10", "c11", 20]],
       "S": [["c00", "c01", 60], ["c04", "c05", 40]]}


def test_preban_candidates_come_from_data():
    m = FakeModel(STRENGTH, POP, preban=0.5)
    out = advisor(m, preban=PRE).preban("F", grades=("emperor", "emperor"))
    recs = out["recommend"]
    assert {tuple(r["heroes"]) for r in recs} == {("c00", "c01"), ("c02", "c03"), ("c10", "c11")}
    assert recs[0]["heroes"] == ["c00", "c01"]  # 假模型里先手方预禁强的英雄更好
    assert recs[0]["share"]["F"] == pytest.approx(0.5)
    # 对手（后手方）的预禁按 60 / 40 加权
    theirs = np.array([STRENGTH["c00"] + STRENGTH["c01"], STRENGTH["c04"] + STRENGTH["c05"]]) * -0.5
    mine = 0.5 * (STRENGTH["c00"] + STRENGTH["c01"])
    assert recs[0]["win"] == pytest.approx(sig(mine + theirs) @ np.array([0.6, 0.4]))
    assert recs[0]["worst"] == pytest.approx(sig(mine + theirs).min())
    assert out["theirs"]["F"][0]["heroes"] == ["c00", "c01"]


def test_preban_skips_heroes_not_in_model():
    # B14h 用户意见：模型没训练进的英雄不进 RTA 助手，预禁推荐和「对方常见预禁」里都不出现
    m = FakeModel(STRENGTH, POP, preban=0.5)
    pre = {"F": [["c00", "c98", 70]] + PRE["F"], "S": [["c99", "c01", 70]] + PRE["S"]}
    out = advisor(m, preban=pre).preban("F", grades=("emperor", "emperor"))
    assert all("c98" not in r["heroes"] for r in out["recommend"])
    assert all("c99" not in t["heroes"] for t in out["theirs"]["F"])
    assert out["recommend"][0]["share"]["F"] == pytest.approx(50 / 170)  # 占比还是按全部数据算


def test_preban_fixed_and_unknown_side():
    m = FakeModel(STRENGTH, POP, preban=0.5)
    out = advisor(m, preban=PRE).preban(None, fixed="c02")
    assert all("c02" in r["heroes"] for r in out["recommend"]) and out["side"] is None
    assert set(out["recommend"][0]["share"]) == {"F", "S"}


# —— 随包模型 ——
@pytest.fixture(scope="module")
def real():
    if not search.available():
        pytest.skip("还没有随包模型 / priors.json")
    return search.load()


def test_bundled_advisor_loads(real):
    info = real.info()
    assert info["model"]["heroes"] > 200 and info["priors"]
    assert real.second is not None and info["second"]["run"]


def test_bundled_advise_speed_and_no_rare_heroes(real):
    heroes = real.model.vocab.heroes
    st = DraftState(prebans={"F": heroes[:2], "S": heroes[2:4]}, picks={"F": [heroes[4]], "S": []},
                    grades=("emperor", "emperor"))
    t = time.perf_counter()
    out = real.advise(st, "S")
    assert time.perf_counter() - t < 6.0
    assert out["slots"] == 2 and 5 <= len(out["recommend"]) <= 8
    for r in out["recommend"]:
        assert not r["rare"], r
        assert 0.02 < r["win"] < 0.98 and "second" in r


def test_bundled_preban_speed(real):
    t = time.perf_counter()
    out = real.preban(None, grades=("legend", "emperor"))
    assert time.perf_counter() - t < 5.0  # 机器忙时会截断（stats.truncated），照样要在时间内给出结果
    assert len(out["recommend"]) == 8
