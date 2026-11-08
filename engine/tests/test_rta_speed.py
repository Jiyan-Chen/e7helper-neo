"""B14d1：先动概率（速度表、开局规则、从开局行动条反推 290 以上、接到推荐上）。合成数据，不联网。"""

import json

import numpy as np
import pytest

from e7helper.core.rta import encode, speed
from e7helper.core.rta.speed import EnergyUnit, SpeedTable, Unit


def one_bin(k: int, n: int = 1000) -> list[int]:
    """官方直方图：人全在第 k 档（0 = 110–130 … 9 = 290 以上）。"""
    h = [0] * 10
    h[k] = n
    return h


def table(**heroes) -> SpeedTable:
    return SpeedTable.from_hists({c: {"legend": h} for c, h in heroes.items()}, jitter=5.0)


def test_dist_and_quantiles():
    t = table(a=one_bin(6), top=one_bin(9))
    p = t.dist("a", "legend")
    assert p.shape == (13,) and p[6] == pytest.approx(1.0)
    assert t.quantiles(p) == pytest.approx([235, 240, 245])  # 230–250 这一档
    # 290 以上按尾部分：没拟合时用先验
    p = t.dist("top", "legend")
    assert p[9:] == pytest.approx(speed.PRIOR_TAIL) and t.top_share(p) == pytest.approx(1.0)
    t2 = SpeedTable({"heroes": {"top": {"legend": {"hist": one_bin(9), "tail": [0, 1, 0, 0]}}}})
    assert t2.quantiles(t2.dist("top", "legend"), (0.5,)) == pytest.approx([320])


def test_grade_fallback_and_mixture():
    t = SpeedTable.from_hists({"a": {"legend": one_bin(7, 300), "champion": one_bin(5, 100)}})
    assert t.dist("a", "legend")[7] == 1.0 and t.dist("a", "champion")[5] == 1.0
    assert t.dist("a", "emperor")[7] == 1.0  # 没有王者段，用最近的传说
    assert t.dist("a", "warlord")[5] == 1.0  # 战神离优胜者更近
    assert t.dist("a", "gold")[5] == 1.0  # 金牌按大师算 → 最近的优胜者
    t2 = SpeedTable.from_hists({"a": {"champion": one_bin(5), "emperor": one_bin(7)}})
    assert t2.dist("a", "warlord")[7] == 1.0  # 一样近时取高的
    mix = t.dist("a", None)  # 不知道段位：按人数混合
    assert mix[7] == pytest.approx(0.75) and mix[5] == pytest.approx(0.25)
    assert t.dist("nobody", "legend") is None
    assert speed.analysis_grade("bronze") == "master" and speed.analysis_grade(None) is None


def test_first_mover_basics():
    t = table(fast=one_bin(8), slow=one_bin(3), b=one_bin(6), c=one_bin(6))
    r = speed.first_mover(t, [Unit("mine", "fast", "legend"), Unit("theirs", "slow", "legend")])
    assert r["sides"]["mine"] == 1.0
    assert r["heroes"][0]["speed"] == [275, 280, 285] and r["heroes"][0]["p"] == 1.0
    # 一样的英雄 → 各一半左右
    r = speed.first_mover(t, [Unit("mine", "b", "legend"), Unit("theirs", "c", "legend")])
    assert 0.45 < r["sides"]["mine"] < 0.55
    # 填了速度的用填的
    r = speed.first_mover(t, [Unit("mine", "slow", "legend", speed=300), Unit("theirs", "fast", "legend")])
    assert r["sides"]["mine"] > 0.95 and r["heroes"][0]["fixed"] == 300 and r["heroes"][0]["speed"] is None
    # 同样的输入结果一样
    us = [Unit("mine", "b", "legend"), Unit("theirs", "c", "legend")]
    assert speed.first_mover(t, us) == speed.first_mover(t, us)
    # 没有数据的英雄按段位平均，标出来
    r = speed.first_mover(t, [Unit("mine", "unknown", "legend"), Unit("theirs", "b", "legend")])
    assert r["heroes"][0]["no_data"] and 0 < r["sides"]["mine"] < 1


