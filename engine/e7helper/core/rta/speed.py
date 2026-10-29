"""先动概率（B14d1）：战斗里谁第一个行动。只依赖 numpy。

速度表（随包 `assets/data/rta/speed.json`，`e7helper rta speed` 生成）：
- 290 以下：官方「英雄分析」按赛季 × 段位 × 英雄的速度直方图（`herostats.py`），口径「60 级 / 6 星满觉醒 /
  穿戴全部装备」，每档 20 速：110–130 … 270–290，最后一档「290 以上」。第 1 档混着很慢的和缺数据的。
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
"""

from __future__ import annotations

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


def build(hists: dict[str, dict[str, list[int]]], matches: Sequence[Sequence[EnergyUnit]], *, season: str,
          holdout: float = 0.2, eval_limit: int = 3000) -> dict:
    """官方直方图 + 有行动条的对局（按时间排好）→ speed.json 的内容。

    前 (1 − holdout) 的对局拟合尾部、选开局随机，最后 holdout 的对局验收（最多 eval_limit 场）。
    先按默认的开局随机拟合尾部，再带着尾部选开局随机（不带尾部时几名一速的分布一样，选不出来），
    选出来的和默认不同就按它重新拟合尾部。"""
    started = time.time()
    split = int(len(matches) * (1 - holdout))
    fit_on, test_on = list(matches[:split]), list(matches[split:])[-eval_limit:]

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
    baseline = evaluate(SpeedTable.from_hists(hists, season=season, jitter=jitter), test_on)
    data["fit"] = {"matches": len(matches), "fit_on": len(fit_on), "test_on": len(test_on), "tail_used": tails["used"],
                   "jitter_scores": {str(k): v for k, v in scores.items()}, "test": evaluate(final, test_on),
                   "test_without_tail": baseline, "seconds": round(time.time() - started, 1)}
    return {"data": data, "check": tails["check"], "residuals": residuals(final, fit_on)}


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
    """在 `Advisor.advise` 的结果上加先动概率（我方先动的概率），胜率不动（速度不在胜率模型里，B14g 再加）：
    - `first`：按目前双方已选（后禁后去掉被禁的）算，`partial` = 还不是最终上场的 4 打 4；
    - 轮到我方时每个推荐 `first`：选了这组之后、对方按目前已选的算；
    - 后禁矩阵 `ban.first`：每一格（行 = 我方禁对方哪名，列 = 对方禁我方哪名）上场 4 打 4 的先动概率。
    双方都还没有英雄、或没有速度表时是 None。我方英雄用英雄池里填的速度（speeds）。"""
    out["first"] = None
    if table is None:
        return out
    opp = "S" if side == "F" else "F"
    grades = {"F": state.grades[0], "S": state.grades[1]}
    speeds = speeds or {}

    def calc(mine: list[str], theirs: list[str]) -> dict | None:
        if not mine or not theirs:
            return None
        units = ([Unit("mine", c, grades[side], speeds.get(c)) for c in mine]
                 + [Unit("theirs", c, grades[opp]) for c in theirs])
        return first_mover(table, units, n=n)

    mine_now, theirs_now = lineup(state, side), lineup(state, opp)
    now = calc(mine_now, theirs_now)
    if now:
        out["first"] = {"mine": now["sides"].get("mine", 0.0), "heroes": now["heroes"],
                        "partial": not (state.banned.get("F") and state.banned.get("S"))}
    for rec in out.get("recommend") or []:
        r = calc(mine_now + list(rec["heroes"]), theirs_now)
        rec["first"] = r["sides"].get("mine", 0.0) if r else None
    ban = out.get("ban")
    if ban:
        ban["first"] = [[(calc([c for c in mine_now if c != col], [c for c in theirs_now if c != row]) or {})
                         .get("sides", {}).get("mine") for col in ban["cols"]] for row in ban["rows"]]
    return out
