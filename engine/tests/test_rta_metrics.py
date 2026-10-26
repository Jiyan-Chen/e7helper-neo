"""B14b：RTA 模型的评估指标。"""

import math

import numpy as np

from e7helper.core.rta import metrics


def test_log_loss_and_brier():
    p, y = np.array([0.5, 0.8, 0.2]), np.array([1, 1, 0])
    assert math.isclose(metrics.log_loss(p, y), -(math.log(0.5) + 2 * math.log(0.8)) / 3)
    assert math.isclose(metrics.brier(p, y), (0.25 + 0.04 + 0.04) / 3)
    assert metrics.log_loss(np.array([0.0, 1.0]), np.array([0, 1])) < 1e-6  # 截断，不出 inf


def test_auc_matches_pairwise():
    rng = np.random.default_rng(0)
    p = np.round(rng.random(300), 1)  # 很多并列
    y = rng.random(300) < p
    pos, neg = p[y], p[~y]
    pairs = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    assert math.isclose(metrics.auc(p, y), pairs / (len(pos) * len(neg)))
    assert metrics.auc(np.array([0.1, 0.9]), np.array([0, 1])) == 1.0
    assert math.isnan(metrics.auc(np.array([0.3, 0.4]), np.array([1, 1])))


def test_calibration_and_ece():
    rng = np.random.default_rng(1)
    p = rng.random(200_000)
    y = rng.random(200_000) < p  # 完全校准
    assert metrics.ece(p, y) < 0.01
    assert metrics.ece(np.full(1000, 0.9), np.zeros(1000)) > 0.89
    table = metrics.calibration(np.array([0.05, 0.06, 0.95]), np.array([0, 1, 1]), bins=10)
    assert [(r["n"], r["actual"]) for r in table] == [(2, 0.5), (1, 1.0)]
    m = metrics.win_metrics(p[:100], y[:100])
    assert set(m) == {"n", "log_loss", "brier", "auc", "ece"} and m["n"] == 100


def test_pick_metrics():
    probs = np.array([[0.5, 0.3, 0.2, 0.0], [0.1, 0.2, 0.3, 0.4]])
    targets = np.array([[1, 0], [0, 3]])
    weights = np.array([[1.0, 0.0], [0.5, 0.5]])  # 第二行是两手回合
    m = metrics.pick_metrics(probs, targets, weights, ks=(1, 2))
    # 第一行目标排第 2；第二行两名分别排第 4、第 1
    assert m["top1"] == (0 + 0.5) / 2 and m["top2"] == (1 + 0.5) / 2
    assert math.isclose(m["ce"], -(math.log(0.3) + 0.5 * math.log(0.1) + 0.5 * math.log(0.4)) / 2)