def test_opening_rules():
    t = table(c1133=one_bin(6), c1153=one_bin(2), other=one_bin(9))
    zio, harsetti = "c1133", "c1153"
    # 智武开局 +30%：240 速能赢 300 速
    r = speed.first_mover(t, [Unit("mine", zio, speed=240), Unit("theirs", "other", speed=300)])
    assert r["sides"]["mine"] == 1.0 and "智武" in r["heroes"][0]["rule"]
    # 用户举的例子：200 速的智武跑不过 320 速的普通英雄
    r = speed.first_mover(t, [Unit("mine", zio, speed=200), Unit("theirs", "other", speed=320)])
    assert r["sides"]["mine"] == 0.0
    # 赫尔赛蒂：其他英雄速度限制在她的 90% 以下 → 150 速也先动
    r = speed.first_mover(t, [Unit("mine", harsetti, speed=150), Unit("theirs", "other", speed=330)])
    assert r["sides"]["mine"] > 0.95
    assert "c6005" not in t.rules  # 天秤之主开局不触发


# —— 从开局行动条反推 290 以上 ——

ANCHORS = [f"a{i}" for i in range(8)]
TRUE_TAIL = {"t0": [0.2, 0.5, 0.2, 0.1], "t1": [0.7, 0.2, 0.1, 0.0]}


def synthetic(n: int = 1500, jitter: float = 5.0, seed: int = 1):
    """合成对局：每方 1 名 290 以上的英雄 + 3 名中间档的；速度按「真实」分布抽，行动条按游戏规则算。"""
    rng = np.random.default_rng(seed)
    hists = {a: {"legend": one_bin(4 + i % 4)} for i, a in enumerate(ANCHORS)}
    hists.update({t: {"legend": [0] * 8 + [200, 800]} for t in TRUE_TAIL})
    out = []
    for _ in range(n):
        units = []
        for side in "FS":
            top = str(rng.choice(list(TRUE_TAIL)))
            for code in [top, *rng.choice(ANCHORS, 3, replace=False)]:
                if code in TRUE_TAIL:
                    if rng.random() < 0.2:
                        s = rng.uniform(270, 290)
                    else:
                        k = rng.choice(4, p=TRUE_TAIL[code])
                        s = 290 + 20 * k + rng.uniform(0, 20)
                else:
                    lo = 110 + 20 * (4 + ANCHORS.index(code) % 4)
                    s = rng.uniform(lo, lo + 20)
                units.append([code, side, s])
        r = rng.uniform(0, jitter, len(units))
        s = np.array([u[2] for u in units])
        t = ((100 - r) / s).min()
        e = np.minimum(np.round(r + s * t), 99)
        e[int(np.argmin((100 - r) / s))] = 100
        out.append([EnergyUnit(c, side, "legend", int(x)) for (c, side, _), x in zip(units, e)])
    return hists, out


def test_fit_tails_recovers_synthetic_tail():
    hists, matches = synthetic()
    t = SpeedTable.from_hists(hists, jitter=5.0)
    res = speed.fit_tails(t, matches)
    assert res["used"] == len(matches)
    for code, truth in TRUE_TAIL.items():
        assert res["heroes"][code]["legend"] == pytest.approx(truth, abs=0.12), code
    # 核对：反推 ≥ 290 的比例接近官方的 80%
    for row in res["check"]:
        if row["code"] in TRUE_TAIL:
            assert row["implied_top"] == pytest.approx(row["official_top"], abs=0.08)


def test_implied_speeds_skip_rules():
    t = table(a=one_bin(6), b=one_bin(6), c=one_bin(6), c1153=one_bin(2))
    units = [EnergyUnit("a", "F", "legend", 80), EnergyUnit("b", "F", "legend", 80), EnergyUnit("c", "S", "legend", 80),
             EnergyUnit("x", "S", "legend", 100)]
    est = speed.implied_speeds(t, units)
    assert est[3] == pytest.approx((100 - 2.5) / ((80 - 2.5) / 240))  # 三名参照都是 240 速、行动条 80
    assert speed.implied_speeds(t, units[:2] + [units[3]]) is None  # 参照不够 3 名
    assert speed.implied_speeds(t, units + [EnergyUnit("c1153", "S", "legend", 60)]) is None  # 有限速英雄不反推


