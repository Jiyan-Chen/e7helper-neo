"""B14c：验收统计（`rta audit`）能在合成快照 + 假模型上算出来（不看数值好坏，只看各项都在、范围对）。"""

import numpy as np

from e7helper.core.rta import audit, search
from rta_fakes import FakeModel, fake_priors, synthetic_dataset


def _setup():
    ds = synthetic_dataset(n=400, heroes=30)
    strength = {f"c{i}": (1.0 if i < 3 else 0.1 * (i % 5)) for i in range(30)}
    model = FakeModel(strength, {c: 0.0 for c in strength})
    pre = {"F": [["c3", "c4", 10], ["c5", "c6", 5]], "S": [["c7", "c8", 10], ["c9", "c10", 5]]}
    adv = search.Advisor(model, fake_priors({c: 5000 for c in strength} | {"c29": 10}, preban=pre))
    rows = audit.test_rows(ds, 2, np.random.default_rng(0))
    return ds, adv, rows


def test_turn_starts_and_actual_move():
    assert audit.TURN_STARTS == [0, 1, 3, 5, 7, 9]
    ds, _, rows = _setup()
    r = int(rows[0])
    assert len(audit.actual_move(ds, r, 1)) == 2 and len(audit.actual_move(ds, r, 9)) == 1
    assert audit.actual_move(ds, r, 0) == [ds.codes[int(ds.tokens[r, 5])]]


def test_rare_check():
    ds, adv, rows = _setup()
    r = audit.rare_check(adv, ds, rows, budget=1.0)
    assert r["states"] == 12 and r["matches"] == 2
    for k in ("top1_rare", "top8_rare", "real_rare", "truncated", "depth3", "top1_uncertain"):
        assert 0 <= r[k] <= 1
    assert r["seconds"]["p95"] >= r["seconds"]["p50"] > 0 and set(r["seconds"]["by_n"]) == set(audit.TURN_STARTS)
    assert set(r["preban_seconds"]) == {"known", "unknown"}


def test_selfplay_and_greedy():
    ds, adv, rows = _setup()
    sp = audit.selfplay(adv, ds, rows, seed=0)
    for label in ("advise", "greedy"):
        v = sp[label]
        assert v["games"] == 2 and 0 <= v["min"] <= v["median"] <= v["max"] <= 1
    lu = sp["advise"]["lineups"]
    assert len(lu) == 2 and all(len(g["lineup"]["picks"][s]) == 5 and g["lineup"]["banned"][s] for g in lu for s in "FS")


def test_follow_check():
    ds, adv, rows = _setup()
    f = audit.follow_check(adv, ds, rows, budget=0.5)
    assert f["all"]["n"] == 12 and f["in_top8"].get("n", 0) + f["not_in_top8"].get("n", 0) == 12
    assert -1 <= f["all"]["real_gain"] <= 1
