from pathlib import Path

import pytest

from e7helper.device.base import DeviceError
from e7helper.device.mumu_manager import MuMuInstall, find_install, parse_info_output

# 来自 MuMu 6.6.4 实测输出
RUNNING_SINGLE = {
    "adb_host_ip": "127.0.0.1",
    "adb_port": 16384,
    "android_version": "15.0",
    "index": "0",
    "is_android_started": True,
    "is_process_started": True,
    "name": "MuMu安卓设备",
    "player_state": "start_finished",
}
STOPPED_ALL = {
    "0": {
        "android_version": "15.0",
        "index": "0",
        "is_android_started": False,
        "is_process_started": False,
        "name": "MuMu安卓设备",
    }
}


def test_parse_single_running():
    [info] = parse_info_output(RUNNING_SINGLE)
    assert info.index == 0
    assert info.android_started
    assert info.adb_serial == "127.0.0.1:16384"
    assert info.player_state == "start_finished"


def test_parse_all_stopped_has_no_adb():
    [info] = parse_info_output(STOPPED_ALL)
    assert not info.android_started
    assert info.adb_serial is None


def test_parse_multiple_sorted():
    data = {
        "2": {**RUNNING_SINGLE, "index": "2", "adb_port": 16448},
        "0": RUNNING_SINGLE,
    }
    infos = parse_info_output(data)
    assert [i.index for i in infos] == [0, 2]
    assert infos[1].adb_port == 16448


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_layout_nx_main(tmp_path):
    _touch(tmp_path / "nx_main/MuMuManager.exe")
    _touch(tmp_path / "nx_main/sdk/external_renderer_ipc.dll")
    _touch(tmp_path / "nx_main/adb.exe")
    install = MuMuInstall.from_root(tmp_path)
    assert install is not None
    assert install.manager_exe.parent.name == "nx_main"
    assert install.ipc_dll is not None and install.adb_exe is not None


def test_layout_legacy_shell_without_dll(tmp_path):
    _touch(tmp_path / "shell/MuMuManager.exe")
    install = MuMuInstall.from_root(tmp_path)
    assert install is not None
    assert install.ipc_dll is None


def test_layout_missing(tmp_path):
    assert MuMuInstall.from_root(tmp_path) is None


def test_find_install_explicit(tmp_path):
    _touch(tmp_path / "nx_main/MuMuManager.exe")
    assert find_install(tmp_path).root == tmp_path


def test_find_install_env(tmp_path, monkeypatch):
    _touch(tmp_path / "shell/MuMuManager.exe")
    monkeypatch.setenv("E7_MUMU_ROOT", str(tmp_path))
    assert find_install().root == tmp_path


def test_find_install_not_found(monkeypatch, tmp_path):
    import e7helper.device.mumu_manager as mm

    monkeypatch.delenv("E7_MUMU_ROOT", raising=False)
    monkeypatch.setattr(mm, "_registry_roots", lambda: [])
    monkeypatch.setattr(mm, "_COMMON_ROOTS", [str(tmp_path / "nope")])
    with pytest.raises(DeviceError):
        find_install()
