"""真机测试：需要本机 MuMu 实例运行中。启用方式：E7_DEVICE_TESTS=1 uv run pytest -m device"""

import os

import pytest

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(os.environ.get("E7_DEVICE_TESTS") != "1", reason="未设置 E7_DEVICE_TESTS=1"),
]


@pytest.fixture(scope="module")
def device():
    from e7helper.device import connect

    with connect() as d:
        yield d


def test_ipc_capture_shape(device):
    w, h = device.resolution
    frame = device.ipc.capture()
    assert frame.shape == (h, w, 3)
    assert frame.std() > 1


def test_adb_and_ipc_agree(device):
    import numpy as np

    if device.adb is None:
        pytest.skip("adb 不可用")
    a = device.ipc.capture().astype(np.int16)
    b = device.adb.screenshot().astype(np.int16)
    assert a.shape == b.shape
    # 两次截图之间画面可能有动画，只要求大部分像素一致（方向/通道顺序正确）
    assert (np.abs(a - b).max(axis=2) < 16).mean() > 0.8


def test_game_installed(device):
    from e7helper import GAME_PACKAGE

    if device.adb is None:
        pytest.skip("adb 不可用")
    assert device.adb.has_package(GAME_PACKAGE)
