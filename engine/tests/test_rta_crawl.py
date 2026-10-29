"""B14a：对局采集（假客户端，不联网）。"""

import json
import sqlite3
import threading

import pytest

from e7helper.core.rta.battle import parse_battle
from e7helper.core.rta.crawl import CrawlConfig, Crawler, connect, iter_battles
from e7helper.core.rta.official import SERVERS, OfficialError
from rta_fakes import battle

SEASON = "pvp_rta_ss21"


class FakeClient:
    """玩家编号 → 对局列表（新的在前）。国服按 100 场一页翻，海外只给最近 100 场。"""

    def __init__(self, server, games: dict[str, list[dict]], seeds=("1",), ranking=(), fail=()):
        self.info = SERVERS[server]
        self.server = server
        self.games = games
        self.seeds = list(seeds)
        self.ranking_rows = list(ranking)
        self.fail = set(fail)
        self.requests = 0
        self.calls: list[tuple[str, int]] = []

    def current_season(self):
        self.requests += 1
        return SEASON

    def recommend(self):
        self.requests += 1
        return [{"nick_no": s, "world_code": "world_zlong1"} for s in self.seeds]

    def ranking(self, season, page=1, world="all"):
        self.requests += 1
        return self.ranking_rows[(page - 1) * 10: page * 10]

    def battles(self, nick_no, world, season, page=1):
        self.requests += 1
        self.calls.append((nick_no, page))
        if nick_no in self.fail:
            raise OfficialError("HTTP 405", status=405)
        rows = self.games.get(nick_no, [])
        if not self.info.pages:
            return rows[:100]
        return rows[(page - 1) * 100: page * 100]


def game(seq, enemy_no, enemy_grade="emperor", **kw):
    return battle(seq, enemy_no=int(enemy_no), grades=("legend", enemy_grade), **kw)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "crawl.sqlite"


def make(db, client, now=None, **cfg):
    clock = now or [1_000_000.0]
    config = CrawlConfig(servers=(client.server,), **cfg)
    return Crawler(db, config, clients={client.server: client}, now=lambda: clock[0]), clock


def test_snowball_dedupe_and_grade_threshold(db):
    games = {
        "1": [game(10, "2"), game(11, "3", enemy_grade="master"), game(12, "2")],
        "2": [game(10, "1", me_first=False, iswin=2), game(13, "4")],  # 10 是同一场的另一边
        "4": [game(14, "1")],
    }
    client = FakeClient("cn", games)
    crawler, _ = make(db, client)
    stats = crawler.run_server("cn", threading.Event())
    assert stats.stopped == "没有待采的玩家"
    assert stats.battles_new == 5 and stats.battles_seen == 1  # 10 从两边各看到一次
    assert [c[0] for c in client.calls] == ["1", "2", "4"]  # 大师段位的 3 号没入队
    conn = sqlite3.connect(db)
    keys = sorted(k for (k,) in conn.execute("SELECT key FROM battles"))
    assert keys == ["cn:10", "cn:11", "cn:12", "cn:13", "cn:14"]
    players = dict(conn.execute("SELECT nick_no, depth FROM players"))
    assert players == {"1": 0, "2": 1, "4": 2}
    # 存的原始字段不含昵称 / 玩家编号，能解析
    for (raw,) in conn.execute("SELECT raw FROM battles"):
        assert "昵称" not in raw and "matchPlayerNicknameno" not in raw and "1100" not in raw
        parse_battle(json.loads(raw), "cn")


def test_cn_paging_stops(db):
    many = [game(1000 + i, "9") for i in range(250)]
    client = FakeClient("cn", {"1": many, "9": []})
    crawler, _ = make(db, client)
    crawler.run_server("cn", threading.Event())
    assert [c for c in client.calls if c[0] == "1"] == [("1", 1), ("1", 2), ("1", 3)]  # 第 3 页不满 100 就停
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM battles").fetchone()[0] == 250

    # 页数上限
    client = FakeClient("cn", {"1": many, "9": []})
    crawler, _ = make(db.with_name("b.sqlite"), client, max_pages=2)
    crawler.run_server("cn", threading.Event())
    assert [c for c in client.calls if c[0] == "1"] == [("1", 1), ("1", 2)]


