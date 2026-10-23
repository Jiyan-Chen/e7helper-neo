"""B14a：采集数据报告。"""

import json

from e7helper.core.rta.battle import strip
from e7helper.core.rta.crawl import connect
from e7helper.core.rta.report import build_report
from rta_fakes import ENEMY, MY, battle


def _insert(conn, server, raw):
    conn.execute("INSERT INTO battles (key, server, season, day, raw, added) VALUES (?, ?, ?, ?, ?, 0)",
                 (f"{server}:{raw['battle_seq'] or 'x'}", server, raw["season_code"], raw["battle_day"][:19],
                  json.dumps(strip(raw), ensure_ascii=False)))


def test_build_report(tmp_path):
    db = tmp_path / "crawl.sqlite"
    conn = connect(db)
    _insert(conn, "cn", battle(1, grades=("legend", "warlord")))
    _insert(conn, "cn", battle(2, me_first=False, iswin=1, day="2026-10-20 01:00:00.0"))  # 后手赢
    _insert(conn, "cn", battle(3, my_deck={"hero_list": [], "preban_list": []}, teamBettleInfo='"my_team":[]'))
    _insert(conn, "global", battle(4, fmt="global", rule="rta_cs_dodge_down_desc", grades=("gold", "champion")))
    _insert(conn, "global", battle(5, fmt="global", rule="rta_cs_new_rule_desc", opening_rule_title="rta_openingrule_category_2",
                                   prebans=(("m8041_apr", "c3002"), ("c3001", "c3003"))))
    conn.execute("INSERT INTO players (server, season, nick_no, world, added) VALUES ('cn', 's', '1', 'w', 0)")
    conn.commit()
    conn.close()

    rep = build_report(db, known_codes=set(MY) | set(ENEMY[:4]))
    assert rep["total"] == 5 and rep["parsed"] == 4 and rep["parse_rate"] == 0.8
    cn, gl = rep["servers"]["cn"], rep["servers"]["global"]
    assert cn["failed"] == {"没有选秀": 1} and cn["first_win_rate"] == 0.5
    assert cn["seasons"] == {"pvp_rta_ss21": 2} and cn["irregular"] == 0
    assert cn["grades"] == {"战神": 1, "王者": 1} and cn["rules"] == {"无": 2}
    assert cn["days"] == ["2026-10-19 10:35:59", "2026-10-20 01:00:00"]
    assert gl["grades"] == {"金牌及以下": 1, "王者": 1} and gl["irregular"] == 1
    assert gl["rules"] == {"特殊": 1, "防御": 1}
    assert rep["rules_seen"]["rta_cs_new_rule_desc"] == {"count": 1, "category": "rta_openingrule_category_2",
                                                         "label": "防御"}
    h = rep["heroes"]
    assert h["picked"] == 10 and h["top_picks"][0][1] == 4
    assert h["top_prebans"][0] == ("c3001", 7)
    assert h["unknown"] == ["c2005", "c3001", "c3002", "c3003", "m8041_apr"]
    assert rep["per_day"] == {"cn:2026-10-19": 1, "cn:2026-10-20": 1, "global:2026-10-19": 2}
    assert rep["queue"] == {"cn/s": (1, 1)}
