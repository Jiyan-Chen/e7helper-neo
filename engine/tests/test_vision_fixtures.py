"""在真实游戏截图（tests/fixtures/）上验证模板识别和 OCR。

截图来源：MuMu 1600x900，国服，2026-10-14 采集。
- lobby.png：大厅主界面
- secret_shop.png：秘密商店（列表顶部）
- secret_shop_scrolled.png：秘密商店（列表滑到底部）
- secret_shop_refresh_confirm.png：点「立即更新」后的确认弹窗（其余部分被遮罩压暗）
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from e7helper.core.geometry import Rect
from e7helper.core.imageio import read_image
from e7helper.core.vision import Ocr, Vision, normalize_text

FIXTURES = Path(__file__).parent / "fixtures"

# 每张截图上应命中的模板及位置（只列 x, y；基准坐标）。未列出的模板都不应命中。
EXPECTED: dict[str, dict[str, list[tuple[int, int]]]] = {
    "lobby": {
        "lobby/secret_shop": [(26, 438)],
        "lobby/shop": [(1480, 629)],
        "top/skystone": [(1009, 31)],
    },
    "secret_shop": {
        "back": [(28, 18)],
        "title": [(80, 20)],
        "refresh": [(270, 800)],
        "top/gold": [(828, 34)],
        "top/skystone": [(1014, 31)],
        "buy": [(1450, 180), (1450, 361), (1450, 542), (1450, 724)],
    },
    "secret_shop_scrolled": {
        "back": [(28, 18)],
        "title": [(80, 20)],
        "refresh": [(270, 800)],
        "top/gold": [(828, 34)],
        "top/skystone": [(1014, 31)],
        "buy": [(1450, 90), (1450, 271), (1450, 452), (1450, 634), (1450, 815)],
    },
    # 弹窗遮罩下：标题和顶栏图标仍然可见（没设 max_diff），可点击的按钮因 max_diff 不算命中
    "secret_shop_refresh_confirm": {
        "title": [(80, 20)],
        "top/gold": [(828, 34)],
        "top/skystone": [(1014, 31)],
        "dialog/cancel": [(565, 545)],
        "dialog/confirm": [(833, 545)],
    },
}

ALL_TEMPLATES = sorted({t for exp in EXPECTED.values() for t in exp})


@pytest.fixture(scope="module")
def vision() -> Vision:
    return Vision.for_module("secret_shop")


def _frame(name: str, size: tuple[int, int] | None = None) -> np.ndarray:
    img = read_image(FIXTURES / f"{name}.png")
    assert img.shape == (900, 1600, 3)
    if size is not None:
        interp = cv2.INTER_AREA if size[0] < 1600 else cv2.INTER_CUBIC
        img = cv2.resize(img, size, interpolation=interp)
    return img


def test_all_templates_exist(vision):
    for name in ALL_TEMPLATES:
        tpl = vision.template(name)
        assert tpl.meta.box is not None, name


@pytest.mark.parametrize("size", [None, (1280, 720), (1920, 1080)], ids=["1600x900", "1280x720", "1920x1080"])
@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_templates_on_fixture(vision, fixture, size):
    frame = _frame(fixture, size)
    tol = 0 if size is None else 3
    expected = EXPECTED[fixture]
    for name in ALL_TEMPLATES:
        hits = vision.find_all(frame, name)
        got = sorted((h.rect.x, h.rect.y) for h in hits)
        want = sorted(expected.get(name, []))
        assert len(got) == len(want), f"{fixture}/{name}: {[str(h) for h in hits]}"
        for (gx, gy), (wx, wy) in zip(got, want, strict=True):
            assert abs(gx - wx) <= tol and abs(gy - wy) <= tol, f"{fixture}/{name}: {got} != {want}"


def test_find_any_identifies_scene(vision):
    scenes = {"lobby": "lobby/shop", "secret_shop": "title"}
    for fixture, marker in scenes.items():
        m = vision.find_any(_frame(fixture), scenes.values())
        assert m is not None and m.name == marker


def test_dimmed_button_rejected_by_max_diff(vision):
    """相关系数对亮度不敏感：遮罩下的「购买」分数依然很高，靠 max_diff 区分。"""
    frame = _frame("secret_shop_refresh_confirm")
    best = vision.best(frame, "buy")
    assert best.score > 0.95 and best.diff > 30
    assert vision.find(frame, "buy") is None


# ---------------------------------------------------------------- OCR


@pytest.fixture(scope="module")
def ocr() -> Ocr:
    o = Ocr()
    o.warmup()
    return o


NUMBERS = [
    ("lobby", Rect(1040, 22, 90, 38), 19891),  # 天空石
    ("secret_shop", Rect(1040, 20, 92, 40), 19891),  # 天空石
    ("secret_shop", Rect(855, 20, 145, 40), 28698072),  # 金币
    ("secret_shop", Rect(1445, 115, 105, 45), 29000),  # 价格
    ("secret_shop", Rect(1445, 478, 105, 45), 18000),
    ("secret_shop", Rect(160, 805, 30, 40), 3),  # 刷新消耗的天空石
    ("secret_shop_scrolled", Rect(1430, 752, 120, 45), 560000),
]


@pytest.mark.parametrize("size", [None, (1280, 720)], ids=["1600x900", "1280x720"])
@pytest.mark.parametrize(("fixture", "region", "expected"), NUMBERS)
def test_ocr_numbers(ocr, fixture, region, expected, size):
    assert ocr.read_number(_frame(fixture, size), region) == expected


def test_ocr_fractions(ocr):
    frame = _frame("lobby")
    assert ocr.read_fraction(frame, Rect(890, 22, 110, 38)) == (43, 360)  # 体力
    assert ocr.read_fraction(frame, Rect(792, 20, 62, 40)) == (5, 5)  # 竞技场旗帜


def test_ocr_chinese_line(ocr):
    frame = _frame("secret_shop")
    assert ocr.read_line(frame, Rect(855, 148, 180, 46)).text == "橄榄石龙"
    assert ocr.read_line(frame, Rect(855, 508, 180, 50)).text == "友情点数"
    assert ocr.read_line(frame, Rect(50, 592, 225, 44)).text == "秘密商店等级13"


def test_ocr_detect_dialog_text(ocr):
    frame = _frame("secret_shop_refresh_confirm")
    assert normalize_text(ocr.read_text(frame, Rect(500, 360, 600, 90))) == normalize_text("要消耗天空石立即更新吗？")
    texts = [r.text for r in ocr.read(frame, Rect(520, 520, 560, 110))]
    assert texts == ["取消", "确认"]


def test_ocr_detect_item_column(ocr):
    """检测 + 识别一整列商品名，按从上到下排序。"""
    frame = _frame("secret_shop")
    texts = [r.text for r in ocr.read(frame, Rect(850, 140, 220, 600))]
    names = [t for t in texts if t not in ("英雄", "货币") and not t.startswith("可购买")]
    assert names == ["橄榄石龙", "铁血剑兵", "友情点数", "风云风獬兽"]
