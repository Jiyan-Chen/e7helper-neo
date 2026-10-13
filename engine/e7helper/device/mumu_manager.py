"""MuMu 安装发现 + MuMuManager.exe 命令行封装。

支持的目录结构（按顺序探测）：
- 新版 MuMu（6.x，例如 E:\\MuMuPlayer-12.0\\nx_main）：nx_main\\MuMuManager.exe、nx_main\\sdk\\external_renderer_ipc.dll
- 旧版 MuMu 12：shell\\MuMuManager.exe、shell\\sdk\\external_renderer_ipc.dll
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .base import DeviceError

log = logging.getLogger(__name__)

ENV_ROOT = "E7_MUMU_ROOT"

# (MuMuManager.exe, external_renderer_ipc.dll, adb.exe) 相对安装根目录
_LAYOUTS: list[tuple[str, str, str]] = [
    ("nx_main/MuMuManager.exe", "nx_main/sdk/external_renderer_ipc.dll", "nx_main/adb.exe"),
    ("shell/MuMuManager.exe", "shell/sdk/external_renderer_ipc.dll", "shell/adb.exe"),
]

_COMMON_ROOTS = [
    r"C:\Program Files\Netease\MuMuPlayer-12.0",
    r"C:\Program Files\Netease\MuMu Player 12",
    r"D:\Program Files\Netease\MuMuPlayer-12.0",
    r"D:\MuMuPlayer-12.0",
    r"E:\MuMuPlayer-12.0",
]


@dataclass(frozen=True)
class MuMuInstall:
    root: Path
    manager_exe: Path
    ipc_dll: Path | None
    adb_exe: Path | None

    @classmethod
    def from_root(cls, root: str | os.PathLike) -> MuMuInstall | None:
        root = Path(root)
        for manager, dll, adb in _LAYOUTS:
            manager_path = root / manager
            if manager_path.is_file():
                dll_path = root / dll
                adb_path = root / adb
                return cls(
                    root=root,
                    manager_exe=manager_path,
                    ipc_dll=dll_path if dll_path.is_file() else None,
                    adb_exe=adb_path if adb_path.is_file() else None,
                )
        return None


def _registry_roots() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg

    roots: list[str] = []
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in keys:
        try:
            parent = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with parent:
            for i in range(winreg.QueryInfoKey(parent)[0]):
                try:
                    with winreg.OpenKey(parent, winreg.EnumKey(parent, i)) as sub:
                        display = winreg.QueryValueEx(sub, "DisplayName")[0]
                        if "mumu" not in str(display).lower():
                            continue
                        location = winreg.QueryValueEx(sub, "InstallLocation")[0]
                        if location:
                            roots.append(str(location))
                except OSError:
                    continue
    return roots


def find_install(explicit_root: str | os.PathLike | None = None) -> MuMuInstall:
    """按 显式参数 → 环境变量 E7_MUMU_ROOT → 注册表 → 常见路径 的顺序查找。"""
    candidates: list[str] = []
    if explicit_root:
        candidates.append(str(explicit_root))
    if os.environ.get(ENV_ROOT):
        candidates.append(os.environ[ENV_ROOT])
    candidates += _registry_roots()
    candidates += _COMMON_ROOTS

    seen: set[str] = set()
    for c in candidates:
        key = os.path.normcase(os.path.abspath(c))
        if key in seen:
            continue
        seen.add(key)
        install = MuMuInstall.from_root(c)
        if install:
            log.debug("MuMu install found at %s", install.root)
            return install
    raise DeviceError(
        f"未找到 MuMu 安装目录（已尝试 {len(seen)} 个位置）。可设置环境变量 {ENV_ROOT} 指向安装根目录。"
    )


@dataclass(frozen=True)
class InstanceInfo:
    index: int
    name: str
    android_version: str
    process_started: bool
    android_started: bool
    adb_host: str | None
    adb_port: int | None
    player_state: str | None

    @property
    def adb_serial(self) -> str | None:
        if self.adb_host and self.adb_port:
            return f"{self.adb_host}:{self.adb_port}"
        return None

    @classmethod
    def from_json(cls, d: dict) -> InstanceInfo:
        port = d.get("adb_port")
        return cls(
            index=int(d["index"]),
            name=str(d.get("name", "")),
            android_version=str(d.get("android_version", "")),
            process_started=bool(d.get("is_process_started", False)),
            android_started=bool(d.get("is_android_started", False)),
            adb_host=d.get("adb_host_ip"),
            adb_port=int(port) if port not in (None, "") else None,
            player_state=d.get("player_state"),
        )


def parse_info_output(data: dict) -> list[InstanceInfo]:
    """`info -v <x>` 在单实例时返回扁平对象，多实例 / all 时返回以 index 为键的字典。"""
    if "index" in data:
        return [InstanceInfo.from_json(data)]
    items = [v for v in data.values() if isinstance(v, dict) and "index" in v]
    return sorted((InstanceInfo.from_json(v) for v in items), key=lambda i: i.index)


class MuMuManager:
    def __init__(self, install: MuMuInstall, timeout: float = 30.0):
        self.install = install
        self.timeout = timeout

    def _run(self, *args: str) -> dict:
        cmd = [str(self.install.manager_exe), *args]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=self.timeout, creationflags=flags
            )
        except subprocess.TimeoutExpired as e:
            raise DeviceError(f"MuMuManager 超时：{' '.join(args)}") from e
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        try:
            return json.loads(out) if out else {}
        except json.JSONDecodeError as e:
            raise DeviceError(f"MuMuManager 输出无法解析（{' '.join(args)}）：{out[:200]}") from e

    def version(self) -> str:
        return str(self._run("version").get("version", ""))

    def instances(self) -> list[InstanceInfo]:
        return parse_info_output(self._run("info", "-v", "all"))

    def instance(self, index: int) -> InstanceInfo:
        infos = parse_info_output(self._run("info", "-v", str(index)))
        if not infos:
            raise DeviceError(f"MuMu 实例 {index} 不存在")
        return infos[0]

    def _control(self, index: int, *args: str) -> None:
        result = self._run("control", "-v", str(index), *args)
        if result.get("errcode", 0) != 0:
            raise DeviceError(f"MuMuManager control 失败：{result}")

    def launch(self, index: int) -> None:
        self._control(index, "launch")

    def shutdown(self, index: int) -> None:
        self._control(index, "shutdown")

    def launch_app(self, index: int, package: str) -> None:
        self._control(index, "app", "launch", "-pkg", package)
