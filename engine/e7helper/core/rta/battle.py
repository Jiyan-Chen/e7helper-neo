"""官方战绩站的一场世界竞技场对局 → 统一结构 `Match`（B14a）。

国服（e7stats.qyzlgame.com）和海外（e7api.onstove.com）是同一套系统，字段相同，差别：
- 海外的 `my_deck` / `enemy_deck` 是 JSON 字符串，国服是对象；
- 只有海外有开战规则 `opening_rule_desc_tid`（优胜者以上每局随机一条）。

一场对局里和选秀有关的字段：
- `my_deck` / `enemy_deck`：`preban_list`（2 名）+ `hero_list[{hero_code, first_pick, ban, mvp}]`，
  先手方的第一名英雄 `first_pick=1`，被后禁的 `ban=1`；
- `teamBettleInfo` / `teamBettleInfoenemy`：字符串 `"my_team":[...]`（JSON 片段，没有外层花括号），
  每名英雄有 `pick_order`（这一方的第几手，1–5）、`position`（站位，0 = 被后禁没上场）、神器、套装、伤害等；
- `iswin`：1 = 「我方」赢，2 = 输；`battle_day` 是 UTC 时间（`battleCompletedate` 是韩国时间，比它晚 9 小时）；
- `energyGauge`：字符串 `"energy_gauge":[{hero_code, energy, team, position_no}, ...]`，**开局行动条**（B14d1 核对：
  国服、海外各 99 场全部成立）：每场 10 条，第一个行动的那名正好是 100，被后禁的两名是 0，其余 ≈ 100 × 自己速度 ÷
  先动者速度 + 开局随机的一点 + 开局效果（例如智武首次战斗开始 +30%）；`team` "1" = 「我方」（采集视角），
  `position_no` = 这一方的第几手（同 `pick_order`），不是站位。B14d1 之前采集没存它（B14a 误认成结算行动条）。

采集时只存 `STORE_KEYS` 里的字段（不含昵称、玩家编号），`parse_battle` 读的也只是这些。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import rules

Server = Literal["cn", "global"]

# 采集时保留的原始字段。原始记录 29 个字段，丢掉的是昵称、玩家编号、对方头像英雄、语言、韩国时间、登记时间、
# 赛季名，以及和 my_deck / myscore_info 重复的预禁、积分字段（B14d1 逐个核对过）
STORE_KEYS = (
    "battle_seq", "season_code", "battle_day", "battle_time", "turn", "iswin", "grade_code", "enemy_grade_code",
    "my_deck", "enemy_deck", "teamBettleInfo", "teamBettleInfoenemy", "opening_rule_title", "opening_rule_desc_tid",
    "worldCode", "enemy_world_code", "myscore_info", "energyGauge",
)
ENERGY_KEY = "energyGauge"


class Pick(BaseModel):
    code: str
    banned: bool = False
    position: int = Field(0, description="站位 1–4；被后禁的是 0")
    artifact: str = ""
    sets: list[str] = []
    dealt: float = 0
    taken: float = 0
    healed: float = 0
    kills: int = 0
    mvp: bool = False
    energy: int | None = Field(None, description="开局行动条 0–100（先动者 100、被后禁的 0）；没采到的是 None")


class Side(BaseModel):
    grade: str = ""
    prebans: list[str] = []
    picks: list[Pick] = Field(default_factory=list, description="这一方按顺序选的 5 名")
    world: str = ""

    @property
    def codes(self) -> list[str]:
        return [p.code for p in self.picks]

    @property
    def banned(self) -> str | None:
        return next((p.code for p in self.picks if p.banned), None)


class Match(BaseModel):
    key: str = Field(description="<服务器>:<battle_seq>，两边视角相同，用来去重")
    server: Server
    season: str
    day: str = Field(description="对局时间（UTC），格式 2026-10-19 10:35:59")
    rule: str | None = Field(None, description="开战规则 opening_rule_desc_tid；国服和优胜者以下没有")
    rule_category: str | None = Field(None, description="开战规则的类别 opening_rule_title")
    turns: int = 0
    seconds: int = 0
    first: Side = Field(description="先手方 F")
    second: Side = Field(description="后手方 S")
    winner: Literal["F", "S"]
    score: int | None = Field(None, description="采集视角那一方的积分（myscore_info.win_score）")
    first_mover: Literal["F", "S"] | None = Field(None, description="战斗里第一个行动的是哪一方；没有开局行动条时是 None")
    first_hero: str | None = Field(None, description="第一个行动的英雄")

    def side(self, name: str) -> Side:
        return self.first if name == "F" else self.second

    def sequence(self) -> list[tuple[str, str]]:
        """整局的选秀顺序 [(F/S, 编号), ...]，共 10 手。"""
        return rules.interleave(self.first.codes, self.second.codes)


class BadBattle(ValueError):
    """解析失败；`reason` 是归类用的简短原因（数据报告按它统计）。"""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}：{detail}" if detail else reason)
        self.reason = reason


def strip(raw: dict) -> dict:
    """采集时去掉不需要的字段（昵称、玩家编号等），只留 `STORE_KEYS`。"""
    return {k: raw[k] for k in STORE_KEYS if k in raw}


def _obj(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError as e:
            raise BadBattle("字段格式不对", value[:40]) from e
    return value


def _fragment(value: Any, key: str) -> Any:
    """`"my_team":[...]` 这种没有外层花括号的 JSON 片段。"""
    if isinstance(value, dict):
        return value.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadBattle("缺对局详情")
    text = value.strip()
    try:
        data = json.loads(text if text.startswith("{") else "{" + text + "}")
    except ValueError as e:
        raise BadBattle("字段格式不对", text[:40]) from e
    return data.get(key)


def _side(deck: Any, team: Any, grade: str, world: str) -> tuple[Side, bool]:
    """一方的牌组 + 对局详情 → (Side, 是否先手)。"""
    deck = _obj(deck)
    if not isinstance(deck, dict) or not isinstance(deck.get("hero_list"), list):
        raise BadBattle("缺牌组")
    heroes = deck["hero_list"]
    if not heroes:  # 选秀阶段有人退出：双方都没有英雄，0 回合（试采 8127 场里有 70 场）
        raise BadBattle("没有选秀")
    team = _fragment(team, "my_team")
    if not isinstance(team, list):
        raise BadBattle("缺对局详情")
    if len(heroes) != rules.PICKS_PER_SIDE or len(team) != rules.PICKS_PER_SIDE:
        raise BadBattle("英雄数量不对", f"{len(heroes)} / {len(team)}")
    flags = {h.get("hero_code"): h for h in heroes}
    try:
        ordered = sorted(team, key=lambda t: int(t["pick_order"]))
    except (KeyError, TypeError, ValueError) as e:
        raise BadBattle("缺选人顺序") from e
    if [int(t["pick_order"]) for t in ordered] != list(range(1, rules.PICKS_PER_SIDE + 1)):
        raise BadBattle("选人顺序不对", str([t.get("pick_order") for t in team]))
    if {t.get("hero_code") for t in ordered} != set(flags):
        raise BadBattle("牌组和对局详情对不上")
    picks = []
    for t in ordered:
        h = flags[t["hero_code"]]
        picks.append(Pick(
            code=t["hero_code"], banned=bool(h.get("ban")), position=int(t.get("position") or 0),
            artifact=t.get("artifact") or "", sets=list(t.get("equip") or []),
            dealt=float(t.get("attack_damage") or 0), taken=float(t.get("receive_damage") or 0),
            healed=float(t.get("recovery") or 0), kills=int(t.get("kill_count") or 0), mvp=bool(h.get("mvp")),
        ))
    first_flags = [bool(h.get("first_pick")) for h in heroes]
    if sum(first_flags) > 1:
        raise BadBattle("先手标记不对", "一方有多个 first_pick")
    # 先手标记在这一方第一手的英雄上
    if any(first_flags) and not flags[ordered[0]["hero_code"]].get("first_pick"):
        raise BadBattle("先手标记不对", "first_pick 不在第一手")
    prebans = [c for c in (deck.get("preban_list") or []) if c]
    return Side(grade=grade or "", prebans=prebans, picks=picks, world=world or ""), any(first_flags)


def read_energy(raw: dict) -> tuple[dict[str, dict[str, int]] | None, str]:
    """开局行动条 → ({"1": {英雄: 行动条}, "2": {...}}, "")；不合格时 (None, 原因)。

    只核对行动条自身：每场 10 条、每方 5 名、第几手 1–5 不重复、行动条 0–100、正好一名 100、正好两名 0。
    和选秀对不对得上由 `parse_battle` 再核对。旧对局没有这个字段，原因是「缺行动条」。"""
    value = raw.get(ENERGY_KEY)
    if not value:
        return None, "缺行动条"
    try:
        units = _fragment(value, "energy_gauge")
    except BadBattle:
        return None, "行动条格式不对"
    if not isinstance(units, list) or len(units) != 2 * rules.PICKS_PER_SIDE:
        return None, "行动条条数不对"
    out: dict[str, dict[str, int]] = {"1": {}, "2": {}}
    orders: dict[str, set[int]] = {"1": set(), "2": set()}
    for u in units:
        if not isinstance(u, dict):
            return None, "行动条格式不对"
        team, code = str(u.get("team")), u.get("hero_code")
        try:
            energy, order = int(u.get("energy")), int(u.get("position_no"))
        except (TypeError, ValueError):
            return None, "行动条格式不对"
        if team not in out or not code or code in out[team] or not 0 <= energy <= 100:
            return None, "行动条格式不对"
        out[team][code] = energy
        orders[team].add(order)
    if any(o != set(range(1, rules.PICKS_PER_SIDE + 1)) for o in orders.values()):
        return None, "行动条格式不对"
    values = [e for side in out.values() for e in side.values()]
    if values.count(100) != 1:
        return None, "先动者不唯一"
    if values.count(0) != 2:
        return None, "行动条为 0 的不是两名"
    return out, ""


def _apply_energy(raw: dict, mine: Side, theirs: Side) -> tuple[str | None, str | None]:
    """把行动条填进双方的 Pick；返回 (先动的一方 "mine" / "theirs", 先动英雄)。对不上就什么都不填。"""
    energy, _ = read_energy(raw)
    if energy is None:
        return None, None
    sides = {"1": mine, "2": theirs}
    for team, side in sides.items():
        if set(energy[team]) != set(side.codes):
            return None, None
        for p in side.picks:
            if (energy[team][p.code] == 0) != p.banned:  # 被后禁的才是 0
                return None, None
    for team, side in sides.items():
        for p in side.picks:
            p.energy = energy[team][p.code]
    team, hero = next((t, c) for t, side in energy.items() for c, e in side.items() if e == 100)
    return ("mine" if team == "1" else "theirs"), hero


def energy_issue(raw: dict, m: Match) -> str:
    """数据报告用：这场为什么没有行动条（"" = 有）。"""
    if m.first_mover:
        return ""
    _, reason = read_energy(raw)
    return reason or "行动条和选秀对不上"


def _rule(value: Any) -> str | None:
    """海外有一方低于优胜者时开战规则字段是占位符「_」，当成没有规则。"""
    return value if isinstance(value, str) and value.strip("_ ") else None


def parse_battle(raw: dict, server: Server) -> Match:
    """一场对局的原始数据 → Match；不合格时抛 BadBattle（带归类原因）。"""
    if not raw.get("battle_seq"):
        raise BadBattle("缺对局编号")
    mine, mine_first = _side(raw.get("my_deck"), raw.get("teamBettleInfo"), raw.get("grade_code", ""),
                             raw.get("worldCode", ""))
    theirs, theirs_first = _side(raw.get("enemy_deck"), raw.get("teamBettleInfoenemy"),
                                 raw.get("enemy_grade_code", ""), raw.get("enemy_world_code", ""))
    if mine_first == theirs_first:
        raise BadBattle("先手标记不对", "双方都是" if mine_first else "双方都不是")
    try:
        iswin = int(raw.get("iswin"))
    except (TypeError, ValueError):
        iswin = 0
    if iswin not in (1, 2):
        raise BadBattle("胜负不明", str(raw.get("iswin")))
    first, second = (mine, theirs) if mine_first else (theirs, mine)
    mover, first_hero = _apply_energy(raw, mine, theirs)
    first_mover = None if mover is None else ("F" if (mover == "mine") == mine_first else "S")
    mine_won = iswin == 1
    winner = "F" if mine_won == mine_first else "S"
    problems = rules.validate(
        {"F": first.prebans, "S": second.prebans}, {"F": first.codes, "S": second.codes},
        {"F": first.banned, "S": second.banned}, complete=True,
    )
    if problems:
        raise BadBattle("不符合选秀规则", "；".join(problems))
    score = _obj(raw.get("myscore_info")) if raw.get("myscore_info") else None
    return Match(
        key=f"{server}:{raw['battle_seq']}", server=server, season=raw.get("season_code", ""),
        day=str(raw.get("battle_day", ""))[:19], rule=_rule(raw.get("opening_rule_desc_tid")),
        rule_category=_rule(raw.get("opening_rule_title")),
        turns=int(raw.get("turn") or 0), seconds=int(raw.get("battle_time") or 0),
        first=first, second=second, winner=winner, first_mover=first_mover, first_hero=first_hero,
        score=int(score["win_score"]) if isinstance(score, dict) and score.get("win_score") is not None else None,
    )