def test_build_and_evaluate():
    hists, matches = synthetic(n=1200)
    res = speed.build(hists, matches, season="pvp_rta_ss21", eval_limit=400)
    data = res["data"]
    assert data["jitter"] == 5.0  # 各取值差不到 0.002，保留默认
    fit = data["fit"]
    # 双方各有一名 290 以上的英雄，先动接近五五开；拟合出尾部才分得出谁更快
    assert fit["test"]["matches"] == 240
    assert fit["test"]["log_loss"] < fit["test_without_tail"]["log_loss"] - 0.01
    assert fit["test"]["accuracy"] > fit["test_without_tail"]["accuracy"]
    assert sum(b["n"] for b in fit["test"]["calibration"]) == 240
    tab = SpeedTable(json.loads(json.dumps(data)))  # 能存成 JSON 再读回
    assert tab.tails["t0"]["legend"].sum() == pytest.approx(1.0) and tab.info()["heroes"] == 10


def test_clean_hists():
    """B14h：基础速度到「基础 × 1.25」那几档的孤立尖峰（没算装备）去掉；平滑的慢速配装、高档的配速尖峰不动。"""
    hists = {
        "fast": {"legend": [0, 2000, 1, 2, 1, 1, 1, 0, 2, 16000], "champion": [0, 0, 0, 0, 0, 0, 0, 0, 0, 500]},
        "slow": {"legend": [9000, 16000, 3500, 400, 160, 0, 0, 0, 0, 0]},  # 基础 100：只看 110–130，比上一档少
        "tuned": {"legend": [0, 0, 0, 0, 0, 1400, 7, 0, 0, 0]},  # 210–230 的配速，不是低档
        "only": {"legend": [0, 800, 0, 0, 0, 0, 0, 0, 0, 0]},  # 全在低档：去掉就什么都没了，不动
        "nobase": {"legend": [0, 2000, 0, 0, 0, 0, 0, 0, 0, 100]},
    }
    out, removed = speed.clean_hists(hists, {"fast": 129, "slow": 100, "tuned": 102, "only": 120})
    assert out["fast"]["legend"] == [0, 0, 0, 2, 1, 1, 1, 0, 2, 16000]  # 129 × 1.25 + 5 = 166：110 / 130 / 150 三档
    assert removed == [{"code": "fast", "grade": "legend", "share": round(2001 / 18008, 4)}]
    for code in ("slow", "tuned", "only", "nobase"):
        assert out[code] == hists[code]
    assert out["fast"]["champion"] == hists["fast"]["champion"]


def test_refit_low_restores_real_slow_builds():
    """去掉的低档按开局行动条反推的低速比例补回：真的慢的补回来，瑕疵不补。"""
    raw = {"slow": {"legend": [0, 8000, 0, 0, 0, 0, 0, 1000, 500, 500]},  # 基础 110：8 成在 130–150，真的慢
           "fake": {"legend": [0, 3000, 0, 0, 0, 0, 0, 0, 0, 7000]},  # 3 成在低档，其实都是 290 以上
           **{f"m{i}": {"legend": one_bin(5)} for i in range(4)}}  # 参照：210–230
    base = {"slow": 110, "fake": 110}
    clean, removed = speed.clean_hists(raw, base)
    assert {r["code"] for r in removed} == {"slow", "fake"}
    # 每场：参照 4 名行动条 50（210–230 中位 220 → 经过的时间 ≈ (50 − 2.5) / 220），slow 慢（约 140）、fake 快（约 320）
    t = 47.5 / 220
    matches = [[EnergyUnit(f"m{i}", "FS"[i % 2], "legend", 50) for i in range(4)]
               + [EnergyUnit("slow", "F", "legend", round(140 * t + 2.5)), EnergyUnit("fake", "S", "legend", 72)]
               for _ in range(80)]
    out, restored = speed.refit_low(raw, clean, removed, matches, base)
    by = {r["code"]: r for r in restored}
    assert set(by) == {"slow"} and by["slow"]["n"] == 80
    assert by["slow"]["share"] == pytest.approx(80 / 100)  # 全部低于 150，向 0 收缩 20 次
    a = np.array(out["slow"]["legend"])
    assert a.sum() == pytest.approx(10000) and a[1] == pytest.approx(8000)
    assert out["fake"]["legend"][1] == 0  # 没补
    # 反推不到 min_n 次的不补
    assert speed.refit_low(raw, clean, removed, matches[:20], base)[1] == []


