"""世界竞技场（RTA）的选秀规则（B14a）。国服和海外相同：

- 双方各秘密预禁 2 名（可以重复），被预禁的英雄双方都不能选；
- 随机决定先手。选人顺序 1-2-2-2-2-1：先手 1 → 后手 2 → 先手 2 → 后手 2 → 先手 2 → 后手 1，双方不能选同一名英雄；
- 每边的第 3 手是保护位，不能被后禁；
- 选完后双方同时从对方的 5 名里禁 1 名（保护位除外），各剩 4 名上场。

这里只放规则和对照表，不依赖设备；对局解析（`battle.py`）、以后的推荐算法和画面识别都用它。
「先手方」记作 F，「后手方」记作 S。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

SIDES = ("F", "S")
PICK_ORDER = ("F", "S", "S", "F", "F", "S", "S", "F", "F", "S")
PICKS_PER_SIDE = 5
PREBANS_PER_SIDE = 2
PROTECTED_SLOT = 2  # 每边按顺序的第 3 手（下标 2）

# 段位（官方战绩站的 grade_code，从低到高）
GRADES = ("bronze", "silver", "gold", "master", "challenger", "champion", "warlord", "emperor", "legend")
GRADE_LABELS = {
    "bronze": "铜牌", "silver": "银牌", "gold": "金牌", "master": "大师", "challenger": "挑战者",
    "champion": "优胜者", "warlord": "战神", "emperor": "王者", "legend": "传说",
}
# 模型和统计用的段位档：金牌及以下合成一档，其余各自一档
GRADE_BUCKETS = ("gold", "master", "challenger", "champion", "warlord", "emperor", "legend")
GRADE_BUCKET_LABELS = {**GRADE_LABELS, "gold": "金牌及以下"}

# 开战规则（优胜者以上，每局随机一条）。键是海外战绩站的 opening_rule_desc_tid；
# 2026 秋季赛季的四条按官方公告（2026 夏季赛季图表）核对。没登记的规则保留原值，名字按类别
# （opening_rule_title）给，类别也不认识才显示「未知规则」。
OPENING_RULES: dict[str, tuple[str, str]] = {
    "rta_cs_soulburn_dmg_up_desc": ("攻击", "灵魂燃烧技能的伤害量增加 15%"),
    "rta_cs_heal_shield_up_desc": ("防御", "恢复量和防护罩效果量增加 30%"),
    "rta_cs_resist_up_50_desc": ("抵抗", "效果抗性增加 50%"),
    "rta_cs_dodge_down_desc": ("特殊", "闪避减少 30%"),
}
# 类别编号 3 / 5 还没见过（2026 夏季的「支援」规则大概是其中一个），见到了再补
OPENING_RULE_CATEGORIES = {
    "rta_openingrule_category_1": "攻击", "rta_openingrule_category_2": "防御",
    "rta_openingrule_category_4": "抵抗", "rta_openingrule_category_6": "特殊",
}


def mover(n: int) -> str | None:
    """已经选了 n 手时，下一手是谁（F / S）；10 手选完返回 None。"""
    return PICK_ORDER[n] if 0 <= n < len(PICK_ORDER) else None


def left_in_turn(n: int) -> int:
    """已经选了 n 手时，当前这一方这一轮还要连选几名（1 或 2）；选完返回 0。"""
    side = mover(n)
    if side is None:
        return 0
    left = 0
    while mover(n + left) == side:
        left += 1
    return left


def side_counts(n: int) -> tuple[int, int]:
    """选了 n 手时先手方、后手方各选了几名。"""
    head = PICK_ORDER[:n]
    return head.count("F"), head.count("S")


def interleave(first: Sequence[str], second: Sequence[str]) -> list[tuple[str, str]]:
    """把双方按顺序的选人合成整局的选秀顺序 [(F/S, 编号), ...]。两边的数量必须是一个合法的前缀。"""
    n = len(first) + len(second)
    if n > len(PICK_ORDER) or side_counts(n) != (len(first), len(second)):
        raise ValueError(f"选人数量不对：先手 {len(first)} 名、后手 {len(second)} 名")
    it = {"F": iter(first), "S": iter(second)}
    return [(side, next(it[side])) for side in PICK_ORDER[:n]]


def grade_bucket(grade: str | None) -> str | None:
    """段位 → 段位档（铜牌 / 银牌 / 金牌合成一档）；不认识的返回 None。"""
    if grade in ("bronze", "silver", "gold"):
        return "gold"
    return grade if grade in GRADE_BUCKETS else None


def rule_label(desc_tid: str | None, category: str | None = None) -> str:
    if not desc_tid:
        return "无"
    if desc_tid in OPENING_RULES:
        return OPENING_RULES[desc_tid][0]
    return OPENING_RULE_CATEGORIES.get(category or "", "未知规则")


def validate(prebans: Mapping[str, Sequence[str]], picks: Mapping[str, Sequence[str]],
             banned: Mapping[str, str | None] | None = None, *, complete: bool = False) -> list[str]:
    """检查一个选秀局面，返回问题列表（中文，空列表 = 合法）。

    prebans / picks / banned 都按 F / S 给：picks 是这一方按顺序选的英雄；banned[F] 是先手方被对方禁掉的那名。
    complete=True 时要求 10 手选完、双方都已后禁。
    """
    banned = banned or {}
    problems: list[str] = []
    f, s = list(picks.get("F", ())), list(picks.get("S", ()))
    n = len(f) + len(s)
    if n > len(PICK_ORDER) or side_counts(n) != (len(f), len(s)):
        problems.append(f"选人数量不符合 1-2-2-2-2-1：先手 {len(f)} 名、后手 {len(s)} 名")
    chosen = f + s
    dup = sorted({c for c in chosen if chosen.count(c) > 1})
    if dup:
        problems.append(f"同一名英雄被选了两次：{'、'.join(dup)}")
    all_prebans: set[str] = set()
    for side in SIDES:
        pre = list(prebans.get(side, ()))
        if len(pre) > PREBANS_PER_SIDE:
            problems.append(f"{side} 预禁了 {len(pre)} 名（最多 {PREBANS_PER_SIDE}）")
        if len(set(pre)) != len(pre):
            problems.append(f"{side} 的预禁有重复")
        all_prebans.update(pre)
    hit = sorted(set(chosen) & all_prebans)
    if hit:
        problems.append(f"被预禁的英雄被选了：{'、'.join(hit)}")
    for side, own in (("F", f), ("S", s)):
        code = banned.get(side)
        if code is None:
            continue
        if n < len(PICK_ORDER):
            problems.append("还没选完就后禁了")
        elif code not in own:
            problems.append(f"{side} 被禁的 {code} 不在这一方的选人里")
        elif own.index(code) == PROTECTED_SLOT:
            problems.append(f"{side} 被禁的 {code} 是第 3 手（保护位）")
    if complete:
        if n != len(PICK_ORDER):
            problems.append(f"没有选完（{n} / {len(PICK_ORDER)} 手）")
        if any(banned.get(side) is None for side in SIDES):
            problems.append("后禁不完整")
    return problems
