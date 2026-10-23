"""采集数据的概况报告（B14a）：场数、解析失败原因、段位 / 开战规则分布、英雄覆盖、先手胜率。"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import rules
from .battle import BadBattle, Match, parse_battle
from .crawl import Crawler, iter_battles


def _lower_bucket(m: Match) -> str | None:
    grades = [g for g in (m.first.grade, m.second.grade) if g in rules.GRADES]
    if not grades:
        return None
    return rules.grade_bucket(min(grades, key=rules.GRADES.index))


def build_report(db_path: Path | None = None, *, known_codes: set[str] | None = None) -> dict[str, Any]:
    """读整个采集库，返回报告（JSON 友好）。known_codes：英雄数据库里的编号，用来找没收录的英雄。"""
    servers: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0, "parsed": 0, "failed": Counter(), "seasons": Counter(), "grades": Counter(), "rules": Counter(),
        "first_wins": 0, "irregular": 0, "days": [None, None], "turns": [], "seconds": [],
    })
    picks, prebans, bans = Counter(), Counter(), Counter()
    rules_seen: Counter = Counter()
    rule_kinds: dict[str, str | None] = {}
    days: Counter = Counter()
    for server, raw in iter_battles(db_path):
        s = servers[server]
        s["total"] += 1
        try:
            m = parse_battle(raw, server)  # type: ignore[arg-type]
        except BadBattle as e:
            s["failed"][e.reason] += 1
            continue
        s["parsed"] += 1
        s["seasons"][m.season] += 1
        # m 开头的是愚人节活动的怪物英雄等，不是常规对局（B14b 训练时去掉）
        if any(not c.startswith("c") for side in (m.first, m.second) for c in side.codes + side.prebans):
            s["irregular"] += 1
        bucket = _lower_bucket(m)
        s["grades"][rules.GRADE_BUCKET_LABELS.get(bucket or "", "未知")] += 1
        s["rules"][rules.rule_label(m.rule, m.rule_category)] += 1
        if m.rule:
            rules_seen[m.rule] += 1
            rule_kinds[m.rule] = m.rule_category
        s["first_wins"] += m.winner == "F"
        lo, hi = s["days"]
        s["days"] = [min(lo or m.day, m.day), max(hi or m.day, m.day)]
        s["turns"].append(m.turns)
        s["seconds"].append(m.seconds)
        days[f"{server}:{m.day[:10]}"] += 1
        for side in (m.first, m.second):
            picks.update(side.codes)
            prebans.update(side.prebans)
            if side.banned:
                bans[side.banned] += 1

    out_servers = {}
    for server, s in servers.items():
        parsed = s["parsed"]
        turns, secs = sorted(s.pop("turns")), sorted(s.pop("seconds"))
        out_servers[server] = {
            **{k: (dict(v.most_common()) if isinstance(v, Counter) else v) for k, v in s.items()},
            "parse_rate": round(parsed / s["total"], 4) if s["total"] else None,
            "first_win_rate": round(s["first_wins"] / parsed, 4) if parsed else None,
            "median_turns": turns[len(turns) // 2] if turns else None,
            "median_seconds": secs[len(secs) // 2] if secs else None,
        }
    total = sum(s["total"] for s in out_servers.values())
    parsed = sum(s["parsed"] for s in out_servers.values())
    report = {
        "total": total, "parsed": parsed, "parse_rate": round(parsed / total, 4) if total else None,
        "servers": out_servers,
        "heroes": {
            "picked": len(picks), "picked_30": sum(n >= 30 for n in picks.values()),
            "picked_300": sum(n >= 300 for n in picks.values()),
            "top_picks": picks.most_common(15), "top_prebans": prebans.most_common(15), "top_bans": bans.most_common(10),
        },
        "rules_seen": {tid: {"count": n, "category": rule_kinds.get(tid), "label": rules.rule_label(tid, rule_kinds.get(tid))}
                       for tid, n in rules_seen.most_common()},
        "per_day": dict(sorted(days.items())),
        "queue": Crawler(db_path).summary()["players"],
    }
    if known_codes is not None:
        report["heroes"]["unknown"] = sorted(c for c in set(picks) | set(prebans) if c not in known_codes)
    return report
