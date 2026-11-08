"""B14b：随包的 RTA 模型（assets/data/rta/）能加载、和 parity 样例一致、推理够快（不需要 torch）。"""

import time

import numpy as np
import pytest

from e7helper.core.rta import encode
from e7helper.core.rta import model as rmodel

pytestmark = pytest.mark.skipif(not rmodel.available(), reason="还没有随包模型")


def test_bundled_model_loads_and_matches_parity():
    m = rmodel.load()
    assert m.meta["kind"] in ("transformer", "hybrid") and m.vocab.size > 200
    res = m.check()
    assert res["ok"], res
    assert m.load_seconds < 1.0


def test_bundled_model_size():
    total = sum(p.stat().st_size for p in rmodel.bundled_dir().iterdir() if p.is_file())
    assert total < 5 * 1024 * 1024


def test_bundled_model_speed():
    m = rmodel.load()
    rng = np.random.default_rng(0)
    heroes = rng.integers(encode.FIRST_HERO, m.vocab.size, (256, encode.SEQ_LEN))
    ctx = np.zeros((256, 3), dtype=np.int64)
    m.run(heroes, ctx)
    times = []
    for _ in range(5):
        t = time.perf_counter()
        m.run(heroes, ctx)
        times.append(time.perf_counter() - t)
    assert min(times) < 0.05  # 取最快的一次（机器忙时中位数会抖），一批 256 场 ≤ 50 ms（B14b 审核时用户同意从 30 ms 放宽，d = 128 实测约 45 ms）


def test_empty_draft_is_close_to_even():
    m = rmodel.load()
    st = encode.DraftState(grades=("legend", "legend"))
    p = m.win([st])[0]
    assert 0.4 < p < 0.6
    top = m.next_picks(st, k=8)
    assert len(top) == 8 and sum(q for _, q in top) < 1


def test_effective_first_and_mix():
    """B14g1：混合用的先动概率 = 速度表按段位的 + 模型隐含的（按两种胜率差加权）；一般玩家时混合 ≈「不知道」的头。"""
    import math

    from e7helper.core.rta import model as rmodel

    heads = np.array([[0.70, 0.30, 0.62],  # 差 40 点：模型隐含先手方先动 q = 0.8
                      [0.51, 0.50, 0.505]])  # 差 1 点：谁先动几乎无所谓
    logit = lambda p: math.log(p / (1 - p))  # noqa: E731
    w0, w1 = 0.16 / (0.16 + 0.01), 1e-4 / (1e-4 + 0.01)
    f = rmodel.effective_first(heads, [0.5, 0.3], [0.5, 0.3])  # 双方一般玩家
    assert f[0] == pytest.approx(1 / (1 + math.exp(-w0 * logit(0.8))), abs=1e-6)
    assert f[1] == pytest.approx(1 / (1 + math.exp(-(logit(0.3) + w1 * (0 - logit(0.3))))), abs=1e-6)  # 差小：基本是速度表
    m = rmodel.mix(heads, [0.5, 0.3], [0.5, 0.3])
    assert m[0] == pytest.approx(0.62, abs=0.01)  # ≈「不知道」的头
    # 段位高（速度表 0.9 vs 一般玩家 0.5）：在模型隐含的 0.8 上再加这个变化量
    hi = rmodel.effective_first(heads[:1], 0.9, 0.5)[0]
    assert hi == pytest.approx(1 / (1 + math.exp(-(logit(0.9) + w0 * logit(0.8)))), abs=1e-6) and hi > 0.95
    assert rmodel.mix(heads[:1], 0.9, 0.5)[0] == pytest.approx(hi * 0.7 + (1 - hi) * 0.3)
    # 不给 ref = 直接用 first；不给 first = 「不知道」的头
    assert np.allclose(rmodel.mix(heads, 0.25), 0.25 * heads[:, 0] + 0.75 * heads[:, 1])
    assert np.allclose(rmodel.mix(heads, None), heads[:, 2])
