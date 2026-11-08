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


# —— 按先动概率混合（B14g2） ——
def _speed_table(fast=("c00",), extra=None):
    """c00 290 以上，其余 190–210（速度档隔开，开局随机翻不过来）；extra = 另加的 {编号: 档}。"""
    from e7helper.core.rta import speed

    def one(k):
        h = [0] * 10
        h[k] = 100
        return h

    hists = {c: {"legend": one(9 if c in fast else 4), "champion": one(9 if c in fast else 3)} for c in CODES}
    hists.update({c: {"legend": one(k)} for c, k in (extra or {}).items()})
    return speed.SpeedTable.from_hists(hists, jitter=5.0)


def mixed_advisor(table=None, gap=0.8, **kw):
    pre = {"F": [["c00", "c01", 50], ["c02", "c03", 30]], "S": [["c00", "c01", 60], ["c04", "c05", 40]]}
    return search.Advisor(FakeModel(STRENGTH, POP, gap=gap, preban=0.5), fake_priors(PICKS, preban=pre),
                          speed_table=table or _speed_table(), **kw)


def test_mixed_values_split_and_first():
    """每个值带「我方先动时 / 后动时」两种；显示的先动概率（审核第 1、2 轮用户意见）只按双方已经选出的英雄、用速度表算：
    推荐 = 加上这一组、对方的选法 = 加上对方这一手、对方回合 = 当前局面；不补还没选的几手、不把之后的回应合进去。
    后禁矩阵每格 4 打 4：先动 × 先动时 + 后动 × 后动时 = 这一格。"""
    from e7helper.core.rta import speed

    adv = mixed_advisor()
    st = state(["c00", "c03", "c04"])  # 轮到先手方（我方）选 2 名
    out = adv.advise(st, "F")
    unit = lambda s, c: speed.Unit(s, c, "emperor")  # noqa: E731
    present = adv.calc.prob([unit("F", "c00")], [unit("S", "c03"), unit("S", "c04")], ("emperor", "emperor"), fill=False)
    assert out["first"]["mine"] == pytest.approx(present) and out["first"]["mine"] > 0.99  # 只有 c00 在场：几乎一定先动
    assert out["first"]["partial"]
    assert adv.advise(state([]), "F")["first"] is None  # 一方还没有英雄：不显示

    def after(base: DraftState, heroes: list[str]) -> DraftState:
        nxt = DraftState.from_dict(base.to_dict())
        for code in heroes:
            nxt.picks[rules.mover(nxt.n_picks)].append(code)
        return nxt

    for r in out["recommend"]:
        assert r["win_first"] > r["win_second"]  # 假模型：先手方先动时 logit + 0.8
        assert r["first"] == pytest.approx(adv.advise(after(st, r["heroes"]), "F")["first"]["mine"], abs=1e-6)
        mine = [unit("F", c) for c in ["c00", *r["heroes"]]]
        assert r["first"] == pytest.approx(adv.calc.prob(mine, [unit("S", "c03"), unit("S", "c04")], ("emperor", "emperor"),
                                                         fill=False))
    st5 = state(["c00", "c03", "c04", "c05", "c06"])
    theirs = adv.advise(st5, "F")  # 先手方（我方）看后手方的回合
    o = theirs["opponent"]
    assert o["first"] == theirs["first"]["mine"] and o["win_first"] > o["win_second"]
    for c in o["likely"][:3]:
        assert c["win_first"] > c["win_second"]
        assert c["first"] == pytest.approx(adv.advise(after(st5, c["heroes"]), "F")["first"]["mine"], abs=1e-6)
    full = ["c00", "c03", "c04", "c05", "c06", "c07", "c08", "c09", "c10", "c11"]
    b = adv.advise(state(full), "F")["ban"]
    m, f, a, s = (np.array(b[k]) for k in ("matrix", "first", "win_first", "win_second"))
    assert np.allclose(f * a + (1 - f) * s, m)
    # c00 是我方第 1 手、最快：对方禁了它的那一列我方先动概率低于其余各列
    # （假模型的三个头隐含「一般玩家五五开」，effective_first 以它为底、只加速度表的变化量，所以不是 0 / 1）
    col = b["cols"].index("c00")
    assert f[:, col].max() < np.delete(f, col, axis=1).min()
    q = np.array([x["prob"] for x in b["their_likely"]])
    for i, row in enumerate(b["row_stats"]):  # 每行：4 格按对方后禁率平均
        assert row["first"] == pytest.approx(float(f[i] @ q / q.sum()), abs=1e-9)
        assert row["win_first"] > row["win_second"]
    done = adv.advise(state(full, banned={"F": "c05", "S": "c08"}), "F")
    assert done["phase"] == "done" and not done["first"]["partial"] and done["win_first"] > done["win_second"]
    fm = done["first"]["mine"]
    assert fm * done["win_first"] + (1 - fm) * done["win_second"] == pytest.approx(done["win"], abs=1e-9)


def test_grades_only_move_the_first_mover():
    """用户原则：段位只影响谁先动。同一阵容换段位，先动时 / 后动时两种胜率不变，只有先动概率（和混合结果）变。"""
    adv = mixed_advisor(_speed_table(fast=()))  # 都一样快：先动概率只看段位
    full = ["c00", "c03", "c04", "c05", "c06", "c07", "c08", "c09", "c10", "c11"]
    hi, lo = state(full), state(full)
    hi.grades, lo.grades = ("legend", "champion"), ("champion", "legend")
    b_hi, b_lo = adv.advise(hi, "F")["ban"], adv.advise(lo, "F")["ban"]
    assert np.allclose(b_hi["win_first"], b_lo["win_first"]) and np.allclose(b_hi["win_second"], b_lo["win_second"])
    assert (np.array(b_hi["first"]) > np.array(b_lo["first"]) + 0.2).all()
    assert (np.array(b_hi["matrix"]) > np.array(b_lo["matrix"])).all()


