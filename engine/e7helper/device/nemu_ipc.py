"""MuMu 截图增强 / 触控 IPC（external_renderer_ipc.dll）的 ctypes 封装。

实测（MuMu 6.6.4, Android 15, 1600x900）：
- nemu_connect(安装根目录, 实例 index) 返回非 0 句柄
- nemu_capture_display 返回 RGBA、上下颠倒的帧，单帧约 3~10ms
- touch 坐标直接使用横屏像素坐标，无需旋转
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from pathlib import Path

import numpy as np

from .base import DeviceError

log = logging.getLogger(__name__)


class NemuIpcError(DeviceError):
    pass


def rgba_flipped_to_bgr(buf: np.ndarray) -> np.ndarray:
    """IPC 帧（RGBA、上下颠倒）→ 正向 BGR。"""
    return np.ascontiguousarray(buf[::-1, :, 2::-1])


class NemuIpc:
    def __init__(self, dll_path: str | Path, mumu_root: str | Path, instance_index: int):
        self._lock = threading.Lock()
        # 注意：DLL 会往原生 stdout 打印调试信息，入口需调用 core.stdio.isolate_native_stdout()
        try:
            self._lib = ctypes.CDLL(str(dll_path))
        except OSError as e:
            raise NemuIpcError(f"无法加载 {dll_path}：{e}") from e
        self._bind()
        self._handle = self._lib.nemu_connect(str(mumu_root), int(instance_index))
        if self._handle == 0:
            raise NemuIpcError(f"nemu_connect 失败（实例 {instance_index} 未启动？）")
        self.display_id = 0
        self._buf: np.ndarray | None = None

    def _bind(self) -> None:
        lib = self._lib
        c_int, c_uint = ctypes.c_int, ctypes.c_uint
        p_int = ctypes.POINTER(ctypes.c_int)
        lib.nemu_connect.argtypes = [ctypes.c_wchar_p, c_int]
        lib.nemu_connect.restype = c_int
        lib.nemu_disconnect.argtypes = [c_int]
        lib.nemu_disconnect.restype = None
        lib.nemu_capture_display.argtypes = [c_int, c_uint, c_int, p_int, p_int, ctypes.c_void_p]
        lib.nemu_capture_display.restype = c_int
        lib.nemu_input_event_touch_down.argtypes = [c_int, c_int, c_int, c_int]
        lib.nemu_input_event_touch_down.restype = c_int
        lib.nemu_input_event_touch_up.argtypes = [c_int, c_int]
        lib.nemu_input_event_touch_up.restype = c_int
        if hasattr(lib, "nemu_get_display_id"):
            lib.nemu_get_display_id.argtypes = [c_int, ctypes.c_char_p, c_int]
            lib.nemu_get_display_id.restype = c_int

    def _check_open(self) -> None:
        if not self._handle:
            raise NemuIpcError("IPC 已断开")

    def get_display_id(self, package: str, app_index: int = 0) -> int:
        """MuMu“后台保活”时应用可能在独立 display 上；普通情况为 0。"""
        if not hasattr(self._lib, "nemu_get_display_id"):
            return 0
        with self._lock:
            self._check_open()
            return int(self._lib.nemu_get_display_id(self._handle, package.encode(), app_index))

    def size(self) -> tuple[int, int]:
        w, h = ctypes.c_int(), ctypes.c_int()
        with self._lock:
            self._check_open()
            ret = self._lib.nemu_capture_display(
                self._handle, self.display_id, 0, ctypes.byref(w), ctypes.byref(h), None
            )
        if ret != 0 or w.value <= 0 or h.value <= 0:
            raise NemuIpcError(f"获取分辨率失败（ret={ret}）")
        return w.value, h.value

    def _capture_into(self, buf: np.ndarray) -> tuple[int, int, int]:
        h, w = buf.shape[:2]
        cw, ch = ctypes.c_int(w), ctypes.c_int(h)
        with self._lock:
            self._check_open()
            ret = self._lib.nemu_capture_display(
                self._handle, self.display_id, buf.nbytes,
                ctypes.byref(cw), ctypes.byref(ch), buf.ctypes.data,
            )
        return ret, cw.value, ch.value

    def capture(self) -> np.ndarray:
        # 复用缓冲区；分辨率变化（或首次）时重新查询尺寸后重试一次
        if self._buf is not None:
            ret, w, h = self._capture_into(self._buf)
            if ret == 0 and self._buf.shape[:2] == (h, w):
                return rgba_flipped_to_bgr(self._buf)
        w, h = self.size()
        self._buf = np.empty((h, w, 4), dtype=np.uint8)
        ret, _, _ = self._capture_into(self._buf)
        if ret != 0:
            raise NemuIpcError(f"截图失败（ret={ret}）")
        return rgba_flipped_to_bgr(self._buf)

    def touch_down(self, x: int, y: int) -> None:
        with self._lock:
            self._check_open()
            self._lib.nemu_input_event_touch_down(self._handle, self.display_id, int(x), int(y))

    def touch_up(self) -> None:
        with self._lock:
            self._check_open()
            self._lib.nemu_input_event_touch_up(self._handle, self.display_id)

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        self.touch_down(x, y)
        time.sleep(duration)
        self.touch_up()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3, steps: int = 0) -> None:
        # 连续 touch_down 即为移动
        steps = steps or max(5, int(duration / 0.016))
        self.touch_down(x1, y1)
        for i in range(1, steps + 1):
            t = i / steps
            time.sleep(duration / steps)
            self.touch_down(round(x1 + (x2 - x1) * t), round(y1 + (y2 - y1) * t))
        time.sleep(0.05)
        self.touch_up()

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._lib.nemu_disconnect(self._handle)
                self._handle = 0
