"""视觉层单元测试（合成图像，不依赖设备和游戏截图）。"""

import json
import logging
import re
import sys

import cv2
import numpy as np
import pytest

from e7helper.core.geometry import FULL_SCREEN, Rect, Scaler
from e7helper.core.imageio import read_image, write_image
from e7helper.core.vision import (
    Ocr,
    Template,
    TemplateMeta,
    TemplateNotFound,
    TemplateStore,
    Vision,
    best_match,
    find,
    find_all,
    normalize_text,
    parse_fraction,
    parse_number,
)
from e7helper.modules import ModuleContext


def _background(seed: int = 0) -> np.ndarray:
    """有纹理的 1600x900 背景，避免大片纯色导致相关系数无意义。"""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, (90, 160, 3), dtype=np.uint8)
    return cv2.resize(noise, (1600, 900), interpolation=cv2.INTER_CUBIC)


def _icon(w: int = 80, h: int = 60, color=(0, 200, 255)) -> np.ndarray:
    icon = np.full((h, w, 3), 40, np.uint8)
    cv2.circle(icon, (w // 3, h // 2), h // 3, color, -1)
    cv2.rectangle(icon, (w // 2, 8), (w - 8, h - 8), (255, 255, 255), 3)
    cv2.line(icon, (4, h - 4), (w - 4, 4), (30, 60, 220), 2)
    return icon


def _paste(frame: np.ndarray, img: np.ndarray, x: int, y: int) -> Rect:
    h, w = img.shape[:2]
    frame[y : y + h, x : x + w] = img
    return Rect(x, y, w, h)


def _close(a: Rect, b: Rect, tol: int = 2) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b, strict=True))


# ---------------------------------------------------------------- geometry


def test_rect_basics():
    r = Rect.parse("10, 20, 30, 40")
    assert r == Rect(10, 20, 30, 40) and r.right == 40 and r.bottom == 60 and r.center == (25, 40)
    assert Rect.parse([1, 2, 3, 4]) == Rect(1, 2, 3, 4)
    with pytest.raises(ValueError):
        Rect.parse("1,2,3")
    with pytest.raises(ValueError):
        Rect.parse("1,2,0,4")
    assert Rect(-10, -10, 50, 50).clip() == Rect(0, 0, 40, 40)
    assert Rect(1590, 890, 50, 50).clip() == Rect(1590, 890, 10, 10)
    assert Rect(2000, 0, 10, 10).clip().area == 0
    assert Rect(0, 0, 10, 10).iou(Rect(0, 0, 10, 10)) == 1.0
    assert Rect(0, 0, 10, 10).iou(Rect(5, 0, 10, 10)) == pytest.approx(50 / 150)
    assert Rect(0, 0, 10, 10).iou(Rect(20, 20, 5, 5)) == 0.0
    assert FULL_SCREEN.contains(Rect(100, 100, 10, 10))
    assert Rect(10, 10, 5, 5).expand(5) == Rect(5, 5, 15, 15)


def test_scaler_rect():
    s = Scaler(1920, 1080)
    assert s.rect_to_device(Rect(100, 50, 200, 100)) == Rect(120, 60, 240, 120)
    assert s.rect_to_base(Rect(120, 60, 240, 120)) == Rect(100, 50, 200, 100)


# ---------------------------------------------------------------- matcher


@pytest.fixture
def scene():
    frame = _background()
    icon = _icon()
    rect = _paste(frame, icon, 700, 400)
    return frame, Template("icon", icon), rect


def test_find_exact(scene):
    frame, tpl, rect = scene
    m = find(frame, tpl)
    assert m is not None and m.rect == rect and m.score > 0.99
    assert m.center == rect.center


@pytest.mark.parametrize("size", [(1920, 1080), (1280, 720), (2560, 1440)])
def test_find_scaled_frame(scene, size):
    frame, tpl, rect = scene
    scaled = cv2.resize(frame, size, interpolation=cv2.INTER_AREA if size[0] < 1600 else cv2.INTER_CUBIC)
    m = find(scaled, tpl)
    assert m is not None, best_match(scaled, tpl)
    assert _close(m.rect, rect), m


def test_region_limits_search(scene):
    frame, tpl, rect = scene
    assert find(frame, tpl, region=Rect(0, 0, 600, 900)) is None
    assert find(frame, tpl, region=rect.expand(10)) is not None
    # 模板比区域大：没有结果，best_match 也返回 None
    assert best_match(frame, tpl, region=Rect(0, 0, 40, 40)) is None
    # 区域完全在画面外
    assert find(frame, tpl, region=Rect(3000, 3000, 100, 100)) is None


def test_template_region_from_meta(scene):
    frame, tpl, rect = scene
    left = Template("icon", tpl.image, TemplateMeta(region=Rect(0, 0, 600, 900)))
    assert find(frame, left) is None
    assert find(frame, left, region=FULL_SCREEN) is not None  # 显式 region 覆盖 meta


def test_threshold(scene):
    frame, tpl, rect = scene
    frame = frame.copy()
    # 把画面中的图标改掉一部分，分数下降
    cv2.rectangle(frame, (rect.x, rect.y), (rect.x + 40, rect.bottom), (0, 0, 0), -1)
    m = best_match(frame, tpl)
    assert m is not None and m.score < 0.85
    assert find(frame, tpl) is None
    assert find(frame, tpl, threshold=m.score - 0.01) is not None


def test_find_all_and_nms():
    frame = _background(1)
    icon = _icon()
    rects = [_paste(frame, icon, x, y) for x, y in ((100, 100), (400, 100), (100, 600))]
    hits = find_all(frame, Template("icon", icon))
    assert len(hits) == 3
    assert sorted(h.rect for h in hits) == sorted(rects)
    assert hits == sorted(hits, key=lambda h: h.score, reverse=True)
    assert len(find_all(frame, Template("icon", icon), max_count=2)) == 2
    assert len(find_all(frame, Template("icon", icon), region=Rect(0, 0, 800, 400))) == 2


def test_multiscale():
    frame = _background(2)
    icon = _icon()
    big = cv2.resize(icon, None, fx=1.2, fy=1.2, interpolation=cv2.INTER_CUBIC)
    rect = _paste(frame, big, 500, 300)
    single = Template("icon", icon)
    multi = Template("icon", icon, TemplateMeta(scales=[0.8, 0.9, 1.0, 1.1, 1.2]))
    assert find(frame, single) is None
    m = find(frame, multi)
    assert m is not None and m.scale == 1.2 and _close(m.rect, rect)


def test_grayscale_ignores_color_shift(scene):
    frame, tpl, rect = scene
    # 只改色相、保持亮度大致不变：彩色匹配分数降低，灰度匹配不受影响
    shifted = frame.copy()
    patch = cv2.cvtColor(rect.crop(shifted), cv2.COLOR_BGR2HSV)
    patch[..., 0] = (patch[..., 0].astype(int) + 60) % 180
    shifted[rect.y : rect.bottom, rect.x : rect.right] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
    color = best_match(shifted, tpl)
    gray = best_match(shifted, Template("icon", tpl.image, TemplateMeta(grayscale=True)))
    assert gray.score > color.score
    assert gray.rect == rect


def test_flat_template_no_nan():
    frame = np.full((900, 1600, 3), 128, np.uint8)
    tpl = Template("flat", np.full((20, 20, 3), 128, np.uint8))
    m = best_match(frame, tpl)
    assert m is not None and np.isfinite(m.score)


def test_find_timing(scene):
    import time

    frame, tpl, rect = scene
    region = rect.expand(40)
    find(frame, tpl, region)
    t = time.perf_counter()
    for _ in range(20):
        find(frame, tpl, region)
    assert (time.perf_counter() - t) / 20 < 0.01  # 小区域匹配应在 10ms 内


# ---------------------------------------------------------------- template store


def test_store_roundtrip(tmp_path):
    root = tmp_path / "中文目录" / "cn"
    store = TemplateStore(root)
    assert store.names() == []
    icon = _icon()
    meta = TemplateMeta(region=Rect(10, 20, 300, 200), box=Rect(50, 60, 80, 60), threshold=0.9, note="测试")
    tpl = store.save("shop/图标", icon, meta)
    assert (root / "shop" / "图标.png").is_file()
    data = json.loads((root / "shop" / "图标.json").read_text(encoding="utf-8"))
    assert data == {
        "ref_size": [1600, 900], "region": [10, 20, 300, 200], "box": [50, 60, 80, 60],
        "threshold": 0.9, "note": "测试",
    }
    assert tpl.region == Rect(10, 20, 300, 200) and tpl.threshold == 0.9
    np.testing.assert_array_equal(tpl.image, icon)

    fresh = TemplateStore(root)
    assert fresh.names() == ["shop/图标"]
    assert "shop/图标" in fresh and "nope" not in fresh
    assert fresh["shop/图标"].meta == tpl.meta
    with pytest.raises(FileExistsError):
        fresh.save("shop/图标", icon)
    fresh.save("shop/图标", icon, TemplateMeta(), overwrite=True)
    assert fresh.get("shop/图标").meta.region is None
    with pytest.raises(TemplateNotFound):
        fresh.get("missing")
    with pytest.raises(ValueError):
        fresh.get("../escape")


def test_store_png_without_json_and_ref_size(tmp_path):
    icon = _icon(64, 48)
    write_image(tmp_path / "plain.png", icon)
    write_image(tmp_path / "small.png", icon)
    (tmp_path / "small.json").write_text('{"ref_size": [1280, 720], "extra_field": 1}', encoding="utf-8")
    store = TemplateStore(tmp_path)
    assert store.get("plain").meta == TemplateMeta()
    small = store.get("small")
    assert small.size == (80, 60)  # 1280 → 1600，放大 1.25 倍
    assert small.meta.model_extra == {"extra_field": 1}


def test_imageio_unicode_path(tmp_path):
    img = _icon()
    p = write_image(tmp_path / "图片" / "a.png", img)
    np.testing.assert_array_equal(read_image(p), img)


def test_vision_lookup_order(tmp_path):
    a, b = TemplateStore(tmp_path / "a"), TemplateStore(tmp_path / "b")
    a.save("x", _icon(color=(255, 0, 0)))
    b.save("x", _icon(color=(0, 255, 0)))
    b.save("y", _icon())
    v = Vision([a, b])
    assert v.template("x").path.parent == a.root
    assert v.template("y").path.parent == b.root
    with pytest.raises(TemplateNotFound):
        v.template("z")

    frame = _background()
    rect = _paste(frame, _icon(), 300, 300)
    assert v.exists(frame, "y") and v.find(frame, "y").rect == rect
    assert v.find_any(frame, ["x", "y"]).name == "y"


def test_module_context_vision_field(tmp_path):
    ctx = ModuleContext(device=None, logger=logging.getLogger("t"), assets_dir=tmp_path, data_dir=tmp_path)
    assert ctx.vision is None


# ---------------------------------------------------------------- OCR


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234,567", 1234567),
        ("１２３４", 1234),
        ("12.5万", 125000),
        ("3亿", 300000000),
        ("金币 98,765", 98765),
        ("1O0", 100),
        ("", None),
        ("体力", None),
    ],
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_normalize_text():
    assert normalize_text("要消耗天空石立即更新吗？") == "要消耗天空石立即更新吗?"
    assert normalize_text(" ＳＴＡＧＥ　１０ ") == "STAGE10"
    assert normalize_text("确认") == "确认"


def test_parse_fraction():
    assert parse_fraction("35/120") == (35, 120)
    assert parse_fraction("1,035 / 2,000") == (1035, 2000)
    assert parse_fraction("35") is None


@pytest.fixture(scope="module")
def ocr():
    o = Ocr()
    o.warmup()
    return o


def test_ocr_number_synthetic(ocr):
    frame = np.full((900, 1600, 3), 25, np.uint8)
    cv2.putText(frame, "1,234,567", (1200, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    region = Rect(1190, 30, 180, 42)
    assert ocr.read_number(frame, region) == 1234567
    # 1280x720 的帧按同一基准区域也能读出
    small = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    assert ocr.read_number(small, region) == 1234567


def test_ocr_read_with_detection(ocr):
    frame = np.full((900, 1600, 3), 25, np.uint8)
    cv2.putText(frame, "STAGE 10", (200, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    cv2.putText(frame, "120/80", (200, 400), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    results = ocr.read(frame, Rect(100, 100, 600, 400))
    assert [r.text.replace(" ", "") for r in results] == ["STAGE10", "120/80"]
    assert results[0].rect.y < results[1].rect.y
    assert Rect(150, 150, 300, 80).contains(results[0].rect)


@pytest.mark.skipif(sys.platform != "win32", reason="只检查 Windows 构建")
def test_opencv_has_gui():
    """capture 的框选窗口依赖 highgui。rapidocr 会带入 opencv-python-headless 并覆盖 cv2，
    pyproject 里用 override-dependencies 排除了它；这里防止回归。"""
    info = cv2.getBuildInformation()
    assert re.search(r"Win32 UI:\s+YES", info), "cv2 不带 GUI，可能被 opencv-python-headless 覆盖了"
