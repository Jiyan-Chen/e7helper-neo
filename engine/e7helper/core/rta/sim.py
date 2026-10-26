"""模拟 BP（B14b 审核时试用模型，开发用，`e7helper rta sim`）。

只用随包模型做一层估算：给我方列出「选了之后胜率最高」的英雄（不考虑对手怎么回应）和「这一手大家常选」的英雄；
对手按选人头抽一名（像真实玩家那样选）；后禁给出双方各禁一名的胜率矩阵。正式的推荐搜索（对手回应、两手回合按对评估、
预禁推荐）在 B14c。胜率一律换成「我方」的。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import encode, rules
from .model import RtaModel


@dataclass
class Suggestion:
    code: str
    win: float  # 选了之后我方的胜率
    common: float  # 这一手选它的概率（选人头）


def other(side: str) -> str:
    return "S" if side == "F" else "F"


def my_win(p_first: float | np.ndarray, side: str):
    """先手方胜率 → 我方胜率。"""
    return p_first if side == "F" else 1.0 - p_first


def with_pick(state: encode.DraftState, side: str, code: str) -> encode.DraftState:
    st = encode.DraftState.from_dict(state.to_dict())
    st.picks[side].append(code)
    return st


def with_bans(state: encode.DraftState, banned: dict[str, str]) -> encode.DraftState:
    """banned[F] 是先手方被禁的那名。"""
    st = encode.DraftState.from_dict(state.to_dict())
    st.banned = dict(banned)
    return st


def available(model: RtaModel, state: encode.DraftState) -> list[str]:
    """下一手能选的英雄（词表里、没被预禁、没被选）。"""
    x = encode.encode_states([state], model.vocab)
    ok = encode.pick_mask(x["heroes"], x["state"], model.vocab.size)[0]
    return [model.vocab.code(i) for i in np.flatnonzero(ok)]


def suggest(model: RtaModel, state: encode.DraftState, side: str, k: int = 8, min_common: float = 0.005,
            keep_top: int = 40) -> list[Suggestion]:
    """轮到我方（side）时：候选英雄选了之后的我方胜率，从高到低前 k 名。

    候选只取这一手「常见度」（选人头概率）≥ min_common 或排前 keep_top 的：冷门英雄的搭档 / 克制项是从很少的对局里
    学出来的，几名叠在一起时模型会外推出离谱的胜率（B14b 审核时用模拟 BP 发现），一层贪心会专挑它们。
    """
    common = model.evaluate([state]).picks[0]
    rank = np.argsort(-common)
    keep = set(rank[:keep_top].tolist()) | set(np.flatnonzero(common >= min_common).tolist())
    cands = [c for c in available(model, state) if model.vocab.hero(c) in keep]
    wins = my_win(model.win([with_pick(state, side, c) for c in cands]), side)
    order = np.argsort(-wins)[:k]
    return [Suggestion(cands[i], float(wins[i]), float(common[model.vocab.hero(cands[i])])) for i in order]


def opponent_pick(model: RtaModel, state: encode.DraftState, rng: np.random.Generator, top: int = 8) -> tuple[str, float]:
    """对手按选人头的前 top 名（重新归一）抽一名；返回 (编号, 选人头给的概率)。"""
    picks = model.next_picks(state, top)
    p = np.array([q for _, q in picks])
    i = int(rng.choice(len(picks), p=p / p.sum()))
    return picks[i]


def bannable(state: encode.DraftState, side: str) -> list[str]:
    """side 这一方能被禁的英雄（保护位第 3 手除外）。"""
    return [c for i, c in enumerate(state.picks[side]) if i != rules.PROTECTED_SLOT]


def ban_matrix(model: RtaModel, state: encode.DraftState, side: str) -> tuple[list[str], list[str], np.ndarray]:
    """选完 10 手后：行 = 我方禁对方哪名，列 = 对方禁我方哪名，值 = 我方胜率。"""
    mine, theirs = other(side), side  # 我方禁的是对方的英雄；对方禁的是我方的
    rows, cols = bannable(state, mine), bannable(state, theirs)
    states = [with_bans(state, {mine: r, theirs: c}) for r in rows for c in cols]
    wins = my_win(model.win(states), side).reshape(len(rows), len(cols))
    return rows, cols, wins


def maximin_row(matrix: np.ndarray) -> int:
    """我方的稳妥后禁：最坏情况（对方怎么禁）下胜率最高的那一行。"""
    return int(np.argmax(matrix.min(axis=1)))


def minimax_col(matrix: np.ndarray) -> int:
    """对方的稳妥后禁：不管我方怎么禁、我方胜率最高也最低的那一列。"""
    return int(np.argmin(matrix.max(axis=0)))


def preban_weights(dataset: Path) -> list[tuple[str, int]]:
    """训练快照里各英雄被预禁的次数（模拟对手的预禁用）。"""
    from .dataset import Dataset

    ds = Dataset.load(dataset)
    idx = ds.tokens[:, 1:encode.PICK_POS].ravel()
    counts = Counter(int(i) for i in idx[idx >= 0])
    return [(ds.codes[i], n) for i, n in counts.most_common()]


def sample_prebans(weights: Sequence[tuple[str, int]], rng: np.random.Generator, k: int = rules.PREBANS_PER_SIDE,
                   top: int = 30) -> list[str]:
    """按预禁热度（前 top 名）不重复地抽 k 名。"""
    pool = list(weights[:top])
    p = np.array([n for _, n in pool], dtype=np.float64)
    idx = rng.choice(len(pool), size=k, replace=False, p=p / p.sum())
    return [pool[int(i)][0] for i in idx]
