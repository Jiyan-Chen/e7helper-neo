"""先动 / 后动两种胜率按阵容差多少（B14g 验收用）：模型目录（随包格式，三头模型）+ 训练快照的一份数据。

差 = 先手方先动时先手方的胜率 − 后手方先动时的（= 这一局「抢到一速」值多少，对两方一样）。打印：
- 后禁后（默认，--state 改）差的分布：分位数、|差| ≥ 10 / 20 / 30 个点的比例；
- 差最大 / 最小的几局（双方上场的英雄）；
- 每名英雄（出场 ≥ --min 次）所在对局的平均差：哪些英雄让「谁先动」变得要紧、哪些几乎不影响。

用法（在 engine/ 下）：
    python -m uv run python tools/rta_first_gap.py <模型目录> F:/e7helper-data/rta/datasets/ss21-2026-11-01.npz [--split test]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from e7helper.core.data import heroes as hero_db
from e7helper.core.rta import encode, rules
from e7helper.core.rta import model as rmodel
from e7helper.core.rta.dataset import Dataset


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--split", default="test", help="test / val / train / all")
    ap.add_argument("--state", type=int, default=encode.POSTBAN, help="看哪个局面（默认后禁后 11）")
    ap.add_argument("--top", type=int, default=8, help="差最大 / 最小的各列几局")
    ap.add_argument("--min", type=int, default=500, help="英雄出场至少几次才列")
    ap.add_argument("--heroes", type=int, default=15, help="英雄各列几名")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    m = rmodel.RtaModel(args.model)
    if not m.first:
        raise SystemExit("这个模型只有一个胜率头（B14g 之前的格式），没有先动 / 后动之分")
    ds = Dataset.load(args.dataset)
    rows = np.arange(len(ds)) if args.split == "all" else ds.split(7, 7)[args.split]
    x = ds.encode(m.vocab, rows)
    heads = m.all_states(x["heroes"], x["ctx"])[:, args.state]
    gap = heads[:, encode.HEAD_F] - heads[:, encode.HEAD_S]
    a = np.abs(gap)
    db = hero_db()
    name = lambda c: (db.get(c).name if c and db.get(c) else c) or "—"  # noqa: E731
    print(f"{args.model} · {args.dataset.name} {args.split} {len(rows)} 场 · 局面 {args.state}")
    print(f"差（个百分点）：平均 {gap.mean() * 100:+.1f}，|差| 平均 {a.mean() * 100:.1f}；分位数 "
          + "、".join(f"{q:.0%} {np.quantile(gap, q) * 100:+.1f}" for q in (0.01, 0.1, 0.5, 0.9, 0.99)))
    print("|差| ≥ 10 / 20 / 30 个点：" + " / ".join(f"{(a >= t).mean():.1%}" for t in (0.1, 0.2, 0.3)))

    def lineup(r: int) -> tuple[list[str], list[str]]:
        t = [ds.codes[i] if i >= 0 else None for i in ds.tokens[rows[r]].tolist()]
        out = {}
        for s in rules.SIDES:
            picks = [c for side, c in zip(rules.PICK_ORDER, t[encode.PICK_POS:encode.PICK_POS + 10]) if side == s]
            banned = t[encode.BAN_POS[s]] if args.state == encode.POSTBAN else None
            out[s] = [c for c in picks if c and c != banned]
        return out["F"], out["S"]

    def show(title: str, order: np.ndarray) -> list[dict]:
        print(f"\n{title}")
        got = []
        for r in order[:args.top]:
            f, s = lineup(int(r))
            h = heads[r]
            print(f"  {gap[r] * 100:+5.1f}  先手 {'、'.join(map(name, f))}  vs  后手 {'、'.join(map(name, s))}"
                  f"  （先手方先动 {h[0]:.0%} / 后手方先动 {h[1]:.0%} / 不知道 {h[2]:.0%}）")
            got.append({"gap": float(gap[r]), "first": f, "second": s, "heads": [float(v) for v in h]})
        return got

    out = {"n": int(len(rows)), "state": args.state, "mean": float(gap.mean()), "abs_mean": float(a.mean()),
           "q": {str(q): float(np.quantile(gap, q)) for q in (0.01, 0.1, 0.5, 0.9, 0.99)},
           "ge": {str(t): float((a >= t).mean()) for t in (0.1, 0.2, 0.3)}}
    out["largest"] = show("差最大的几局", np.argsort(-a))
    out["smallest"] = show("差最小的几局", np.argsort(a))

    sums, counts = {}, {}
    for r in range(len(rows)):
        f, s = lineup(r)
        for c in f + s:
            sums[c] = sums.get(c, 0.0) + float(gap[r])
            counts[c] = counts.get(c, 0) + 1
    avg = sorted(((sums[c] / n, n, c) for c, n in counts.items() if n >= args.min), reverse=True)
    print(f"\n每名英雄所在对局的平均差（出场 ≥ {args.min} 次，{len(avg)} 名；全体平均 {gap.mean() * 100:+.1f}）")
    print("  最要紧：" + "、".join(f"{name(c)} {v * 100:+.1f}" for v, _, c in avg[:args.heroes]))
    print("  最不要紧：" + "、".join(f"{name(c)} {v * 100:+.1f}" for v, _, c in avg[::-1][:args.heroes]))
    out["heroes"] = [{"code": c, "name": name(c), "n": n, "gap": v} for v, n, c in avg]
    if args.json:
        args.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