def test_cn_paging_stops_at_season_start(db):
    """国服不按赛季过滤：翻到上个赛季的对局就停，那些对局照样入库，但不从里面扩展对手。"""
    rows = [game(1000 + i, "9") for i in range(150)] + [game(2000 + i, "8", season="pvp_rta_ss20") for i in range(150)]
    client = FakeClient("cn", {"1": rows, "9": [], "8": []})
    crawler, _ = make(db, client)
    crawler.run_server("cn", threading.Event())
    assert [c for c in client.calls if c[0] == "1"] == [("1", 1), ("1", 2)]
    assert [c[0] for c in client.calls] == ["1", "9", "1"]  # 8 号只在上个赛季的对局里出现，不入队
    conn = sqlite3.connect(db)
    assert dict(conn.execute("SELECT season, COUNT(*) FROM battles GROUP BY season")) == {
        "pvp_rta_ss20": 50, SEASON: 150}


def test_cn_page_without_new_battles_stops(db):
    rows = [game(1000 + i, "9") for i in range(300)]
    client = FakeClient("cn", {"1": rows, "9": rows[:100]})  # 9 号的第 1 页全是已有的
    crawler, _ = make(db, client)
    crawler.run_server("cn", threading.Event())
    assert [c for c in client.calls if c[0] == "9"] == [("9", 1)]


def test_global_seeds_and_refresh(db):
    ranking = [{"nick_no": 100 + i, "world_code": "world_kor", "season_tiercode": "legend"} for i in range(12)]
    games = {"100": [game(1, "500", fmt="global", rule="rta_cs_dodge_down_desc")]}
    client = FakeClient("global", games, seeds=(), ranking=ranking)
    crawler, clock = make(db, client)
    stats = crawler.run_server("global", threading.Event())
    assert stats.players_new == 13  # 排行榜 12 名 + 对手 500
    assert len(client.calls) == 13 and all(p == 1 for _, p in client.calls)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT rule FROM battles").fetchone()[0] == "rta_cs_dodge_down_desc"
    # 没到刷新时间不再采；过了 refresh_hours 每人再采一次
    client.calls.clear()
    crawler.run_server("global", threading.Event())
    assert client.calls == []
    clock[0] += 21 * 3600
    crawler.run_server("global", threading.Event())
    assert len(client.calls) == 13


def test_failing_players_and_consecutive_errors(db):
    client = FakeClient("cn", {"1": [game(1, "2"), game(2, "3")], "3": [game(3, "1")]}, fail={"2"})
    crawler, _ = make(db, client)
    stats = crawler.run_server("cn", threading.Event())
    assert stats.errors == 1 and stats.battles_new == 3
    assert sqlite3.connect(db).execute("SELECT fails FROM players WHERE nick_no='2'").fetchone()[0] == 1

    games = {"1": [game(i, str(100 + i)) for i in range(20)]}
    client = FakeClient("cn", games, fail={str(100 + i) for i in range(20)})
    crawler, _ = make(db.with_name("c.sqlite"), client, max_errors=5)
    stats = crawler.run_server("cn", threading.Event())
    assert stats.stopped.startswith("连续出错 5 次")


def test_request_caps_and_resume(db):
    games = {str(i): [game(i, str(i + 1))] for i in range(1, 30)}
    client = FakeClient("cn", games)
    crawler, _ = make(db, client, max_requests=5)
    stats = crawler.run_server("cn", threading.Event())
    assert "请求上限 5" in stats.stopped and stats.requests == 5
    first = len(client.calls)
    # 断点续采：新的 Crawler 接着队列往下采
    crawler, _ = make(db, client, max_requests=5)
    crawler.run_server("cn", threading.Event())
    assert client.calls[first][0] == str(first + 1)
    # 每天上限（两次运行合计）
    crawler, _ = make(db, client, daily_cap=12)
    stats = crawler.run_server("cn", threading.Event())
    assert "每天的请求上限" in stats.stopped
    day = connect(db).execute("SELECT v FROM meta").fetchone()[0]
    assert int(day) == 12


def test_stop_event(db):
    client = FakeClient("cn", {"1": [game(1, "2")]})
    crawler, _ = make(db, client)
    stop = threading.Event()
    stop.set()
    assert crawler.run_server("cn", stop).stopped == "手动停止"


