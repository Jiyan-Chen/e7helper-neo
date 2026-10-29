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


def gauge(my=MY, enemy=ENEMY, mine=(100, 80, 70, 60, 0), theirs=(90, 75, 65, 0, 55)) -> str:
    """开局行动条（B14d1，`energyGauge` 的格式）：mine / theirs 按这一方的选人顺序，被后禁的是 0（默认的
    battle() 里我方第 5 手、对方第 4 手被禁）。team "1" 是「我方」，position_no 是第几手。顺序打乱过。"""
    units = [{"hero_code": c, "energy": e, "team": team, "position_no": str(i + 1)}
             for team, codes, es in (("1", my, mine), ("2", enemy, theirs)) for i, (c, e) in enumerate(zip(codes, es))]
    units.sort(key=lambda u: u["energy"])
    return '"energy_gauge":' + json.dumps(units)


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


def synthetic_dataset(n: int = 1500, heroes: int = 40, days: int = 30, seed: int = 0):
    """B14b：合法选秀的合成快照（不用采集库）。c0 / c1 / c2 是强英雄（在哪边哪边大概率赢），给训练测试一个能学到的信号。"""
    import numpy as np

    from e7helper.core.rta import encode, rules
    from e7helper.core.rta.dataset import Dataset

    rng = np.random.default_rng(seed)
    tokens = np.full((n, encode.SEQ_LEN), -1, dtype=np.int16)
    first_wins = np.zeros(n, dtype=np.int8)
    for i in range(n):
        drawn = rng.choice(heroes, 14, replace=False)
        tokens[i, 1:5] = drawn[:4]
        tokens[i, 5:15] = drawn[4:]
        f = [drawn[4 + k] for k, s in enumerate(rules.PICK_ORDER) if s == "F"]
        s_ = [drawn[4 + k] for k, s in enumerate(rules.PICK_ORDER) if s == "S"]
        tokens[i, 15] = f[rng.choice([0, 1, 3, 4])]  # 保护位（第 3 手）不能被禁
        tokens[i, 16] = s_[rng.choice([0, 1, 3, 4])]
        score = sum(h in f for h in (0, 1, 2)) - sum(h in s_ for h in (0, 1, 2))
        first_wins[i] = rng.random() < 1 / (1 + np.exp(-1.5 * score))
    grades = rng.integers(4, encode.N_GRADES, size=(n, 2)).astype(np.int8)
    return Dataset(
        codes=[f"c{i}" for i in range(heroes)], rule_table=[("rta_cs_dodge_down_desc", "rta_openingrule_category_6")],
        tokens=tokens, grades=grades, rule=rng.choice([-2, -1, 0], n).astype(np.int16),
        server=rng.integers(0, 2, n).astype(np.int8), day=np.sort(rng.integers(739900, 739900 + days, n)).astype(np.int32),
        first_wins=first_wins, turns=np.full(n, 10, dtype=np.int16), meta={"season": "test", "kept": n},
    )


class FakeModel:
    """B14c 搜索测试用的假模型（和 `model.RtaModel` 一样有 vocab / calibration / run）：
    胜率 logit = 先手方已选英雄的强度之和 − 后手方的（被禁的减掉），按位置累加（因果）；
    选人头 = 每名英雄固定的热度（logit），不看局面。校准是恒等的，所以胜率 = σ(logit)，结果能手算。
    order 不为 0 时，每一手再加 order × 位置编号 × 强度（让同一对英雄换顺序结果不一样）；
    preban 不为 0 时，先手方预禁的英雄按 +preban × 强度算（后手方的是 −），让预禁也有影响。"""

    def __init__(self, strength: dict[str, float], pop: dict[str, float], order: float = 0.0, preban: float = 0.0):
        import numpy as np

        from e7helper.core.rta import encode, rules

        codes = list(strength)
        self.vocab = encode.Vocab(heroes=codes)
        self.calibration = {"scale": [1.0] * encode.N_STATES, "bias": [0.0] * encode.N_STATES}
        self.meta = {"kind": "fake", "run": "fake"}
        v = self.vocab.size
        self.s = np.zeros(v)
        self.pop = np.full(v, -30.0)
        for c, x in strength.items():
            self.s[self.vocab.hero(c)] = x
            self.pop[self.vocab.hero(c)] = pop.get(c, -30.0)
        sign = np.zeros(encode.SEQ_LEN)
        for k, side in enumerate(rules.PICK_ORDER):
            sign[encode.PICK_POS + k] = (1 if side == "F" else -1) * (1 + order * k)
        sign[encode.BAN_POS["F"]], sign[encode.BAN_POS["S"]] = -1, 1
        sign[list(encode.PREBAN_POS["F"])], sign[list(encode.PREBAN_POS["S"])] = preban, -preban
        self.sign = sign
        self.calls = 0

    def run(self, heroes, ctx):
        import numpy as np

        self.calls += 1
        w = np.cumsum(self.s[heroes] * self.sign[None, :], axis=1)
        p = np.broadcast_to(self.pop, (len(heroes), heroes.shape[1], len(self.pop)))
        return w.astype(np.float32), p.astype(np.float32)


    # 和 RtaModel 一样的几个高层方法（只用到 vocab / run / calibration），audit 和 sim 要用
    def evaluate(self, states):
        from e7helper.core.rta.model import RtaModel

        return RtaModel.evaluate(self, states)

    def win(self, states):
        return self.evaluate(states).win

    def next_picks(self, state, k: int = 8):
        from e7helper.core.rta.model import RtaModel

        return RtaModel.next_picks(self, state, k)

def fake_priors(picks: dict[str, int], preban: dict[str, list] | None = None, postban: dict[str, list] | None = None):
    """B14c：假数据先验。preban = {"F": [[a, b, 次数], ...], "S": [...]}；postban = {编号: [被禁, 可被禁]}。"""
    from e7helper.core.rta.priors import Priors

    pre = {s: {"total": sum(x[2] for x in v), "pairs": v} for s, v in (preban or {"F": [], "S": []}).items()}
    return Priors(picks=dict(picks), preban=pre, postban=dict(postban or {}), meta={"built": "fake"})

