"""训练数据快照（B14b）：采集库里一个赛季的对局 → 解析、过滤、编码成紧凑的数组，存成 npz。

- 只存模型要的：每场 17 个位置的英雄（存英雄表的下标，-1 = 空位）、双方段位档、开战规则、服务器、日期、
  先手方是否赢、回合数；B14d1 起还有 10 手各自的开局行动条和谁先动（给 ss22 重训用，没有的记 -1）；不存原始字段。之后训练、评估都读快照，结果可复现（采集还在往库里加新对局）。
- 去掉：解析失败的（几乎都是选秀阶段退出）、含 `m` 开头英雄的（愚人节怪物英雄）、0 回合的、截止日之后的；
  B14h 起还可以只用某些服（`servers`）、去掉含某些英雄的（`exclude`，刚出、还没养成的新英雄，预禁 / 选人 / 被禁都算）。
- 切分按日期（UTC）：最后 test_days 天测试、再往前 val_days 天验证，其余训练；一场的所有局面在同一份。
- 解析在多个进程里并行（一个赛季约 90 万场，单进程要 10 分钟）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from . import encode, rules
from .battle import BadBattle, parse_battle
from .crawl import default_db_path

SEASON = "pvp_rta_ss21"
SERVERS = ("cn", "global")
CHUNK = 2000


def default_dir() -> Path:
    """快照目录：采集库旁边的 datasets/（F:\\e7helper-data\\rta\\datasets）。"""
    return default_db_path().parent / "datasets"


def _parse_chunk(rows: list[tuple[str, str]]) -> tuple[list[tuple], Counter]:
    """子进程：一批 (服务器, raw 文本) → 编码前的元组 + 去掉的原因计数。"""
    out, dropped = [], Counter()
    for server, text in rows:
        try:
            m = parse_battle(json.loads(text), server)  # type: ignore[arg-type]
        except BadBattle as e:
            dropped[f"解析失败：{e.reason}"] += 1
            continue
        tokens = encode.match_tokens(m)
        if any(c and not c.startswith("c") for c in tokens):
            dropped["含 m 开头英雄"] += 1
            continue
        if m.turns <= 0:
            dropped["0 回合"] += 1
            continue
        energy = {(s, p.code): p.energy for s in rules.SIDES for p in m.side(s).picks}
        out.append((m.key, server, m.day[:10], tokens, encode.grade_id(m.first.grade), encode.grade_id(m.second.grade),
                    encode.match_rule(m), m.rule_category, m.winner == "F", m.turns,
                    [-1 if energy[sc] is None else energy[sc] for sc in m.sequence()],
                    -1 if m.first_mover is None else int(m.first_mover == "F")))
    return out, dropped


def _read_rows(db_path: Path, season: str, servers: Sequence[str] = SERVERS) -> Iterable[list[tuple[str, str]]]:
    """只读打开采集库（采集可能还在写），按块读出 (服务器, raw)。"""
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=60)
    try:
        marks = ",".join("?" * len(servers))
        cur = conn.execute(f"SELECT server, raw FROM battles WHERE server IN ({marks}) AND season = ?", (*servers, season))
        while rows := cur.fetchmany(CHUNK):
            yield rows
    finally:
        conn.close()


@dataclass
class Dataset:
    codes: list[str]  # 英雄表：tokens 里存的是这里的下标
    rule_table: list[tuple[str, str | None]]  # 开战规则表：rule 里存的是这里的下标；-1 = 没有规则，-2 = 不知道
    tokens: np.ndarray  # [N, 17] int16，-1 = 空位
    grades: np.ndarray  # [N, 2] int8，encode.grade_id
    rule: np.ndarray  # [N] int16
    server: np.ndarray  # [N] int8，SERVERS 的下标
    day: np.ndarray  # [N] int32，UTC 日期的序数（date.toordinal）
    first_wins: np.ndarray  # [N] int8
    turns: np.ndarray  # [N] int16
    energy: np.ndarray | None = None  # [N, 10] int8，按选秀顺序 10 手各自的开局行动条，-1 = 没有（B14d1）
    first_mover: np.ndarray | None = None  # [N] int8，1 = 先手方先动、0 = 后手方先动、-1 = 不知道（B14d1）
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # B14d1 之前的快照没有这两项
        n = len(self.tokens)
        if self.energy is None:
            self.energy = np.full((n, rules.PICKS_PER_SIDE * 2), -1, dtype=np.int8)
        if self.first_mover is None:
            self.first_mover = np.full(n, -1, dtype=np.int8)

    def __len__(self) -> int:
        return len(self.tokens)

    # —— 存取 ——
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(
            tmp, tokens=self.tokens, grades=self.grades, rule=self.rule, server=self.server, day=self.day,
            first_wins=self.first_wins, turns=self.turns, energy=self.energy, first_mover=self.first_mover,
            info=np.array(json.dumps({"codes": self.codes, "rule_table": self.rule_table, "meta": self.meta},
                                     ensure_ascii=False)))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Dataset:
        with np.load(path) as z:
            info = json.loads(str(z["info"]))
            return cls(codes=info["codes"], rule_table=[(r[0], r[1]) for r in info["rule_table"]], meta=info["meta"],
                       **{k: z[k] for k in ("tokens", "grades", "rule", "server", "day", "first_wins", "turns")},
                       **{k: z[k] for k in ("energy", "first_mover") if k in z.files})

    # —— 切分和编码 ——
    def split(self, test_days: int = 7, val_days: int = 7) -> dict[str, np.ndarray]:
        """按日期切分，返回每份的行号。test_days = 0 时全部是训练集（全量重训用）。"""
        last = int(self.day.max())
        test_from = last - test_days + 1
        val_from = test_from - val_days
        idx = np.arange(len(self))
        if test_days <= 0:
            return {"train": idx, "val": idx[:0], "test": idx[:0]}
        return {"train": idx[self.day < val_from], "val": idx[(self.day >= val_from) & (self.day < test_from)],
                "test": idx[self.day >= test_from]}

    def vocab(self, rows: np.ndarray, min_picks: int = 30) -> encode.Vocab:
        return encode.Vocab.build(encode.pick_counts(self.tokens[rows], self.codes), self.rule_table, min_picks)

    def rule_ids(self, vocab: encode.Vocab) -> np.ndarray:
        lut = np.array([vocab.rule(tid, cat) for tid, cat in self.rule_table] + [encode.RULE_UNKNOWN, encode.RULE_NONE],
                       dtype=np.int64)
        return lut[self.rule]  # -2 → 倒数第二个（不知道），-1 → 最后一个（没有）

    def encode(self, vocab: encode.Vocab, rows: np.ndarray | None = None) -> dict[str, np.ndarray]:
        """→ heroes [n, 17]、ctx [n, 3]（int64）、y [n]（float32，先手方赢 = 1）、head [n]（int64，谁先动对应的
        胜率头 encode.first_heads：0 = 先手方先动、1 = 后手方、2 = 不知道；B14g）。"""
        rows = np.arange(len(self)) if rows is None else rows
        heroes = vocab.lut(self.codes)[self.tokens[rows].astype(np.int64) + 1]
        ctx = np.stack([self.grades[rows, 0], self.grades[rows, 1], self.rule_ids(vocab)[rows]], axis=1).astype(np.int64)
        return {"heroes": heroes, "ctx": ctx, "y": self.first_wins[rows].astype(np.float32),
                "head": encode.first_heads(self.first_mover[rows])}

    def champion_plus(self) -> np.ndarray:
        """双方都 ≥ 优胜者（主指标的子集），布尔 [N]。"""
        champ = encode.grade_id("champion")
        return (self.grades[:, 0] >= champ) & (self.grades[:, 1] >= champ)

    def day_str(self, ordinal: int) -> str:
        return date.fromordinal(int(ordinal)).isoformat()

    def state(self, row: int, n: int | None = None) -> encode.DraftState:
        """第 row 场在局面 n（默认后禁之后）时的 DraftState（parity 样例、预测试用）。"""
        # 默认值不能直接写 encode.POSTBAN：类体里 encode 是上面的方法
        n = encode.POSTBAN if n is None else n
        t = [self.codes[i] if i >= 0 else None for i in self.tokens[row].tolist()]
        seq = t[encode.PICK_POS:encode.PICK_POS + min(n, encode.N_PICKS)]
        picks = {s: [c for side, c in zip(rules.PICK_ORDER, seq) if side == s] for s in rules.SIDES}
        banned = ({s: t[encode.BAN_POS[s]] for s in rules.SIDES} if n == encode.POSTBAN else {"F": None, "S": None})
        grade = lambda g: rules.GRADE_BUCKETS[g - 1] if g > 0 else None  # noqa: E731
        r = int(self.rule[row])
        rule, cat = (encode.UNKNOWN_RULE, None) if r == -2 else (None, None) if r == -1 else self.rule_table[r]
        return encode.DraftState(prebans={"F": [c for c in t[1:3] if c], "S": [c for c in t[3:5] if c]}, picks=picks,
                                 banned=banned, grades=(grade(int(self.grades[row, 0])), grade(int(self.grades[row, 1]))),
                                 rule=rule, rule_category=cat)


def build(db_path: Path | None = None, *, season: str = SEASON, until: str | None = None,
          servers: Sequence[str] = SERVERS, exclude: Iterable[str] = (), workers: int | None = None,
          progress: Callable[[int, int], None] | None = None) -> Dataset:
    """从采集库建快照。until：只要这一天（UTC，含）以前的对局；servers：只读这些服；exclude：去掉含这些英雄
    （编号）的对局；progress(已读, 已收) 每块调一次。"""
    db_path = db_path or default_db_path()
    servers = [s for s in SERVERS if s in servers]
    if not servers:
        raise ValueError(f"servers 只能是 {', '.join(SERVERS)}")
    exclude = set(exclude)
    started = time.time()
    kept: list[tuple] = []
    dropped: Counter = Counter()
    read = 0
    workers = workers or max(1, min(6, (os.cpu_count() or 2) - 1))

    def collect(result: tuple[list[tuple], Counter]) -> None:
        nonlocal read
        out, drop = result
        read += len(out) + sum(drop.values())
        dropped.update(drop)
        for row in out:
            if until and row[2] > until:
                dropped["截止日之后"] += 1
            elif exclude and (hit := exclude.intersection(row[3])):
                dropped[f"含 {'、'.join(sorted(hit))}"] += 1
            else:
                kept.append(row)
        if progress:
            progress(read, len(kept))

    # 手动限制在途的块数：Executor.map 会先把整个库读进内存
    with ProcessPoolExecutor(workers) as pool:
        pending: deque = deque()
        for rows in _read_rows(db_path, season, servers):
            pending.append(pool.submit(_parse_chunk, rows))
            if len(pending) >= workers * 3:
                collect(pending.popleft().result())
        while pending:
            collect(pending.popleft().result())
    kept.sort(key=lambda r: (r[2], r[0]))  # 按日期，同一天按 key，结果和读的顺序无关

    codes = sorted({c for r in kept for c in r[3] if c})
    code_idx = {c: i for i, c in enumerate(codes)}
    rule_table = sorted({(r[6], r[7]) for r in kept if r[6] and r[6] != encode.UNKNOWN_RULE})
    rule_idx = {tid: i for i, (tid, _) in enumerate(rule_table)}
    n = len(kept)
    ds = Dataset(
        codes=codes, rule_table=rule_table,
        tokens=np.array([[code_idx[c] if c else -1 for c in r[3]] for r in kept], dtype=np.int16).reshape(n, encode.SEQ_LEN),
        grades=np.array([(r[4], r[5]) for r in kept], dtype=np.int8).reshape(n, 2),
        rule=np.array([-2 if r[6] == encode.UNKNOWN_RULE else rule_idx[r[6]] if r[6] else -1 for r in kept], dtype=np.int16),
        server=np.array([SERVERS.index(r[1]) for r in kept], dtype=np.int8),
        day=np.array([date.fromisoformat(r[2]).toordinal() for r in kept], dtype=np.int32),
        first_wins=np.array([r[8] for r in kept], dtype=np.int8),
        turns=np.array([r[9] for r in kept], dtype=np.int16),
        energy=np.array([r[10] for r in kept], dtype=np.int8).reshape(n, rules.PICKS_PER_SIDE * 2),
        first_mover=np.array([r[11] for r in kept], dtype=np.int8),
    )
    ds.meta = {
        "season": season, "until": until, "servers": servers, "exclude": sorted(exclude),
        "built": time.strftime("%Y-%m-%d %H:%M:%S"), "db": str(db_path),
        "read": read, "kept": n, "dropped": dict(dropped.most_common()), "seconds": round(time.time() - started, 1),
        "first_day": ds.day_str(ds.day.min()) if n else None, "last_day": ds.day_str(ds.day.max()) if n else None,
        "per_server": {s: int((ds.server == i).sum()) for i, s in enumerate(SERVERS)},
        "with_energy": int((ds.first_mover >= 0).sum()),
    }
    return ds


def summary(ds: Dataset, test_days: int = 7, val_days: int = 7, min_picks: int = 30) -> dict:
    """快照概况：每份的场数 / 日期 / 先手胜率、双方 ≥ 优胜者的场数、词表大小。"""
    parts = ds.split(test_days, val_days)
    champ = ds.champion_plus()
    out = {"meta": ds.meta, "heroes": len(ds.codes), "rules": [t for t, _ in ds.rule_table], "splits": {}}
    for name, rows in parts.items():
        if not len(rows):
            continue
        out["splits"][name] = {
            "matches": int(len(rows)), "champion_plus": int(champ[rows].sum()),
            "from": ds.day_str(ds.day[rows].min()), "to": ds.day_str(ds.day[rows].max()),
            "first_win_rate": round(float(ds.first_wins[rows].mean()), 4),
            "per_server": {s: int((ds.server[rows] == i).sum()) for i, s in enumerate(SERVERS)},
        }
    out["vocab"] = len(ds.vocab(parts["train"], min_picks).heroes)
    out["grade_mix"] = {rules.GRADE_BUCKET_LABELS.get(b, b): int(((ds.grades.min(axis=1)) == i + 1).sum())
                        for i, b in enumerate(rules.GRADE_BUCKETS)}
    return out