def test_build_cleans_and_reports():
    hists, matches = synthetic(n=600)
    res = speed.build(hists, matches, season="pvp_rta_ss21", eval_limit=100, base_speeds={})
    fit = res["data"]["fit"]
    assert fit["test_raw_hists"] == fit["test_cleaned_only"] == fit["test_without_tail"]  # 没有基础速度：什么都没去掉
    assert fit["low_removed"] == 0 and res["removed"] == [] and res["restored"] == []


def test_load(tmp_path):
    assert speed.load(tmp_path / "none.json") is None
    path = tmp_path / "speed.json"
    path.write_text(json.dumps({"format": 1, "season": "s", "heroes": {"a": {"legend": {"hist": one_bin(6)}}}}))
    assert speed.load(path).season == "s"


# —— 接到推荐上 ——

def test_annotate():
    """B14g2：先动概率由搜索给（混合胜率用的那个），annotate 只加每名在场英雄第一个行动的概率（命令行显示用）。"""
    # 速度档隔开，开局随机翻不过来：f1 290 以上 > s1 250–270 > 其余 190–210
    t = table(f1=one_bin(9), f2=one_bin(4), f3=one_bin(4), s1=one_bin(7), s2=one_bin(4))
    st = encode.DraftState(picks={"F": ["f1", "f2", "f3"], "S": ["s1", "s2"]}, grades=("legend", "legend"))
    out = speed.annotate({"first": {"mine": 0.7, "partial": True}}, st, "F", t)
    assert out["first"]["mine"] == 0.7  # 搜索给的不动
    top = max(out["first"]["heroes"], key=lambda h: h["p"])
    assert top["code"] == "f1" and top["side"] == "mine" and top["p"] == 1.0
    # 我方是后手、英雄池里给 s2 填了 400 速
    top = max(speed.annotate({"first": {"mine": 0.2}}, st, "S", t, speeds={"s2": 400})["first"]["heroes"], key=lambda h: h["p"])
    assert top["code"] == "s2" and top["side"] == "mine" and top["p"] == 1.0
    assert speed.annotate({"first": None}, st, "F", t)["first"] is None  # 没有速度表时搜索给的是 None
    assert "heroes" not in speed.annotate({"first": {"mine": 0.5}}, st, "F", None)["first"]
    st = encode.DraftState(picks={"F": ["f1"], "S": []})
    assert "heroes" not in speed.annotate({"first": {"mine": 0.5}}, st, "F", t)["first"]  # 对方还没有英雄


# —— 快速先动概率（B14g） ——

def _calc_table() -> SpeedTable:
    hists = {f"h{i}": {"legend": one_bin(3 + i % 7, 500), "champion": one_bin(2 + i % 6, 500)} for i in range(12)}
    hists["c1133"] = {"legend": one_bin(6)}  # 智武：开局 +30%
    hists["c1153"] = {"legend": one_bin(4)}  # 赫尔赛蒂：限速
    hists["top"] = {"legend": [0] * 8 + [300, 700]}
    return SpeedTable.from_hists(hists, jitter=5.0)


def test_first_calc_matches_monte_carlo():
    t = _calc_table()
    calc = speed.FirstCalc(t)
    rng = np.random.default_rng(3)
    codes = sorted(t.hists)
    for i in range(40):
        pick = list(rng.choice(codes, 8, replace=False))
        g = ("legend", "champion") if i % 2 else ("legend", "legend")
        fixed = {pick[1]: 300.0} if i % 3 == 0 else {}
        a = [Unit("F", c, g[0], fixed.get(c)) for c in pick[:4]]
        b = [Unit("S", c, g[1]) for c in pick[4:]]
        mc = speed.first_mover(t, a + b, n=40000)["sides"]["F"]
        assert calc.prob(a, b, g) == pytest.approx(mc, abs=0.02), (pick, g, fixed)


