from __future__ import annotations

import os
import sys
from pathlib import Path

# 冻结版（PyInstaller onedir，B10）：资源在 sys._MEIPASS（即 e7engine/_internal/）下；源码运行时是 engine/
FROZEN = bool(getattr(sys, "frozen", False))
ENGINE_ROOT = Path(getattr(sys, "_MEIPASS")) if FROZEN else Path(__file__).resolve().parents[2]
ASSETS_DIR = ENGINE_ROOT / "assets"


def data_dir() -> Path:
    """用户数据目录：E7_DATA_DIR 或 %LOCALAPPDATA%\\e7helper。"""
    if os.environ.get("E7_DATA_DIR"):
        base = Path(os.environ["E7_DATA_DIR"])
    else:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "e7helper"
    base.mkdir(parents=True, exist_ok=True)
    return base


def module_assets_dir(module_id: str) -> Path:
    return ASSETS_DIR / module_id


def module_data_dir(module_id: str) -> Path:
    path = data_dir() / "modules" / module_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_data_dir(name: str) -> Path:
    """随包的游戏数据（B13，`core.data`）：assets/data/<name>/，只读。"""
    return ASSETS_DIR / "data" / name


def user_data_dir(name: str) -> Path:
    """联网更新后的游戏数据（B13）：<数据目录>/data/<name>/，比随包的新时优先用。"""
    path = data_dir() / "data" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def debug_dir() -> Path:
    """任务失败时的调试信息目录：<数据目录>/debug/。"""
    path = data_dir() / "debug"
    path.mkdir(parents=True, exist_ok=True)
    return path


def flows_dir() -> Path:
    """玩家自定义流程（B11）：<数据目录>/flows/<id>.json。"""
    path = data_dir() / "flows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_templates_dir() -> Path:
    """玩家采集的模板（B11）：<数据目录>/flows/templates/，只给自定义流程用。

    打包版的安装目录可能没有写权限（Program Files），所以玩家模板一律放数据目录，不写 assets。
    """
    path = flows_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path
