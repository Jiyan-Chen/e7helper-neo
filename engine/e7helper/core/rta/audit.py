"""选秀推荐的验收统计（B14c，开发用，`e7helper rta audit`）：要训练快照，只看测试期（最后 7 天）双方 ≥ 优胜者的对局。

- `rare_check`：真实对局每个回合开头，让轮到的一方跑 advise：推荐第一名 / 前 8 名里有没有冷门英雄（训练时被选
  < 1000 次）、这一手的常见度、用时；对照真实玩家在同样局面实际选的。
- `selfplay`：我方每手按推荐第一名、对手按选人头抽（前 8 名），预禁 / 后禁双方都按各自的推荐；看最终胜率会不会推到
  极端。`greedy` 是对照组：B14b 那种不筛候选的一层贪心。
- `follow_check`：用切分模型（没见过测试期）当推荐器，看真实对局里实际选的正好在推荐前 8 名里的那一方，
  「实际胜率 − 选之前的模型胜率」是不是不低于没选推荐的那一方（推荐有没有钻模型的空子）。

B14g2：胜率一律和搜索同一口径（`Advisor.win`：按先动概率混合；快照的段位是赛后的，只影响先动概率）。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from . import encode, rules, sim
from .dataset import Dataset
from .search import Advisor, other

TURN_STARTS = [n for n in range(encode.N_PICKS) if n == 0 or rules.mover(n) != rules.mover(n - 1)]  # 0 1 3 5 7 9
Progress = Callable[[str, int, int], None] | None


def test_rows(ds: Dataset, k: int, rng: np.random.Generator) -> np.ndarray:
    sp = ds.split()
    test = sp["test"][ds.champion_plus()[sp["test"]]]
    return rng.choice(test, min(k, len(test)), replace=False)


def actual_move(ds: Dataset, row: int, n: int) -> list[str]:
    """第 row 场在已选 n 手时，轮到的一方这一轮实际选的英雄。"""
    k = rules.left_in_turn(n)
    return [ds.codes[int(i)] for i in ds.tokens[row, encode.PICK_POS + n:encode.PICK_POS + n + k]]


def _pct(xs, q) -> float:
    return float(np.percentile(xs, q)) if len(xs) else float("nan")


def rare_check(adv: Advisor, ds: Dataset, rows: np.ndarray, budget: float, progress: Progress = None) -> dict:
    rare = adv.cfg.rare_picks
    recs = []
    for i, row in enumerate(rows):
        for n in TURN_STARTS:
            st = ds.state(int(row), n)
            side = rules.mover(n)
            t = time.perf_counter()
            out = adv.advise(st, side, budget=budget)
            dt = time.perf_counter() - t
            prior = adv.model.evaluate([st]).picks[0]
            real = actual_move(ds, int(row), n)
            top = out["recommend"]
            recs.append({
                "n": n, "seconds": dt, "truncated": out["stats"]["truncated"], "depth": out["stats"]["depth"],
                "top1_rare": bool(top and top[0]["rare"]), "top8_rare": any(r["rare"] for r in top),
                "top1_common": min(top[0]["common"]) if top else float("nan"),
                "top1_uncertain": bool(top and top[0].get("uncertain")),
                "top1_win": top[0]["win"] if top else float("nan"), "now": out["win"],
                "real_rare": any(adv.priors.pick_count(c) < rare for c in real),
                "real_common": min(float(prior[adv.model.vocab.hero(c)]) for c in real),
            })
        if progress:
            progress("冷门比例 / 用时", i + 1, len(rows))
    # 预禁用时：每个局面先清掉缓存（很多对局的段位 / 规则一样）
    pre = {"known": [], "unknown": []}
    for i, row in enumerate(rows[:20]):
        grades, rule, cat = _context(ds, int(row))
        for label, side in (("known", rules.SIDES[i % 2]), ("unknown", None)):
            adv.clear_cache()
            t = time.perf_counter()
            adv.preban(side, grades=grades, rule=rule, rule_category=cat)
            pre[label].append(time.perf_counter() - t)
    sec = np.array([r["seconds"] for r in recs])
    by_n = {}
    for n in TURN_STARTS:
        s = np.array([r["seconds"] for r in recs if r["n"] == n])
        by_n[n] = {"p50": _pct(s, 50), "p95": _pct(s, 95), "max": float(s.max())}
    mean = lambda k: float(np.mean([r[k] for r in recs]))  # noqa: E731
    tc = np.array([r["top1_common"] for r in recs])
    rc = np.array([r["real_common"] for r in recs])
    return {
        "states": len(recs), "matches": len(rows), "budget": budget,
        "seconds": {"p50": _pct(sec, 50), "p95": _pct(sec, 95), "max": float(sec.max()), "by_n": by_n},
        "truncated": mean("truncated"), "depth3": float(np.mean([r["depth"] >= 3 for r in recs])),
        "top1_rare": mean("top1_rare"), "top8_rare": mean("top8_rare"), "real_rare": mean("real_rare"),
        "top1_common": {"median": _pct(tc, 50), "below_0.5%": float((tc < 0.005).mean()), "below_1%": float((tc < 0.01).mean())},
        "real_common": {"median": _pct(rc, 50), "below_0.5%": float((rc < 0.005).mean()), "below_1%": float((rc < 0.01).mean())},
        "top1_uncertain": mean("top1_uncertain"),
        "preban_seconds": {k: {"p50": _pct(v, 50), "p95": _pct(v, 95), "max": float(max(v))} for k, v in pre.items() if v},
        "top1_gain": float(np.mean([r["top1_win"] - r["now"] for r in recs])),
    }


def sample_preban(adv: Advisor, role: str, rng: np.random.Generator) -> list[str]:
    pairs = adv.priors.preban_pairs(role)[:100]
    p = np.array([s for _, s in pairs])
    return list(pairs[int(rng.choice(len(pairs), p=p / p.sum()))][0])


def _context(ds: Dataset, row: int) -> tuple[tuple[str | None, str | None], str | None, str | None]:
    st = ds.state(row, 0)
    return st.grades, st.rule, st.rule_category


def _play(adv: Advisor, ds: Dataset, row: int, side: str, rng: np.random.Generator, greedy: bool) -> dict:
    """一局：我方 side 按推荐（greedy = 不筛候选的一层贪心）、对手按选人头抽。返回每一手之后我方的胜率。"""
    m = adv.model
    grades, rule, cat = _context(ds, row)
    foe = other(side)
    mine_g, theirs_g = (grades if side == "F" else grades[::-1])
    if greedy:
        my_pre = sample_preban(adv, side, rng)
    else:
        my_pre = adv.preban(side, grades=(mine_g, theirs_g), rule=rule, rule_category=cat)["recommend"][0]["heroes"]
    st = encode.DraftState(prebans={side: list(my_pre), foe: sample_preban(adv, foe, rng)}, grades=grades, rule=rule,
                           rule_category=cat)
    curve = []
    while st.n_picks < encode.N_PICKS:
        n = st.n_picks
        mover = rules.mover(n)
        if mover == side:
            if greedy:
                code = sim.suggest(m, st, side, k=1, min_common=0.0, keep_top=10 ** 6)[0].code
                st = sim.with_pick(st, side, code)
            else:
                out = adv.advise(st, side)
                for code in out["recommend"][0]["heroes"]:
                    st = sim.with_pick(st, side, code)
        else:
            code, _ = sim.opponent_pick(m, st, rng)
            st = sim.with_pick(st, mover, code)
        curve.append(float(sim.my_win(adv.win([st])[0], side)))
    if greedy:
        rows_, cols, mat = sim.ban_matrix(m, st, side)
        mine_ban = rows_[sim.maximin_row(mat)]
    else:
        ban = adv.advise(st, side)["ban"]
        rows_, cols, mat = ban["rows"], ban["cols"], np.array(ban["matrix"])
        mine_ban = ban["recommend"]
    theirs_ban = cols[sim.minimax_col(np.asarray(mat))]  # 对手按对它最稳妥的禁
    st = sim.with_bans(st, {foe: mine_ban, side: theirs_ban})
    final = float(sim.my_win(adv.win([st])[0], side))
    rare = sum(1 for c in st.picks[side] if adv.priors.pick_count(c) < adv.cfg.rare_picks)
    lineup = {"prebans": st.prebans, "picks": st.picks, "banned": st.banned}
    return {"final": final, "curve": curve, "rare": rare, "side": side, "lineup": lineup}


def _summary(games: list[dict]) -> dict:
    f = np.array([g["final"] for g in games])
    return {"games": len(games), "median": _pct(f, 50), "mean": float(f.mean()), "p95": _pct(f, 95), "max": float(f.max()),
            "min": float(f.min()), "ge90": int((f >= 0.9).sum()), "ge95": int((f >= 0.95).sum()),
            "rare_heroes_per_game": float(np.mean([g["rare"] for g in games])),
            "by_side": {s: _pct([g["final"] for g in games if g["side"] == s], 50) for s in rules.SIDES}}


def selfplay(adv: Advisor, ds: Dataset, rows: np.ndarray, seed: int, progress: Progress = None) -> dict:
    out = {}
    for label, greedy in (("advise", False), ("greedy", True)):
        games = []
        for i, row in enumerate(rows):
            rng = np.random.default_rng(seed + i)  # 两组用同样的种子（对手的预禁一样）
            games.append(_play(adv, ds, int(row), rules.SIDES[i % 2], rng, greedy))
            if progress:
                progress("自对弈" if not greedy else "对照：不筛的一层贪心", i + 1, len(rows))
        out[label] = _summary(games)
        if not greedy:  # 按推荐的每局阵容都留着（看胜率高的那几局是什么阵容）
            out[label]["lineups"] = [{k: g[k] for k in ("side", "final", "lineup")} for g in games]
    return out


def follow_check(adv: Advisor, ds: Dataset, rows: np.ndarray, budget: float, progress: Progress = None) -> dict:
    """adv 应该用切分模型（没见过测试期）。每一手记三样（都是这一手出手方的视角）：实际胜负 − 选之前的模型胜率
    （实际兑现的提升）、模型对这一手的原始提升（选之后 − 选之前）、推荐里这一项的提升（`now` − 选之前，扣过高估的）。"""
    groups: dict[str, list[tuple[float, float, float]]] = {"in_top8": [], "not_in_top8": [], "top1": [], "all": []}
    for i, row in enumerate(rows):
        for n in TURN_STARTS:
            st = ds.state(int(row), n)
            side = rules.mover(n)
            out = adv.advise(st, side, budget=budget)
            real = frozenset(actual_move(ds, int(row), n))
            sets = [frozenset(r["heroes"]) for r in out["recommend"]]
            won = float(ds.first_wins[row] == (1 if side == "F" else 0))
            after = float(sim.my_win(adv.win([ds.state(int(row), n + rules.left_in_turn(n))])[0], side))
            raw = after - out["win"]
            rec = out["recommend"][sets.index(real)] if real in sets else None
            item = (won - out["win"], raw, (rec["now"] - out["win"]) if rec else float("nan"))
            groups["all"].append(item)
            groups["in_top8" if rec else "not_in_top8"].append(item)
            if sets and real == sets[0]:
                groups["top1"].append(item)
        if progress:
            progress("跟着推荐（切分模型）", i + 1, len(rows))

    def stat(xs):
        a = np.array(xs, dtype=np.float64).reshape(-1, 3)
        if not len(a):
            return {"n": 0}
        real, raw, adj = a[:, 0], a[:, 1], a[:, 2]
        se = float(real.std() / np.sqrt(len(a))) if len(a) > 1 else float("nan")
        out = {"n": len(a), "real_gain": float(real.mean()), "se": se, "model_gain": float(raw.mean()),
               "realized": float(real.mean() / raw.mean()) if abs(raw.mean()) > 1e-6 else float("nan")}
        if np.isfinite(adj).all():  # 只有实际选的在推荐里时才有「推荐给的提升」
            out["advised_gain"] = float(np.nanmean(adj))
            out["realized_advised"] = float(real.mean() / np.nanmean(adj)) if abs(np.nanmean(adj)) > 1e-6 else float("nan")
        return out

    return {**{k: stat(v) for k, v in groups.items()}, "budget": budget}
