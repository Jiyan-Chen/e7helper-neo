"""先动概率（B14d1）：战斗里谁第一个行动。只依赖 numpy。

速度表（随包 `assets/data/rta/speed.json`，`e7helper rta speed` 生成）：
- 290 以下：官方「英雄分析」按赛季 × 段位 × 英雄的速度直方图（`herostats.py`），口径「60 级 / 6 星满觉醒 /
  穿戴全部装备」，每档 20 速：110–130 … 270–290，最后一档「290 以上」。第 1 档混着很慢的和缺数据的。
  B14h：直方图里有大量「没算装备」的记录（基础速度到「基础 × 1.25」那几档的孤立尖峰），先去掉（`clean_hists`），
  再按开局行动条反推的低速比例把真的慢速配装补回（`refit_low`）。
- 290 以上：官方只给占比，看不到 320、340 的一速。用开局行动条反推（`fit_tails`）：同场速度在中间档的英雄当参照，
  行动条 ≈ 开局随机 + 速度 × 经过的时间，参照英雄的速度已知（直方图中位数），就能算出经过的时间，再用它反推
  290 以上英雄的速度。290 以上再分 290–310 / 310–330 / 330–350 / 350–370 四档，每名英雄每个段位一份，
  样本少的向这个段位所有英雄的合计收缩。
- 开局规则（`RULES`）：智武首次战斗开始时 +30% 行动条；赫尔赛蒂（只在 PvP 生效）把其他英雄的速度限制在她的 90% 以下。
  天秤之主是别人加行动条时跟着加，开局不触发（用户意见），不算。
- 开局随机：每名英雄 0–jitter% 行动条（社区说法 5%，`rta speed` 在有行动条的对局上选）。
- 英雄池里填了速度的英雄，用填的速度。

先动概率：每名英雄按自己的段位抽速度（蒙特卡洛），到 100 的时间 = (100 − 开局行动条) ÷ 速度，最先到的先动。
同样的输入结果相同（固定随机种子）。

B14g1：胜率模型分三种「谁先动」，用的时候按先动概率混合（段位只用来算先动概率）。`FirstCalc` 是同一个模型的快速版
（按分布积分、不抽样，一批阵容一次算完），`state_first_probs` / `match_first_probs` 给选秀局面 / 训练快照的对局用；
选秀中间还没选的那几手用「这一手常被选的英雄」的混合补（`slot_counts`）。
"""

from __future__ import annotations

import dataclasses
import json
import math
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import rules

SPEED_FILE = "speed.json"
FORMAT = 1
OFFICIAL_BINS = 10  # 官方直方图 10 档：110–130 … 270–290、290 以上
TAIL_BINS = 4  # 290 以上再分 4 档
EDGES = np.arange(110, 371, 20, dtype=float)  # 13 档的边界 110, 130, …, 370
TOP = 290.0
# 段位：官方英雄分析只有大师到传说
GRADES = ("master", "challenger", "champion", "warlord", "emperor", "legend")
# 拟合前 290 以上四档的先验：B14d1 方案阶段 198 场样本（112 场能反推）的粗估
PRIOR_TAIL = (0.45, 0.35, 0.15, 0.05)
JITTER = 5.0
JITTER_CHOICES = (0.0, 2.5, 5.0, 7.5, 10.0)
# 开局随机量从「谁先动」上很难分辨（合成数据里 0–10% 的 log loss 只差约 0.001），比默认好不到这么多就不换
JITTER_MIN_GAIN = 0.002
SHRINK = 20.0  # 尾部：每名英雄向段位合计收缩的强度（相当于这么多场）
GRADE_PRIOR = 50.0  # 段位合计向 PRIOR_TAIL 收缩的强度
# 开局规则：push = 首次战斗开始加的行动条；cap = 把其他英雄的速度限制在自己的这个比例以下
RULES: dict[str, dict] = {
    "c1133": {"push": 30.0, "note": "智武：首次战斗开始时行动条 +30%"},
    "c1153": {"cap": 0.9, "note": "赫尔赛蒂：其他英雄的速度限制在她的 90% 以下（PvP）"},
}
# 反推尾部时的参照英雄：290 以上占比 < 这个、第 1 档占比 < 这个、行动条在这个范围
ANCHOR_TOP = 0.2
ANCHOR_LOW = 0.3
ANCHOR_ENERGY = (20, 95)
MIN_ANCHORS = 3
SAMPLES = 4000
# 官方直方图里「没算装备」的记录（B14h 用国际服快照时发现）：很多英雄在基础速度到「基础 × 1.25」（只算速度套）
# 那几档有孤立的尖峰，传说段也有 10%–50%（修里 55%、苏琳 41%），不可能是真实配装。这几档（下边界 ≤ 基础 × 1.25
# + CLEAN_MARGIN）里最高的一档比紧挨的上一档多 CLEAN_RATIO 倍以上，就整块去掉（`clean_hists`）。高档的配速尖峰
# （小泡芙 210–230 占 87%）不动。
CLEAN_RATIO = 5.0
CLEAN_MARGIN = 5.0
# 去掉的低档里有真的慢速配装（宝剑君主伊赛丽亚反推中位 130、八成低于 150）：用开局行动条反推的低速比例补回（`refit_low`）
LOW_MIN = 30  # 这名英雄在这个段位至少反推这么多次才补
LOW_SHRINK = 20.0  # 低速比例向 0（全是瑕疵）收缩的强度（相当于这么多次）


def analysis_grade(grade: str | None) -> str | None:
    """段位（官方 grade_code 或模型的段位档）→ 英雄分析的段位；金牌及以下按大师算；不知道是 None。"""
    if grade in GRADES:
        return grade
    if grade in rules.GRADES:  # 铜牌 / 银牌 / 金牌
        return GRADES[0]
    return None


@dataclass
class Unit:
    side: str  # 哪一方（调用方自己定，例如 "mine" / "theirs" 或 "F" / "S"）
    code: str
    grade: str | None = None
    speed: float | None = None  # 已知速度（英雄池里填的）


