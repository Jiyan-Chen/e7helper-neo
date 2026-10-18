"""API 测试用的假模块和工具：不点游戏，只截图（GameSim 提供画面）。"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from game_sim import GameSim
from pydantic import BaseModel, Field

from e7helper.api import Engine
from e7helper.core.runtime import Humanize
from e7helper.modules import AssistantModule, ModuleTimer, TaskModule


class SlowConfig(BaseModel):
    seconds: float = Field(30.0, gt=0, description="跑多久")


class SlowTask(TaskModule):
    """一直截图直到急停或到时间。"""

    id = "slow"
    name = "慢任务"
    config_model = SlowConfig

    def run(self) -> None:
        end = time.monotonic() + self.config.seconds
        while time.monotonic() < end:
            self.ctl.screenshot()
            self.ctl.sleep(0.05)


class QuickConfig(BaseModel):
    fail: bool = False
    dry_run: bool = True


class QuickTask(TaskModule):
    id = "quick"
    name = "快任务"
    config_model = QuickConfig
    due: datetime | None = None  # next_due 的返回值，测试里改
    due_calls: list = []

    def run(self) -> None:
        self.log.info("快任务：fail=%s dry_run=%s", self.config.fail, self.config.dry_run)
        if self.config.fail:
            raise RuntimeError("故意失败")

    @classmethod
    def next_due(cls, config, data_dir: Path, last_success):
        cls.due_calls.append(last_success)
        return cls.due

    @classmethod
    def timers(cls, data_dir: Path) -> list[ModuleTimer]:
        return [ModuleTimer("next", "下次", cls.due, "测试")]

    @classmethod
    def routes(cls):
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/ping")
        def ping() -> dict:
            return {"module": cls.id, "pong": True}

        return router


class EchoAssistant(AssistantModule):
    id = "echo"
    name = "回声助手"

    def setup(self) -> None:
        self.frames = 0
        self.got = threading.Event()

    def on_frame(self, frame: np.ndarray) -> None:
        self.frames += 1
        self.got.set()


FAKE_MODULES = {m.id: m for m in (SlowTask, QuickTask, EchoAssistant)}


def make_engine(tmp_path: Path, detector, *, fail_connect: bool = False, modules=None) -> Engine:
    sims: list[GameSim] = []

    def factory(index):
        if fail_connect:
            raise RuntimeError("MuMu 没开")
        sim = GameSim("lobby")
        sims.append(sim)
        return sim

    engine = Engine(
        modules=modules or dict(FAKE_MODULES),
        device_factory=factory,
        runtime_kwargs={"humanize": Humanize.off(), "scenes": detector, "debug_root": tmp_path / "debug",
                        "seed": 1, "frame_interval": 0.1},
    )
    engine.sims = sims
    return engine


def wait_for(cond, timeout: float = 5.0, interval: float = 0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError("等待超时")
