import numpy as np

from e7helper.core.geometry import Scaler, is_16_9
from e7helper.device.nemu_ipc import rgba_flipped_to_bgr


def test_is_16_9():
    assert is_16_9(1600, 900)
    assert is_16_9(1920, 1080)
    assert not is_16_9(1600, 1000)


def test_scaler_roundtrip():
    s = Scaler(1920, 1080)
    assert s.to_device(800, 450) == (960, 540)
    assert s.to_base(960, 540) == (800, 450)
    assert not s.is_base
    assert Scaler(1600, 900).is_base


def test_rgba_flipped_to_bgr():
    # 2x1 图，第一行（IPC 中的底行）红色，第二行蓝色
    buf = np.zeros((2, 1, 4), dtype=np.uint8)
    buf[0, 0] = (255, 0, 0, 255)  # RGBA 红
    buf[1, 0] = (0, 0, 255, 255)  # RGBA 蓝
    out = rgba_flipped_to_bgr(buf)
    assert out.shape == (2, 1, 3)
    assert out.flags["C_CONTIGUOUS"]
    assert tuple(out[0, 0]) == (255, 0, 0)  # 翻转后首行是蓝，BGR=(255,0,0)
    assert tuple(out[1, 0]) == (0, 0, 255)  # 红，BGR=(0,0,255)


def _load_paths_copy():
    # 另载一份 paths，不影响其他模块持有的 e7helper.core.paths
    import importlib.util

    from e7helper.core import paths

    spec = importlib.util.spec_from_file_location("_paths_copy", paths.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_paths_source_layout():
    from pathlib import Path

    mod = _load_paths_copy()
    assert not mod.FROZEN
    assert mod.ASSETS_DIR == Path(__file__).resolve().parents[1] / "assets"
    assert (mod.ASSETS_DIR / "common").is_dir()


def test_paths_frozen_uses_meipass(monkeypatch, tmp_path):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    mod = _load_paths_copy()
    assert mod.FROZEN
    assert mod.ENGINE_ROOT == tmp_path
    assert mod.module_assets_dir("common") == tmp_path / "assets" / "common"
