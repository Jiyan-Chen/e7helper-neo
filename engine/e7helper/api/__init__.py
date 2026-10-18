"""API 层（B08）：FastAPI 核心路由 + 模块子路由 + WebSocket + 定时调度。

入口是 `e7helper serve`（cli.py）；结构见 docs/architecture.md「API 层」一节。
"""

from .app import create_app
from .auth import AuthConfig, generate_token
from .engine import ApiError, Engine
from .scheduler import Scheduler, ScheduleSpec

__all__ = ["ApiError", "AuthConfig", "Engine", "ScheduleSpec", "Scheduler", "create_app", "generate_token"]
