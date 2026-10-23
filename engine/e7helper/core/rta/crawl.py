"""开发用：从国服 / 海外官方战绩站采集世界竞技场对局，给 B14b 训练模型（B14a）。

存在 sqlite `<数据目录>/dev/rta/crawl.sqlite`（不进 git、不随包）：
- `players`：待采 / 已采的玩家队列。**玩家编号只存在这里**；
- `battles`：每场对局一行，`key = <服务器>:<battle_seq>`（两边视角相同，天然去重），
  `raw` 是 `battle.strip()` 之后的原始字段（不含昵称、玩家编号），解析交给 `battle.parse_battle`；
- `meta`：每天的请求计数等。

滚雪球：种子（国服推荐玩家；海外排行榜前 100 + 推荐）→ 采他们的对局 → 对手段位 ≥ 阈值就入队 → …
- 国服能往前翻页：一名玩家从第 1 页翻到这个赛季的头（或 `max_pages`、或一页里没有新对局）为止；
- 海外每人只能看最近 100 场：采一次后隔 `refresh_hours` 再采（每天重复采才能积累）；国服翻完的玩家也按这个间隔回来看第 1 页。
没采过的、段位高的、离种子近的优先。每个服一个线程、各自限速，Ctrl+C（stop 事件）后安全退出，下次接着采。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from e7helper.core.paths import data_dir

from . import rules
from .battle import strip
from .official import CN_WORLD, OfficialClient, OfficialError

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    server TEXT NOT NULL, season TEXT NOT NULL, nick_no TEXT NOT NULL, world TEXT NOT NULL,
    grade TEXT, grade_rank INTEGER NOT NULL DEFAULT 0, depth INTEGER NOT NULL DEFAULT 0,
    next_page INTEGER NOT NULL DEFAULT 1, done INTEGER NOT NULL DEFAULT 0, last_fetch REAL NOT NULL DEFAULT 0,
    fails INTEGER NOT NULL DEFAULT 0, added REAL NOT NULL,
    PRIMARY KEY (server, season, nick_no, world)
);
CREATE TABLE IF NOT EXISTS battles (
    key TEXT PRIMARY KEY, server TEXT NOT NULL, season TEXT NOT NULL, day TEXT, grade TEXT, enemy_grade TEXT,
    rule TEXT, raw TEXT NOT NULL, added REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS battles_server_season ON battles (server, season);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""
MAX_PLAYER_FAILS = 3


def default_db_path() -> Path:
    path = data_dir() / "dev" / "rta"
    path.mkdir(parents=True, exist_ok=True)
    return path / "crawl.sqlite"


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def grade_rank(grade: str | None) -> int:
    return rules.GRADES.index(grade) + 1 if grade in rules.GRADES else 0


@dataclass
class CrawlConfig:
    servers: tuple[str, ...] = ("cn", "global")
    seasons: dict[str, list[str]] | None = None  # 服务器 → 赛季；None = 各服的当前赛季
    min_grade: str = "champion"  # 对手段位 ≥ 这个才入队
    interval: float = 1.0  # 两次请求至少隔几秒（另加 0–0.3 秒抖动）
    max_requests: int | None = None  # 这次运行每个服最多发几次请求
    daily_cap: int = 20000  # 每个服每天（UTC）最多发几次请求
    max_pages: int = 10  # 国服每名玩家最多往前翻几页（一页 100 场）
    refresh_hours: float = 20.0  # 采过的玩家隔多久再看一次最新的对局
    max_errors: int = 10  # 连续出错几次就停（可能被限流了）


@dataclass
class ServerStats:
    server: str
    seasons: list[str] = field(default_factory=list)
    requests: int = 0
    battles_new: int = 0
    battles_seen: int = 0
    players_new: int = 0
    errors: int = 0
    stopped: str = ""


@dataclass
class _Job:
    season: str
    nick_no: str
    world: str
    depth: int
    next_page: int
    done: int
    last_fetch: float


class Crawler:
    def __init__(self, db_path: Path | None = None, config: CrawlConfig | None = None, *,
                 clients: dict[str, OfficialClient] | None = None, now: Callable[[], float] = time.time,
                 progress: Callable[[ServerStats], None] | None = None, progress_every: int = 20):
        self.db_path = db_path or default_db_path()
        self.config = config or CrawlConfig()
        self.clients = dict(clients or {})
        self.now = now
        self.progress = progress
        self.progress_every = progress_every
        connect(self.db_path).close()  # 建表

    # ---- 对外 ----
    def run(self, stop: threading.Event | None = None) -> dict[str, ServerStats]:
        """每个服一个线程并行采，直到停止条件；返回各服这次的统计。"""
        stop = stop or threading.Event()
        results: dict[str, ServerStats] = {}

        def work(server: str) -> None:
            results[server] = self.run_server(server, stop)

        threads = [threading.Thread(target=work, args=(s,), name=f"rta-crawl:{s}", daemon=True)
                   for s in self.config.servers]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(0.2)
        except KeyboardInterrupt:
            stop.set()
            for t in threads:
                t.join()
        return results

    def run_server(self, server: str, stop: threading.Event) -> ServerStats:
        cfg = self.config
        # 限速 / 退避的等待用 stop.wait，Ctrl+C 后不用等完
        client = self.clients.get(server) or OfficialClient(server, interval=cfg.interval, sleep=stop.wait)
        self.clients[server] = client
        stats = ServerStats(server)
        conn = connect(self.db_path)
        start = client.requests
        consecutive = 0
        try:
            seasons = (cfg.seasons or {}).get(server) or [client.current_season()]
            stats.seasons = list(seasons)
            for season in seasons:
                stats.players_new += self._seed(conn, client, server, season)
            self._count_requests(conn, server, client.requests - start)
            while True:
                stats.requests = client.requests - start
                if stop.is_set():
                    stats.stopped = "手动停止"
                    break
                if cfg.max_requests is not None and stats.requests >= cfg.max_requests:
                    stats.stopped = f"达到这次的请求上限 {cfg.max_requests}"
                    break
                if self._today_requests(conn, server) >= cfg.daily_cap:
                    stats.stopped = f"达到每天的请求上限 {cfg.daily_cap}"
                    break
                job = self._next_job(conn, server, seasons)
                if job is None:
                    stats.stopped = "没有待采的玩家"
                    break
                before = client.requests
                try:
                    rows = client.battles(job.nick_no, job.world, job.season, job.next_page if not job.done else 1)
                except OfficialError as e:
                    self._count_requests(conn, server, client.requests - before)
                    stats.errors += 1
                    consecutive += 1
                    # 取不到的玩家（多半是 405）隔 refresh_hours 再试，失败 MAX_PLAYER_FAILS 次就不再采
                    conn.execute("UPDATE players SET fails = fails + 1, done = 1, last_fetch = ? WHERE server=? AND "
                                 "season=? AND nick_no=? AND world=?",
                                 (self.now(), server, job.season, job.nick_no, job.world))
                    conn.commit()
                    log.debug("%s 玩家对局取不到：%s", server, e)
                    if consecutive >= cfg.max_errors:
                        stats.stopped = f"连续出错 {consecutive} 次（最后一次：{e}）"
                        break
                    continue
                consecutive = 0
                self._count_requests(conn, server, client.requests - before)
                new, seen, players = self._store(conn, server, job, rows)
                stats.battles_new += new
                stats.battles_seen += seen
                stats.players_new += players
                self._advance(conn, server, job, rows, new)
                stats.requests = client.requests - start
                if self.progress and stats.requests % self.progress_every == 0:
                    self.progress(stats)
        except OfficialError as e:
            stats.errors += 1
            stats.stopped = f"出错：{e}"
        finally:
            stats.requests = client.requests - start
            conn.close()
        return stats

    def summary(self) -> dict:
        """数据库里的概况：各服 / 赛季的对局数、玩家数、待采的玩家数。"""
        conn = connect(self.db_path)
        try:
            battles = {f"{s}/{season}": n for s, season, n in conn.execute(
                "SELECT server, season, COUNT(*) FROM battles GROUP BY server, season")}
            players = {f"{s}/{season}": (n, pending) for s, season, n, pending in conn.execute(
                "SELECT server, season, COUNT(*), SUM(last_fetch = 0) FROM players GROUP BY server, season")}
            return {"battles": battles, "players": players}
        finally:
            conn.close()

    # ---- 内部 ----
    def _seed(self, conn: sqlite3.Connection, client: OfficialClient, server: str, season: str) -> int:
        seeds = list(client.recommend())
        if server == "global":
            for page in range(1, 11):  # 排行榜前 100 名，每页 10
                rows = client.ranking(season, page)
                if not rows:
                    break
                seeds += [{**r, "grade": r.get("season_tiercode")} for r in rows]
        return self._enqueue(conn, server, season, ((s.get("nick_no"), s.get("world_code") or CN_WORLD,
                                                     s.get("grade") or "legend", 0) for s in seeds))

    def _enqueue(self, conn: sqlite3.Connection, server: str, season: str,
                 players: Iterable[tuple[object, str, str | None, int]]) -> int:
        now, n = self.now(), 0
        for nick_no, world, grade, depth in players:
            nick = str(nick_no or "")
            if not nick.isdigit() or not world:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO players (server, season, nick_no, world, grade, grade_rank, depth, added) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (server, season, nick, world, grade, grade_rank(grade), depth, now))
            n += cur.rowcount
        conn.commit()
        return n

    def _next_job(self, conn: sqlite3.Connection, server: str, seasons: list[str]) -> _Job | None:
        stale = self.now() - self.config.refresh_hours * 3600
        marks = ",".join("?" * len(seasons))
        row = conn.execute(
            f"SELECT season, nick_no, world, depth, next_page, done, last_fetch FROM players "
            f"WHERE server = ? AND season IN ({marks}) AND fails < ? AND (done = 0 OR last_fetch < ?) "
            f"ORDER BY (last_fetch = 0) DESC, done ASC, grade_rank DESC, depth ASC, added ASC LIMIT 1",
            (server, *seasons, MAX_PLAYER_FAILS, stale)).fetchone()
        return _Job(*row) if row else None

    def _store(self, conn: sqlite3.Connection, server: str, job: _Job, rows: list[dict]) -> tuple[int, int, int]:
        now, new, seen = self.now(), 0, 0
        opponents = []
        min_rank = grade_rank(self.config.min_grade)
        for raw in rows:
            if not raw.get("battle_seq"):
                continue
            kept = strip(raw)
            cur = conn.execute(
                "INSERT OR IGNORE INTO battles (key, server, season, day, grade, enemy_grade, rule, raw, added) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{server}:{raw['battle_seq']}", server, raw.get("season_code") or job.season,
                 str(raw.get("battle_day", ""))[:19], raw.get("grade_code"), raw.get("enemy_grade_code"),
                 raw.get("opening_rule_desc_tid"), json.dumps(kept, ensure_ascii=False, separators=(",", ":")), now))
            if cur.rowcount:
                new += 1
            else:
                seen += 1
            grade = raw.get("enemy_grade_code")
            # 只从这个赛季的对局扩展对手（国服往前翻会翻到以前的赛季，那时的对手这个赛季未必还在打）
            if raw.get("season_code", job.season) == job.season and grade_rank(grade) >= min_rank:
                opponents.append((raw.get("matchPlayerNicknameno"), raw.get("enemy_world_code"), grade, job.depth + 1))
        if rows and rows[0].get("grade_code"):
            conn.execute("UPDATE players SET grade = ?, grade_rank = ? WHERE server=? AND season=? AND nick_no=? "
                         "AND world=?", (rows[0]["grade_code"], grade_rank(rows[0]["grade_code"]), server, job.season,
                                         job.nick_no, job.world))
        conn.commit()
        return new, seen, self._enqueue(conn, server, job.season, opponents)

    def _advance(self, conn: sqlite3.Connection, server: str, job: _Job, rows: list[dict], new: int) -> None:
        """国服：这一页满了、全是这个赛季的、有新对局、没到页数上限就继续往前翻；否则这个赛季翻完了。
        海外：采一次就算完。国服的 getBattleList 不按赛季过滤，翻过赛季开头就是以前赛季的对局（照样入库，带赛季标记）。"""
        in_season = all(r.get("season_code", job.season) == job.season for r in rows)
        more = (not job.done and self.clients[server].info.pages and len(rows) >= 100 and in_season and new > 0
                and job.next_page < self.config.max_pages)
        conn.execute("UPDATE players SET next_page = ?, done = ?, last_fetch = ?, fails = 0 WHERE server=? AND "
                     "season=? AND nick_no=? AND world=?",
                     (job.next_page + 1 if more else job.next_page, 0 if more else 1, self.now(), server, job.season,
                      job.nick_no, job.world))
        conn.commit()

    def _today_key(self, server: str) -> str:
        return f"requests:{server}:{datetime.fromtimestamp(self.now(), timezone.utc):%Y-%m-%d}"

    def _today_requests(self, conn: sqlite3.Connection, server: str) -> int:
        row = conn.execute("SELECT v FROM meta WHERE k = ?", (self._today_key(server),)).fetchone()
        return int(row[0]) if row else 0

    def _count_requests(self, conn: sqlite3.Connection, server: str, n: int) -> None:
        key = self._today_key(server)
        conn.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = CAST(v AS INTEGER) + ?",
                     (key, str(n), n))
        conn.commit()


def iter_battles(db_path: Path | None = None, *, server: str | None = None,
                 season: str | None = None) -> Iterable[tuple[str, dict]]:
    """逐场读出采集的对局：(服务器, 原始字段)。"""
    conn = connect(db_path or default_db_path())
    try:
        sql, args = "SELECT server, raw FROM battles WHERE 1=1", []
        if server:
            sql += " AND server = ?"
            args.append(server)
        if season:
            sql += " AND season = ?"
            args.append(season)
        for srv, raw in conn.execute(sql + " ORDER BY day", args):
            yield srv, json.loads(raw)
    finally:
        conn.close()
