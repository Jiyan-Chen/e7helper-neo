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
