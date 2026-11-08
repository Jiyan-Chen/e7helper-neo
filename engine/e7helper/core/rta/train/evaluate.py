"""RTA 模型的评估（B14b）：批量推理、胜率指标（按局面 / 子集）、选人指标（对比热度基线）、温度缩放。

B14g 起胜率头分三种「谁先动」：评估同时给
- `win`：实际用的读数 = 按速度表算的先动概率混合先动 / 后动两种胜率（没有速度表时是「不知道」的头），全部对局；
- `win_unknown`：「不知道谁先动」的头，全部对局；
- `win_first` / `win_first_u`：知道谁先动的对局上，用实际先动方那个头 / 用「不知道」的头（看知道谁先动能好多少）；
- `first_gap`：先动 / 后动两种胜率的差按阵容的分布。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import torch

from .. import encode, metrics
from ..model import calibrate, calibrate_heads, effective_first, mix
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


def fit_calibration(logits: np.ndarray, y: np.ndarray, head: np.ndarray | None = None) -> dict:
    """在一份数据（验证集）上给每个局面拟合 σ(a · logit + b)（Platt 缩放，牛顿法）。logits [N, 12]。

    比只调温度多一个截距：前几手模型偏自信、后禁后偏保守，有的模型在某个局面还整体偏向一方，温度修不了偏移。
    B14g：logits [N, 12, 3] 时每个头一组 {"F": …, "S": …, "U": …}：先手方先动的头只用先手方先动的对局拟合，
    后手方的同理，「不知道」的头用全部对局（head 是每场的头编号，encode.first_heads）。
    """
    if logits.ndim == 3:
        out = {}
        for h, name in enumerate(encode.FIRST_HEADS):
            rows = np.ones(len(y), dtype=bool) if h == encode.HEAD_U or head is None else head == h
            if rows.sum() < 100:  # 几乎没有这种对局（合成数据）：用全部对局
                rows = np.ones(len(y), dtype=bool)
            out[name] = fit_calibration(logits[rows, :, h], y[rows])
        return out
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


def prob_report(p: np.ndarray, y: np.ndarray, subsets: dict[str, np.ndarray],
                states: tuple[int, ...] = tuple(range(encode.N_STATES))) -> dict:
    """每个子集、每个局面的胜率指标；p [N, 12] 是先手方赢的概率，subsets 是 名字 → 布尔掩码。"""
    out = {}
    for name, mask in subsets.items():
        if not mask.any():
            continue
        out[name] = {str(n): metrics.win_metrics(p[mask, n], y[mask]) for n in states}
    return out


def win_report(win_logits: np.ndarray, y: np.ndarray, cal, subsets: dict[str, np.ndarray],
               states: tuple[int, ...] = tuple(range(encode.N_STATES))) -> dict:
    """每个子集、每个局面的胜率指标（按 cal 校准后）；subsets 是 名字 → 布尔掩码。三个头的 logit 用「不知道」的头。"""
    grid = np.arange(encode.N_STATES)[None, :]
    p = calibrate_heads(win_logits, grid, cal)[..., encode.HEAD_U] if win_logits.ndim == 3 else calibrate(win_logits, grid, cal)
    return prob_report(p, y, subsets, states)


def calibration_table(win_logits: np.ndarray, y: np.ndarray, cal, n: int = encode.POSTBAN,
                      bins: int = 10) -> list[dict]:
    return metrics.calibration(calibrate(win_logits[:, n], np.full(len(win_logits), n), cal), y, bins)


def gap_stats(heads: np.ndarray, states: tuple[int, ...] = (encode.N_PICKS, encode.POSTBAN)) -> dict:
    """先动 / 后动两种胜率的差（先手方先动时先手方的胜率 − 后手方先动时的）按阵容的分布：每个局面的分位数、
    |差| ≥ 10 / 20 / 30 个百分点的比例。heads [N, 12, 3] 是校准后的概率。"""
    out = {}
    for n in states:
        d = heads[:, n, encode.HEAD_F] - heads[:, n, encode.HEAD_S]
        a = np.abs(d)
        out[str(n)] = {"mean": float(d.mean()), "abs_mean": float(a.mean()),
                       "q": {str(q): float(np.quantile(d, q)) for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)},
                       "abs_q": {str(q): float(np.quantile(a, q)) for q in (0.5, 0.9, 0.99)},
                       "ge10": float((a >= 0.10).mean()), "ge20": float((a >= 0.20).mean()), "ge30": float((a >= 0.30).mean())}
    return out


def subsets(ds, rows: np.ndarray, vocab: encode.Vocab) -> dict[str, np.ndarray]:
    """评估的子集：全部、双方 ≥ 优胜者、分服、分开战规则。"""
    from ..dataset import SERVERS

    out = {"all": np.ones(len(rows), dtype=bool), "champion+": ds.champion_plus()[rows]}
    for i, s in enumerate(SERVERS):
        out[s] = ds.server[rows] == i
    # B14g：战绩站的段位是赛后的，看段位的旧模型在段位不同的对局上占便宜（相差两档的段位高的一方全胜），分开看才公平
    gap = np.abs(ds.grades[rows, 0].astype(int) - ds.grades[rows, 1].astype(int))
    known = (ds.grades[rows] > 0).all(axis=1)
    out["段位:同档"] = known & (gap == 0)
    out["段位:差1档"] = known & (gap == 1)
    out["段位:差≥2档"] = known & (gap >= 2)
    rule_ids = ds.rule_ids(vocab)[rows]
    names = {encode.RULE_NONE: "规则:无", encode.RULE_UNKNOWN: "规则:未知"}
    for i, (tid, _) in enumerate(vocab.rules):
        names[2 + i] = "规则:" + tid.removeprefix("rta_cs_").removesuffix("_desc")
    for rid, name in names.items():
        out[name] = rule_ids == rid
    return out


def evaluate_run(run: Path, ds, split: str = "test", device: str = "cpu", speed_table=None) -> dict:
    """在快照的一份数据上评估一个 run（用 run 自己的词表和温度），结果写进 run/eval-<split>.json。
    B14g 的三头模型：speed_table（默认随包的速度表）用来算每场每个局面的先动概率，`win` 是混合后的读数。"""
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
    subs = subsets(ds, rows, vocab)
    res = {"run": run.name, "split": split, "n": int(len(rows)), "calibration": t, "model": cfg["model"],
           "params": ckpt.get("params"), "epoch": ckpt.get("epoch"), "pick": out.get("pick"), "pop": out.get("pop")}
    if out["win"].ndim == 3:  # B14g：三种「谁先动」
        res.update(first_report(out["win"], x, t, subs, ds, rows, first_calc(ds, parts["train"], speed_table)))
        first, ref = res.pop("first"), res.pop("first_ref")
        if first is not None:  # 每场每个局面的先动概率（和模型无关，分析脚本直接读，不用再算几分钟）
            np.save(run / f"eval-{split}-first.npy", first.astype(np.float32))
            np.save(run / f"eval-{split}-first-ref.npy", ref.astype(np.float32))
    else:
        res.update({"win": win_report(out["win"], x["y"], t, subs),
                    "win_raw_n11": metrics.win_metrics(sigmoid(out["win"][:, encode.POSTBAN]), x["y"]),
                    "calibration_n11": calibration_table(out["win"], x["y"], t)})
    (run / f"eval-{split}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def first_calc(ds, train_rows: np.ndarray, speed_table=None):
    """评估用的快速先动概率：速度表（默认随包的）+ 训练集里每名英雄 / 每一手的被选次数（占位用）；没有速度表返回 None。"""
    from .. import speed

    table = speed_table if speed_table is not None else speed.load()
    if table is None:
        return None
    tokens = ds.tokens[train_rows]
    return speed.FirstCalc(table, weights=dict(encode.pick_counts(tokens, ds.codes)),
                           slot_weights=speed.slot_counts(tokens, ds.codes))


def first_report(logits: np.ndarray, x: dict, cal, subs: dict[str, np.ndarray], ds, rows: np.ndarray, calc=None) -> dict:
    """三头模型（B14g）的胜率指标，见模块说明。先动概率按速度表、双方段位和每个局面的阵容算（`speed.match_first_probs`；
    calc 是 `first_calc` 的结果，None = 没有速度表，`win` 用「不知道」的头）。"""
    from .. import speed

    y, head = x["y"], x["head"]
    heads = calibrate_heads(logits, np.arange(encode.N_STATES)[None, :], cal)  # [N, 12, 3]
    first = ref = None
    if calc is not None:  # 按双方段位的先动概率，和同一阵容按一般玩家（不知道段位）的（effective_first 用两者的差）
        first = speed.match_first_probs(calc, ds.tokens[rows], ds.codes, ds.grades[rows])
        ref = speed.match_first_probs(calc, ds.tokens[rows], ds.codes, np.zeros_like(ds.grades[rows]))
    p = mix(heads, first, ref)
    known = head < encode.HEAD_U
    oracle = np.where(head[:, None] == encode.HEAD_F, heads[..., encode.HEAD_F], heads[..., encode.HEAD_S])
    ksubs = {k: m & known for k, m in subs.items()}
    out = {"mix": "speed" if first is not None else "unknown", "first": first, "first_ref": ref,
           "win": prob_report(p, y, subs), "win_unknown": prob_report(heads[..., encode.HEAD_U], y, subs),
           "win_first": prob_report(oracle, y, ksubs), "win_first_u": prob_report(heads[..., encode.HEAD_U], y, ksubs),
           "known": int(known.sum()), "first_gap": gap_stats(heads),
           "win_raw_n11": metrics.win_metrics(sigmoid(logits[:, encode.POSTBAN, encode.HEAD_U]), y),
           "calibration_n11": metrics.calibration(p[:, encode.POSTBAN], y, 10)}
    if first is not None:
        out["win_speed"] = prob_report(mix(heads, first), y, subs)  # 对照：直接用速度表的先动概率混合
        f_first = head[known] == encode.HEAD_F

        def acc(prob: np.ndarray) -> dict:
            pf = np.clip(prob[known], 0.01, 0.99)
            return {"n": int(known.sum()), "log_loss": float(-np.mean(np.where(f_first, np.log(pf), np.log(1 - pf)))),
                    "accuracy": float(np.mean((pf > 0.5) == f_first)), "mean": float(prob.mean()),
                    "actual": float(f_first.mean())}

        n = encode.POSTBAN
        out["first_prob"] = acc(effective_first(heads[:, n], first[:, n], ref[:, n]))  # 混合实际用的
        out["first_prob_speed"] = acc(first[:, n])  # 速度表
    return out
