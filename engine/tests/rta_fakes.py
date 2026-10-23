"""RTA 测试用的合成对局（B14a）：字段照官方战绩站的格式手写，不含真实玩家数据。"""

from __future__ import annotations

import json

MY = ("c1001", "c1002", "c1003", "c1004", "c1005")
ENEMY = ("c2001", "c2002", "c2003", "c2004", "c2005")


def _team(codes, banned: int) -> list[dict]:
    out, pos = [], 1
    for i, code in enumerate(codes):
        on_field = i != banned
        out.append({
            "pick_order": i + 1, "hero_code": code, "attack_damage": 1000 * (i + 1) if on_field else 0,
            "receive_damage": 500.5 if on_field else 0.0, "recovery": 0, "mvp_point": 10, "artifact": "efk01",
            "equip": ["set_speed", "set_immune"] if on_field else [], "respawn": 0, "mvp": 0,
            "kill_count": 1 if on_field else 0, "position": pos if on_field else 0, "grade": 6, "awaken_grade": 6,
            "attribute_cd": "fire", "level": 60, "job_cd": "knight",
        })
        if on_field:
            pos += 1
    return out


def _deck(codes, prebans, banned: int, first: bool, fmt: str):
    deck = {
        "hero_list": [{"hero_code": c, "first_pick": int(first and i == 0), "mvp": 0, "ban": int(i == banned)}
                      for i, c in enumerate(codes)],
        "preban_list": list(prebans),
    }
    return json.dumps(deck) if fmt == "global" else deck


def battle(seq: int | str = 1, *, me_first: bool = True, my=MY, enemy=ENEMY, my_banned: int = 4,
           enemy_banned: int = 3, iswin: int = 1, fmt: str = "cn", rule: str | None = None,
           grades=("legend", "emperor"), prebans=(("c3001", "c3002"), ("c3001", "c3003")),
           day: str = "2026-10-19 10:35:59.0", season: str = "pvp_rta_ss21", enemy_no: int = 1100100000002,
           **extra) -> dict:
    """一场合成对局（「我方」视角）。my_banned / enemy_banned 是被后禁的那名在这一方选人里的下标。"""
    team = '"my_team":' + json.dumps(_team(my, my_banned)).replace('"pick_order"', '"pick_order" ')
    team_enemy = '"my_team":' + json.dumps(_team(enemy, enemy_banned))
    raw = {
        "battleCompletedate": "2026-10-19 19:35:59.0", "battle_day": day, "battle_seq": str(seq), "battle_time": 53,
        "my_deck": _deck(my, prebans[0], my_banned, me_first, fmt),
        "enemy_deck": _deck(enemy, prebans[1], enemy_banned, not me_first, fmt),
        "enemy_grade_code": grades[1], "grade_code": grades[0], "enemy_hero_code": "c1179",
        "enemy_nick_no": "对手昵称", "enemy_world_code": "world_zlong1", "iswin": iswin,
        "matchPlayerNicknameno": enemy_no, "nicknameno": "自己昵称", "langCode": "zh-CN",
        "myscore_info": {"up_down_score": 6, "up_down_type": 1, "win_score": 3007}, "regDate": "2026-10-21",
        "season_code": season, "season_name": "2026秋季", "teamBettleInfo": team, "teamBettleInfoenemy": team_enemy,
        "turn": 5, "worldCode": "world_zlong1", "energyGauge": '"energy_gauge":[]',
    }
    if fmt == "global":
        raw["myscore_info"] = json.dumps(raw["myscore_info"])
        raw["enemy_world_code"] = raw["worldCode"] = "world_global"
    if rule:
        raw["opening_rule_title"] = "rta_openingrule_category_1"
        raw["opening_rule_desc_tid"] = rule
    raw.update(extra)
    return raw