def test_first_calc_rules_and_placeholders():
    t = _calc_table()
    calc = speed.FirstCalc(t)
    slow = lambda side: [Unit(side, f"h{i}", "legend", 120) for i in range(3)]  # noqa: E731
    zio = calc.prob([Unit("F", "c1133", "legend", 240), *slow("F")], [Unit("S", "top", "legend", 300), *slow("S")])
    assert zio == pytest.approx(1.0, abs=1e-3)  # 智武开局 +30%：240 速能赢 300 速
    harsetti = calc.prob([Unit("F", "c1153", "legend", 150), *slow("F")], [Unit("S", "top", "legend", 330), *slow("S")])
    assert harsetti > 0.95  # 赫尔赛蒂把别人限速到她的 90% 以下
    assert calc.prob([], [], ("legend", "legend")) == pytest.approx(0.5, abs=1e-6)  # 都是占位：一半一半
    # 段位高的占位更快：快的一方先动概率 > 一半
    assert calc.prob([], [], ("legend", "champion")) > 0.5
    # 按选取次数加权的占位：只选很快的英雄 → 空位比官方合计的「平均英雄」快
    fast = speed.FirstCalc(t, weights={"top": 10})
    one_top = [Unit("F", "top", "legend")]
    assert fast.prob(one_top, [], ("legend", "legend")) < calc.prob(one_top, [], ("legend", "legend")) - 0.2
    # 第几手的占位：第 1 手全是 top、之后全是 h0（慢）→ 已经选了第 1 手的一方补上的占位慢
    slots = speed.FirstCalc(t, weights={"h0": 1}, slot_weights=[{"top": 1}, {"h0": 1}, {"h0": 1}, {"h0": 1}, {"h0": 1}])
    f = slots.fills("legend")
    assert f.shape == (speed.TEAM + 1, len(speed.GRID)) and np.allclose(f[speed.TEAM], 0)
    assert np.allclose(f[0] - f[1], slots._mixture({"top": 1.0}, "legend", None))
    one_each = slots.prob([Unit("F", "h1", "legend")], [Unit("S", "h1", "legend")], ("legend", "legend"))
    assert one_each == pytest.approx(0.5, abs=1e-6)
    assert slots.prob([Unit("F", "h1", "legend")], [], ("legend", "legend")) < 0.5  # 对方还有第 1 手（快）没选


def test_prob_batch_matches_single():
    t = _calc_table()
    calc = speed.FirstCalc(t, weights={c: 1 + i for i, c in enumerate(sorted(t.hists))})
    names = [None, None, *sorted(t.hists)]
    rng = np.random.default_rng(5)
    rows_a = np.zeros((30, 5), dtype=np.int64)
    rows_b = np.zeros((30, 5), dtype=np.int64)
    for r in range(30):
        ids = rng.choice(np.arange(2, len(names)), 10, replace=False)
        na, nb = int(rng.integers(0, 6)), int(rng.integers(0, 5))
        rows_a[r, :na], rows_b[r, :nb] = ids[:na], ids[5:5 + nb]
    rows_a[0, :2] = [names.index("c1153"), names.index("h3")]  # 有限速英雄的行
    rows_b[1, :1] = [names.index("c1153")]
    g = ("legend", "champion")
    speeds = ({"h2": 310.0}, None)
    got = calc.prob_batch(rows_a, rows_b, names, g, speeds)
    for r in range(30):
        a = [Unit("F", names[i], None, speeds[0].get(names[i])) for i in rows_a[r] if i]
        b = [Unit("S", names[i]) for i in rows_b[r] if i]
        assert got[r] == pytest.approx(calc.prob(a, b, g), abs=1e-9)


