from __future__ import annotations

import os
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]
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


def debug_dir() -> Path:
    """任务失败时的调试信息目录：<数据目录>/debug/。"""
    path = data_dir() / "debug"
    path.mkdir(parents=True, exist_ok=True)
    return path
