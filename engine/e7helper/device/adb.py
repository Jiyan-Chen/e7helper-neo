"""adb 后备通道：直接调用 MuMu 自带的 adb.exe，避免与其他 adb 版本冲突。"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .base import DeviceError

log = logging.getLogger(__name__)


class AdbError(DeviceError):
    pass


class Adb:
    def __init__(self, adb_exe: str | Path, serial: str, timeout: float = 15.0):
        self.adb_exe = str(adb_exe)
        self.serial = serial
        self.timeout = timeout

    def _exec(self, *args: str, use_serial: bool = True) -> bytes:
        cmd = [self.adb_exe, *(["-s", self.serial] if use_serial else []), *args]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=self.timeout, creationflags=flags)
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb 超时：{' '.join(args)}") from e
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise AdbError(f"adb 失败（{' '.join(args)}）：{err}")
        return proc.stdout

    def connect(self) -> None:
        out = self._exec("connect", self.serial, use_serial=False).decode(errors="replace")
        if "connected" not in out:
            raise AdbError(f"adb connect {self.serial} 失败：{out.strip()}")

    def shell(self, *args: str) -> str:
        return self._exec("shell", *args).decode("utf-8", errors="replace")

    def screenshot(self) -> np.ndarray:
        data = self._exec("exec-out", "screencap", "-p")
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError("screencap 返回的数据无法解码")
        return img

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        self.shell("input", "swipe", *map(str, (int(x1), int(y1), int(x2), int(y2))), str(int(duration * 1000)))

    def has_package(self, package: str) -> bool:
        return f"package:{package}" in self.shell("pm", "list", "packages", package).split()
