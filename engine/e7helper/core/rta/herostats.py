"""开发用：官方战绩站「英雄分析」（getHeroAnalysis）的快照（B14d1）。

按赛季 × 段位 × 英雄取一次，原样存进采集库的 `hero_stats` 表（`raw` 是 result_body 的 JSON；官方没有数据时返回
-10002，存空串，下次不再取）。先动概率的速度表（`speed.py`）用里面的能力值直方图，以后的英雄统计也读这里。

能力值直方图（`abillity`）：每项属性 10 档的人数，逗号分隔。口径「60 级 / 6 星满觉醒 / 穿戴全部装备」。
官方页面每项的刻度（bundle.js 里的 `re` / `ie`，10 档等宽，最后一档没有上限）：
攻击 1200–6000、防御 800–3000、生命 9000–40000、速度 110–310、暴击率 15–100、暴击伤害 150–350、
效果命中 0–200、效果抗性 0–300。B14a 以为这些只是「+1…+10」相对档位，B14d1 查官方页面代码后改正。

段位只有大师到传说 6 档（页面的选项，默认大师）。每次请求按客户端限速（默认 1 秒）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .crawl import connect, default_db_path
from .official import OfficialClient, OfficialError

GRADES = ("master", "challenger", "champion", "warlord", "emperor", "legend")
NO_DATA = -10002
# 每项属性直方图的刻度（下限, 上限），10 档等宽
SCALES = {
    "att": (1200, 6000), "def": (800, 3000), "max_hp": (9000, 40000), "speed": (110, 310),
    "cri": (15, 100), "cri_dmg": (150, 350), "acc": (0, 200), "res": (0, 300),
}
BINS = 10
SCHEMA = """
CREATE TABLE IF NOT EXISTS hero_stats (
    server TEXT NOT NULL, season TEXT NOT NULL, grade TEXT NOT NULL, hero TEXT NOT NULL,
    fetched REAL NOT NULL, raw TEXT NOT NULL,
    PRIMARY KEY (server, season, grade, hero)
);
"""


def open_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = connect(db_path or default_db_path())
    conn.executescript(SCHEMA)
    return conn


def histogram(body: dict, stat: str = "speed") -> list[int] | None:
    """result_body → 这项属性 10 档的人数；没有或格式不对返回 None。"""
    text = ((body or {}).get("abillity") or {}).get(stat)
    if not isinstance(text, str):
        return None
    try:
        counts = [int(x.strip()) for x in text.split(",")]
    except ValueError:
        return None
    return counts if len(counts) == BINS and all(c >= 0 for c in counts) else None


def snapshot(client: OfficialClient, season: str, codes: Iterable[str], *, grades: Iterable[str] = GRADES,
             db_path: Path | None = None, max_age_hours: float = 72.0, stop: threading.Event | None = None,
             progress: Callable[[int, int], None] | None = None, now: Callable[[], float] = time.time) -> dict:
    """取这些英雄在这些段位的英雄分析，存进 hero_stats；`max_age_hours` 内取过的跳过。返回计数。"""
    conn = open_db(db_path)
    jobs = [(g, c) for g in grades for c in codes]
    stale = now() - max_age_hours * 3600
    done = {(g, h) for g, h in conn.execute(
        "SELECT grade, hero FROM hero_stats WHERE server = ? AND season = ? AND fetched >= ?",
        (client.server, season, stale))}
    counts = {"jobs": len(jobs), "skipped": 0, "fetched": 0, "no_data": 0, "errors": 0}
    try:
        for k, (grade, code) in enumerate(jobs):
            if stop is not None and stop.is_set():
                break
            if (grade, code) in done:
                counts["skipped"] += 1
                continue
            try:
                body = client.hero_analysis(code, season, grade)
                raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body else ""
            except OfficialError as e:
                if e.code != NO_DATA:
                    counts["errors"] += 1
                    continue
                raw = ""
            counts["fetched" if raw else "no_data"] += 1
            conn.execute("INSERT OR REPLACE INTO hero_stats (server, season, grade, hero, fetched, raw) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (client.server, season, grade, code, now(), raw))
            conn.commit()
            if progress:
                progress(k + 1, len(jobs))
    finally:
        conn.close()
    return counts


def speed_histograms(season: str, *, server: str = "cn", db_path: Path | None = None) -> dict[str, dict[str, list[int]]]:
    """快照里的速度直方图：{英雄: {段位: 10 档人数}}（没有数据的不在里面）。"""
    conn = open_db(db_path)
    try:
        out: dict[str, dict[str, list[int]]] = {}
        for grade, hero, raw in conn.execute(
                "SELECT grade, hero, raw FROM hero_stats WHERE server = ? AND season = ? AND raw != ''", (server, season)):
            h = histogram(json.loads(raw))
            if h and sum(h):
                out.setdefault(hero, {})[grade] = h
        return out
    finally:
        conn.close()


def energy_matches(season: str, *, servers: Iterable[str] = ("cn",), db_path: Path | None = None,
                   limit: int | None = None) -> list:
    """采集库里这个赛季有开局行动条的对局 → 每场上场 8 名的 `speed.EnergyUnit` 列表，按时间排（limit：只要最近的几场）。"""
    from .battle import ENERGY_KEY, BadBattle, parse_battle
    from .speed import match_units

    servers = list(servers)
    conn = sqlite3.connect(f"file:{(db_path or default_db_path()).as_posix()}?mode=ro", uri=True, timeout=60)
    try:
        marks = ",".join("?" * len(servers))
        # 不在 SQL 里 ORDER BY（大库上会整表排序），读出来再按时间排
        sql = f"SELECT server, raw FROM battles WHERE server IN ({marks}) AND season = ? AND instr(raw, ?) > 0"
        out = []
        for server, raw in conn.execute(sql, (*servers, season, f'"{ENERGY_KEY}"')):
            try:
                m = parse_battle(json.loads(raw), server)
            except BadBattle:
                continue
            units = match_units(m)
            if units:
                out.append((m.day, m.key, units))
        out.sort(key=lambda x: (x[0], x[1]))
        rows = [u for _, _, u in out]
        return rows[-limit:] if limit else rows
    finally:
        conn.close()