def test_default_db_path(tmp_path, monkeypatch):
    from e7helper.core.rta import crawl

    target = tmp_path / "x" / "crawl.sqlite"
    monkeypatch.setenv("E7_RTA_DB", str(target))
    assert crawl.default_db_path() == target and target.parent.is_dir()
    monkeypatch.delenv("E7_RTA_DB")
    monkeypatch.setattr(crawl, "DEFAULT_DB", tmp_path / "d" / "crawl.sqlite")
    assert crawl.default_db_path() == tmp_path / "d" / "crawl.sqlite"


def test_run_threads_and_iter(db):
    cn = FakeClient("cn", {"1": [game(1, "2")]})
    gl = FakeClient("global", {"7": [game(1, "8", fmt="global")]}, seeds=("7",))
    crawler = Crawler(db, CrawlConfig(), clients={"cn": cn, "global": gl}, now=lambda: 1_000_000.0)
    res = crawler.run()
    assert set(res) == {"cn", "global"} and res["cn"].battles_new == 1 and res["global"].battles_new == 1
    assert sorted(s for s, _ in iter_battles(db)) == ["cn", "global"]
    assert [r["battle_seq"] for _, r in iter_battles(db, server="global")] == ["1"]
    summary = crawler.summary()
    assert summary["battles"] == {f"cn/{SEASON}": 1, f"global/{SEASON}": 1}


# —— 补开局行动条（B14d1） ——

def old_game(seq, enemy_no):
    """B14d1 之前存的对局：原始字段里没有 energyGauge。"""
    raw = game(seq, enemy_no)
    raw.pop("energyGauge")
    return raw


def test_fill_energy_on_seen_battles(db):
    from rta_fakes import gauge

    client = FakeClient("cn", {"1": [old_game(10, "9"), old_game(11, "9")], "9": []})
    crawler, clock = make(db, client)
    crawler.run_server("cn", threading.Event())
    # 再采到时一场带行动条（还换成了对方视角）、一场没有
    client = FakeClient("cn", {"1": [game(10, "9", me_first=False, iswin=2, energyGauge=gauge()), old_game(11, "9")],
                               "9": []})
    clock[0] += 30 * 3600
    crawler, _ = make(db, client, now=clock)
    stats = crawler.run_server("cn", threading.Event())
    assert stats.battles_filled == 1 and stats.battles_seen == 1 and stats.battles_new == 0
    m = parse_battle(json.loads(sqlite3.connect(db).execute("SELECT raw FROM battles WHERE key='cn:10'").fetchone()[0]), "cn")
    assert m.first_mover == "S" and m.winner == "F"  # 换了视角，同一场的结果不变
    # 已经有行动条的不再改
    client = FakeClient("cn", {"1": [game(10, "9", energyGauge=gauge(mine=(100, 1, 2, 3, 0)))], "9": []})
    clock[0] += 30 * 3600
    crawler, _ = make(db, client, now=clock)
    assert crawler.run_server("cn", threading.Event()).battles_filled == 0


def test_backfill_repages_season(db):
    """--backfill：国服翻完的玩家从第 1 页重翻，补上行动条的页面算有新内容、继续往前翻。"""
    from rta_fakes import gauge

    old = [old_game(1000 + i, "9") for i in range(250)]
    client = FakeClient("cn", {"1": old, "9": []})
    crawler, clock = make(db, client)
    crawler.run_server("cn", threading.Event())
    new = [game(1000 + i, "9", energyGauge=gauge()) for i in range(250)]
    # 不补采：刚采过，没有待采的玩家
    client = FakeClient("cn", {"1": new, "9": []})
    crawler, _ = make(db, client, now=clock)
    assert crawler.run_server("cn", threading.Event()).stopped == "没有待采的玩家"
    # 补采：1 号从第 1 页翻到第 3 页，250 场都补上
    client = FakeClient("cn", {"1": new, "9": []})
    crawler, _ = make(db, client, now=clock, backfill=True)
    stats = crawler.run_server("cn", threading.Event())
    assert [c for c in client.calls if c[0] == "1"] == [("1", 1), ("1", 2), ("1", 3)]
    assert stats.battles_filled == 250 and stats.battles_new == 0
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM battles WHERE instr(raw, '\"energyGauge\"') > 0").fetchone()[0] == 250
