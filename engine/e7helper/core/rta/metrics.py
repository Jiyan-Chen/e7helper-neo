"""RTA 模型的评估指标（B14b），只依赖 numpy：训练时的验证、`rta eval` 的对比表和测试都用这一份。"""

from __future__ import annotations

import numpy as np

EPS = 1e-7


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(np.asarray(p, dtype=np.float64), EPS, 1 - EPS)
    y = np.asarray(y, dtype=np.float64)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, dtype=np.float64) - np.asarray(y, dtype=np.float64)) ** 2))


def auc(p: np.ndarray, y: np.ndarray) -> float:
    """ROC AUC（秩和公式，并列取平均秩）；只有一类时返回 nan。"""
    p = np.asarray(p, dtype=np.float64)
    y = np.asarray(y).astype(bool)
    pos, neg = int(y.sum()), int((~y).sum())
    if not pos or not neg:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    sorted_p = p[order]
    ranks = np.empty(len(p), dtype=np.float64)
    # 并列的一段取平均秩
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_p)) + 1]
    ends = np.r_[starts[1:], len(p)]
    avg = (starts + ends + 1) / 2.0  # 秩从 1 开始：(start+1 + end) / 2
    ranks[order] = np.repeat(avg, ends - starts)
    return float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * neg))


def calibration(p: np.ndarray, y: np.ndarray, bins: int = 15) -> list[dict]:
    """等宽分档的校准表：每档的场数、平均预测、实际胜率（空档省略）。"""
    p = np.asarray(p, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    out = []
    for b in range(bins):
        sel = idx == b
        n = int(sel.sum())
        if n:
            out.append({"lo": b / bins, "hi": (b + 1) / bins, "n": n, "pred": float(p[sel].mean()),
                        "actual": float(y[sel].mean())})
    return out


def ece(p: np.ndarray, y: np.ndarray, bins: int = 15) -> float:
    """期望校准误差：各档 |平均预测 − 实际胜率| 按场数加权。"""
    total = len(p)
    return float(sum(row["n"] * abs(row["pred"] - row["actual"]) for row in calibration(p, y, bins)) / total) if total else 0.0


def win_metrics(p: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {"n": int(len(p)), "log_loss": log_loss(p, y), "brier": brier(p, y), "auc": auc(p, y), "ece": ece(p, y)}


def pick_metrics(probs: np.ndarray, targets: np.ndarray, weights: np.ndarray, ks: tuple[int, ...] = (1, 5, 8)) -> dict:
    """选人指标。probs [n, V]（已屏蔽不可选的），targets / weights [n, 2]（权重 0 的不算；两手回合两名各 0.5）。

    命中前 k = 实际选的英雄落在预测前 k 名里的比例（按权重）；交叉熵 = −Σ 权重 × log p。
    """
    probs = np.asarray(probs, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    total = w.sum()
    rows = np.arange(len(probs))[:, None]
    p_t = probs[rows, targets]
    out: dict[str, float] = {"n": int(len(probs)), "ce": float(-(w * np.log(np.maximum(p_t, EPS))).sum() / total)}
    # 目标的名次 = 概率比它大的英雄个数（分块算，避免 [n, 2, V] 太大）
    rank = np.empty(p_t.shape, dtype=np.int64)
    for s in range(0, len(probs), 8192):
        rank[s:s + 8192] = (probs[s:s + 8192, None, :] > p_t[s:s + 8192, :, None]).sum(axis=2)
    for k in ks:
        out[f"top{k}"] = float((w * (rank < k)).sum() / total)
    return out
