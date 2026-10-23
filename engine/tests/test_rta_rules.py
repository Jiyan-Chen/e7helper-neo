"""B14a：选秀规则。"""

import pytest

from e7helper.core.rta import rules


def test_pick_order_is_1_2_2_2_2_1():
    assert "".join(rules.PICK_ORDER) == "FSSFFSSFFS"
    assert [rules.mover(n) for n in range(11)] == [*rules.PICK_ORDER, None]
    assert [rules.left_in_turn(n) for n in range(11)] == [1, 2, 1, 2, 1, 2, 1, 2, 1, 1, 0]
    assert rules.side_counts(0) == (0, 0)
    assert rules.side_counts(3) == (1, 2)
    assert rules.side_counts(10) == (5, 5)


def test_interleave():
    seq = rules.interleave(["f1", "f2", "f3"], ["s1", "s2"])
    assert seq == [("F", "f1"), ("S", "s1"), ("S", "s2"), ("F", "f2"), ("F", "f3")]
    with pytest.raises(ValueError):
        rules.interleave(["f1", "f2"], ["s1"])  # 先手第 2 手要在后手两手之后


def test_grade_bucket_and_rule_label():
    assert rules.grade_bucket("bronze") == rules.grade_bucket("gold") == "gold"
    assert rules.grade_bucket("legend") == "legend"
    assert rules.grade_bucket("") is None
    assert rules.rule_label("rta_cs_soulburn_dmg_up_desc") == "攻击"
    assert rules.rule_label("rta_cs_something_new_desc") == "未知规则"
    assert rules.rule_label("rta_cs_something_new_desc", "rta_openingrule_category_4") == "抵抗"
    assert rules.rule_label(None) == "无"


FULL_F = ["a1", "a2", "a3", "a4", "a5"]
FULL_S = ["b1", "b2", "b3", "b4", "b5"]


def test_validate_ok():
    assert rules.validate({"F": ["x1", "x2"], "S": ["x1", "x3"]}, {"F": ["a1"], "S": ["b1", "b2"]}) == []
    assert rules.validate({}, {"F": FULL_F, "S": FULL_S}, {"F": "a5", "S": "b1"}, complete=True) == []


@pytest.mark.parametrize("prebans,picks,banned,complete,needle", [
    ({}, {"F": ["a1", "a2"], "S": ["b1"]}, {}, False, "1-2-2-2-2-1"),
    ({}, {"F": ["a1"], "S": ["a1", "b2"]}, {}, False, "选了两次"),
    ({"F": ["b1"]}, {"F": ["a1"], "S": ["b1", "b2"]}, {}, False, "被预禁"),
    ({"F": ["x1", "x2", "x3"]}, {}, {}, False, "最多 2"),
    ({"S": ["x1", "x1"]}, {}, {}, False, "重复"),
    ({}, {"F": FULL_F, "S": FULL_S}, {"F": "a3", "S": "b1"}, True, "保护位"),
    ({}, {"F": FULL_F, "S": FULL_S}, {"F": "b2", "S": "b1"}, True, "不在这一方"),
    ({}, {"F": ["a1"], "S": []}, {"F": "a1"}, False, "还没选完"),
    ({}, {"F": FULL_F, "S": FULL_S}, {"F": "a1"}, True, "后禁不完整"),
    ({}, {"F": ["a1"], "S": ["b1", "b2"]}, {}, True, "没有选完"),
])
def test_validate_problems(prebans, picks, banned, complete, needle):
    problems = rules.validate(prebans, picks, banned, complete=complete)
    assert any(needle in p for p in problems), problems
