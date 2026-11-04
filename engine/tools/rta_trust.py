"""量选秀推荐「少见选择的高估修正」的常数（B14c 的做法，B14h 写成脚本；每次重训后跑一次）。

用切分训练的模型（没见过测试期）在测试期的真实对局上：每一手实际选的英雄 → 这一手的常见度 q（选人头给它的概率）、
模型说的变化 Δ = 选后 − 选前（出手方的胜率），实际兑现 = 出手方实际输赢 − 选前。按 q 分档，只看模型说「能提升」的
那些（Δ > 0），兑现比例 = Σ 实际兑现 / Σ Δ。搜索的可信度是 q / (q + c)（`SearchConfig.trust_c`），这里在网格上
找和各档兑现比例最接近的 c（按 Σ Δ 加权）。

用法（在 engine/ 下）：
  python -m uv run python tools/rta_trust.py <快照.npz> <切分模型导出目录> [--test-days 7] [--json 结果.json]
切分模型导出目录 = `rta export <切分 run> --out <目录>` 的输出（随包第二个模型 assets/data/rta/second/ 就是）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from e7helper.core.rta import encode, rules  # noqa: E402
from e7helper.core.rta.dataset import Dataset  # noqa: E402
from e7helper.core.rta.model import calibrate, load  # noqa: E402

BINS = [0, 0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.2, 1.01]
GRID = [0.0025, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.0175, 0.02, 0.025, 0.03, 0.04, 0.05]
CHUNK = 4000


def measure(ds: Dataset, folder: Path, test_days: int = 7) -> dict:
    m = load(folder)
    rows = ds.split(test_days)["test"]
    x = ds.encode(m.vocab, rows)
    heroes, y = x["heroes"], x["y"].astype(np.float64)
    size = m.vocab.size
    q_all, d_all, r_all, n_all = [], [], [], []
    for s in range(0, len(rows), CHUNK):
        h, c, yy = heroes[s:s + CHUNK], x["ctx"][s:s + CHUNK], y[s:s + CHUNK]
        win, pick = m.run(h, c)
        b = len(h)
        # 已选 n 手时先手方的胜率（n = 0…10）
        w = np.stack([calibrate(win[:, encode.STATE_POS[n]], np.full(b, n), m.calibration)
                      for n in range(encode.N_PICKS + 1)], axis=1)
        for n in range(encode.N_PICKS):
            chosen = h[:, encode.PICK_POS + n]
            ok = chosen >= encode.FIRST_HERO  # 词表外（UNK）的那手不算
            z = pick[:, encode.STATE_POS[n]].astype(np.float64)
            z = np.where(encode.pick_mask(h, np.full(b, n), size), z, -np.inf)
            z -= z.max(axis=1, keepdims=True)
            p = np.exp(z)
            p /= p.sum(axis=1, keepdims=True)
            q = p[np.arange(b), chosen]
            sign = 1.0 if rules.PICK_ORDER[n] == "F" else -1.0  # 换成出手方的胜率
            before = w[:, n] if sign > 0 else 1 - w[:, n]
            after = w[:, n + 1] if sign > 0 else 1 - w[:, n + 1]
            actual = yy if sign > 0 else 1 - yy
            q_all.append(q[ok])
            d_all.append((after - before)[ok])
            r_all.append((actual - before)[ok])
            n_all.append(np.full(int(ok.sum()), n))
    q, d, r = np.concatenate(q_all), np.concatenate(d_all), np.concatenate(r_all)
    up = d > 0
    table = []
    for lo, hi in zip(BINS[:-1], BINS[1:]):
        sel = (q >= lo) & (q < hi)
        u, dn = sel & up, sel & ~up
        table.append({"from": lo, "to": min(hi, 1.0), "moves": int(sel.sum()), "up": int(u.sum()),
                      "realized_up": float(r[u].sum() / d[u].sum()) if u.any() else None,
                      "realized_down": float(r[dn].sum() / d[dn].sum()) if dn.any() and d[dn].sum() != 0 else None,
                      "model_mean": float(d[sel].mean()) if sel.any() else None,
                      "actual_mean": float(r[sel].mean()) if sel.any() else None})
    # 网格找 c：每档「Σ 实际兑现 / Σ Δ」和「Σ q/(q+c)·Δ / Σ Δ」的加权误差
    fits = []
    for c in GRID:
        err = wsum = 0.0
        for lo, hi in zip(BINS[:-1], BINS[1:]):
            u = up & (q >= lo) & (q < hi)
            if not u.any():
                continue
            wt = d[u].sum()
            pred = float((q[u] / (q[u] + c) * d[u]).sum() / wt)
            err += wt * (r[u].sum() / wt - pred) ** 2
            wsum += wt
        fits.append({"c": c, "err": err / wsum})
    best = min(fits, key=lambda f: f["err"])
    return {"matches": int(len(rows)), "moves": int(len(q)), "from": ds.day_str(ds.day[rows].min()),
            "to": ds.day_str(ds.day[rows].max()), "table": table, "fits": fits, "best_c": best["c"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dataset", type=Path)
    ap.add_argument("model", type=Path, help="切分模型的导出目录")
    ap.add_argument("--test-days", type=int, default=7)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    res = measure(Dataset.load(a.dataset), a.model, a.test_days)
    print(f"测试期 {res['from']} ~ {res['to']}：{res['matches']} 场、{res['moves']} 手")
    print(f"{'常见度':>14} {'手数':>8} {'说提升的':>8} {'提升兑现':>8} {'不利兑现':>8}")
    for t in res["table"]:
        f = lambda v: "—" if v is None else f"{v:.2f}"  # noqa: E731
        print(f"{t['from']:>6.1%}–{t['to']:<6.1%} {t['moves']:>8} {t['up']:>8} {f(t['realized_up']):>8} {f(t['realized_down']):>8}")
    print("c 的误差：" + "、".join(f"{x['c']:.2%} {x['err']:.4f}" for x in res["fits"]))
    print(f"最接近的 c = {res['best_c']:.2%}（现在 SearchConfig.trust_c = 1.5%）")
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
