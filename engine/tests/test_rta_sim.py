"""B14b：模拟 BP（`rta sim`）用到的一层估算和后禁矩阵（用随包模型，不需要 torch）。"""

import numpy as np
import pytest

from e7helper.core.rta import encode, rules, sim
from e7helper.core.rta import model as rmodel
from rta_fakes import synthetic_dataset

pytestmark = pytest.mark.skipif(not rmodel.available(), reason="还没有随包模型")


@pytest.fixture(scope="module")
def m():
    return rmodel.load()


@pytest.fixture(scope="module")
def heroes(m):
    return m.vocab.heroes[:20]


def _draft(heroes, n):
    st = encode.DraftState(prebans={"F": heroes[:2], "S": heroes[2:4]}, grades=("emperor", "emperor"))
    rest = iter(heroes[4:])
    for k in range(n):
        st = sim.with_pick(st, rules.mover(k), next(rest))
    return st


@pytest.mark.parametrize("side", ["F", "S"])
def test_suggest(m, heroes, side):
    st = _draft(heroes, 3 if side == "F" else 1)  # 轮到 side
    assert rules.mover(st.n_picks) == side
    sugg = sim.suggest(m, st, side, k=8)
    assert len(sugg) == 8 and [s.win for s in sugg] == sorted((s.win for s in sugg), reverse=True)
    taken = set(st.prebans["F"] + st.prebans["S"] + st.picks["F"] + st.picks["S"])
    assert not taken & {s.code for s in sugg} and all(0 < s.win < 1 and 0 <= s.common <= 1 for s in sugg)
    # 和直接算的一致（换成我方视角）
    p = m.win([sim.with_pick(st, side, sugg[0].code)])[0]
    assert sugg[0].win == pytest.approx(p if side == "F" else 1 - p)


def test_with_pick_copies(heroes):
    st = _draft(heroes, 2)
    st2 = sim.with_pick(st, "F", heroes[10])
    assert st.picks["F"] == [heroes[4]] and st2.picks["F"] == [heroes[4], heroes[10]]


def test_opponent_pick(m, heroes):
    st = _draft(heroes, 1)
    rng = np.random.default_rng(0)
    top = dict(m.next_picks(st, 8))
    for _ in range(5):
        code, p = sim.opponent_pick(m, st, rng)
        assert code in top and p == pytest.approx(top[code]) and not sim.with_pick(st, "S", code).problems()


def test_ban_matrix(m, heroes):
    st = _draft(heroes, 10)
    rows, cols, mat = sim.ban_matrix(m, st, "S")
    assert rows == sim.bannable(st, "F") and cols == sim.bannable(st, "S")
    assert len(rows) == len(cols) == 4 and mat.shape == (4, 4)
    assert st.picks["F"][rules.PROTECTED_SLOT] not in rows and st.picks["S"][rules.PROTECTED_SLOT] not in cols
    p = m.win([sim.with_bans(st, {"F": rows[1], "S": cols[2]})])[0]
    assert mat[1, 2] == pytest.approx(1 - p)  # 我方是后手


def test_maximin():
    mat = np.array([[0.6, 0.4], [0.55, 0.5]])
    assert sim.maximin_row(mat) == 1  # 最坏 0.4 vs 0.5
    assert sim.minimax_col(mat) == 1  # 每列的最大 0.6 vs 0.5


def test_prebans(tmp_path):
    ds = synthetic_dataset(n=200)
    path = tmp_path / "ds.npz"
    ds.save(path)
    weights = sim.preban_weights(path)
    assert sum(n for _, n in weights) == 200 * 4 and weights[0][1] >= weights[-1][1]
    rng = np.random.default_rng(0)
    for _ in range(10):
        pre = sim.sample_prebans(weights, rng, top=10)
        assert len(pre) == 2 and len(set(pre)) == 2 and set(pre) <= {c for c, _ in weights[:10]}
