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
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import APIRouter

    from e7helper.core.events import EventBus
    from e7helper.core.runtime import Controller
    from e7helper.core.vision import Vision
    from e7helper.device import Device


class ModuleKind(StrEnum):
    TASK = "task"
    ASSISTANT = "assistant"


class EmptyConfig(BaseModel):
    pass


@dataclass
class ModuleContext:
    """模块运行时能拿到的平台能力。后续块会追加字段（storage、data），只增不改。"""

    device: Device | None
    logger: logging.Logger
    assets_dir: Path  # engine/assets/<module_id>/
    data_dir: Path  # 用户数据目录/<module_id>/，模块自己的持久化文件放这里
    stop_event: threading.Event = field(default_factory=threading.Event)
    extras: dict[str, Any] = field(default_factory=dict)
    # B02：模板匹配 + OCR，模板查找顺序为 assets/<module_id>/cn → assets/common/cn
    vision: Vision | None = None
    # B03：事件总线（发布/订阅帧、日志、任务状态）
    events: EventBus | None = None
    # B03：任务的操作入口（基准坐标点击、场景/弹窗、急停检查）；只有 TaskModule 经 Runtime 启动时才有
    controller: Controller | None = None


@dataclass(frozen=True)
class ModuleTimer:
    """模块对外公布的计时（B08），GUI 用来显示倒计时，例如「每日重置」「精灵之森」。

    at 为带时区的时间；None 表示没有确定的时间（note 里说明原因，例如「今天已完成」「下次运行时查看」）。
    """

    key: str
    label: str
    at: datetime | None = None
    note: str = ""


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
        """可选：模块自定义 HTTP 路由，挂载在 /api/modules/<id>/ 下（B08）。

        路径的第一段不能是 config / stats / timers（核心路由占用）。路由里需要模块数据时用
        `core.paths.module_data_dir(cls.id)`；fastapi 在 routes() 里再导入，免得拖慢 CLI 启动。
        """
        return None

    @classmethod
    def make_vision(cls) -> Vision:
        """模块的识别器（B11）：默认按 本模块 → common 查找模板。自定义流程改成只查玩家模板。"""
        from e7helper.core.vision import Vision

        return Vision.for_module(cls.id)

    @classmethod
    def timers(cls, data_dir: Path) -> list[ModuleTimer]:
        """可选（B08）：模块的计时，例如下一次每日重置、精灵之森下次可领。只读文件，不碰设备。"""
        return []

    @property
    def device(self) -> Device:
        if self.ctx.device is None:
            raise RuntimeError(f"模块 {self.id} 需要设备，但未连接")
        return self.ctx.device

    @property
    def vision(self) -> Vision:
        if self.ctx.vision is None:
            raise RuntimeError(f"模块 {self.id} 需要视觉层，但 ctx.vision 未设置")
        return self.ctx.vision

    @property
    def ctl(self) -> Controller:
        if self.ctx.controller is None:
            raise RuntimeError(f"模块 {self.id} 需要 Controller，但没有经 Runtime 启动")
        return self.ctx.controller

    @property
    def events(self) -> EventBus:
        if self.ctx.events is None:
            raise RuntimeError(f"模块 {self.id} 需要事件总线，但 ctx.events 未设置")
        return self.ctx.events

    @property
    def stopped(self) -> bool:
        return self.ctx.stop_event.is_set()


class TaskModule(Module):
    kind: ClassVar[ModuleKind] = ModuleKind.TASK

    @abstractmethod
    def run(self) -> None:
        """执行任务。应定期检查 self.stopped 以响应急停。"""

    @classmethod
    def next_due(cls, config: BaseModel, data_dir: Path, last_success: datetime | None) -> datetime | None:
        """可选（B08）：「按模块时间」的计划用它决定下一次运行时间（带时区）。

        last_success 是这条计划上一次成功结束的时间（没有为 None）。返回 None 表示暂时不需要运行。
        只读文件，不碰设备；调度器会定期调用，并另外保证两次运行之间的最短间隔。
        """
        return None

    @classmethod
    def supports_next_due(cls) -> bool:
        return cls.next_due.__func__ is not TaskModule.next_due.__func__


class AssistantModule(Module):
    kind: ClassVar[ModuleKind] = ModuleKind.ASSISTANT

    @abstractmethod
    def on_frame(self, frame: np.ndarray) -> None:
        """收到一帧截图（BGR）。不得操作设备输入。"""