class SpeedTable:
    """速度表：每名英雄每个段位 13 档的概率 + 开局规则 + 开局随机的范围。"""

    def __init__(self, data: dict):
        self.data = data
        self.jitter = float(data.get("jitter", JITTER))
        self.rules = {**RULES, **(data.get("rules") or {})}
        self.season = data.get("season")
        self.hists: dict[str, dict[str, np.ndarray]] = {}
        self.tails: dict[str, dict[str, np.ndarray]] = {}
        for code, grades in (data.get("heroes") or {}).items():
            for grade, d in grades.items():
                h = np.asarray(d["hist"], dtype=float)
                if len(h) == OFFICIAL_BINS and h.sum() > 0:
                    self.hists.setdefault(code, {})[grade] = h
                    if d.get("tail"):
                        self.tails.setdefault(code, {})[grade] = _norm(np.asarray(d["tail"], dtype=float))
        self.grade_tails = {g: _norm(np.asarray(t, dtype=float)) for g, t in (data.get("grade_tails") or {}).items()}
        self._dist: dict[tuple[str, str | None], np.ndarray | None] = {}

    @classmethod
    def from_hists(cls, hists: dict[str, dict[str, Sequence[int]]], **extra) -> SpeedTable:
        return cls({"format": FORMAT, "heroes": {c: {g: {"hist": list(h)} for g, h in gs.items()}
                                                 for c, gs in hists.items()}, **extra})

    # —— 分布 ——
    def tail(self, code: str, grade: str) -> np.ndarray:
        t = self.tails.get(code, {}).get(grade)
        if t is not None:
            return t
        return self.grade_tails.get(grade, np.asarray(PRIOR_TAIL, dtype=float))

    def _grade_dist(self, code: str, grade: str) -> np.ndarray:
        h = self.hists[code][grade]
        p = h / h.sum()
        return np.concatenate([p[:OFFICIAL_BINS - 1], p[OFFICIAL_BINS - 1] * self.tail(code, grade)])

    def dist(self, code: str, grade: str | None = None) -> np.ndarray | None:
        """13 档的概率；没有这个段位用最近的段位；段位不知道用各段位按人数混合；没有这名英雄返回 None。"""
        g = analysis_grade(grade)
        key = (code, g)
        if key in self._dist:
            return self._dist[key]
        have = self.hists.get(code)
        out = None
        if have:
            if g is None:
                total = sum(h.sum() for h in have.values())
                out = sum(self._grade_dist(code, x) * (have[x].sum() / total) for x in have)
            else:
                i = GRADES.index(g)
                near = min(have, key=lambda x: (abs(GRADES.index(x) - i), -GRADES.index(x)))
                out = self._grade_dist(code, near)
        self._dist[key] = out
        return out

    def average(self, grade: str | None = None) -> np.ndarray:
        """这个段位所有英雄合计的分布（没有数据的英雄用它）。"""
        g = analysis_grade(grade)
        key = ("*", g)
        if key not in self._dist:
            acc = np.zeros(OFFICIAL_BINS)
            for have in self.hists.values():
                for x, h in have.items():
                    if g is None or x == g:
                        acc += h
            if not acc.sum():
                acc = np.ones(OFFICIAL_BINS)
            p = acc / acc.sum()
            t = self.grade_tails.get(g or "", np.asarray(PRIOR_TAIL, dtype=float))
            self._dist[key] = np.concatenate([p[:OFFICIAL_BINS - 1], p[OFFICIAL_BINS - 1] * t])
        return self._dist[key]

    def quantiles(self, p: np.ndarray, qs: Sequence[float] = (0.25, 0.5, 0.75)) -> list[float]:
        cdf = np.cumsum(p)
        out = []
        for q in qs:
            k = int(min(np.searchsorted(cdf, q), len(p) - 1))
            lo = cdf[k - 1] if k else 0.0
            f = (q - lo) / max(cdf[k] - lo, 1e-12)
            out.append(float(EDGES[k] + min(max(f, 0.0), 1.0) * (EDGES[k + 1] - EDGES[k])))
        return out

    def top_share(self, p: np.ndarray) -> float:
        return float(p[OFFICIAL_BINS - 1:].sum())

    def sample(self, p: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
        k = rng.choice(len(p), n, p=p / p.sum())
        return EDGES[k] + rng.uniform(0, 1, n) * (EDGES[k + 1] - EDGES[k])

    def info(self) -> dict:
        return {"season": self.season, "built": self.data.get("built"), "heroes": len(self.hists),
                "jitter": self.jitter, "tails": sum(len(t) for t in self.tails.values()),
                "fit": self.data.get("fit"), "rules": {c: r.get("note") for c, r in self.rules.items()}}


def _norm(p: np.ndarray) -> np.ndarray:
    s = p.sum()
    return p / s if s > 0 else np.full(len(p), 1.0 / len(p))


# —— 先动概率 ——

def first_mover(table: SpeedTable, units: Sequence[Unit], *, n: int = SAMPLES, seed: int = 0,
                jitter: float | None = None) -> dict:
    """这些英雄里谁先动：{"sides": {一方: 概率}, "heroes": [每名英雄的先动概率、速度分布、用了哪条规则]}。"""
    if not units:
        return {"sides": {}, "heroes": []}
    rng = np.random.default_rng(seed)
    jitter = table.jitter if jitter is None else jitter
    speeds, heroes = [], []
    for u in units:
        info = {"side": u.side, "code": u.code, "fixed": u.speed, "no_data": False, "speed": None,
                "rule": (table.rules.get(u.code) or {}).get("note")}
        if u.speed:
            speeds.append(np.full(n, float(u.speed)))
        else:
            p = table.dist(u.code, u.grade)
            if p is None:
                p = table.average(u.grade)
                info["no_data"] = True
            speeds.append(table.sample(p, n, rng))
            info["speed"] = [round(x) for x in table.quantiles(p)]
        heroes.append(info)
    s = np.stack(speeds)
    r = rng.uniform(0, jitter, s.shape) if jitter > 0 else np.zeros_like(s)
    for k, u in enumerate(units):
        rule = table.rules.get(u.code) or {}
        if rule.get("push"):
            r[k] += float(rule["push"])
    for k, u in enumerate(units):
        cap = (table.rules.get(u.code) or {}).get("cap")
        if cap:
            own = s[k].copy()
            s = np.minimum(s, cap * own)
            s[k] = own
    t = (100.0 - np.minimum(r, 100.0)) / s
    first = np.argmin(t, axis=0)
    share = np.bincount(first, minlength=len(units)) / n
    sides: dict[str, float] = defaultdict(float)
    for k, u in enumerate(units):
        heroes[k]["p"] = float(share[k])
        sides[u.side] += float(share[k])
    return {"sides": dict(sides), "heroes": heroes}


# —— 快速先动概率（B14g：胜率按先动概率混合，评估和搜索里一次要算几千到几十万个阵容） ——

# 「等效速度」网格：到 100 的时间 = 100 ÷ 它（640 … 40，每档 2），覆盖开局加行动条的英雄和英雄池里填的 50–400
GRID_SPEEDS = np.arange(640.0, 39.0, -2.0)
GRID = 100.0 / GRID_SPEEDS
QUAD = 8  # 开局随机按几个点积分
CAP_LEVELS = 8  # 有限速英雄（赫尔赛蒂）时按她的速度分几档分别算再平均
TEAM = rules.PICKS_PER_SIDE - 1  # 上场 4 名
# 搜索用的快速档（B14g2）：网格每档 4、限速分 4 档、float32，比默认快约 3 倍；和默认差 p95 0.07、最多约 0.1 个百分点
# （有赫尔赛蒂的阵容几乎总是她那一方先动，除非对方有开局加行动条的，分 4 档和 8 档一样）
FAST = {"step": 4.0, "levels": 4, "dtype": np.float32}


def _integrate(log_a: np.ndarray, log_b: np.ndarray) -> np.ndarray:
    """两方「最先到的时间」的对数生存函数 [B, K] → a 方先到的概率 [B]：∫ P(T_b > x) d(−P(T_a > x))（梯形）。"""
    sa, sb = np.exp(log_a), np.exp(log_b)
    da = np.empty_like(sa)  # P(T_a > x_{k−1}) − P(T_a > x_k)，x_{−1} 处是 1
    da[:, 0] = 1.0 - sa[:, 0]
    np.subtract(sa[:, :-1], sa[:, 1:], out=da[:, 1:])
    mb = np.empty_like(sb)  # 区间两端 P(T_b > x) 的平均
    mb[:, 0] = 0.5 * (1.0 + sb[:, 0])
    np.add(sb[:, :-1], sb[:, 1:], out=mb[:, 1:])
    mb[:, 1:] *= 0.5
    return np.einsum("bk,bk->b", da, mb).astype(np.float64)


class FirstCalc:
    """快速先动概率（B14g），和 `first_mover` 同一个模型，但按速度分布直接积分、不抽样，一批阵容一次算完。

    每名英雄到 100 的时间 t = (100 − 开局行动条) ÷ 速度，开局行动条 = 开局随机 U(0, jitter) + 开局效果；一方最先到的
    时间 T = min t，英雄之间独立，所以 P(T > x) = Π P(t > x)（对数相加），P(a 方先动) = ∫ P(T_b > x) d(−P(T_a > x))。
    时间按 GRID 离散，每名英雄（段位、填的速度、限速）的对数生存函数缓存起来。
    - 一方不到 4 名时用「占位」补还没选的那几手：slot_weights（一方第 k 手各英雄被选的次数，k = 0…4）给了就是
      「这一手随便一名被选的英雄」（先选的多是快的，后面几手偏慢），否则用 weights（不分第几手的被选次数），都没有用
      这个段位官方直方图的合计（偏慢：官方合计按配装数，RTA 里常选的多是快的）。模型没见过的英雄（编号 None）也用后两种。
    - 赫尔赛蒂把其他英雄的速度限制在她的 90% 以下，英雄不再独立：按她的速度分 CAP_LEVELS 档分别算再平均。
    """

    def __init__(self, table: SpeedTable, *, weights: dict[str, float] | None = None,
                 slot_weights: Sequence[dict[str, float]] | None = None, levels: int = CAP_LEVELS,
                 step: float = 2.0, dtype=np.float64):
        """step = 网格每档几速、levels = 限速分几档、dtype = 表和积分的精度（搜索用 `FAST`，评估用默认）。"""
        self.table = table
        self.levels = levels
        self.grid = 100.0 / np.arange(640.0, 39.0, -step)  # 到 100 的时间（见 GRID）
        self.dtype = dtype
        self.weights = _normalize(weights)
        self.slot_weights = [_normalize(w) for w in slot_weights] if slot_weights else None
        self._cache: dict[tuple, np.ndarray] = {}
        self._tables: dict[tuple, np.ndarray] = {}  # tables() 的结果（B14g2：搜索里同一组编号反复用）

    def _rule(self, code: str | None) -> dict:
        return (self.table.rules.get(code) or {}) if code else {}

    def _survival(self, code: str | None, grade: str | None, speed: float | None, cap: float | None) -> np.ndarray:
        """[K] P(t > GRID[k])，code None = 官方直方图的合计。"""
        push = float(self._rule(code).get("push") or 0.0)
        jitter = self.table.jitter
        if speed:
            s = min(float(speed), cap) if cap else float(speed)
            room = 100.0 - push - self.grid * s  # 开局随机 < room 才比 x 晚到
            return np.clip(room / jitter, 0.0, 1.0) if jitter > 0 else (room > 0).astype(float)
        p = self.table.dist(code, grade) if code else None
        if p is None:
            p = self.table.average(grade)
        cdf = np.concatenate([[0.0], np.cumsum(p / p.sum())])
        r = push + jitter * (np.arange(QUAD) + 0.5) / QUAD
        y = (100.0 - np.minimum(r, 100.0))[:, None] / self.grid[None, :]  # 要比 x 晚到，速度得低于 y
        f = np.interp(y, EDGES, cdf)
        if cap:
            f = np.where(y >= cap, 1.0, f)
        return f.mean(axis=0)

    def _mixture(self, weights: dict[str, float], grade: str | None, cap: float | None) -> np.ndarray:
        return np.log(np.maximum(sum(w * np.exp(self.log_survival(c, grade, None, cap)) for c, w in weights.items()),
                                 1e-300))

    def log_survival(self, code: str | None, grade: str | None = None, speed: float | None = None,
                     cap: float | None = None) -> np.ndarray:
        """[K] log P(t > GRID[k])。code None = 不分第几手的占位（模型没见过的英雄也用它）；speed = 填的速度；
        cap = 被限速到多少。"""
        key = (code, analysis_grade(grade), speed, cap)
        hit = self._cache.get(key)
        if hit is None:
            hit = (self._mixture(self.weights, grade, cap) if code is None and self.weights
                   else np.log(np.maximum(self._survival(code, grade, speed, cap), 1e-300)))
            self._cache[key] = hit
        return hit

    def fills(self, grade: str | None, cap: float | None = None) -> np.ndarray:
        """[TEAM + 1, K]：一方已经有 m 名时，补上第 m … TEAM − 1 手的占位之和（m ≥ TEAM 是 0）。"""
        key = ("#fills", analysis_grade(grade), cap)
        hit = self._cache.get(key)
        if hit is None:
            slots = [self._mixture(self.slot_weights[k], grade, cap) if self.slot_weights and self.slot_weights[k]
                     else self.log_survival(None, grade, None, cap) for k in range(TEAM)]
            hit = np.zeros((TEAM + 1, len(self.grid)))
            for m in range(TEAM - 1, -1, -1):
                hit[m] = hit[m + 1] + slots[m]
            self._cache[key] = hit
        return hit

    def tables(self, codes: Sequence[str | None], grade: str | None, speeds: dict[str, float] | None = None,
               cap: float | None = None) -> np.ndarray:
        """一组编号（例如 [None, None] + 词表）→ [len(codes) + TEAM + 1, K] 对数生存表：每个编号一行（None = 占位），
        最后 TEAM + 1 行是 `fills`（已有 m 名时补上的占位）。结果缓存起来，**不要改**返回的数组。"""
        speeds = speeds or {}
        key = (tuple(codes), analysis_grade(grade), tuple(sorted((c, float(v)) for c, v in speeds.items() if v)), cap)
        hit = self._tables.get(key)
        if hit is None:
            rows = [self.log_survival(c, grade, speeds.get(c) if c else None, cap) for c in codes]
            hit = np.concatenate([np.stack(rows), self.fills(grade, cap)])
            if self.dtype != np.float64:  # float32：截到 e^−60（≈ 0），team_log 减空位时不丢精度
                hit = np.maximum(hit, -60.0).astype(self.dtype)
            hit.setflags(write=False)
            if len(self._tables) > 256:
                self._tables.clear()
            self._tables[key] = hit
        return hit

    def team_log(self, ids: np.ndarray, table: np.ndarray, pad: int = 0) -> np.ndarray:
        """ids [B, m]（table 的行号，pad = 空位）→ 这一方最先到的时间的对数生存函数 [B, K]；不到 4 名用占位补。"""
        ids = np.asarray(ids, dtype=np.int64).reshape(len(ids), -1)
        n = np.count_nonzero(ids != pad, axis=1)
        out = table[ids].sum(axis=1)  # 空位也加进去了，下面减掉
        out -= (ids.shape[1] - n)[:, None].astype(table.dtype) * table[pad][None, :]
        return out + table[len(table) - TEAM - 1 + np.minimum(n, TEAM)]

    def prob_ids(self, ids_a: np.ndarray, ids_b: np.ndarray, table_a: np.ndarray, table_b: np.ndarray,
                 pad: int = 0, chunk: int = 4096, own: tuple[int, int, np.ndarray] | None = None) -> np.ndarray:
        """一批阵容（行号，两方各一份表）→ a 方先动的概率 [B]（不管限速英雄，见 `prob_batch`）。
        own = (哪一方 0 / 1, 行号, 对数生存函数)：这一方里这个行号的英雄改用给的那一行（限速英雄自己不被限速）。"""
        out = np.empty(len(ids_a))
        for s in range(0, len(ids_a), chunk):
            la = self.team_log(ids_a[s:s + chunk], table_a, pad)
            lb = self.team_log(ids_b[s:s + chunk], table_b, pad)
            if own is not None:
                side, row, log = own
                ids, tab, acc = (ids_a, table_a, la) if side == 0 else (ids_b, table_b, lb)
                n = (np.asarray(ids[s:s + chunk]).reshape(len(acc), -1) == row).sum(axis=1)
                acc += n[:, None].astype(acc.dtype) * (log - tab[row]).astype(acc.dtype)[None, :]
            out[s:s + chunk] = _integrate(la, lb)
        return out

    def cap_levels(self, u: Unit) -> list[float]:
        """限速英雄的速度分几档（填了速度就是那一个）：分布的 (i + ½) / levels 分位数。"""
        if u.speed:
            return [float(u.speed)]
        p = self.table.dist(u.code, u.grade)
        if p is None:
            p = self.table.average(u.grade)
        return self.table.quantiles(p, [(i + 0.5) / self.levels for i in range(self.levels)])

    def prob_batch(self, ids_a: np.ndarray, ids_b: np.ndarray, codes: Sequence[str | None],
                   grades: tuple[str | None, str | None] = (None, None),
                   speeds: tuple[dict[str, float] | None, dict[str, float] | None] = (None, None),
                   pad: int = 0) -> np.ndarray:
        """一批阵容（codes 的行号，两方各自一个段位）→ a 方先动的概率 [B]。有限速英雄的行按她的速度分档、
        其余英雄限速后分别算再平均。"""
        ids_a = np.asarray(ids_a, dtype=np.int64).reshape(len(ids_a), -1)
        ids_b = np.asarray(ids_b, dtype=np.int64).reshape(len(ids_b), -1)
        tabs = [self.tables(codes, grades[i], speeds[i]) for i in (0, 1)]
        out = np.empty(len(ids_a))
        rest = np.ones(len(ids_a), dtype=bool)
        for c in {i for i, code in enumerate(codes) if code and self._rule(code).get("cap")}:
            for side, ids in enumerate((ids_a, ids_b)):
                rows = (ids == c).any(axis=1) & rest
                if not rows.any():
                    continue
                rest &= ~rows
                code = codes[c]
                acc = np.zeros(int(rows.sum()))
                levels = self.cap_levels(Unit("", code, grades[side], (speeds[side] or {}).get(code)))
                for v in levels:
                    cap = float(self._rule(code)["cap"]) * v
                    t = [self.tables(codes, grades[i], speeds[i], cap) for i in (0, 1)]
                    own = (side, c, self.log_survival(code, grades[side], v, None))  # 她自己不被限速
                    acc += self.prob_ids(ids_a[rows], ids_b[rows], t[0], t[1], pad, own=own)
                out[rows] = acc / len(levels)
        if rest.any():
            out[rest] = self.prob_ids(ids_a[rest], ids_b[rest], tabs[0], tabs[1], pad)
        return out

    def prob(self, a: Sequence[Unit], b: Sequence[Unit], grades: tuple[str | None, str | None] = (None, None),
             fill: bool = True) -> float:
        """a 方先动的概率（单个阵容，英雄按这一方的选人顺序）。每方不到 4 名时用各自段位（grades）的占位补还没选的
        那几手（fill=False 不补：只看已有的英雄，B14g2 页面显示用；两方都要有英雄）；Unit.grade 没填的用这一方的段位。"""
        units = [*a, *b]
        cap_unit = next((u for u in units if self._rule(u.code).get("cap")), None)
        levels = self.cap_levels(Unit("", cap_unit.code, cap_unit.grade or grades[0 if cap_unit in a else 1],
                                      cap_unit.speed)) if cap_unit else [None]
        total = 0.0
        for v in levels:
            cap = float(self._rule(cap_unit.code)["cap"]) * v if cap_unit else None

            def side(units: Sequence[Unit], grade: str | None) -> np.ndarray:
                acc = np.zeros(len(self.grid))
                for u in units:
                    if u is cap_unit:
                        acc += self.log_survival(u.code, u.grade or grade, v, None)
                    else:
                        acc += self.log_survival(u.code, u.grade or grade, u.speed, cap)
                return acc + self.fills(grade, cap)[min(len(units), TEAM)] if fill else acc

            total += float(_integrate(side(a, grades[0])[None], side(b, grades[1])[None])[0])
        return total / len(levels)


def _normalize(weights: dict[str, float] | None) -> dict[str, float] | None:
    total = sum(w for w in (weights or {}).values() if w > 0)
    return {c: w / total for c, w in weights.items() if w > 0} if total else None


def slot_counts(tokens: np.ndarray, codes: Sequence[str]) -> list[dict[str, int]]:
    """训练快照的 tokens（-1 = 空位）→ 一方第 k 手（k = 0…4，两方合在一起）各英雄被选的次数（`FirstCalc` 的占位用）。"""
    out = []
    for k in range(rules.PICKS_PER_SIDE):
        cols = [5 + _ORDER_SLOTS[s][k] for s in rules.SIDES]  # encode.PICK_POS = 5
        v = tokens[:, cols].ravel()
        counts = np.bincount(v[v >= 0], minlength=len(codes))
        out.append({codes[i]: int(c) for i, c in enumerate(counts) if c})
    return out


def _side_options(picks: Sequence[str], banned: str | None) -> list[list[str]]:
    """一方最后上场的可能：后禁了就去掉被禁的；5 名都在、还没后禁时 = 去掉一名可被禁的（保护位除外）的各种情况。"""
    if banned:
        return [[c for c in picks if c != banned]]
    if len(picks) > TEAM:
        return [[c for j, c in enumerate(picks) if j != i] for i in range(len(picks)) if i != rules.PROTECTED_SLOT]
    return [list(picks)]


POSTBAN_STATE = 2 * rules.PICKS_PER_SIDE + 1  # 后禁之后的局面编号（= encode.POSTBAN，这里不 import encode）
_ORDER_SLOTS = {s: [k for k, x in enumerate(rules.PICK_ORDER) if x == s] for s in rules.SIDES}


def state_first_probs(calc: FirstCalc, states: Sequence, speeds: dict[str, dict[str, float]] | None = None) -> np.ndarray:
    """每个选秀局面（encode.DraftState）先手方先动的概率 [B]：双方目前在场的英雄（后禁了去掉被禁的），不到 4 名用
    各自段位的占位补；5 名都在、还没后禁时对各种被禁的情况平均。speeds = {"F": {编号: 速度}, "S": {...}}（英雄池里填的）。"""
    speeds = speeds or {}
    out = np.empty(len(states))
    for i, st in enumerate(states):
        g = {"F": st.grades[0], "S": st.grades[1]}
        opts = {s: _side_options(st.picks.get(s, []), st.banned.get(s) if st.state == POSTBAN_STATE else None)
                for s in rules.SIDES}
        unit = lambda s, c: Unit(s, c, g[s], (speeds.get(s) or {}).get(c))  # noqa: E731
        ps = [calc.prob([unit("F", c) for c in f], [unit("S", c) for c in sd], (g["F"], g["S"]))
              for f in opts["F"] for sd in opts["S"]]
        out[i] = float(np.mean(ps))
    return out


def first_pair(calc: FirstCalc, states: Sequence, speeds: dict[str, dict[str, float]] | None = None
               ) -> tuple[np.ndarray, np.ndarray]:
    """选秀局面 → (按双方段位 + 英雄池速度算的先动概率, 同一阵容按一般玩家（不知道段位、没填速度）算的)，
    就是 `model.mix` / `RtaModel.win` 的 first / ref（B14g1：段位、速度只通过这两者的差影响胜率）。"""
    ref_states = [dataclasses.replace(st, grades=(None, None)) for st in states]
    return state_first_probs(calc, states, speeds), state_first_probs(calc, ref_states, None)


def _canon(a: np.ndarray, pad: int) -> np.ndarray:
    """一方按顺序的已选 [B, m]（行号）→ [保护位, 其余（排好序）]：先动概率和顺序无关，只和谁在保护位（不会被后禁）有关。"""
    if a.shape[1] > rules.PROTECTED_SLOT:
        prot, rest = a[:, [rules.PROTECTED_SLOT]], np.delete(a, rules.PROTECTED_SLOT, axis=1)
    else:
        prot, rest = np.full((len(a), 1), pad, dtype=a.dtype), a
    return np.concatenate([prot, np.sort(rest, axis=1)], axis=1)


def ids_first_probs(calc: FirstCalc, ids: np.ndarray, states: Sequence[int], codes: Sequence[str | None],
                    grades: tuple[str | None, str | None] = (None, None),
                    speeds: tuple[dict[str, float] | None, dict[str, float] | None] = (None, None),
                    pad: int = 0) -> np.ndarray:
    """一批选秀局面（`encode` 的 17 个位置，值是 codes 的行号，pad = 空位）→ 局面 states[j] 先手方先动的概率
    [B, len(states)]（B14g2 搜索用）。规则同 `state_first_probs`：后禁之后去掉被禁的；一方 5 名都在、还没后禁时对
    去掉一名（保护位除外）的各种情况平均；不到 4 名用各自段位的占位补。同一阵容（不管顺序）只算一次。"""
    ids = np.asarray(ids, dtype=np.int64)
    out = np.empty((len(ids), len(states)))
    for j, state in enumerate(states):
        k = min(int(state), 2 * rules.PICKS_PER_SIDE)
        sides = []
        for t, s in enumerate(rules.SIDES):
            a = ids[:, [5 + x for x in _ORDER_SLOTS[s] if x < k]].copy()  # encode.PICK_POS = 5
            if state == POSTBAN_STATE:  # 去掉被禁的那名（只去一名）
                ban = ids[:, [15 + t]]  # encode.BAN_POS
                hit = (a == ban) & (ban != pad)
                a[hit & (np.cumsum(hit, axis=1) == 1)] = pad
            sides.append(_canon(a, pad))
        key = np.concatenate(sides, axis=1)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        cut = sides[0].shape[1]
        opts = []
        for part in (uniq[:, :cut], uniq[:, cut:]):
            if state != POSTBAN_STATE and part.shape[1] > TEAM:  # 5 名都在：去掉一名（第 0 列是保护位，不去）
                opts.append([np.delete(part, i, axis=1) for i in range(1, part.shape[1])])
            else:
                opts.append([part])
        a_all = np.concatenate([fa for fa in opts[0] for _ in opts[1]])
        b_all = np.concatenate([sb for _ in opts[0] for sb in opts[1]])
        p = calc.prob_batch(a_all, b_all, codes, grades, speeds, pad).reshape(-1, len(uniq))
        out[:, j] = p.mean(axis=0)[inv]
    return out


def match_first_probs(calc: FirstCalc, tokens: np.ndarray, codes: Sequence[str], grade_ids: np.ndarray) -> np.ndarray:
    """训练快照的对局（`Dataset.tokens` 的行、英雄表、`Dataset.grades` 段位档编号）→ 每场 12 个局面先手方先动的概率
    [N, 12]，规则同 `state_first_probs`（评估三头模型用）。"""
    n = len(tokens)
    out = np.empty((n, POSTBAN_STATE + 1))
    buckets = [None, *rules.GRADE_BUCKETS]  # 段位档编号 → 段位档（0 = 不知道）
    names = [None, *codes]  # tokens 的下标 + 1 → 编号（-1 空位 → 0）
    idx = tokens.astype(np.int64) + 1
    pick_ids = idx[:, 5:5 + 2 * rules.PICKS_PER_SIDE]  # encode.PICK_POS = 5
    ban_ids = idx[:, 15:17]  # encode.BAN_POS
    gf, gs = grade_ids[:, 0], grade_ids[:, 1]
    groups = [(a, b, (gf == a) & (gs == b)) for a in np.unique(gf) for b in np.unique(gs)]
    for state in range(POSTBAN_STATE + 1):
        k = min(state, 2 * rules.PICKS_PER_SIDE)
        side_ids = {s: pick_ids[:, [j for j in _ORDER_SLOTS[s] if j < k]] for s in rules.SIDES}
        if state == POSTBAN_STATE:  # 去掉被禁的那名（换成空位）
            for t, s in enumerate(rules.SIDES):
                ids = side_ids[s].copy()
                ids[ids == ban_ids[:, [t]]] = 0
                side_ids[s] = ids
        opts = {}
        for s in rules.SIDES:  # 5 名都在、还没后禁：去掉一名可被禁的各种情况
            ids = side_ids[s]
            if ids.shape[1] > TEAM and state != POSTBAN_STATE:
                opts[s] = [np.delete(ids, i, axis=1) for i in range(ids.shape[1]) if i != rules.PROTECTED_SLOT]
            else:
                opts[s] = [ids]
        acc = np.zeros(n)
        for fa in opts["F"]:
            for sb in opts["S"]:
                for a, b, m in groups:
                    if m.any():
                        acc[m] += calc.prob_batch(fa[m], sb[m], names, (buckets[a], buckets[b]))
        out[:, state] = acc / (len(opts["F"]) * len(opts["S"]))
    return out


# —— 从开局行动条反推 290 以上（开发用：rta speed） ——

@dataclass
class EnergyUnit:
    code: str
    side: str  # F / S
    grade: str | None
    energy: int


def match_units(m) -> list[EnergyUnit] | None:
    """一场对局（`battle.Match`）里上场的 8 名英雄和开局行动条；没有行动条返回 None。"""
    if m.first_mover is None:
        return None
    out = []
    for s in rules.SIDES:
        side = m.side(s)
        for p in side.picks:
            if not p.banned and p.energy is not None:
                out.append(EnergyUnit(p.code, s, side.grade or None, int(p.energy)))
    return out if len(out) == 2 * (rules.PICKS_PER_SIDE - 1) else None


def _elapsed(table: SpeedTable, units: Sequence[EnergyUnit], half: float) -> float | None:
    """参照英雄 → 第一个行动前经过的「时间」（行动条 / 速度）；参照不够返回 None。"""
    est = []
    for u in units:
        if u.energy >= 100 or u.code in table.rules or not ANCHOR_ENERGY[0] <= u.energy <= ANCHOR_ENERGY[1]:
            continue
        p = table.dist(u.code, u.grade)
        if p is None or table.top_share(p) >= ANCHOR_TOP or p[0] >= ANCHOR_LOW:
            continue
        est.append((u.energy - half) / table.quantiles(p, (0.5,))[0])
    return float(np.median(est)) if len(est) >= MIN_ANCHORS else None


def implied_speeds(table: SpeedTable, units: Sequence[EnergyUnit]) -> list[float | None] | None:
    """按参照英雄反推这场每名英雄的速度（有开局规则的、对局里有限速英雄的不反推）；参照不够返回 None。"""
    if any((table.rules.get(u.code) or {}).get("cap") for u in units):
        return None
    half = table.jitter / 2
    t = _elapsed(table, units, half)
    if not t:
        return None
    out: list[float | None] = []
    for u in units:
        push = float((table.rules.get(u.code) or {}).get("push") or 0)
        out.append(None if push else (u.energy - half) / t)
    return out


def fit_tails(table: SpeedTable, matches: Iterable[Sequence[EnergyUnit]], *, shrink: float = SHRINK,
              grade_prior: float = GRADE_PRIOR) -> dict:
    """反推 290 以上四档 → {"heroes": {英雄: {段位: [4 档]}}, "grade_tails": {段位: [4 档]}, "check": 核对, "used": 场数}。

    核对：每名英雄每个段位，反推出 ≥ 290 的比例 vs 官方直方图 290 以上的占比（两者接近说明参照的绝对值没偏）。"""
    counts: dict[tuple[str, str], np.ndarray] = defaultdict(lambda: np.zeros(TAIL_BINS))
    check: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])  # [反推 ≥ 290, 反推总数]
    used = 0
    for units in matches:
        est = implied_speeds(table, units)
        if est is None:
            continue
        used += 1
        for u, s in zip(units, est):
            g = analysis_grade(u.grade)
            p = table.dist(u.code, g)
            if s is None or g is None or p is None or table.top_share(p) < 0.05:
                continue
            c = check[(u.code, g)]
            c[1] += 1
            if s >= TOP:
                c[0] += 1
                counts[(u.code, g)][min(TAIL_BINS - 1, int((s - TOP) // 20))] += 1
    grade_counts: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(TAIL_BINS))
    for (_, g), c in counts.items():
        grade_counts[g] += c
    prior = np.asarray(PRIOR_TAIL, dtype=float)
    grade_tails = {g: (c + grade_prior * prior) / (c.sum() + grade_prior) for g, c in grade_counts.items()}
    heroes: dict[str, dict[str, list[float]]] = {}
    for (code, g), c in counts.items():
        base = grade_tails.get(g, prior)
        heroes.setdefault(code, {})[g] = [round(float(x), 4) for x in (c + shrink * base) / (c.sum() + shrink)]
    rows = []
    for (code, g), (hi, n) in check.items():
        p = table.dist(code, g)
        rows.append({"code": code, "grade": g, "n": n, "implied_top": round(hi / n, 4),
                     "official_top": round(table.top_share(p), 4) if p is not None else None})
    return {"heroes": heroes, "grade_tails": {g: [round(float(x), 4) for x in t] for g, t in grade_tails.items()},
            "check": sorted(rows, key=lambda r: -r["n"]), "used": used}


def residuals(table: SpeedTable, matches: Iterable[Sequence[EnergyUnit]], min_n: int = 20) -> list[dict]:
    """每名英雄：实际行动条 − 按速度中位数应有的行动条（不含先动者）。明显偏高的可能有没登记的开局加行动条。"""
    acc: dict[str, list[float]] = defaultdict(list)
    firsts: dict[str, int] = defaultdict(int)
    for units in matches:
        if any((table.rules.get(u.code) or {}).get("cap") for u in units):
            continue
        half = table.jitter / 2
        t = _elapsed(table, units, half)
        if not t:
            continue
        for u in units:
            if u.energy >= 100:
                firsts[u.code] += 1
                continue
            p = table.dist(u.code, u.grade)
            if p is not None:
                acc[u.code].append(u.energy - (half + table.quantiles(p, (0.5,))[0] * t))
    out = [{"code": c, "n": len(v), "mean": round(float(np.mean(v)), 2), "first": firsts[c]}
           for c, v in acc.items() if len(v) >= min_n]
    return sorted(out, key=lambda r: -r["mean"])


def evaluate(table: SpeedTable, matches: Sequence[Sequence[EnergyUnit]], *, n: int = 1000,
             jitter: float | None = None) -> dict:
    """在有行动条的对局上验收：只看双方 8 名英雄预测「先手方先动」的 log loss（瞎猜 0.693）、命中率、
    先动英雄猜中率、按预测概率分 5 档的校准。"""
    ll, hit, hero_hit, bins = [], 0, 0, defaultdict(lambda: [0, 0.0, 0])
    for k, units in enumerate(matches):
        res = first_mover(table, [Unit(u.side, u.code, u.grade) for u in units], n=n, seed=k, jitter=jitter)
        p = min(max(res["sides"].get("F", 0.0), 0.01), 0.99)
        f_first = any(u.energy >= 100 and u.side == "F" for u in units)
        ll.append(-math.log(p if f_first else 1 - p))
        hit += (p > 0.5) == f_first
        top = max(range(len(units)), key=lambda i: res["heroes"][i]["p"])
        hero_hit += units[top].energy >= 100
        b = bins[min(4, int(p * 5))]
        b[0] += 1
        b[1] += p
        b[2] += f_first
    m = len(matches)
    if not m:
        return {"matches": 0}
    return {"matches": m, "log_loss": round(float(np.mean(ll)), 4), "accuracy": round(hit / m, 4),
            "hero_hit": round(hero_hit / m, 4),
            "calibration": [{"bin": f"{i * 20}–{i * 20 + 20}%", "n": b[0], "predicted": round(b[1] / b[0], 4),
                             "actual": round(b[2] / b[0], 4)} for i, b in sorted(bins.items()) if b[0]]}


def choose_jitter(table: SpeedTable, matches: Sequence[Sequence[EnergyUnit]], choices: Sequence[float] = JITTER_CHOICES,
                  n: int = 1000) -> tuple[float, dict[float, float]]:
    """开局随机取多大：在这些对局上 log loss 最低的那个；比默认（JITTER）好不到 JITTER_MIN_GAIN 就用默认。"""
    scores = {j: evaluate(table, matches, n=n, jitter=j)["log_loss"] for j in choices}
    best = min(scores, key=lambda j: scores[j])
    if JITTER in scores and scores[JITTER] - scores[best] < JITTER_MIN_GAIN:
        best = JITTER
    return best, scores


def _low_bins(base: float | None, margin: float = CLEAN_MARGIN) -> list[int]:
    """不穿装备也到得了的低档（下边界 ≤ 基础 × 1.25 + margin），不含最后一档。"""
    return [i for i in range(OFFICIAL_BINS - 1) if base and EDGES[i] <= base * 1.25 + margin]


def clean_hists(hists: dict[str, dict[str, Sequence[float]]], base_speeds: dict[str, float], *,
                ratio: float = CLEAN_RATIO) -> tuple[dict[str, dict[str, list[float]]], list[dict]]:
    """去掉官方直方图里「没算装备」的低档尖峰（见 CLEAN_RATIO）。base_speeds：英雄的基础速度（英雄数据库的满觉醒属性），
    没有的不动。返回 (清理后的直方图, 去掉的 [{code, grade, share}])。真的不堆速度的配装也会被去掉，由 `refit_low` 补回。"""
    out: dict[str, dict[str, list[float]]] = {}
    removed = []
    for code, grades in hists.items():
        low = _low_bins(base_speeds.get(code))
        out[code] = {}
        for g, h in grades.items():
            a = [float(x) for x in h]
            total, low_sum = sum(a), sum(a[i] for i in low)
            if low and 0 < low_sum < total and max(a[i] for i in low) > ratio * max(a[low[-1] + 1], 1):
                removed.append({"code": code, "grade": g, "share": round(low_sum / total, 4)})
                for i in low:
                    a[i] = 0.0
            out[code][g] = a
    return out, removed


def refit_low(raw: dict[str, dict[str, Sequence[float]]], clean: dict[str, dict[str, list[float]]], removed: list[dict],
              matches: Iterable[Sequence[EnergyUnit]], base_speeds: dict[str, float], *, min_n: int = LOW_MIN,
              shrink: float = LOW_SHRINK) -> tuple[dict[str, dict[str, list[float]]], list[dict]]:
    """`clean_hists` 去掉的低档里有多少是真的（不堆速度的配装，例如宝剑君主伊赛丽亚）：用开局行动条反推这名英雄在这个
    段位的速度，低于低档上界的比例（向 0 收缩，强度 shrink 场；反推不到 min_n 次的当 0）就是低档该有的占比，
    低档内部按官方原来的比例分，其余档按清理后的比例分。返回 (直方图, 补回的 [{code, grade, share, n}])。"""
    table = SpeedTable.from_hists(clean, jitter=JITTER)
    targets = {(r["code"], r["grade"]) for r in removed}
    codes = {c for c, _ in targets}
    implied: dict[tuple[str, str], list[float]] = defaultdict(list)
    for units in matches:
        if not any(u.code in codes for u in units):
            continue
        est = implied_speeds(table, units)
        for u, sp in zip(units, est or ()):
            key = (u.code, analysis_grade(u.grade))
            if sp is not None and key in targets:
                implied[key].append(sp)
    out = {c: {g: list(h) for g, h in gs.items()} for c, gs in clean.items()}
    restored = []
    for r in removed:
        code, g = r["code"], r["grade"]
        low = _low_bins(base_speeds.get(code))
        sp = implied.get((code, g), [])
        cut = EDGES[low[-1] + 1]
        share = sum(x < cut for x in sp) / (len(sp) + shrink) if len(sp) >= min_n else 0.0
        if share <= 0:
            continue
        a = np.asarray(raw[code][g], dtype=float)
        rest = np.asarray(out[code][g], dtype=float)
        total = a.sum()
        new = rest * ((1 - share) * total / rest.sum())
        new[low] = a[low] * (share * total / a[low].sum())
        out[code][g] = [round(float(x), 1) for x in new]
        restored.append({"code": code, "grade": g, "share": round(share, 4), "n": len(sp)})
    return out, restored


def build(hists: dict[str, dict[str, list[float]]], matches: Sequence[Sequence[EnergyUnit]], *, season: str,
          holdout: float = 0.2, eval_limit: int = 3000, base_speeds: dict[str, float] | None = None) -> dict:
    """官方直方图 + 有行动条的对局（按时间排好）→ speed.json 的内容。

    前 (1 − holdout) 的对局拟合尾部、选开局随机，最后 holdout 的对局验收（最多 eval_limit 场）。
    base_speeds（英雄的基础速度）给了时先去掉「没算装备」的低档尖峰（`clean_hists`），再用拟合用的对局把真的慢速配装
    补回来（`refit_low`），验收里另给「官方原样」「只去掉」两种（都不加尾部）对照。
    先按默认的开局随机拟合尾部，再带着尾部选开局随机（不带尾部时几名一速的分布一样，选不出来），
    选出来的和默认不同就按它重新拟合尾部。"""
    started = time.time()
    split = int(len(matches) * (1 - holdout))
    fit_on, test_on = list(matches[:split]), list(matches[split:])[-eval_limit:]
    raw, removed, restored, cleaned = hists, [], [], None
    if base_speeds is not None:
        cleaned, removed = clean_hists(raw, base_speeds)
        hists, restored = refit_low(raw, cleaned, removed, fit_on, base_speeds)

    def make(jitter: float, tails: dict) -> dict:
        return {
            "format": FORMAT, "season": season, "built": time.strftime("%Y-%m-%d %H:%M:%S"), "jitter": jitter,
            "grade_tails": tails["grade_tails"],
            "heroes": {c: {g: {"hist": list(h), **({"tail": tails["heroes"][c][g]} if g in tails["heroes"].get(c, {})
                                                   else {})} for g, h in gs.items()} for c, gs in hists.items()},
        }

    tails = fit_tails(SpeedTable.from_hists(hists, season=season, jitter=JITTER), fit_on)
    jitter, scores = JITTER, {}
    if len(fit_on) >= 500:
        jitter, scores = choose_jitter(SpeedTable(make(JITTER, tails)), fit_on[-eval_limit:])
        if jitter != JITTER:
            tails = fit_tails(SpeedTable.from_hists(hists, season=season, jitter=jitter), fit_on)
    data = make(jitter, tails)
    final = SpeedTable(data)
    no_tail = lambda h: evaluate(SpeedTable.from_hists(h, season=season, jitter=jitter), test_on)  # noqa: E731
    data["fit"] = {"matches": len(matches), "fit_on": len(fit_on), "test_on": len(test_on), "tail_used": tails["used"],
                   "jitter_scores": {str(k): v for k, v in scores.items()}, "test": evaluate(final, test_on),
                   "test_without_tail": no_tail(hists)}
    if cleaned is not None:
        data["fit"].update(test_raw_hists=no_tail(raw), test_cleaned_only=no_tail(cleaned),
                           low_removed=len(removed), low_restored=len(restored))
    data["fit"]["seconds"] = round(time.time() - started, 1)
    return {"data": data, "check": tails["check"], "residuals": residuals(final, fit_on), "removed": removed,
            "restored": restored}


def bundled_path() -> Path:
    from .model import bundled_dir

    return bundled_dir() / SPEED_FILE


@lru_cache(maxsize=4)
def load(path: Path | None = None) -> SpeedTable | None:
    """读速度表；没有文件返回 None（还没生成：先动概率不可用）。"""
    path = path or bundled_path()
    if not path.is_file():
        return None
    return SpeedTable(json.loads(path.read_text(encoding="utf-8")))


# —— 接到选秀推荐上（只加显示，不改胜率） ——

def lineup(state, s: str) -> list[str]:
    """这一方目前在场的英雄：已选的去掉被后禁的。"""
    banned = state.banned.get(s)
    return [c for c in state.picks[s] if c != banned]


def annotate(out: dict, state, side: str, table: SpeedTable | None, speeds: dict[str, int] | None = None,
             n: int = SAMPLES) -> dict:
    """B14g2 起先动概率由搜索给（`out["first"]`、每个推荐 / 对方选法 / 后禁矩阵每格的 `first`，都是混合胜率用的那个，
    见 search.py）。这里只在 `out["first"]` 上加 `heroes`：按速度表、
    目前双方在场的英雄（后禁后去掉被禁的）每名英雄第一个行动的概率（命令行显示「谁最可能先动」用）。
    双方都还有英雄、有速度表、搜索给了 first 时才加。我方英雄用英雄池里填的速度（speeds）。"""
    first = out.get("first")
    if table is None or not first:
        return out
    opp = "S" if side == "F" else "F"
    grades = {"F": state.grades[0], "S": state.grades[1]}
    speeds = speeds or {}
    mine, theirs = lineup(state, side), lineup(state, opp)
    if mine and theirs:
        units = ([Unit("mine", c, grades[side], speeds.get(c)) for c in mine]
                 + [Unit("theirs", c, grades[opp]) for c in theirs])
        first["heroes"] = first_mover(table, units, n=n)["heroes"]
    return out
