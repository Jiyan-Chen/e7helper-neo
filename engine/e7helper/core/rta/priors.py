"""选秀推荐用的数据先验（B14c）：随包 `assets/data/rta/priors.json`，由 `e7helper rta priors` 从训练快照生成。

模型自己给不了的几样，按真实对局的频率算：
- 每名英雄在训练数据里被选的次数：判断「冷门」（被选 < 1000 次的，模型的搭档 / 克制项学得不准，B14b 审核发现）；
- 预禁组合的频率（双方 ≥ 优胜者，先手方 / 后手方分开）：预禁没有模型头，用它当对手预禁的分布和我方候选的先验；
- 后禁率（双方 ≥ 优胜者，一名英雄可被禁（不在保护位）时被禁的比例）：后禁矩阵里对方会禁谁的期望；
- 一方第 k 手（k = 0…4）各英雄被选的次数（B14g2，`speed.slot_counts`）：算先动概率时补还没选的那几手（`speed.FirstCalc`）。

以后每次重训（新赛季）都要和 `rta export` 一起重新生成。
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import encode, rules

PRIORS_FILE = "priors.json"
TOP_PREBAN_PAIRS = 300  # 每个先后手存多少组预禁组合


def bundled_path() -> Path:
    from .model import bundled_dir

    return bundled_dir() / PRIORS_FILE


def build(ds, source: str = "") -> dict:
    """训练快照（`dataset.Dataset`）→ priors.json 的内容。被选次数用全部对局（和随包模型的训练数据一致），
    预禁和后禁只看双方 ≥ 优胜者的。"""
    picks = encode.pick_counts(ds.tokens, ds.codes)
    champ = ds.champion_plus()
    tok = ds.tokens[champ]
    preban: dict[str, dict] = {}
    for side, (a, b) in encode.PREBAN_POS.items():
        pair = tok[:, [a, b]]
        pair = pair[(pair >= 0).all(axis=1) & (pair[:, 0] != pair[:, 1])]
        counts = Counter(tuple(sorted((ds.codes[x], ds.codes[y]))) for x, y in pair.tolist())
        preban[side] = {"total": int(len(pair)),
                        "pairs": [[x, y, n] for (x, y), n in counts.most_common(TOP_PREBAN_PAIRS)]}
    banned, bannable = Counter(), Counter()
    order = np.array(rules.PICK_ORDER)
    for side in rules.SIDES:
        cols = encode.PICK_POS + np.flatnonzero(order == side)  # 这一方按顺序的 5 手
        own = np.delete(tok[:, cols], rules.PROTECTED_SLOT, axis=1)
        bannable.update(int(h) for h in own.ravel() if h >= 0)
        banned.update(int(h) for h in tok[:, encode.BAN_POS[side]] if h >= 0)
    from .speed import slot_counts

    return {
        "format": 1, "built": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source,
        "dataset": {k: ds.meta.get(k) for k in ("season", "until", "first_day", "last_day", "kept")},
        "matches": int(len(ds)), "champion_plus": int(champ.sum()),
        "picks": dict(sorted(picks.items(), key=lambda kv: -kv[1])),
        "preban": preban,
        "postban": {ds.codes[h]: [int(banned[h]), int(n)] for h, n in bannable.most_common()},
        "slots": [dict(sorted(c.items(), key=lambda kv: -kv[1])) for c in slot_counts(ds.tokens, ds.codes)],
    }


@dataclass
class Priors:
    picks: dict[str, int] = field(default_factory=dict)
    preban: dict[str, dict] = field(default_factory=dict)
    postban: dict[str, list[int]] = field(default_factory=dict)
    slots: list[dict[str, int]] = field(default_factory=list)  # B14g2：一方第 k 手各英雄被选的次数（旧文件没有 = []）
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> Priors:
        return cls(picks=dict(d.get("picks", {})), preban=dict(d.get("preban", {})), postban=dict(d.get("postban", {})),
                   slots=[dict(x) for x in d.get("slots") or []],
                   meta={k: v for k, v in d.items() if k not in ("picks", "preban", "postban", "slots")})

    def pick_count(self, code: str | None) -> int:
        return int(self.picks.get(code or "", 0))

    def preban_pairs(self, side: str) -> list[tuple[tuple[str, str], float]]:
        """这一方（F / S）的预禁组合和占比，从多到少。"""
        d = self.preban.get(side) or {}
        total = max(int(d.get("total", 0)), 1)
        return [((a, b), n / total) for a, b, n in d.get("pairs", [])]

    def ban_rate(self, code: str, min_seen: int = 100) -> float | None:
        """可被禁时被禁的比例；数据太少（< min_seen 次可被禁）返回 None。"""
        b, n = self.postban.get(code, (0, 0))
        return b / n if n >= min_seen else None

    def mean_ban_rate(self) -> float:
        b = sum(v[0] for v in self.postban.values())
        n = sum(v[1] for v in self.postban.values())
        return b / n if n else 0.25


def load(path: Path | None = None) -> Priors:
    return _load(str(path or bundled_path()))


@lru_cache(maxsize=4)
def _load(path: str) -> Priors:
    return Priors.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def available(path: Path | None = None) -> bool:
    return (path or bundled_path()).exists()
