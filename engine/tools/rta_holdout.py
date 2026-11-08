"""新旧 RTA 模型在留出日上的直接比较（B14g 写成脚本；B14h 时只在会话里跑过）。

两个全量模型都没见过的那一天（建一份含这一天的快照放到 F:\\e7helper-data\\rta\\holdout\\，别放 datasets\\）：
每个模型目录读随包格式（model.onnx + meta.json），按局面 0 / 5 / 10 / 11 给 log loss / AUC，分子集（全部、双方 ≥ 优胜者、
段位同档 / 差 1 档 / 差 ≥ 2 档），n11 对第一个模型做配对自助法（1000 次）的 95% 区间。

- B14g 的三头模型：按先动概率混合（`model.effective_first`：速度表按双方段位的 + 模型隐含的；占位按 --train 快照里每一手的
  被选次数），另列「只用速度表混合」「不知道谁先动」「知道谁先动」（实际先动方的头）。
- 看段位的旧模型另列一行「段位换成不知道」：战绩站的段位是赛后的，旧模型在段位不同的对局上会占便宜。

用法（在 engine/ 下）：
    python -m uv run python tools/rta_holdout.py F:/e7helper-data/rta/holdout/ss21-2026-11-02.npz --day 2026-11-02 \\
        --train F:/e7helper-data/rta/datasets/ss21-2026-11-01.npz --model <新模型目录> --model assets/data/rta [--json 结果.json]
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from e7helper.core.rta import encode, metrics, speed
from e7helper.core.rta import model as rmodel
from e7helper.core.rta.dataset import Dataset

STATES = (0, 5, 10, 11)


def subsets(ds: Dataset, rows: np.ndarray) -> dict[str, np.ndarray]:
    gap = np.abs(ds.grades[rows, 0].astype(int) - ds.grades[rows, 1].astype(int))
    known = (ds.grades[rows] > 0).all(axis=1)
    return {"全部": np.ones(len(rows), dtype=bool), "≥优胜者": ds.champion_plus()[rows],
            "段位同档": known & (gap == 0), "段位差1档": known & (gap == 1), "段位差≥2档": known & (gap >= 2)}


def ll_rows(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("holdout", type=Path)
    ap.add_argument("--day", required=True, help="留出的那一天（UTC），如 2026-11-02")
    ap.add_argument("--model", type=Path, action="append", required=True, help="模型目录（可以给几个，第一个是基准）")
    ap.add_argument("--train", type=Path, help="训练快照（占位用每一手的被选次数）；不给用留出快照里这一天以前的")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    ds = Dataset.load(args.holdout)
    day = date.fromisoformat(args.day).toordinal()
    rows = np.flatnonzero(ds.day == day)
    if not len(rows):
        raise SystemExit(f"{args.holdout.name} 里没有 {args.day} 的对局")
    y = ds.first_wins[rows].astype(np.float64)
    head = encode.first_heads(ds.first_mover[rows])
    subs = subsets(ds, rows)
    print(f"{args.holdout.name} · {args.day}：{len(rows)} 场，知道谁先动 {int((head < 2).sum())} 场；"
          + "，".join(f"{k} {int(v.sum())}" for k, v in subs.items()))

    table = speed.load()
    first = ref = None
    if table is not None:
        src = Dataset.load(args.train) if args.train else ds
        train_rows = np.arange(len(src)) if args.train else np.flatnonzero(src.day < day)
        tokens = src.tokens[train_rows]
        calc = speed.FirstCalc(table, weights=dict(encode.pick_counts(tokens, src.codes)),
                               slot_weights=speed.slot_counts(tokens, src.codes))
        first = speed.match_first_probs(calc, ds.tokens[rows], ds.codes, ds.grades[rows])
        ref = speed.match_first_probs(calc, ds.tokens[rows], ds.codes, np.zeros_like(ds.grades[rows]))
        f_first = head == encode.HEAD_F
        known = head < encode.HEAD_U
        pf = np.clip(first[known, encode.POSTBAN], 0.01, 0.99)
        print(f"先动概率（后禁后，知道谁先动的 {int(known.sum())} 场）：log loss "
              f"{-np.mean(np.where(f_first[known], np.log(pf), np.log(1 - pf))):.4f}，命中 {np.mean((pf > 0.5) == f_first[known]):.1%}")

    variants: list[tuple[str, np.ndarray]] = []  # (名字, 先手方赢的概率 [N, 12])
    for folder in args.model:
        m = rmodel.RtaModel(folder)
        x = ds.encode(m.vocab, rows)
        name = f"{folder.name if folder.name != 'rta' else 'assets/data/rta'}（{m.meta.get('run')}）"
        heads = m.all_states(x["heroes"], x["ctx"])
        if m.first:
            variants.append((name + (" · 按先动概率混合" if first is not None else " · 不知道谁先动"),
                             rmodel.mix(heads, first, ref)))
            if first is not None:
                variants.append((name + " · 只用速度表混合", rmodel.mix(heads, first)))
                variants.append((name + " · 不知道谁先动", heads[..., encode.HEAD_U]))
            oracle = np.where(head[:, None] == encode.HEAD_F, heads[..., encode.HEAD_F], heads[..., encode.HEAD_S])
            variants.append((name + " · 实际先动方（只看知道的）", np.where((head < 2)[:, None], oracle, np.nan)))
        else:
            variants.append((name, heads[..., encode.HEAD_U]))
            if m.grades:
                ctx = x["ctx"].copy()
                ctx[:, :2] = encode.GRADE_UNKNOWN
                variants.append((name + " · 段位换成不知道", m.all_states(x["heroes"], ctx)[..., encode.HEAD_U]))

    out = {"day": args.day, "n": int(len(rows)), "models": {}}
    rng = np.random.default_rng(0)
    base = variants[0][1]
    for name, p in variants:
        res = {}
        for sub, mask in subs.items():
            m = mask & ~np.isnan(p[:, encode.POSTBAN])
            if m.sum() < 50:
                continue
            res[sub] = {str(n): metrics.win_metrics(p[m, n], y[m]) for n in STATES}
        # n11 配对差（对基准），只算两者都有的对局
        both = ~np.isnan(p[:, encode.POSTBAN]) & ~np.isnan(base[:, encode.POSTBAN])
        d = ll_rows(p[both, encode.POSTBAN], y[both]) - ll_rows(base[both, encode.POSTBAN], y[both])
        boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(args.boot)]
        res["vs_base_n11"] = {"n": int(both.sum()), "diff": float(d.mean()),
                              "ci": [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))]}
        out["models"][name] = res
        print(f"\n{name}")
        for sub in subs:
            if sub in res:
                print(f"  {sub:8s} " + "  ".join(f"n{n} {res[sub][str(n)]['log_loss']:.4f}/{res[sub][str(n)]['auc']:.3f}"
                                                 for n in STATES))
        v = res["vs_base_n11"]
        print(f"  n11 对基准 {v['diff']:+.4f}（95% {v['ci'][0]:+.4f} ~ {v['ci'][1]:+.4f}，{v['n']} 场）")
    if args.json:
        args.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
