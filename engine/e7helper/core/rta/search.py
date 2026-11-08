"""RTA 选秀推荐（B14c）：在随包的胜率 / 选人模型（`model.py`）上做搜索，只依赖 numpy + onnxruntime。

```python
from e7helper.core.rta import search
adv = search.load()                              # 随包模型 + 第二个模型（切分训练的）+ priors.json，进程内缓存
adv.advise(state, "F", pool=None)                # 当前局面：轮到我方 → 推荐；轮到对手 → 对手可能怎么选；选完 → 后禁矩阵
adv.preban("F", grades=("legend", "emperor"))    # 预禁推荐（先后手不知道传 None）
```

轮到我方时的搜索：
1. 候选只从选人头先验里取：这一手常见度 ≥ 0.5%，或常见度前 40 且训练数据里被选过 ≥ 1000 次（冷门英雄的搭档 /
   克制项学得不准，B14b 审核；不筛的话一层贪心 85% 挑到冷门英雄，B14c 开工测量）。英雄池里过不了筛的冷门英雄
   也算候选（靠下面的折扣压住）。英雄池里能选的（没被选、没被禁）不够这一轮要选的名数时，这一轮不限制
   （B14e2：根上的这一轮标 `pool_short`，第 3 层我方再回应也按同样的规则）。
2. 扣掉少见选择的高估：一手的单步变化里对出手方有利的那部分，有 (1 − 可信度) 当成模型的高估，从这一手之后的
   所有结果里扣掉（冷门英雄的高估在它上场后一直都在，后面几手、后禁都会带着）。可信度 = q / (q + 1.5%)
   （q = 这一手的常见度）× min(1, 被选次数 / 1000)。按切分模型在没见过的测试期上量的：模型说「这一手能提升」的
   选择里，常见度 < 1% 的几乎不兑现、1%–3% 兑现约一半、3%–20% 约八成、≥ 20% 几乎全部；说「这一手不好」的
   各档都兑现八成以上，所以不利的那部分不扣（B14c 审核记录）。搜索专挑模型说提升最大的，不扣就会被少见选择带偏。
3. 三层：我方这一轮 → 对手下一轮 → 我方再下一轮。对手的回应 = 先验前 12 名 ∪ 威胁前 4 名（加上之后我方胜率
   掉得最多的）；对手连选两名时是两两组合，组合的先验 = q(a)·q(b|a) + q(b)·q(a|b)。分数 = ½ 预期（按回应的先验
   加权）+ ½ 最坏。第 3 层只给前 8 个候选算：回应取先验前 10 个 + 最坏的 2 个，我方再回应取先验前 12 名。
4. 两手回合按对评估：游戏里先后无所谓的回合，我方两个顺序取平均（抵掉模型对顺序的噪声）；含保护位的回合两个
   顺序都算、取对这一方好的那个（并给出哪名放保护位）；对手的普通两手回合只算先验高的在前的那个顺序。
5. 搜到选秀结束时叶子用后禁博弈的值：4 × 4 矩阵每行 ½ 最坏 + ½ 预期（对方按数据里的后禁率），取最好的一行。
6. 有截止时间：第 2 / 3 层按候选的名次一个个算，到时间就停；没算到的候选按浅一层的结果排在后面。
第二个模型（切分训练的，没见过最后 14 天）只给最后列出的推荐重算第 2 层，两个模型的差当不确定性。

轮到对手时（B14e2 审核，用户意见：始终用我方的读数，不用不知道英雄池的模型读数）：对手最可能的几种选法和
模型读数最差的几种，各自往下算「我方这一轮从英雄池里挑最好的回应（先验前 16 名）→ 对手再下一轮按先验回应」，
每种选法之后的胜率 = 那个回应的预期（同推荐卡的「预期」），`opponent.win` = 按选法的先验加权。
返回的胜率一律是「我方」的。

B14g2：模型的胜率分「先手方先动 / 后手方先动 / 不知道」三种，每个局面按这个阵容的先动概率混合（用户原则：段位只
影响谁先动，胜率按 BP 算再按先动概率混合）：先动概率按双方段位 + 我方英雄池里填的速度算（`speed.FirstCalc`，
同一阵容按一般玩家算的作参照，`model.effective_first`），没有速度表时用「不知道」的头。推荐、最坏、对手回应、
后禁矩阵、`opponent.win`、预禁都是混合后的值。另外每个值都带着「我方先动时 / 后动时」两种（同样的回应、权重），
推荐卡、后禁矩阵每格、对方回合的读数都给出这两种。显示的先动概率 `first`（审核第 1、2 轮用户意见）：选秀中只按双方
已经选出的英雄、用速度表算（推荐 = 加上这一组、对方的选法 = 加上对方这一手；不补还没选的几手，也不把之后的回应合进去；
一方还没有英雄时是 None）；后禁矩阵每格 / 结束时是上场 4 打 4 混合用的先动概率。混合胜率时还是按补全的阵容算。
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from itertools import combinations
from typing import NamedTuple

import numpy as np

from . import encode, rules, speed
from . import model as rmodel
from . import priors as rpriors

SECOND_DIR = "second"  # 随包 assets/data/rta/second/：切分训练的模型
N = encode.N_PICKS
_ORDER = {s: [k for k, x in enumerate(rules.PICK_ORDER) if x == s] for s in rules.SIDES}
BANNABLE = {s: [k for i, k in enumerate(_ORDER[s]) if i != rules.PROTECTED_SLOT] for s in rules.SIDES}  # 整局第几手


@dataclass
class SearchConfig:
    min_common: float = 0.005  # 这一手常见度 ≥ 这个就算候选
    keep_top: int = 40  # 或者常见度前这么多名、而且训练数据里不冷门
    rare_picks: int = 1000  # 训练数据里被选少于这么多次 = 冷门
    trust_c: float = 0.015  # 每一手的变化 × q / (q + trust_c)
    stage2: int = 24  # 第 2 层算几个候选
    stage3: int = 8  # 第 3 层算几个候选
    responses: int = 12  # 对手回应：先验前几名
    threats: int = 4  # 加上威胁前几名
    responses3: int = 10  # 第 3 层：回应取先验前几个
    threats3: int = 2  # 再加最坏的几个
    replies: int = 12  # 第 3 层我方再回应：先验前几名
    opp_list: int = 16  # 轮到对手时：两手回合取先验前几名两两组合
    their_replies: int = 16  # 轮到对手时算「我方的读数」：我方回应取先验前几名（英雄池里的）
    reply_cands: int = 4  # 再往下算对手回应的我方回应个数
    alpha: float = 0.5  # 分数 = alpha × 最坏 + (1 − alpha) × 预期
    close_gap: float = 0.01  # 和第一名差不到这个 = 差距不明显
    uncertain_gap: float = 0.05  # 两个模型差这么多 = 不确定
    top: int = 8
    budget: float = 5.0  # 秒
    preban_budget: float = 4.0
    preban_min_share: float = 0.002  # 我方预禁候选：数据里占比 ≥ 这个
    preban_keep_top: int = 60  # 或者最常见的前这么多组
    preban_partners: int = 24  # 固定一名时，搭档从预禁最多的前这么多名里找
    preban_opponents: int = 100  # 对手的预禁按最常见的这么多组加权
    preban_worst: int = 10  # 最坏：对手最常见的这么多组里最差的
    batch: int = 256  # 一次送进 onnxruntime 的局面数（64–256 每个局面最快）
    cache: int = 64


def other(side: str) -> str:
    return "S" if side == "F" else "F"


def protected_index(n: int, k: int) -> int | None:
    """已选 n 手、轮到的一方这一轮连选 k 名：其中第几名（0 起）落在这一方的保护位；没有返回 None。"""
    side = rules.mover(n)
    if side is None:
        return None
    before = rules.side_counts(n)[rules.SIDES.index(side)]
    for i in range(k):
        if before + i == rules.PROTECTED_SLOT:
            return i
    return None


def nash(m: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """零和同时博弈（行方要大、列方要小）的混合策略均衡：逐个支撑集解等值方程，4 × 4 只有 69 组。"""
    m = np.asarray(m, dtype=np.float64)
    r, c = m.shape
    for k in range(1, min(r, c) + 1):
        for rs in combinations(range(r), k):
            for cs in combinations(range(c), k):
                sub = m[np.ix_(rs, cs)]
                sol = []
                for a in (sub.T, sub):  # 行方让列方在 cs 上无差别；列方让行方在 rs 上无差别
                    lhs = np.zeros((k + 1, k + 1))
                    lhs[:k, :k], lhs[:k, k], lhs[k, :k] = a, -1.0, 1.0
                    rhs = np.zeros(k + 1)
                    rhs[k] = 1.0
                    try:
                        sol.append(np.linalg.solve(lhs, rhs))
                    except np.linalg.LinAlgError:
                        break
                if len(sol) < 2 or (sol[0][:k] < -1e-9).any() or (sol[1][:k] < -1e-9).any():
                    continue
                x, y = np.zeros(r), np.zeros(c)
                x[list(rs)], y[list(cs)] = np.clip(sol[0][:k], 0, None), np.clip(sol[1][:k], 0, None)
                x, y = x / x.sum(), y / y.sum()
                v = float(x @ m @ y)
                if (m @ y <= v + 1e-7).all() and (x @ m >= v - 1e-7).all():
                    return x, y, v
    # 退化的矩阵（几乎不会遇到）：虚拟对弈近似
    xs, ys = np.zeros(r), np.zeros(c)
    i, j = 0, 0
    for _ in range(5000):
        xs[i] += 1
        ys[j] += 1
        i = int(np.argmax(m @ ys))
        j = int(np.argmin(xs @ m))
    x, y = xs / xs.sum(), ys / ys.sum()
    return x, y, float(x @ m @ y)


class _Clock:
    """截止时间和推理计数。"""

    def __init__(self, budget: float, batch: int):
        self.t0 = time.perf_counter()
        self.deadline = self.t0 + budget
        self.batch = batch
        self.rows = 0
        self.seconds = 0.0
        self.truncated = False

    def count(self, rows: int, seconds: float) -> None:
        self.rows += rows
        self.seconds += seconds

    def affordable(self, rows: int) -> bool:
        rate = self.seconds / self.rows if self.rows > 500 else 160e-6
        if rows * rate <= self.deadline - time.perf_counter():
            return True
        self.truncated = True
        return False

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0


class _FirstCtx:
    """一次搜索里的先动概率（B14g2）：双方段位、我方英雄池里填的速度固定，每批局面按阵容算 (first, ref)：
    first = 按双方段位 + 速度，ref = 同一阵容按一般玩家（不知道段位、没填速度），给 `model.effective_first` 用。
    局面用主模型词表的编号；局面里模型没见过的英雄（UNK）换回它自己的编号（速度表里可能有它）。"""

    def __init__(self, calc: speed.FirstCalc, vocab: encode.Vocab, grades: tuple[str | None, str | None],
                 speeds: tuple[dict[str, float] | None, dict[str, float] | None] = (None, None),
                 tokens: Sequence[str | None] | None = None):
        self.calc = calc
        self.codes: list[str | None] = [None] * encode.FIRST_HERO + list(vocab.heroes)  # 行号 = 词表编号
        self.grades = (grades[0], grades[1])
        self.speeds = (speeds[0] or None, speeds[1] or None)
        self.same = self.grades == (None, None) and not any(self.speeds)  # first 就是 ref
        self.unk: dict[int, int] = {}  # 位置 → 行号
        if tokens is not None:
            first_unk: dict[str, int] = {}
            for s in rules.SIDES:
                for j in _ORDER[s]:
                    code = tokens[encode.PICK_POS + j]
                    if code and vocab.hero(code) == encode.UNK:
                        self.unk[encode.PICK_POS + j] = len(self.codes)
                        first_unk.setdefault(s, len(self.codes))
                        self.codes.append(code)
                if s in first_unk:  # 后禁矩阵把选的英雄编号抄进被禁的位置：UNK 当这一方第一名没见过的
                    self.unk[encode.BAN_POS[s]] = first_unk[s]

    def pair(self, heroes: np.ndarray, states: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
        ids = heroes
        if self.unk:
            ids = heroes.copy()
            for pos, row in self.unk.items():
                ids[:, pos] = np.where(ids[:, pos] == encode.UNK, row, ids[:, pos])
        f = speed.ids_first_probs(self.calc, ids, states, self.codes, self.grades, self.speeds, pad=encode.PAD)
        r = f if self.same else speed.ids_first_probs(self.calc, ids, states, self.codes, pad=encode.PAD)
        return f, r


class _Fwd(NamedTuple):
    win: np.ndarray  # [B, S] 先手方赢的概率（按先动概率混合的；没有速度表是「不知道」的头）
    probs: np.ndarray | None  # [B, V] 下一手的分布
    split: np.ndarray  # [B, S, 2] 先手方先动时 / 后手方先动时 先手方赢的概率
    pi: np.ndarray | None  # [B, S] 混合用的「先手方先动」概率（没有速度表是 None）


class _Net:
    """一个模型在一次搜索里的推理。局面统一用主模型词表的编号拼，这里换成这个模型自己的编号和上下文。"""

    def __init__(self, model, state: encode.DraftState, main_vocab: encode.Vocab, clock: _Clock,
                 first: _FirstCtx | None = None):
        self.model = model
        self.clock = clock
        self.first = first
        self.ctx = encode.encode_states([state], model.vocab)["ctx"][0]
        self.lut = None
        if model.vocab is not main_vocab:
            self.lut = np.array([i if i < encode.FIRST_HERO else model.vocab.hero(main_vocab.code(i))
                                 for i in range(main_vocab.size)], dtype=np.int64)

    def forward(self, heroes: np.ndarray, win_states: Sequence[int], pick_state: int | None = None) -> _Fwd:
        """heroes [B, 17]（主模型编号）→ 各局面先手方的胜率 [B, len(win_states)]（混合的）、先动 / 后动两种、
        混合用的先动概率，局面 pick_state 下一手的分布 [B, V] 或 None。"""
        started = time.perf_counter()
        h = heroes if self.lut is None else self.lut[heroes]
        pos = encode.STATE_POS[list(win_states)]
        wins, picks = [], []
        for s in range(0, len(h), self.clock.batch):
            chunk = h[s:s + self.clock.batch]
            w, p = self.model.run(chunk, np.repeat(self.ctx[None], len(chunk), axis=0))
            wins.append(w[:, pos])
            if pick_state is not None:
                picks.append(p[:, encode.STATE_POS[pick_state]].astype(np.float64))
        z = np.concatenate(wins) if wins else np.zeros((0, len(pos)))
        heads = rmodel.calibrate_heads(z, np.broadcast_to(np.asarray(win_states), z.shape[:2]), self.model.calibration)
        pi = None
        if self.first is not None and len(heroes):
            f, r = self.first.pair(heroes, win_states)
            pi = rmodel.effective_first(heads, f, r)
            win = pi * heads[..., encode.HEAD_F] + (1.0 - pi) * heads[..., encode.HEAD_S]
        else:
            win = heads[..., encode.HEAD_U]
        probs = None
        if pick_state is not None:
            assert self.lut is None, "下一手的分布只从主模型取"
            logits = np.concatenate(picks)
            ok = np.ones(logits.shape, dtype=bool)
            ok[:, :encode.FIRST_HERO] = False
            ok[np.arange(len(heroes))[:, None], heroes[:, 1:encode.PICK_POS + pick_state]] = False
            logits = np.where(ok, logits, -np.inf)
            logits -= logits.max(axis=1, keepdims=True)
            e = np.exp(logits)
            probs = e / e.sum(axis=1, keepdims=True)
        self.clock.count(len(h), time.perf_counter() - started)
        return _Fwd(win, probs, heads[..., :2], pi)


@dataclass
class _Move:
    """一方这一轮的一种走法：ids 是规范顺序（先验高的在前），variants 是要算的顺序。"""
    ids: tuple[int, ...]
    variants: list[tuple[int, ...]]
    combine: str  # "one" / "mean"（两个顺序取平均）/ "best"（取对这一方好的那个，含保护位）
    trust: float = 1.0  # 这一手带来的胜率变化打几折
    prior: float = 0.0  # 对手的回应：这个走法的先验（加权用）；我方：只用来显示


_NO_SPLIT = np.full(2, 0.5)


@dataclass
class _Vals:
    """`_Search.values` 的结果（每行一个局面，我方视角）。s_* = 同一个值「我方先动时 / 后动时」两种 [B, 2]。"""
    raw: np.ndarray  # 走完这一步模型给的我方胜率（选完 10 手时 = 后禁前的）
    value: np.ndarray  # 选完 10 手 = 后禁博弈的值，否则 = raw
    exp: np.ndarray  # 后禁博弈推荐那一行的预期（否则 = raw）
    worst: np.ndarray
    probs: np.ndarray | None
    s_raw: np.ndarray
    s_value: np.ndarray
    s_exp: np.ndarray
    pi: np.ndarray | None  # [B] 混合用的我方先动概率（选完 10 手时是后禁前的）


@dataclass
class _Result:
    raw: float  # 走完这一步模型给的我方胜率（选完 10 手时 = 后禁前的）
    value: float  # 选完 10 手 = 后禁博弈的值，否则 = raw
    exp: float  # 后禁博弈推荐那一行的预期（否则 = raw）
    worst: float
    line: tuple[int, ...]  # 往下算用的顺序
    probs: np.ndarray | None = None  # 下一手的分布（主模型）
    s_raw: np.ndarray = field(default_factory=lambda: _NO_SPLIT)  # 我方先动时 / 后动时（B14g2）
    s_value: np.ndarray = field(default_factory=lambda: _NO_SPLIT)
    s_exp: np.ndarray = field(default_factory=lambda: _NO_SPLIT)
    pi: float | None = None  # 混合用的我方先动概率


def correction(f: float, delta: float, mine: bool) -> float:
    """一手的单步变化 delta（我方视角）里，对出手方有利的那部分有 (1 − f) 当成模型的高估；返回要加到这一手之后
    所有结果上的修正（我方视角）。不利的那部分不动：模型说「这一手不好」的少见选择，实际也差不多那么不好。"""
    if mine:
        return -(1.0 - f) * max(delta, 0.0)
    return (1.0 - f) * max(-delta, 0.0)


@dataclass
class _Cand:
    """我方这一轮的一个候选。值都从下往上算：子树的值 → 加上这一手的修正 → 分数。"""
    move: _Move
    res: _Result
    corr: float = 0.0  # 这一手的修正（加在子树的所有值上）
    depth: int = 1
    end: bool = False  # 已经算到后禁
    exp: float = 0.0  # 子树的预期 / 最坏（不含这一手的修正）
    worst: float = 0.0
    score: float = 0.0
    win: float = 0.0  # 加上修正的预期 / 最坏
    low: float = 0.0
    responses: list[tuple[_Move, _Result]] = field(default_factory=list)
    level2: list[float] = field(default_factory=list)  # 第 2 层每个回应之后的值（不往下看我方再回应）
    level2_split: list[np.ndarray] = field(default_factory=list)  # 同上，我方先动时 / 后动时
    level3: dict = field(default_factory=dict)  # 回应下标 → (我方再回应后的值, 再回应的顺序)
    second: dict | None = None
    s_exp: np.ndarray = field(default_factory=lambda: _NO_SPLIT)  # 子树预期的「我方先动时 / 后动时」（不含修正）
    s_win: np.ndarray = field(default_factory=lambda: _NO_SPLIT)  # 加上修正的


class _Search:
    def __init__(self, adv: Advisor, cfg: SearchConfig, state: encode.DraftState, side: str, pool: Sequence[str] | None,
                 budget: float, speeds: dict[str, float] | None = None):
        self.adv, self.cfg = adv, cfg
        self.state, self.side, self.opp = state, side, other(side)
        self.n = state.n_picks
        self.vocab = adv.model.vocab
        self.clock = _Clock(budget, cfg.batch)
        self.base = encode.encode_states([state], self.vocab)["heroes"][0]
        # 先动概率：双方段位 + 我方英雄池里填的速度（对方的不知道）
        self.speeds = dict(speeds or {})  # 我方英雄的速度
        sp = {side: self.speeds or None, self.opp: None}
        fc = adv.first_ctx(state.grades, (sp["F"], sp["S"]), state.tokens())
        self.has_first = fc is not None
        self.main = _Net(adv.model, state, self.vocab, self.clock, fc)
        self.second = _Net(adv.second, state, self.vocab, self.clock, fc) if adv.second is not None else None
        self.root_pi: float | None = None  # 当前局面混合用的我方先动概率（后禁 / 结束时显示）
        self._shown: dict[tuple, float | None] = {}  # 显示用的先动概率（只按已选英雄）
        self.pool = None
        self.pool_short = False  # 英雄池里能选的不够这一轮（这一轮推荐全部英雄）
        # 模型没见过的英雄（按 UNK 算）：局面里的（B14h 快照里去掉的新英雄）和英雄池里的
        self.unknown: list[str] = []
        self.tokens = state.tokens()
        for code in self.tokens:
            if code and self.vocab.hero(code) < encode.FIRST_HERO and code not in self.unknown:
                self.unknown.append(code)
        if pool is not None:
            self.pool = np.zeros(self.vocab.size, dtype=bool)
            for code in pool:
                i = self.vocab.hero(code)
                if i >= encode.FIRST_HERO:
                    self.pool[i] = True
                elif code not in self.unknown:
                    self.unknown.append(code)
        self.counts = adv.counts
        self.ban_rates = adv.ban_rates
        self.depth = 1
        self.second_cur: float | None = None
        self.cur = 0.5  # 当前局面我方胜率（my_turn 里算）
        self.empty = np.zeros((1, 0), dtype=np.int64)

    # —— 基本操作 ——
    def mine(self, p_first):
        return p_first if self.side == "F" else 1.0 - p_first

    def mine_split(self, split: np.ndarray) -> np.ndarray:
        """[..., 2] 先手方先动时 / 后手方先动时 先手方的胜率 → 我方先动时 / 我方后动时 我方的胜率。"""
        return split if self.side == "F" else 1.0 - split[..., ::-1]

    def mine_pi(self, pi: np.ndarray | None) -> np.ndarray | None:
        return None if pi is None else self.mine(pi)

    def code(self, i: int) -> str | None:
        return self.vocab.code(int(i))

    def lines(self, fills: np.ndarray) -> np.ndarray:
        """从已选 n 手之后接着填 fills [B, L]（主模型编号）→ 完整的 heroes [B, 17]。"""
        h = np.repeat(self.base[None], len(fills), axis=0)
        if fills.shape[1]:
            h[:, encode.PICK_POS + self.n:encode.PICK_POS + self.n + fills.shape[1]] = fills
        return h

    def root(self, net: _Net, pick: bool = False) -> tuple[float, np.ndarray | None]:
        f = net.forward(self.lines(self.empty), [self.n], self.n if pick else None)
        if net is self.main:
            self.root_pi = None if f.pi is None else float(self.mine(f.pi[0, 0]))
        return float(self.mine(f.win[0, 0])), (f.probs[0] if f.probs is not None else None)

    def ban_values(self, net: _Net, h: np.ndarray) -> dict:
        """选完 10 手的局面 h [B, 17] → 后禁博弈。行 = 我方禁对方哪名，列 = 对方禁我方哪名（保护位除外）。
        `*_split` 是同一个值「我方先动时 / 后动时」两种（最坏取最坏那一格的，预期按同样的权重），`pi` 是每格混合用的
        我方先动概率。"""
        b = len(h)
        picks = h[:, encode.PICK_POS:encode.PICK_POS + N]
        rows, cols = picks[:, BANNABLE[self.opp]], picks[:, BANNABLE[self.side]]
        hh = np.repeat(h, 16, axis=0)
        hh[:, encode.BAN_POS[self.opp]] = np.repeat(rows, 4, axis=1).ravel()
        hh[:, encode.BAN_POS[self.side]] = np.tile(cols, (1, 4)).ravel()
        f = net.forward(hh, [N, encode.POSTBAN])
        raw = self.mine(f.win[::16, 0])  # 后禁前（同一组 16 行一样）
        m = self.mine(f.win[:, 1]).reshape(b, 4, 4)
        ms = self.mine_split(f.split[:, 1]).reshape(b, 4, 4, 2)
        q = self.ban_rates[cols]
        q = q / q.sum(axis=1, keepdims=True)
        a = self.cfg.alpha
        arg = m.argmin(axis=2)
        row_worst = m.min(axis=2)
        row_exp = (m * q[:, None, :]).sum(axis=2)
        row_score = a * row_worst + (1 - a) * row_exp
        worst_split = np.take_along_axis(ms, arg[:, :, None, None], axis=2)[:, :, 0]
        exp_split = (ms * q[:, None, :, None]).sum(axis=2)
        score_split = a * worst_split + (1 - a) * exp_split
        best = row_score.argmax(axis=1)
        at = np.arange(b)
        pi = None if f.pi is None else self.mine(f.pi)
        return {"raw": raw, "value": row_score[at, best], "exp": row_exp[at, best], "worst": row_worst[at, best],
                "matrix": m, "rows": rows, "cols": cols, "q": q, "row_exp": row_exp, "row_worst": row_worst,
                "row_score": row_score, "best": best,
                "raw_split": self.mine_split(f.split[::16, 0]), "value_split": score_split[at, best],
                "exp_split": exp_split[at, best], "matrix_split": ms, "row_exp_split": exp_split,
                "raw_pi": None if pi is None else pi[::16, 0], "matrix_pi": None if pi is None else pi[:, 1].reshape(b, 4, 4)}

    def values(self, net: _Net, fills: np.ndarray, pick: bool) -> _Vals:
        """走到 fills 之后的模型胜率、值、预期、最坏、下一手分布（或 None）和各自的「我方先动时 / 后动时」；
        选完 10 手时值 = 后禁博弈的值。"""
        end = self.n + fills.shape[1]
        h = self.lines(fills)
        if end == N:
            d = self.ban_values(net, h)
            return _Vals(d["raw"], d["value"], d["exp"], d["worst"], None, d["raw_split"], d["value_split"],
                         d["exp_split"], d["raw_pi"])
        f = net.forward(h, [end], end if pick else None)
        v = self.mine(f.win[:, 0])
        s = self.mine_split(f.split[:, 0])
        return _Vals(v, v, v, v, f.probs, s, s, s, None if f.pi is None else self.mine(f.pi[:, 0]))

    def cost(self, rows: int, end: int) -> int:
        return rows * (16 if end == N else 1)

    # —— 候选 ——
    def limited(self, prior: np.ndarray, need: int) -> bool:
        """我方这一轮只在英雄池里选？没有英雄池、或池里能选的（先验 > 0 = 没被选、没被禁）不到 need 名时不限制。"""
        return self.pool is not None and int(np.count_nonzero(self.pool & (prior > 0))) >= need

    def eligible(self, prior: np.ndarray, mine: bool, need: int = 1) -> list[int]:
        """先验 prior [V]（不能选的是 0）→ 候选（按先验从高到低）。我方有英雄池时只在池里选，
        池里过不了筛的冷门英雄排在最后（靠打折压住）；池里能选的不到这一轮要选的 need 名时不限制（B14e2）。"""
        cfg = self.cfg
        ids = np.flatnonzero(prior > 0)
        pool = mine and self.limited(prior, need)
        if pool:
            ids = ids[self.pool[ids]]
        ids = ids[np.argsort(-prior[ids], kind="stable")]
        top = np.arange(len(ids)) < cfg.keep_top
        ok = (prior[ids] >= cfg.min_common) | (top & (self.counts[ids] >= cfg.rare_picks))
        keep = [int(i) for i in ids[ok]]
        if pool:
            keep += [int(i) for i in ids[~ok] if self.counts[i] < cfg.rare_picks]
            if len(keep) < need:  # 池很大、够数的都排在前 40 名以后又不常见：池里能选的全算
                keep = [int(i) for i in ids]
        return keep

    def trust(self, ids: Sequence[int], prior: np.ndarray) -> float:
        """这一手带来的胜率变化打几折：常见度 q / (q + c) × min(1, 被选次数 / 门槛)，两名取低的。"""
        cfg = self.cfg
        f = 1.0
        for i in ids:
            q = float(prior[i])
            f = min(f, q / (q + cfg.trust_c) * min(1.0, float(self.counts[i]) / cfg.rare_picks))
        return f

    def moves(self, n: int, ids: list[int], prior: np.ndarray, mine: bool) -> list[_Move]:
        """已选 n 手、轮到的一方这一轮的走法。"""
        k = rules.left_in_turn(n)
        if k == 1:
            return [_Move((a,), [(a,)], "one", self.trust((a,), prior), float(prior[a])) for a in ids]
        ids = sorted(ids, key=lambda i: -prior[i])
        prot = protected_index(n, 2) is not None
        out = []
        for a, b in combinations(ids, 2):
            if prot:
                variants, combine = [(a, b), (b, a)], "best"
            elif mine:
                variants, combine = [(a, b), (b, a)], "mean"
            else:
                variants, combine = [(a, b)], "one"
            out.append(_Move((a, b), variants, combine, self.trust((a, b), prior), float(prior[a] + prior[b])))
        return out

    def evaluate(self, net: _Net, items: list[tuple[tuple[int, ...], list[_Move]]], mine: bool, pick: bool,
                 force: bool = False) -> list[list[_Result]] | None:
        """每个 (父局面的 fills, 走法) 一起送进模型（父局面的 fills 一样长）。时间不够返回 None（force 时照算）。"""
        rows, owner = [], []
        for it, (parent, moves) in enumerate(items):
            for mi, mv in enumerate(moves):
                for var in mv.variants:
                    rows.append(parent + var)
                    owner.append((it, mi))
        if not rows:
            return [[] for _ in items]
        fills = np.array(rows, dtype=np.int64)
        end = self.n + fills.shape[1]
        if not force and not self.clock.affordable(self.cost(len(fills), end)):
            return None
        v = self.values(net, fills, pick and end < N)
        groups: list[list[list[int]]] = [[[] for _ in moves] for _, moves in items]
        for r, (it, mi) in enumerate(owner):
            groups[it][mi].append(r)
        out = []
        for it, (_, moves) in enumerate(items):
            lst = []
            for mi, mv in enumerate(moves):
                rs = groups[it][mi]
                if mv.combine == "mean":
                    lst.append(_Result(float(v.raw[rs].mean()), float(v.value[rs].mean()), float(v.exp[rs].mean()),
                                       float(v.worst[rs].mean()), mv.variants[0],
                                       v.probs[rs[0]] if v.probs is not None else None,
                                       v.s_raw[rs].mean(axis=0), v.s_value[rs].mean(axis=0), v.s_exp[rs].mean(axis=0),
                                       float(v.pi[rs].mean()) if v.pi is not None else None))
                    continue
                if mv.combine == "best":  # 含保护位：这一方挑对自己好的顺序（对手的就是对我方差的）
                    r = max(rs, key=lambda x: v.value[x]) if mine else min(rs, key=lambda x: v.value[x])
                else:
                    r = rs[0]
                lst.append(_Result(float(v.raw[r]), float(v.value[r]), float(v.exp[r]), float(v.worst[r]),
                                   mv.variants[rs.index(r)], v.probs[r] if v.probs is not None else None,
                                   v.s_raw[r], v.s_value[r], v.s_exp[r], float(v.pi[r]) if v.pi is not None else None))
            out.append(lst)
        return out

    def pair_priors(self, parent: tuple[int, ...], n_at: int, ids: list[int], prior: np.ndarray,
                    moves: list[_Move]) -> None:
        """对手连选两名：组合的先验 q(a)·q(b|a) + q(b)·q(a|b)，q(·|a) 是对手选了 a 之后选人头给的。"""
        if not ids:
            return
        fills = np.array([parent + (a,) for a in ids], dtype=np.int64)
        cond = self.main.forward(self.lines(fills), [n_at + 1], n_at + 1).probs
        row = {a: k for k, a in enumerate(ids)}
        for mv in moves:
            a, b = mv.ids
            mv.prior = float(prior[a] * cond[row[a], b] + prior[b] * cond[row[b], a])

    def their_moves(self, parent: tuple[int, ...], n_at: int, ids: list[int], prior: np.ndarray) -> list[_Move]:
        mv = self.moves(n_at, ids, prior, mine=False)
        if rules.left_in_turn(n_at) == 2:
            self.pair_priors(parent, n_at, ids, prior, mv)
        return mv

    def response_value(self, c: _Cand, mv: _Move, r: _Result, sub: float) -> float:
        """对手回应 mv（结果 r）之后、子树的值 sub → 加上这一手回应的修正。"""
        return sub + correction(mv.trust, r.raw - c.res.raw, mine=False)

    def finish(self, c: _Cand, vals: dict[int, float], depth: int, end: bool, splits: dict[int, np.ndarray]) -> None:
        """回应的值 → 子树的预期（按回应的先验加权）/ 最坏 → 打折 → 分数。splits = 每个值的「我方先动时 / 后动时」。"""
        p = np.array([max(c.responses[i][0].prior, 1e-12) for i in vals])
        v = np.array(list(vals.values()))
        c.exp, c.worst = float(p @ v / p.sum()), float(v.min())
        c.s_exp = p @ np.array([splits[i] for i in vals]) / p.sum()
        c.depth, c.end = depth, end
        self.depth = max(self.depth, depth)
        self.rescore(c)

    def rescore(self, c: _Cand) -> None:
        c.win, c.low = c.exp + c.corr, c.worst + c.corr
        c.s_win = c.s_exp + c.corr
        c.score = self.cfg.alpha * c.low + (1 - self.cfg.alpha) * c.win

    def shown_value(self, c: _Cand, v: float) -> float:
        """子树里某个值换成和候选的胜率同一口径（加上候选那一手的修正）。"""
        return v + c.corr

    # —— 轮到我方 ——
    def my_turn(self) -> dict:
        cfg, n = self.cfg, self.n
        self.cur, prior0 = self.root(self.main, pick=True)
        k = rules.left_in_turn(n)
        self.pool_short = self.pool is not None and not self.limited(prior0, k)
        moves1 = self.moves(n, self.eligible(prior0, mine=True, need=k), prior0, mine=True)
        n1 = n + rules.left_in_turn(n)
        cands = []
        for mv, r in zip(moves1, self.evaluate(self.main, [((), moves1)], mine=True, pick=True, force=True)[0]):
            c = _Cand(mv, r, corr=correction(mv.trust, r.raw - self.cur, True), end=n1 == N, exp=r.exp, worst=r.worst,
                      s_exp=r.s_exp)
            self.rescore(c)
            cands.append(c)
        cands.sort(key=lambda c: -c.score)
        if n1 < N and cands:
            self.level2(cands[:cfg.stage2], n1)
            n2 = n1 + rules.left_in_turn(n1)
            if n2 < N:
                deep = sorted((c for c in cands if c.depth >= 2), key=lambda c: -c.score)[:cfg.stage3]
                self.level3(deep, n2)
        # 算得深的排前面（同一层的分数才能比），同一层按分数
        ranked = sorted(cands, key=lambda c: (-c.end, -c.depth, -c.score))
        shown = ranked[:cfg.top]
        if self.second is not None:
            self.second_opinion(shown)
        return self.my_output(prior0, ranked, shown)

    def level2(self, cands: list[_Cand], n1: int) -> None:
        cfg = self.cfg
        k2 = rules.left_in_turn(n1)
        n2 = n1 + k2
        # 威胁：对手在第一名之后加上哪名英雄我方胜率掉得最多（打折后；所有候选共用）
        best = cands[0]
        e = self.eligible(best.res.probs, mine=False)
        tm = [_Move((a,), [(a,)], "one", self.trust((a,), best.res.probs)) for a in e]
        tr = self.evaluate(self.main, [(best.res.line, tm)], mine=False, pick=False, force=True)[0]
        harm = [self.response_value(best, mv, r, r.value) for mv, r in zip(tm, tr)]
        threats = [tm[i].ids[0] for i in np.argsort(harm)[:cfg.threats]]
        prot = protected_index(n1, 2) is not None
        for c in cands:
            prior = c.res.probs
            head = self.eligible(prior, mine=False)[:cfg.responses]
            ids = head + [t for t in threats if t not in head and prior[t] > 0]
            rows = len(ids) if k2 == 1 else len(ids) * (len(ids) - 1) // 2 * (2 if prot else 1)
            if not self.clock.affordable(self.cost(rows, n2) + len(ids)):
                break
            moves = self.their_moves(c.res.line, n1, ids, prior)
            res = self.evaluate(self.main, [(c.res.line, moves)], mine=False, pick=True)
            if res is None:
                break
            c.responses = list(zip(moves, res[0]))
            c.level2 = [self.response_value(c, mv, r, r.value) for mv, r in c.responses]
            c.level2_split = [r.s_value + (v - r.value) for (_, r), v in zip(c.responses, c.level2)]
            self.finish(c, dict(enumerate(c.level2)), 2, end=n2 == N, splits=dict(enumerate(c.level2_split)))

    def level3(self, cands: list[_Cand], n2: int) -> None:
        cfg = self.cfg
        n3 = n2 + rules.left_in_turn(n2)
        for c in cands:
            order = sorted(range(len(c.responses)), key=lambda i: -c.responses[i][0].prior)
            worst = sorted(range(len(c.responses)), key=lambda i: c.level2[i])
            pick = order[:cfg.responses3] + [i for i in worst[:cfg.threats3] if i not in order[:cfg.responses3]]
            items = []
            for i in pick:
                r = c.responses[i][1]
                ids = self.eligible(r.probs, mine=True, need=rules.left_in_turn(n2))[:cfg.replies]
                items.append((c.res.line + r.line, self.moves(n2, ids, r.probs, mine=True)))
            if not self.clock.affordable(self.cost(sum(len(m.variants) for _, ms in items for m in ms), n3)):
                break
            res = self.evaluate(self.main, items, mine=True, pick=False)
            if res is None:
                break
            vals, splits = {}, {}
            for i, (_, ms), rs in zip(pick, items, res):
                mv, r = c.responses[i]
                sub, sub_split = r.value, r.s_value
                if rs:  # 我方再回应：取最好的（加上再回应那一手的修正）。可信度不超过候选那一手的：
                    # 少见的候选在场时，模型对它和后面英雄搭配的估计也不准（高估常在再回应这一手才冒出来）
                    kids = [x.value + correction(min(m.trust, c.move.trust), x.raw - r.raw, True) for m, x in zip(ms, rs)]
                    j = int(np.argmax(kids))
                    sub, sub_split = kids[j], rs[j].s_value + (kids[j] - rs[j].value)
                    c.level3[i] = (self.response_value(c, mv, r, sub), rs[j].line)
                vals[i] = self.response_value(c, mv, r, sub)
                splits[i] = sub_split + (vals[i] - sub)
            self.finish(c, vals, 3, end=n3 == N, splits=splits)

    def second_opinion(self, shown: list[_Cand]) -> None:
        """第二个模型：每个列出的推荐重算到第 2 层（同样的回应、顺序、折扣），和主模型同一层的结果比。"""
        net = self.second
        cur2, _ = self.root(net)
        self.second_cur = cur2
        if not shown:
            return
        v1 = self.values(net, np.array([c.res.line for c in shown], dtype=np.int64), pick=False)
        raw1, exp1 = v1.raw, v1.exp
        for k, c in enumerate(shown):
            corr = correction(c.move.trust, raw1[k] - cur2, True)
            if c.responses:
                fills = np.array([c.res.line + r.line for _, r in c.responses], dtype=np.int64)
                v2 = self.values(net, fills, pick=False)
                raw2, val2 = v2.raw, v2.value
                p = np.array([max(mv.prior, 1e-12) for mv, _ in c.responses])
                sec = np.array([val2[i] + correction(mv.trust, raw2[i] - raw1[k], False)
                                for i, (mv, _) in enumerate(c.responses)])
                main = np.array(c.level2)
                out = {"win": float(p @ sec / p.sum()) + corr, "worst": float(sec.min()) + corr, "depth": 2}
                main_win = float(p @ main / p.sum()) + c.corr
            else:
                out = {"win": float(exp1[k]) + corr, "depth": 1}
                main_win = c.res.exp + c.corr
            out["spread"] = out["win"] - main_win
            c.second = out

    # —— 轮到对手 ——
    def their_turn(self) -> dict:
        cfg, n = self.cfg, self.n
        cur, prior0 = self.root(self.main, pick=True)
        ids = self.eligible(prior0, mine=False)
        if rules.left_in_turn(n) == 2:
            ids = ids[:cfg.opp_list]
        moves = self.their_moves((), n, ids, prior0)
        n1 = n + rules.left_in_turn(n)
        res = self.evaluate(self.main, [((), moves)], mine=False, pick=n1 < N, force=True)[0]
        items, keep, splits = [], [], []
        for mv, r in zip(moves, res):
            corr = correction(mv.trust, r.raw - cur, False)
            # 选完 10 手：后禁博弈推荐行的预期（同后禁这一步信息条上的）；否则先放模型读数，下面换成我方的读数
            now = (r.exp if n1 == N else r.value) + corr
            items.append({"heroes": [self.code(i) for i in r.line], "prob": mv.prior, "win": now, "now": now})
            keep.append((r, corr))
            splits.append((r.s_exp if n1 == N else r.s_value) + corr)
        # 我方的读数（B14e2 审核）：最可能的几种 + 模型读数最差的几种，往下算我方从英雄池里挑的回应
        likely = sorted(range(len(items)), key=lambda i: -items[i]["prob"])[:cfg.top]
        worst = [i for i in sorted(range(len(items)), key=lambda i: items[i]["now"]) if i not in likely][:cfg.threats]
        done = []
        for i in likely + worst:
            r, corr = keep[i]
            if n1 < N:
                got = self.reply_value(r.line, r.probs, r.raw, n1)
                if got is None:  # 时间不够：剩下的还是模型读数（stats.truncated）
                    break
                items[i]["win"], splits[i] = got[0] + corr, got[1] + corr
            done.append(i)
        for i, it in enumerate(items):
            self.put_split(it, splits[i], self.shown_first(keep[i][0].line))
        p = sum(items[i]["prob"] for i in done)
        expected = sum(items[i]["prob"] * items[i]["win"] for i in done) / p if p > 0 else None
        opponent = {"likely": [items[i] for i in likely], "win": expected}
        if expected is not None:
            self.put_split(opponent, sum(items[i]["prob"] * splits[i] for i in done) / p, self.shown_first())
        opponent["threats"] = sorted((items[i] for i in done), key=lambda x: x["win"])[:3]
        sec = self.root(self.second)[0] if self.second is not None else None
        return {**self.head("pick", "theirs", cur, sec), "opponent": opponent}

    def reply_value(self, parent: tuple[int, ...], probs: np.ndarray, raw0: float,
                    n1: int) -> tuple[float, np.ndarray] | None:
        """对手走完 parent（从根局面往下的 fills，之后已选 n1 手、轮到我方）之后「我方的读数」：我方这一轮从英雄池里挑
        最好的回应（先验前 their_replies 名；分数 = ½ 预期 + ½ 最坏，按对手下一轮先验前 responses 名的回应算），
        返回这个回应的预期（含我方回应的修正，同推荐卡的「预期」）和它的「我方先动时 / 后动时」。
        raw0 = parent 之后模型给的我方胜率。时间不够返回 None。"""
        cfg = self.cfg
        k1 = rules.left_in_turn(n1)
        n2 = n1 + k1
        mv1 = self.moves(n1, self.eligible(probs, mine=True, need=k1)[:cfg.their_replies], probs, mine=True)
        r1 = self.evaluate(self.main, [(parent, mv1)], mine=True, pick=True)
        if r1 is None or not mv1:
            return None
        cands = [(r, correction(mv.trust, r.raw - raw0, True)) for mv, r in zip(mv1, r1[0])]
        a = cfg.alpha
        if n2 == N:  # 我方这一轮选完就到后禁：叶子是后禁博弈
            r, c = max(cands, key=lambda x: a * (x[0].worst + x[1]) + (1 - a) * (x[0].exp + x[1]))
            return r.exp + c, r.s_exp + c
        top = sorted(cands, key=lambda x: -(x[0].value + x[1]))[:cfg.reply_cands]
        items = []
        for r, _ in top:
            line = parent + r.line
            items.append((line, self.their_moves(line, n2, self.eligible(r.probs, mine=False)[:cfg.responses], r.probs)))
        r2 = self.evaluate(self.main, items, mine=False, pick=False)
        if r2 is None:
            return None
        best = None
        for (r, c), (_, rmoves), rres in zip(top, items, r2):
            if rres:
                corr = np.array([correction(m.trust, x.raw - r.raw, False) for m, x in zip(rmoves, rres)])
                v = np.array([x.value for x in rres]) + corr
                sv = np.array([x.s_value for x in rres]) + corr[:, None]
                q = np.array([max(m.prior, 1e-12) for m in rmoves])
                exp, low, s_exp = float(q @ v / q.sum()), float(v.min()), q @ sv / q.sum()
            else:
                exp = low = r.value
                s_exp = r.s_value
            score = a * (low + c) + (1 - a) * (exp + c)
            if best is None or score > best[0]:
                best = (score, exp + c, s_exp + c)
        return best[1], best[2]

    # —— 后禁 ——
    def ban_turn(self) -> dict:
        h = self.lines(self.empty)
        d = self.ban_values(self.main, h)
        cur = float(d["raw"][0])
        self.root_pi = None if d["raw_pi"] is None else float(d["raw_pi"][0])
        m = d["matrix"][0]
        x, y, v = nash(m)
        # 英雄编号从局面里取：模型没见过的英雄按 UNK 算，从模型编号换不回来
        picks = self.tokens[encode.PICK_POS:encode.PICK_POS + N]
        rows, cols = [picks[j] for j in BANNABLE[self.opp]], [picks[j] for j in BANNABLE[self.side]]
        stats = [{"code": rows[i], "worst": float(d["row_worst"][0, i]), "win": float(d["row_exp"][0, i]),
                  "score": float(d["row_score"][0, i])} for i in range(len(rows))]
        q = d["q"][0]
        for i, s in enumerate(stats):  # 这一行（对方按后禁率）的「我方先动时 / 后动时」和对应的先动概率
            pis = d["matrix_pi"]
            self.put_split(s, d["row_exp_split"][0, i], None if pis is None else float(pis[0, i] @ q))
        sec, sec_cur = None, None
        if self.second is not None:
            d2 = self.ban_values(self.second, h)
            sec_cur = float(d2["raw"][0])
            for i, s in enumerate(stats):
                s["second"] = {"win": float(d2["row_exp"][0, i]), "worst": float(d2["row_worst"][0, i]),
                               "spread": float(d2["row_exp"][0, i] - d["row_exp"][0, i])}
            sec = {"matrix": d2["matrix"][0].tolist()}
        ms = d["matrix_split"][0]
        ban = {"rows": rows, "cols": cols, "matrix": m.tolist(), "row_stats": stats, "recommend": rows[int(d["best"][0])],
               "their_likely": [{"code": c, "prob": float(p)} for c, p in zip(cols, q)],
               "nash": {"mine": x.tolist(), "theirs": y.tolist(), "value": v}, "second": sec,
               # 每格：我方先动时 / 后动时的胜率、混合用的我方先动概率（4 打 4，先动 × 先动时 + 后动 × 后动时 = 这一格）
               "win_first": ms[..., 0].tolist(), "win_second": ms[..., 1].tolist(),
               "first": d["matrix_pi"][0].tolist() if d["matrix_pi"] is not None else None}
        return {**self.head("ban", None, cur, sec_cur), "ban": ban}

    # —— 输出 ——
    def shown_first(self, extra: Sequence[int] = ()) -> float | None:
        """页面上显示的我方先动概率（审核第 1、2 轮用户意见）：当前局面接着选 extra（主模型编号）之后，只按双方已经选出的
        英雄（不补还没选的几手）、双方段位 + 我方英雄池速度，用速度表算。一方还没有英雄、或没有速度表时 None。"""
        if not self.has_first:
            return None
        sides: dict[str, list[str]] = {s: [] for s in rules.SIDES}
        for j in range(self.n + len(extra)):
            code = self.tokens[encode.PICK_POS + j] if j < self.n else self.code(extra[j - self.n])
            if code:
                sides[rules.PICK_ORDER[j]].append(code)
        key = (tuple(sorted(sides["F"])), tuple(sorted(sides["S"])))
        if key not in self._shown:
            out = None
            if sides["F"] and sides["S"]:
                g = {"F": self.state.grades[0], "S": self.state.grades[1]}
                sp = self.speeds
                units = {s: [speed.Unit(s, c, g[s], sp.get(c) if s == self.side else None) for c in sides[s]]
                         for s in rules.SIDES}
                out = float(self.mine(self.adv.calc.prob(units["F"], units["S"], (g["F"], g["S"]), fill=False)))
            self._shown[key] = out
        return self._shown[key]

    def put_split(self, item: dict, split: np.ndarray, pi: float | None) -> None:
        """一个值的「我方先动时 / 后动时」两种胜率，和显示的先动概率 pi（选秀中见 `shown_first`；后禁每行 = 这一行 4 格
        按对方后禁率平均）。pi × 先动时 + (1 − pi) × 后动时 不一定等于主数字（后禁矩阵每格除外）。"""
        item["win_first"], item["win_second"] = float(split[0]), float(split[1])
        item["first"] = pi if self.has_first else None

    def head(self, phase: str, turn: str | None, cur: float, second: float | None) -> dict:
        # first：我方先动概率。选秀中只按双方已选的英雄（shown_first，一方还没有英雄时没有）；后禁 / 结束时是混合用的
        # （后禁前对 16 种被禁平均）。partial = 还不是最终上场的 4 打 4
        mine = self.shown_first() if phase == "pick" else self.root_pi
        first = None if mine is None else {"mine": mine, "partial": self.state.state != encode.POSTBAN}
        return {"phase": phase, "turn": turn, "side": self.side, "n": self.n, "slots": rules.left_in_turn(self.n),
                "win": cur, "second_win": second, "unknown": self.unknown, "first": first}

    def my_output(self, prior0: np.ndarray, ranked: list[_Cand], shown: list[_Cand]) -> dict:
        cfg = self.cfg
        k = rules.left_in_turn(self.n)
        prot = protected_index(self.n, k)
        best = shown[0].score if shown else 0.0
        runner = shown[1].score if len(shown) > 1 else None

        def response(i: int, c: _Cand) -> dict:
            mv, r = c.responses[i]
            out = {"heroes": [self.code(h) for h in r.line], "prob": mv.prior,
                   "win": self.shown_value(c, self.response_value(c, mv, r, r.value))}
            if i in c.level3:
                out["reply"] = [self.code(h) for h in c.level3[i][1]]
                out["reply_win"] = self.shown_value(c, c.level3[i][0])
            return out

        recs = []
        for rank, c in enumerate(shown):
            line = list(c.res.line)
            in_pool = self.pool is not None and not self.pool_short
            item = {"heroes": [self.code(h) for h in line], "protected": self.code(line[prot]) if prot is not None else None,
                    "score": c.score, "win": c.win, "worst": c.low,
                    "now": c.res.value + c.corr, "trust": c.move.trust,
                    "depth": c.depth, "end": c.end, "gap": c.score - best,
                    "close": bool((best - c.score < cfg.close_gap) if rank else (runner is not None and best - runner < cfg.close_gap)),
                    "common": [float(prior0[i]) for i in line],
                    "rare": [self.code(i) for i in line if self.counts[i] < cfg.rare_picks],
                    "pool_only": [self.code(i) for i in line if in_pool and self.counts[i] < cfg.rare_picks
                                  and prior0[i] < cfg.min_common],
                    "responses": [], "threat": None}
            if c.responses:
                order = sorted(range(len(c.responses)), key=lambda i: -c.responses[i][0].prior)
                item["responses"] = [response(i, c) for i in order[:3]]
                pool = list(c.level3) if c.level3 else range(len(c.responses))
                key = (lambda i: c.level3[i][0]) if c.level3 else (lambda i: c.level2[i])
                item["threat"] = response(min(pool, key=key), c)
            if c.second is not None:
                item["second"] = c.second
                item["uncertain"] = bool(abs(c.second["spread"]) >= cfg.uncertain_gap)
            # 预期的「我方先动时 / 后动时」（同样的回应和权重）；先动概率只按加上这一组之后已选的英雄
            self.put_split(item, c.s_win, self.shown_first(c.res.line))
            recs.append(item)
        heroes = []
        if k == 2:  # 按英雄：每名英雄取它所在最好的那组
            seen = set()
            for c in ranked:
                line = c.res.line
                for j, h in enumerate(line):
                    if h not in seen:
                        seen.add(h)
                        heroes.append({"code": self.code(h), "score": c.score, "win": c.win,
                                       "partner": self.code(line[1 - j]), "protected": prot == j})
                if len(heroes) >= cfg.top:
                    break
            heroes = heroes[:cfg.top]
        return {**self.head("pick", "mine", self.cur, self.second_cur), "recommend": recs, "heroes": heroes,
                "pool_short": self.pool_short}

    def run(self) -> dict:
        if self.state.state == encode.POSTBAN:
            f = self.main.forward(self.lines(self.empty), [encode.POSTBAN])
            self.root_pi = None if f.pi is None else float(self.mine(f.pi[0, 0]))
            sec = None
            if self.second is not None:
                sec = float(self.mine(self.second.forward(self.lines(self.empty), [encode.POSTBAN]).win[0, 0]))
            out = self.head("done", None, float(self.mine(f.win[0, 0])), sec)
            # 一个局面：first.mine 就是配套的先动概率（先动 × 先动时 + 后动 × 后动时 = win）
            out["win_first"], out["win_second"] = (float(x) for x in self.mine_split(f.split[0, 0]))
        elif self.n == N:
            out = self.ban_turn()
        elif rules.mover(self.n) == self.side:
            out = self.my_turn()
        else:
            out = self.their_turn()
        out["stats"] = {"ms": round(self.clock.elapsed() * 1000), "states": self.clock.rows,
                        "truncated": self.clock.truncated, "depth": self.depth}
        return out


class Advisor:
    """推荐器：主模型 + 第二个模型（可选）+ 数据先验 + 速度表（可选，B14g2：按先动概率混合胜率；没有就用「不知道
    谁先动」的头）。同一时间只跑一个搜索，结果按局面缓存。"""

    def __init__(self, model, priors: rpriors.Priors, second=None, cfg: SearchConfig | None = None,
                 speed_table: speed.SpeedTable | None = None):
        self.model, self.priors, self.second = model, priors, second
        self.cfg = cfg or SearchConfig()
        self.speed = speed_table
        # 占位（还没选的几手）按数据里每名英雄 / 每一手的被选次数（priors.json；旧文件没有每一手的就只按整体）
        self.calc = (speed.FirstCalc(speed_table, weights=dict(priors.picks) or None, slot_weights=priors.slots or None,
                                     **speed.FAST)
                     if speed_table is not None else None)
        vocab = model.vocab
        self.counts = np.zeros(vocab.size)
        self.ban_rates = np.full(vocab.size, priors.mean_ban_rate())
        for i in range(encode.FIRST_HERO, vocab.size):
            code = vocab.code(i)
            self.counts[i] = priors.pick_count(code)
            rate = priors.ban_rate(code)
            if rate is not None:
                self.ban_rates[i] = max(rate, 0.01)
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _cached(self, key: str, budget: float, compute) -> dict:
        with self._lock:
            hit = self._cache.get(key)
            if hit and (hit[1] >= budget or not hit[0]["stats"]["truncated"]):
                self._cache.move_to_end(key)
                out = json.loads(json.dumps(hit[0]))
                out["stats"]["cached"] = True
                return out
            out = compute()
            out["stats"]["cached"] = False
            out["stats"]["budget"] = budget
            self._cache[key] = (out, budget)
            while len(self._cache) > self.cfg.cache:
                self._cache.popitem(last=False)
            return json.loads(json.dumps(out))

    def first_ctx(self, grades: tuple[str | None, str | None],
                  speeds: tuple[dict[str, float] | None, dict[str, float] | None] = (None, None),
                  tokens: Sequence[str | None] | None = None) -> _FirstCtx | None:
        """一次搜索的先动概率（grades / speeds 按先手方、后手方）；没有速度表返回 None（用「不知道」的头）。"""
        if self.calc is None:
            return None
        return _FirstCtx(self.calc, self.model.vocab, grades, speeds, tokens)

    def win(self, states: Sequence[encode.DraftState], speeds: dict[str, dict[str, float]] | None = None) -> np.ndarray:
        """一批局面「先手方赢」的概率，和搜索同一口径（按先动概率混合；没有速度表用「不知道」的头）。
        speeds = {"F": {编号: 速度}, "S": {...}}。模拟 BP、验收统计的胜率曲线用。"""
        if self.calc is None:
            return self.model.win(states)
        first, ref = speed.first_pair(self.calc, states, speeds)
        return self.model.win(states, first, ref)

    def advise(self, state: encode.DraftState, side: str, pool: Sequence[str] | None = None, top: int | None = None,
               budget: float | None = None, speeds: dict[str, float] | None = None) -> dict:
        """当前局面的推荐。speeds = 我方英雄的速度（英雄池里填的，影响先动概率）。
        局面不合法抛 ValueError（args[0] 是中文问题列表）。"""
        if side not in rules.SIDES:
            raise ValueError([f"side 只能是 F / S：{side}"])
        problems = state.problems()
        if problems:
            raise ValueError(problems)
        budget = self.cfg.budget if budget is None else budget
        cfg = _with_top(self.cfg, top)
        speeds = {c: float(v) for c, v in (speeds or {}).items() if v} if self.calc is not None else {}
        key = json.dumps({"k": "advise", "s": state.to_dict(), "side": side, "pool": sorted(pool) if pool is not None else None,
                          "top": cfg.top, "speeds": speeds}, sort_keys=True, ensure_ascii=False)
        return self._cached(key, budget, lambda: _Search(self, cfg, state, side, pool, budget, speeds).run())

    def preban(self, side: str | None, grades: tuple[str | None, str | None] = (None, None),
               rule: str | None = encode.UNKNOWN_RULE, rule_category: str | None = None, fixed: str | None = None,
               top: int | None = None, budget: float | None = None) -> dict:
        """预禁推荐。side = 我方是先手 F / 后手 S / 不知道 None；grades = (我方, 对方)。"""
        if side not in (None, *rules.SIDES):
            raise ValueError([f"side 只能是 F / S / 不填：{side}"])
        budget = self.cfg.preban_budget if budget is None else budget
        cfg = _with_top(self.cfg, top)
        key = json.dumps({"k": "preban", "side": side, "g": list(grades), "r": rule, "c": rule_category, "f": fixed,
                          "top": cfg.top}, sort_keys=True, ensure_ascii=False)
        return self._cached(key, budget, lambda: _Preban(self, cfg, side, grades, rule, rule_category, fixed, budget).run())

    def info(self) -> dict:
        def one(m) -> dict | None:
            if m is None:
                return None
            meta = getattr(m, "meta", {}) or {}
            tm = ((meta.get("test_metrics") or {}).get("win") or {}).get("all", {}).get("11")
            return {"kind": meta.get("kind"), "run": meta.get("run"), "built": meta.get("built"),
                    "heroes": len(m.vocab.heroes), "trained_on": meta.get("trained_on"), "test_n11": tm}

        # codes：主模型里有的英雄（B14h 用户意见：RTA 助手和英雄池只用这些，别的只在图鉴里看）
        # mix：胜率怎么算（B14g2）：first = 按先动概率混合先动 / 后动两种，unknown = 「不知道谁先动」的头（没有速度表）
        return {"model": one(self.model), "second": one(self.second), "priors": self.priors.meta.get("built"),
                "rare_picks": self.cfg.rare_picks, "codes": list(self.model.vocab.heroes),
                "mix": "first" if self.calc is not None else "unknown"}


def _with_top(cfg: SearchConfig, top: int | None) -> SearchConfig:
    return cfg if not top or top == cfg.top else replace(cfg, top=top)


class _Preban:
    """预禁：我方候选 = 数据里常见的组合；对手 = 数据里最常见的组合按频率加权；胜率读「已选 0 手」的局面
    （模型能看到双方 4 名预禁；用选人头模拟的期望就是这个值，开工时测过自洽）。"""

    def __init__(self, adv: Advisor, cfg: SearchConfig, side, grades, rule, rule_category, fixed, budget):
        self.adv, self.cfg = adv, cfg
        self.roles = [side] if side else list(rules.SIDES)
        self.grades, self.rule, self.rule_category, self.fixed = grades, rule, rule_category, fixed
        self.vocab = adv.model.vocab
        self.clock = _Clock(budget, cfg.batch)

    def net(self, model, role: str) -> _Net:
        """我方是 role 时的推理；还没选人，先动概率全靠两方段位的占位（同一个先后手每行一样，按行的三个头混合）。"""
        mine, theirs = self.grades
        grades = (mine, theirs) if role == "F" else (theirs, mine)
        st = encode.DraftState(grades=grades, rule=self.rule, rule_category=self.rule_category)
        return _Net(model, st, self.vocab, self.clock, self.adv.first_ctx(grades))

    def pairs(self, role: str) -> list[tuple[tuple[str, str], float]]:
        """数据里这个先后手的预禁组合，只留模型里有的英雄（B14h 用户意见：模型没训练进的英雄不进 RTA 助手）。"""
        return [(p, s) for p, s in self.adv.priors.preban_pairs(role)
                if all(self.vocab.hero(c) >= encode.FIRST_HERO for c in p)]

    def candidates(self, role: str) -> list[tuple[str, str]]:
        cfg = self.cfg
        pairs = self.pairs(role)
        if not self.fixed:
            return [p for i, (p, s) in enumerate(pairs) if s >= cfg.preban_min_share or i < cfg.preban_keep_top]
        share: dict[str, float] = {}
        for (a, b), s in pairs:
            share[a] = share.get(a, 0) + s
            share[b] = share.get(b, 0) + s
        partners = [c for c, _ in sorted(share.items(), key=lambda kv: -kv[1])[:cfg.preban_partners]]
        partners += [b if a == self.fixed else a for (a, b), _ in pairs if self.fixed in (a, b)]
        out = []
        for y in partners:
            p = tuple(sorted((self.fixed, y)))
            if y != self.fixed and p not in out:
                out.append(p)
        return out

    def evaluate(self, net: _Net, role: str, mine: list[tuple[str, str]], theirs: list[tuple[str, str]]) -> np.ndarray:
        """[len(mine), len(theirs)] 我方胜率。"""
        h = np.zeros((len(mine) * len(theirs), encode.SEQ_LEN), dtype=np.int64)
        ids = lambda p: [self.vocab.hero(c) for c in p]  # noqa: E731
        h[:, list(encode.PREBAN_POS[role])] = np.repeat(np.array([ids(p) for p in mine]), len(theirs), axis=0)
        h[:, list(encode.PREBAN_POS[other(role)])] = np.tile(np.array([ids(p) for p in theirs]), (len(mine), 1))
        w = net.forward(h, [0]).win
        w = w[:, 0] if role == "F" else 1.0 - w[:, 0]
        return w.reshape(len(mine), len(theirs))

    def run(self) -> dict:
        cfg = self.cfg
        cands: list[tuple[str, str]] = []
        for role in self.roles:
            for p in self.candidates(role):
                if p not in cands:
                    cands.append(p)
        per_role = {}
        for role in self.roles:
            opp = self.pairs(other(role))[:cfg.preban_opponents]
            wts = np.array([s for _, s in opp])
            per_role[role] = {"theirs": [p for p, _ in opp], "w": wts / wts.sum(), "net": self.net(self.adv.model, role),
                              "share": dict(self.pairs(role)), "m": []}
        per_cand = sum(len(v["theirs"]) for v in per_role.values())
        step = max(1, cfg.batch * 4 // max(per_cand, 1))
        done = 0
        while done < len(cands):  # 候选按数据里的常见程度排好，时间不够时少算后面的
            part = cands[done:done + step]
            if done and not self.clock.affordable(len(part) * per_cand):
                break
            for role, v in per_role.items():
                v["m"].append(self.evaluate(v["net"], role, part, v["theirs"]))
            done += len(part)
        cands = cands[:done]
        for v in per_role.values():
            v["m"] = np.concatenate(v["m"]) if v["m"] else np.zeros((0, len(v["theirs"])))
        exp = np.mean([v["m"] @ v["w"] for v in per_role.values()], axis=0)
        worst = np.mean([v["m"][:, :cfg.preban_worst].min(axis=1) for v in per_role.values()], axis=0)
        score = cfg.alpha * worst + (1 - cfg.alpha) * exp
        order = np.argsort(-score)
        best = float(score[order[0]]) if len(order) else 0.0
        recs = []
        for rank, i in enumerate(order[:cfg.top]):
            worst_vs = {r: list(v["theirs"][int(np.argmin(v["m"][i, :cfg.preban_worst]))]) for r, v in per_role.items()}
            recs.append({"heroes": list(cands[i]), "score": float(score[i]), "win": float(exp[i]), "worst": float(worst[i]),
                         "worst_vs": worst_vs, "gap": float(score[i]) - best,
                         "share": {r: float(v["share"].get(cands[i], 0.0)) for r, v in per_role.items()},
                         "close": bool((best - float(score[i]) < cfg.close_gap) if rank else
                                       (len(order) > 1 and best - float(score[order[1]]) < cfg.close_gap))})
        if self.adv.second is not None and recs:
            shown = [tuple(r["heroes"]) for r in recs]
            sec = np.mean([self.evaluate(self.net(self.adv.second, role), role, shown, v["theirs"]) @ v["w"]
                           for role, v in per_role.items()], axis=0)
            for r, s in zip(recs, sec):
                r["second"] = {"win": float(s), "spread": float(s) - r["win"]}
                r["uncertain"] = bool(abs(float(s) - r["win"]) >= cfg.uncertain_gap)
        heroes, seen = [], set()
        for i in order:
            for j, h in enumerate(cands[i]):
                if h not in seen:
                    seen.add(h)
                    heroes.append({"code": h, "score": float(score[i]), "win": float(exp[i]), "partner": cands[i][1 - j]})
            if len(heroes) >= cfg.top:
                break
        theirs = {r: [{"heroes": list(p), "share": float(s)} for p, s in self.pairs(other(r))[:5]]
                  for r in self.roles}
        return {"phase": "preban", "side": self.roles[0] if len(self.roles) == 1 else None, "recommend": recs,
                "heroes": heroes[:cfg.top], "theirs": theirs,
                "stats": {"ms": round(self.clock.elapsed() * 1000), "states": self.clock.rows,
                          "truncated": self.clock.truncated, "candidates": len(cands)}}


@lru_cache(maxsize=1)
def load() -> Advisor:
    """随包的推荐器（主模型 + 第二个模型 + priors.json），进程内只读一次。"""
    second_dir = rmodel.bundled_dir() / SECOND_DIR
    second = rmodel.load(second_dir) if rmodel.available(second_dir) else None
    return Advisor(rmodel.load(), rpriors.load(), second, speed_table=speed.load())


def available() -> bool:
    return rmodel.available() and rpriors.available()
