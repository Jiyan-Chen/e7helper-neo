"""RTA 模型的评估（B14b）：批量推理、胜率指标（按局面 / 子集）、选人指标（对比热度基线）、温度缩放。"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import torch

from .. import encode, metrics
from ..model import calibrate
from . import nets

TOPK = (1, 5, 8)


def popularity(heroes: np.ndarray, size: int) -> np.ndarray:
    """热度基线：训练集里每个局面 n 下一手选各名英雄的次数（加 1 平滑），[10, V]。"""
    pop = np.ones((encode.N_PICKS, size))
    for n in range(encode.N_PICKS):
        for pos, w in encode.pick_targets(n):
            pop[n] += w * np.bincount(heroes[:, pos], minlength=size)
    pop[:, :encode.FIRST_HERO] = 0
    return pop


class PickStats:
    """按局面累计选人指标：权重和、交叉熵和、命中前 k 的权重和。"""

    def __init__(self):
        self.w = np.zeros(encode.N_PICKS)
        self.ce = np.zeros(encode.N_PICKS)
        self.hits = {k: np.zeros(encode.N_PICKS) for k in TOPK}

    def add(self, probs: torch.Tensor, tgt: torch.Tensor, w: torch.Tensor) -> None:
        """probs [B, 10, V]（已屏蔽、已归一）、tgt [B, 10, 2]、w [10, 2]。"""
        p_t = probs.gather(2, tgt)  # [B, 10, 2]
        rank = (probs.unsqueeze(2) > p_t.unsqueeze(-1)).sum(-1)  # [B, 10, 2]
        ww = w.expand_as(p_t)
        self.w += ww.sum((0, 2)).double().cpu().numpy()
        self.ce += (-(ww * torch.log(p_t.clamp_min(1e-12)))).sum((0, 2)).double().cpu().numpy()
        for k in TOPK:
            self.hits[k] += (ww * (rank < k)).sum((0, 2)).double().cpu().numpy()

    def summary(self) -> dict:
        total = self.w.sum()
        out = {"ce": float(self.ce.sum() / total), **{f"top{k}": float(self.hits[k].sum() / total) for k in TOPK}}
        out["per_state"] = [{"ce": float(self.ce[n] / self.w[n]), **{f"top{k}": float(self.hits[k][n] / self.w[n])
                                                                    for k in TOPK}} for n in range(encode.N_PICKS)]
        return out


@torch.no_grad()
def infer(model: torch.nn.Module, heroes: np.ndarray, ctx: np.ndarray, size: int, *, device: str = "cpu",
          batch: int = 4096, pop: np.ndarray | None = None) -> dict:
    """整份数据推理：win [N, 12] 的 logit；有选人头 / 给了热度表时返回选人指标。"""
    model.eval()
    wins = []
    picks, pops = PickStats(), PickStats()
    pop_t = torch.as_tensor(pop, dtype=torch.float32, device=device) if pop is not None else None
    for s in range(0, len(heroes), batch):
        h = torch.as_tensor(heroes[s:s + batch], device=device)
        c = torch.as_tensor(ctx[s:s + batch], device=device)
        win, pick = model.predict(h, c)
        wins.append(win.float().cpu().numpy())
        if pick is None and pop_t is None:
            continue
        avail = nets.pick_available(h, size)
        tgt, w = nets.pick_targets(h)
        if pick is not None:
            picks.add(torch.softmax(pick.float().masked_fill(~avail, nets.NEG), dim=-1), tgt, w)
        if pop_t is not None:
            p = pop_t.unsqueeze(0) * avail
            pops.add(p / p.sum(-1, keepdim=True), tgt, w)
    out = {"win": np.concatenate(wins) if wins else np.zeros((0, encode.N_STATES))}
    if getattr(model, "has_pick", False):
        out["pick"] = picks.summary()
    if pop_t is not None:
        out["pop"] = pops.summary()
    return out


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def fit_calibration(logits: np.ndarray, y: np.ndarray) -> dict:
    """在一份数据（验证集）上给每个局面拟合 σ(a · logit + b)（Platt 缩放，牛顿法）。logits [N, 12]。

    比只调温度多一个截距：前几手模型偏自信、后禁后偏保守，有的模型在某个局面还整体偏向一方，温度修不了偏移。
    """
    scale, bias = [], []
    for n in range(logits.shape[1]):
        a, b = _platt(logits[:, n].astype(np.float64), y.astype(np.float64))
        scale.append(a)
        bias.append(b)
    return {"scale": scale, "bias": bias}


def _platt(z: np.ndarray, y: np.ndarray, iters: int = 30) -> tuple[float, float]:
    x = np.stack([z, np.ones_like(z)], axis=1)
    w = np.array([1.0, 0.0])
    for _ in range(iters):
        p = sigmoid(x @ w)
        g = x.T @ (p - y)
        h = x.T @ (x * (p * (1 - p))[:, None]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(h, g)
        w -= step
        if np.abs(step).max() < 1e-10:
            break
    return float(w[0]), float(w[1])


def win_report(win_logits: np.ndarray, y: np.ndarray, cal, subsets: dict[str, np.ndarray],
               states: tuple[int, ...] = tuple(range(encode.N_STATES))) -> dict:
    """每个子集、每个局面的胜率指标（按 cal 校准后）；subsets 是 名字 → 布尔掩码。"""
    p = calibrate(win_logits, np.arange(encode.N_STATES)[None, :], cal)
    out = {}
    for name, mask in subsets.items():
        if not mask.any():
            continue
        out[name] = {str(n): metrics.win_metrics(p[mask, n], y[mask]) for n in states}
    return out


def calibration_table(win_logits: np.ndarray, y: np.ndarray, cal, n: int = encode.POSTBAN,
                      bins: int = 10) -> list[dict]:
    return metrics.calibration(calibrate(win_logits[:, n], np.full(len(win_logits), n), cal), y, bins)


def subsets(ds, rows: np.ndarray, vocab: encode.Vocab) -> dict[str, np.ndarray]:
    """评估的子集：全部、双方 ≥ 优胜者、分服、分开战规则。"""
    from ..dataset import SERVERS

    out = {"all": np.ones(len(rows), dtype=bool), "champion+": ds.champion_plus()[rows]}
    for i, s in enumerate(SERVERS):
        out[s] = ds.server[rows] == i
    rule_ids = ds.rule_ids(vocab)[rows]
    names = {encode.RULE_NONE: "规则:无", encode.RULE_UNKNOWN: "规则:未知"}
    for i, (tid, _) in enumerate(vocab.rules):
        names[2 + i] = "规则:" + tid.removeprefix("rta_cs_").removesuffix("_desc")
    for rid, name in names.items():
        out[name] = rule_ids == rid
    return out


def evaluate_run(run: Path, ds, split: str = "test", device: str = "cpu") -> dict:
    """在快照的一份数据上评估一个 run（用 run 自己的词表和温度），结果写进 run/eval-<split>.json。"""
    from .fit import load_run

    model, vocab, ckpt = load_run(run, device)
    cfg = ckpt["config"]
    parts = ds.split(cfg["test_days"], cfg["val_days"])
    rows = parts[split]
    x = ds.encode(vocab, rows)
    pop = popularity(ds.encode(vocab, parts["train"])["heroes"], vocab.size)
    out = infer(model, x["heroes"], x["ctx"], vocab.size, device=device, pop=pop)
    t = ckpt.get("calibration")
    if t is None:
        if (run / "val_logits.npy").exists():
            # 早期的 run 只存了温度：用存下来的验证集 logit 按局面重新拟合
            t = fit_calibration(np.load(run / "val_logits.npy"), ds.encode(vocab, parts["val"])["y"])
        else:
            t = ckpt.get("temperature", 1.0)
    res = {"run": run.name, "split": split, "n": int(len(rows)), "calibration": t, "model": cfg["model"],
           "params": ckpt.get("params"), "epoch": ckpt.get("epoch"),
           "win": win_report(out["win"], x["y"], t, subsets(ds, rows, vocab)),
           "win_raw_n11": metrics.win_metrics(sigmoid(out["win"][:, encode.POSTBAN]), x["y"]),
           "calibration_n11": calibration_table(out["win"], x["y"], t),
           "pick": out.get("pick"), "pop": out.get("pop")}
    (run / f"eval-{split}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
