"""模块契约。所有功能（自动化任务、RTA BP 助手、装备扫描……）都以模块形式接入。

- TaskModule：会操作游戏（点击/滑动），同一设备同一时间只运行一个。
- AssistantModule：只读屏幕帧、不点击，可以与任务并行（例如 BP 助手）。

配置用 pydantic 模型声明，前端通过 config_schema() 拿到 JSON Schema 自动生成表单。
详见 docs/architecture.md。
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import APIRouter

    from e7helper.device import Device


class ModuleKind(StrEnum):
    TASK = "task"
    ASSISTANT = "assistant"


class EmptyConfig(BaseModel):
    pass


@dataclass
class ModuleContext:
    """模块运行时能拿到的平台能力。后续块会追加字段（vision、events、storage、data），只增不改。"""

    device: Device | None
    logger: logging.Logger
    assets_dir: Path  # engine/assets/<module_id>/
    data_dir: Path  # 用户数据目录/<module_id>/，模块自己的持久化文件放这里
    stop_event: threading.Event = field(default_factory=threading.Event)
    extras: dict[str, Any] = field(default_factory=dict)


class Module(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    kind: ClassVar[ModuleKind]
    description: ClassVar[str] = ""
    config_model: ClassVar[type[BaseModel]] = EmptyConfig

    def __init__(self, ctx: ModuleContext, config: BaseModel | None = None):
        self.ctx = ctx
        self.log = ctx.logger
        self.config = config if config is not None else self.config_model()
        self.setup()

    def setup(self) -> None:
        """实例化后的初始化钩子（加载模板、数据等）。"""

    @classmethod
    def config_schema(cls) -> dict:
        return cls.config_model.model_json_schema()

    @classmethod
    def routes(cls) -> APIRouter | None:
        """可选：模块自定义 HTTP 路由，挂载在 /api/modules/<id>/ 下（B08 接入）。"""
        return None

    @property
    def device(self) -> Device:
        if self.ctx.device is None:
            raise RuntimeError(f"模块 {self.id} 需要设备，但未连接")
        return self.ctx.device

    @property
    def stopped(self) -> bool:
        return self.ctx.stop_event.is_set()


class TaskModule(Module):
    kind: ClassVar[ModuleKind] = ModuleKind.TASK

    @abstractmethod
    def run(self) -> None:
        """执行任务。应定期检查 self.stopped 以响应急停。"""


class AssistantModule(Module):
    kind: ClassVar[ModuleKind] = ModuleKind.ASSISTANT

    @abstractmethod
    def on_frame(self, frame: np.ndarray) -> None:
        """收到一帧截图（BGR）。不得操作设备输入。"""