def test_no_speed_table_uses_the_unknown_head():
    adv = search.Advisor(FakeModel(STRENGTH, POP, gap=0.8), fake_priors(PICKS))
    full = ["c00", "c03", "c04", "c05", "c06", "c07", "c08", "c09", "c10", "c11"]
    out = adv.advise(state(full), "F")
    b = out["ban"]
    assert out["first"] is None and b["first"] is None and all(st["first"] is None for st in b["row_stats"])
    st = state(full, banned={"F": b["cols"][0], "S": b["rows"][0]})
    assert b["matrix"][0][0] == pytest.approx(float(adv.model.win([st])[0]))  # 「不知道」的头 = σ(logit)
    assert adv.info()["mix"] == "unknown" and mixed_advisor().info()["mix"] == "first"


def test_speeds_change_the_first_mover_and_the_cache_key():
    adv = mixed_advisor()
    st = state(["c00", "c03", "c04"])  # 先手方 c00（最快）；后手方 c03、c04（慢）
    slow = adv.advise(st, "S")  # 我方是后手
    fast = adv.advise(st, "S", speeds={"c03": 400})  # 我方 c03 填了 400 速：跑得过 c00
    assert fast["first"]["mine"] > slow["first"]["mine"] + 0.2 and not fast["stats"]["cached"]
    theirs = adv.advise(st, "F", speeds={"c03": 400})  # 我方是先手时 c03 是对方的：填的速度只算我方英雄
    assert theirs["first"]["mine"] == pytest.approx(1 - slow["first"]["mine"], abs=1e-6)


def test_unknown_hero_uses_its_own_speed():
    """局面里模型没见过的英雄（UNK）先动概率按它自己的速度算（速度表里有它）。"""
    adv = mixed_advisor(_speed_table(fast=(), extra={"zz": 9}))
    full = ["zz", "c03", "c04", "c05", "c06", "c07", "c08", "c09", "c10", "c11"]
    b = adv.advise(state(full), "F")["ban"]
    f = np.array(b["first"])
    col = b["cols"].index("zz")
    assert np.delete(f, col, axis=1).min() > f[:, col].max() + 0.1  # 被禁了 zz 的那一列我方不再快


def test_mixed_preban_and_win():
    adv = mixed_advisor(_speed_table(fast=()))
    hi = adv.preban("F", grades=("legend", "champion"))
    lo = adv.preban("F", grades=("champion", "legend"))
    assert hi["recommend"][0]["win"] > lo["recommend"][0]["win"]  # 段位高 → 先动概率大 → 混合后更高
    st = state(["c00", "c03"])
    from e7helper.core.rta import speed

    first, ref = speed.first_pair(adv.calc, [st])
    assert adv.win([st])[0] == pytest.approx(float(adv.model.win([st], first, ref)[0]))


def test_priors_slots_roundtrip():
    from e7helper.core.rta import priors as rpriors
    from rta_fakes import synthetic_dataset

    data = rpriors.build(synthetic_dataset(n=50))
    assert len(data["slots"]) == rules.PICKS_PER_SIDE and sum(data["slots"][0].values()) == 100
    p = rpriors.Priors.from_dict(data)
    assert p.slots == data["slots"] and "slots" not in p.meta
    assert rpriors.Priors.from_dict({k: v for k, v in data.items() if k != "slots"}).slots == []  # 旧文件


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


def test_bundled_grades_only_shift_through_first_mover(real):
    """0.4.0-beta.1 的复现用例（B14g2 验收）：段位从「挑战者 vs 战神」改到「传说 vs 传说」，推荐的预期只因先动概率小幅变动
    （旧模型把赛后段位当成实力，挑战者一方的推荐只有 3%）。"""
    from e7helper.core.data import heroes as hero_db

    db = hero_db()
    code = lambda n: db.find(n).code  # noqa: E731
    out = {}
    for g in (("challenger", "warlord"), ("legend", "legend")):
        st = DraftState(prebans={"F": [code("里安娜路西艾拉"), code("天秤之主")], "S": [code("黎洁特"), code("天秤之主")]},
                        picks={"F": [code("调香师维波里丝")], "S": [code("诺托斯"), code("波涛裂痕艾碧拉")]}, grades=g, rule=None)
        out[g] = real.advise(st, "F", budget=8.0)
    a, b = out[("challenger", "warlord")], out[("legend", "legend")]
    assert real.calc is not None and a["first"]["mine"] < b["first"]["mine"]
    assert abs(a["win"] - b["win"]) < 0.03  # 当前局面：只差先动概率带来的一两个点
    assert a["recommend"][0]["win"] > 0.4 and abs(a["recommend"][0]["win"] - b["recommend"][0]["win"]) < 0.05


def test_bundled_preban_speed(real):
    t = time.perf_counter()
    out = real.preban(None, grades=("legend", "emperor"))
    assert time.perf_counter() - t < 5.0  # 机器忙时会截断（stats.truncated），照样要在时间内给出结果
    assert len(out["recommend"]) == 8
