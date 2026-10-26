"""RTA 模型的特征编码（B14b）：训练（`core/rta/train`）和运行（`model.py`）共用这一份，只依赖 numpy。

一场选秀 = 17 个 token：

    位置  0      CTX（双方段位档 + 开战规则，编号放在 ctx 数组里）
          1–4    预禁：先手方 2 名、后手方 2 名（开局就公开）
          5–14   选秀第 1…10 手（谁选见 rules.PICK_ORDER）
          15–16  后禁：先手方被禁的那名、后手方被禁的那名

0–4 互相可见，之后是因果注意力，所以一次前向能读出 12 个局面：已选 n 手（n = 0…10）读位置 4 + n，
后禁之后（n = 11）读位置 16。胜率一律是「先手方赢」的概率（后手方 = 1 − p）；
选人头给的是下一手（轮到的那一方）选各名英雄的概率，这一方这一轮要连选 2 名时两名各占一半。
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from . import rules
from .battle import Match

SEQ_LEN = 17
PREBAN_POS = {"F": (1, 2), "S": (3, 4)}
PICK_POS = 5  # 第 k 手（0 起）在 PICK_POS + k
BAN_POS = {"F": 15, "S": 16}  # 这一方被禁的那名
N_PICKS = len(rules.PICK_ORDER)
N_STATES = N_PICKS + 2  # 已选 0…10 手 + 后禁之后
POSTBAN = N_PICKS + 1  # 后禁之后的局面编号 11
STATE_POS = np.array([PICK_POS - 1 + n for n in range(N_PICKS + 1)] + [BAN_POS["S"]], dtype=np.int64)
PREFIX_LEN = PICK_POS  # 0–4 互相可见

# token 类型
CTX, PREBAN_F, PREBAN_S, PICK_F, PICK_S, BANNED_F, BANNED_S = range(7)
N_TYPES = 7
TOKEN_TYPES = np.array(
    [CTX, PREBAN_F, PREBAN_F, PREBAN_S, PREBAN_S]
    + [PICK_F if s == "F" else PICK_S for s in rules.PICK_ORDER] + [BANNED_F, BANNED_S], dtype=np.int64)
# 位置编号：同一方的两个预禁共用一个（预禁是集合，没有先后）
POSITION_IDS = np.array([0, 1, 1, 2, 2] + list(range(3, 3 + N_PICKS)) + [3 + N_PICKS, 4 + N_PICKS], dtype=np.int64)
N_POSITIONS = int(POSITION_IDS.max()) + 1

# 英雄编号里的特殊值
PAD = 0  # 空位：CTX、没预禁、还没选、还没后禁
UNK = 1  # 词表外的英雄
FIRST_HERO = 2

# ctx 数组：[先手方段位档, 后手方段位档, 开战规则]
GRADE_UNKNOWN = 0  # 段位档编号 = rules.GRADE_BUCKETS 的下标 + 1
N_GRADES = len(rules.GRADE_BUCKETS) + 1
RULE_NONE = 0  # 没有开战规则（有一方低于优胜者）
RULE_UNKNOWN = 1  # 不知道有没有 / 是哪条（国服接口没有这个字段）
UNKNOWN_RULE = "unknown"  # DraftState.rule 用这个值表示「不知道」


def attention_mask() -> np.ndarray:
    """[17, 17] 布尔矩阵，mask[i, j] = 位置 i 能看到位置 j。"""
    i = np.arange(SEQ_LEN)[:, None]
    j = np.arange(SEQ_LEN)[None, :]
    return (j <= i) | ((i < PREFIX_LEN) & (j < PREFIX_LEN))


def pick_targets(n: int) -> list[tuple[int, float]]:
    """已选 n 手时选人头的标签：[(token 位置, 权重)]。这一轮连选 2 名时两名各 0.5（同一轮里的先后没意义）。"""
    if not 0 <= n < N_PICKS:
        return []
    left = rules.left_in_turn(n)
    return [(PICK_POS + n + k, 1.0 / left) for k in range(left)]


def grade_id(grade: str | None) -> int:
    bucket = rules.grade_bucket(grade)
    return rules.GRADE_BUCKETS.index(bucket) + 1 if bucket else GRADE_UNKNOWN


@dataclass
class Vocab:
    """英雄词表和开战规则表。英雄编号 = FIRST_HERO + 下标，规则编号 = 2 + 下标。"""
    heroes: list[str]
    rules: list[tuple[str, str | None]] = field(default_factory=list)  # (opening_rule_desc_tid, 类别)
    min_picks: int = 30

    def __post_init__(self) -> None:
        self._hero = {c: FIRST_HERO + i for i, c in enumerate(self.heroes)}
        self._rule = {tid: 2 + i for i, (tid, _) in enumerate(self.rules)}
        self._category: dict[str, int] = {}
        for i, (_, cat) in enumerate(self.rules):
            if cat:
                self._category.setdefault(cat, 2 + i)

    @property
    def size(self) -> int:
        """英雄编号的个数（含 PAD / UNK），也就是选人头的输出维度。"""
        return FIRST_HERO + len(self.heroes)

    @property
    def n_rules(self) -> int:
        return 2 + len(self.rules)

    def hero(self, code: str | None) -> int:
        if not code:
            return PAD
        return self._hero.get(code, UNK)

    def code(self, hero_id: int) -> str | None:
        """英雄编号 → 英雄编号字符串；PAD / UNK 返回 None。"""
        i = int(hero_id) - FIRST_HERO
        return self.heroes[i] if 0 <= i < len(self.heroes) else None

    def rule(self, tid: str | None, category: str | None = None) -> int:
        """开战规则 → 编号。None = 没有规则；UNKNOWN_RULE = 不知道；没见过的规则按类别找同类的，再不行算不知道。"""
        if tid is None:
            return RULE_NONE
        if tid == UNKNOWN_RULE:
            return RULE_UNKNOWN
        if tid in self._rule:
            return self._rule[tid]
        return self._category.get(category or "", RULE_UNKNOWN)

    def lut(self, codes: Sequence[str]) -> np.ndarray:
        """codes[i] → 英雄编号的查找表（数据集里存的是 codes 的下标，-1 = 空位，用 lut[idx + 1]）。"""
        return np.array([PAD] + [self.hero(c) for c in codes], dtype=np.int64)

    def to_dict(self) -> dict:
        return {"heroes": self.heroes, "rules": [list(r) for r in self.rules], "min_picks": self.min_picks}

    @classmethod
    def from_dict(cls, d: Mapping) -> Vocab:
        return cls(heroes=list(d["heroes"]), rules=[(r[0], r[1]) for r in d.get("rules", [])],
                   min_picks=int(d.get("min_picks", 30)))

    @classmethod
    def build(cls, pick_counts: Mapping[str, int], rules_seen: Iterable[tuple[str, str | None]],
              min_picks: int = 30) -> Vocab:
        """选过 ≥ min_picks 次的英雄按次数从多到少进词表；规则按出现顺序去重。"""
        heroes = [c for c, n in sorted(pick_counts.items(), key=lambda kv: (-kv[1], kv[0])) if n >= min_picks]
        seen: dict[str, str | None] = {}
        for tid, cat in rules_seen:
            if tid and tid != UNKNOWN_RULE:
                seen.setdefault(tid, cat)
        return cls(heroes=heroes, rules=sorted(seen.items()), min_picks=min_picks)

    def save(self, path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")


def match_rule(m: Match) -> str | None:
    """一场对局的开战规则输入：国服接口没有这个字段 → 不知道；海外没有规则（有一方低于优胜者）→ None。"""
    if m.server == "cn" and not m.rule:
        return UNKNOWN_RULE
    return m.rule


def match_tokens(m: Match) -> list[str | None]:
    """一场对局 → 17 个位置上的英雄编号（CTX 和空位是 None）。"""
    out: list[str | None] = [None] * SEQ_LEN
    for side in rules.SIDES:
        s = m.side(side)
        for pos, code in zip(PREBAN_POS[side], s.prebans[:rules.PREBANS_PER_SIDE]):
            out[pos] = code
        out[BAN_POS[side]] = s.banned
    for k, (_, code) in enumerate(m.sequence()):
        out[PICK_POS + k] = code
    return out


@dataclass
class DraftState:
    """一个选秀局面（运行时用，F = 先手方、S = 后手方）。

    picks 按这一方的选人顺序；banned[F] 是先手方被对方禁掉的那名（后禁之后才有）；
    rule：None = 没有开战规则，UNKNOWN_RULE = 不知道（国服），其余是 opening_rule_desc_tid。
    """
    prebans: dict[str, list[str]] = field(default_factory=lambda: {"F": [], "S": []})
    picks: dict[str, list[str]] = field(default_factory=lambda: {"F": [], "S": []})
    banned: dict[str, str | None] = field(default_factory=lambda: {"F": None, "S": None})
    grades: tuple[str | None, str | None] = (None, None)
    rule: str | None = UNKNOWN_RULE
    rule_category: str | None = None

    @property
    def n_picks(self) -> int:
        return len(self.picks.get("F", ())) + len(self.picks.get("S", ()))

    @property
    def state(self) -> int:
        """局面编号 0…11：已选几手；选完且双方都后禁了是 11。"""
        n = self.n_picks
        if n == N_PICKS and all(self.banned.get(s) for s in rules.SIDES):
            return POSTBAN
        return n

    def mover(self) -> str | None:
        return rules.mover(self.n_picks)

    def problems(self) -> list[str]:
        banned = {s: self.banned.get(s) for s in rules.SIDES}
        return rules.validate(self.prebans, self.picks, banned)

    def tokens(self) -> list[str | None]:
        out: list[str | None] = [None] * SEQ_LEN
        for side in rules.SIDES:
            for pos, code in zip(PREBAN_POS[side], list(self.prebans.get(side, ()))[:rules.PREBANS_PER_SIDE]):
                out[pos] = code
            if self.state == POSTBAN:
                out[BAN_POS[side]] = self.banned[side]
        for k, (_, code) in enumerate(rules.interleave(self.picks.get("F", []), self.picks.get("S", []))):
            out[PICK_POS + k] = code
        return out

    def to_dict(self) -> dict:
        return {"prebans": self.prebans, "picks": self.picks, "banned": self.banned, "grades": list(self.grades),
                "rule": self.rule, "rule_category": self.rule_category}

    @classmethod
    def from_dict(cls, d: Mapping) -> DraftState:
        return cls(prebans={s: list(d["prebans"].get(s, [])) for s in rules.SIDES},
                   picks={s: list(d["picks"].get(s, [])) for s in rules.SIDES},
                   banned={s: d.get("banned", {}).get(s) for s in rules.SIDES},
                   grades=tuple(d.get("grades") or (None, None)), rule=d.get("rule"), rule_category=d.get("rule_category"))

    @classmethod
    def from_match(cls, m: Match, n: int = POSTBAN) -> DraftState:
        """一场对局在局面 n 时的样子（测试和 parity 样例用）。"""
        seq = m.sequence()[:min(n, N_PICKS)]
        picks = {"F": [c for s, c in seq if s == "F"], "S": [c for s, c in seq if s == "S"]}
        banned = {s: m.side(s).banned for s in rules.SIDES} if n == POSTBAN else {"F": None, "S": None}
        return cls(prebans={"F": list(m.first.prebans), "S": list(m.second.prebans)}, picks=picks, banned=banned,
                   grades=(m.first.grade, m.second.grade), rule=match_rule(m), rule_category=m.rule_category)


def encode_states(states: Sequence[DraftState], vocab: Vocab) -> dict[str, np.ndarray]:
    """一批局面 → 模型输入：heroes [B, 17]、ctx [B, 3]（int64），以及每个局面的编号 state [B]。"""
    heroes = np.zeros((len(states), SEQ_LEN), dtype=np.int64)
    ctx = np.zeros((len(states), 3), dtype=np.int64)
    state = np.zeros(len(states), dtype=np.int64)
    for i, st in enumerate(states):
        heroes[i] = [vocab.hero(c) for c in st.tokens()]
        ctx[i] = (grade_id(st.grades[0]), grade_id(st.grades[1]), vocab.rule(st.rule, st.rule_category))
        state[i] = st.state
    return {"heroes": heroes, "ctx": ctx, "state": state}


def pick_mask(heroes: np.ndarray, state: np.ndarray, size: int) -> np.ndarray:
    """[B, size] 布尔：局面 state 时下一手能选谁（PAD、UNK、被预禁的、已经选了的都不能选）。"""
    ok = np.ones((len(heroes), size), dtype=bool)
    ok[:, :FIRST_HERO] = False
    for i, (row, n) in enumerate(zip(heroes, state)):
        taken = row[1:PICK_POS + min(int(n), N_PICKS)]
        ok[i, taken[taken >= FIRST_HERO]] = False
    return ok


def pick_counts(tokens: np.ndarray, codes: Sequence[str]) -> Counter:
    """数据集的 token 下标（-1 = 空位）→ 每名英雄在选秀位置上出现的次数（建词表用）。"""
    picks = tokens[:, PICK_POS:PICK_POS + N_PICKS].ravel()
    counts = np.bincount(picks[picks >= 0], minlength=len(codes))
    return Counter({codes[i]: int(n) for i, n in enumerate(counts) if n})
