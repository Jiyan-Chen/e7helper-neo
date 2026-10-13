"""MuMu 设备：IPC 为主通道，adb 为后备。"""

from __future__ import annotations

import logging
from enum import StrEnum

import numpy as np

from .adb import Adb, AdbError
from .base import Device, DeviceError
from .mumu_manager import InstanceInfo, MuMuInstall, MuMuManager, find_install
from .nemu_ipc import NemuIpc, NemuIpcError

log = logging.getLogger(__name__)


class Backend(StrEnum):
    AUTO = "auto"  # IPC 优先，失败回退 adb
    IPC = "ipc"
    ADB = "adb"


class MuMuDevice(Device):
    def __init__(
        self,
        install: MuMuInstall,
        info: InstanceInfo,
        backend: Backend = Backend.AUTO,
    ):
        self.install = install
        self.info = info
        self.backend = Backend(backend)
        self.ipc: NemuIpc | None = None
        self.adb: Adb | None = None

        if not info.android_started:
            raise DeviceError(f"MuMu 实例 {info.index}（{info.name}）未启动")

        if self.backend in (Backend.AUTO, Backend.IPC):
            try:
                if install.ipc_dll is None:
                    raise NemuIpcError("未找到 external_renderer_ipc.dll")
                self.ipc = NemuIpc(install.ipc_dll, install.root, info.index)
            except NemuIpcError as e:
                if self.backend is Backend.IPC:
                    raise
                log.warning("IPC 不可用，回退到 adb：%s", e)

        if self.backend in (Backend.AUTO, Backend.ADB):
            if install.adb_exe and info.adb_serial:
                adb = Adb(install.adb_exe, info.adb_serial)
                try:
                    adb.connect()
                    self.adb = adb
                except AdbError as e:
                    if self.backend is Backend.ADB or self.ipc is None:
                        raise
                    log.warning("adb 连接失败（仅影响后备通道）：%s", e)
            elif self.backend is Backend.ADB:
                raise DeviceError("未找到 adb.exe 或实例没有 adb 端口")

        if self.ipc is None and self.adb is None:
            raise DeviceError("IPC 与 adb 均不可用")

        self._resolution = self._detect_resolution()

    def _detect_resolution(self) -> tuple[int, int]:
        if self.ipc:
            return self.ipc.size()
        h, w = self.adb.screenshot().shape[:2]
        return w, h

    @property
    def name(self) -> str:
        return f"MuMu#{self.info.index} {self.info.name}"

    @property
    def resolution(self) -> tuple[int, int]:
        return self._resolution

    @property
    def active_backend(self) -> str:
        return "ipc" if self.ipc else "adb"

    def screenshot(self) -> np.ndarray:
        if self.ipc:
            try:
                return self.ipc.capture()
            except NemuIpcError as e:
                if not self.adb:
                    raise
                log.warning("IPC 截图失败，本次改用 adb：%s", e)
        return self.adb.screenshot()

    def tap(self, x: int, y: int, duration: float = 0.05) -> None:
        if self.ipc:
            self.ipc.tap(x, y, duration)
        else:
            self.adb.tap(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        if self.ipc:
            self.ipc.swipe(x1, y1, x2, y2, duration)
        else:
            self.adb.swipe(x1, y1, x2, y2, duration)

    def close(self) -> None:
        if self.ipc:
            self.ipc.close()
            self.ipc = None


def connect(
    index: int | None = None,
    backend: Backend | str = Backend.AUTO,
    mumu_root: str | None = None,
) -> MuMuDevice:
    """连接 MuMu 实例；index 为空时选第一个已启动的实例。"""
    install = find_install(mumu_root)
    manager = MuMuManager(install)
    if index is None:
        running = [i for i in manager.instances() if i.android_started]
        if not running:
            raise DeviceError("没有已启动的 MuMu 实例")
        info = running[0]
    else:
        info = manager.instance(index)
    return MuMuDevice(install, info, Backend(backend))