def test_state_and_match_first_probs():
    from rta_fakes import synthetic_dataset

    ds = synthetic_dataset(n=60, heroes=40)
    t = SpeedTable.from_hists({f"c{i}": {"legend": one_bin(i % 10)} for i in range(40)}, jitter=5.0)
    calc = speed.FirstCalc(t, slot_weights=speed.slot_counts(ds.tokens, ds.codes))
    got = speed.match_first_probs(calc, ds.tokens, ds.codes, ds.grades)
    assert got.shape == (60, 12) and ((got >= 0) & (got <= 1)).all()
    for row in (0, 7, 33):
        states = [ds.state(row, n) for n in range(12)]
        assert np.allclose(speed.state_first_probs(calc, states), got[row], atol=1e-9)
    # 后禁前 5 名都在：对 4 × 4 种被禁的情况平均；后禁后只剩上场的 4 名
    st = ds.state(0, 10)
    opts = [(f, s) for f in speed._side_options(st.picks["F"], None) for s in speed._side_options(st.picks["S"], None)]
    assert len(opts) == 16 and all(len(f) == len(s) == 4 for f, s in opts)
    assert all(st.picks["F"][2] in f for f, _ in opts)  # 保护位不会被禁
    counts = speed.slot_counts(ds.tokens, ds.codes)
    assert len(counts) == 5 and sum(counts[0].values()) == 2 * len(ds)


def test_first_pair_uses_typical_player_as_reference():
    from rta_fakes import synthetic_dataset

    ds = synthetic_dataset(n=10, heroes=40)
    t = SpeedTable.from_hists({f"c{i}": {"legend": one_bin(i % 10), "champion": one_bin(max(i % 10 - 2, 0))}
                               for i in range(40)}, jitter=5.0)
    calc = speed.FirstCalc(t)
    states = [encode.DraftState.from_dict({**ds.state(2, n).to_dict(), "grades": ["legend", "champion"]}) for n in (3, 11)]
    first, ref = speed.first_pair(calc, states, {"F": {"c5": 350}})
    assert np.allclose(first, speed.state_first_probs(calc, states, {"F": {"c5": 350}}))
    plain = [encode.DraftState.from_dict({**st.to_dict(), "grades": [None, None]}) for st in states]
    assert np.allclose(ref, speed.state_first_probs(calc, plain))
    assert states[0].grades == ("legend", "champion")  # 原来的局面不动


def test_ids_first_probs_matches_states():
    """B14g2 搜索用的：按编号一批算各局面的先动概率 = 逐个局面算的（含限速、开局加行动条、后禁、5 名都在时平均、填的速度）。"""
    from rta_fakes import synthetic_dataset

    ds = synthetic_dataset(n=40, heroes=40)
    hists = {f"c{i}": {"legend": one_bin(i % 10), "champion": one_bin(max(i % 10 - 2, 0))} for i in range(40)}
    t = SpeedTable.from_hists(hists, jitter=5.0, rules={"c3": {"cap": 0.9}, "c4": {"push": 30.0}})
    calc = speed.FirstCalc(t, weights={c: 1 for c in ds.codes}, slot_weights=speed.slot_counts(ds.tokens, ds.codes))
    codes = [None, *ds.codes]  # 行号 = token + 1，0 = 空位
    ids = ds.tokens.astype(np.int64) + 1
    g = ("legend", "champion")
    got = speed.ids_first_probs(calc, ids, list(range(12)), codes, g, ({"c5": 350.0}, None))
    assert got.shape == (40, 12)
    for row in range(0, 40, 3):
        states = [encode.DraftState.from_dict({**ds.state(row, n).to_dict(), "grades": list(g)}) for n in range(12)]
        assert np.allclose(got[row], speed.state_first_probs(calc, states, {"F": {"c5": 350.0}}), atol=1e-9), row
    # 只要部分局面、顺序随意也一样；同一阵容（顺序不同）只算一次，结果一样
    assert np.allclose(speed.ids_first_probs(calc, ids, [11, 5], codes, g, ({"c5": 350.0}, None)), got[:, [11, 5]])
    # 搜索用的快速档（网格每档 4、限速 4 档、float32）和默认差不到 0.5 个百分点
    fast = speed.FirstCalc(t, weights={c: 1 for c in ds.codes}, slot_weights=speed.slot_counts(ds.tokens, ds.codes),
                           **speed.FAST)
    approx = speed.ids_first_probs(fast, ids, list(range(12)), codes, g, ({"c5": 350.0}, None))
    assert np.abs(approx - got).max() < 0.005
    tab = fast.tables(codes, "legend")
    assert tab.dtype == np.float32 and not tab.flags.writeable  # 缓存的表不能改
    assert fast.tables(codes, "legend") is tab
