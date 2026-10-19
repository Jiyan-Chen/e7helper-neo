"""自定义流程（B11）：运行玩家在「我的流程」里编排的流程。

一个通用模块（用户选择）：config 里选流程 id，运行、急停、进计划都和内置模块一样。
流程定义和存储在 `core/flows`，执行器在 runner.py，安全规则在 guard.py。

- 模板：不带前缀的名字只在玩家模板（`<数据目录>/flows/templates/`）里找，`common:` 是内置共用模板；
- 限制：流程自己的「最多运行时间」（到点按超时停止）和「最多点击次数」；
- 统计：`<数据目录>/modules/custom_flow/history.jsonl`（每次一行）、`stats.json`（总数 + 每个流程）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from e7helper.core.flows import FlowNotFound, FlowStore, flow_vision, missing_templates
from e7helper.core.runtime import TaskAborted, TaskStatus
from e7helper.core.vision import Vision
from e7helper.modules.base import TaskModule

from .guard import GUARD_POPUPS
from .runner import FlowBlocked, FlowFailed, FlowRunner, RunReport

log = logging.getLogger(__name__)


class CustomFlowConfig(BaseModel):
    flow: str = Field("", title="流程", description="要运行的流程（在「我的流程」里编辑）")


class CustomFlow(TaskModule):
    id = "custom_flow"
    name = "自定义流程"
    description = "运行你在「我的流程」里编排的步骤：点击、等待、条件分支、循环"
    config_model = CustomFlowConfig
    store_factory: ClassVar = FlowStore  # 测试里换成临时目录

    @classmethod
    def make_vision(cls) -> Vision:
        return flow_vision()

    @classmethod
    def config_schema(cls) -> dict:
        """流程字段带上现有流程的列表（GUI 的计划编辑里显示成下拉框）。"""
        schema = super().config_schema()
        flows = [f for f in cls.store_factory().list() if not isinstance(f, tuple)]
        if flows:
            prop = schema["properties"]["flow"]
            prop["enum"] = [f.id for f in flows]
            prop["x-enum-labels"] = {f.id: f.name for f in flows}
        return schema

    def setup(self) -> None:
        if self.ctx.controller is not None:
            # 排到最前：先于各模块自己注册的同类弹窗判定（那些在模块里可能有别的处理方式）
            for popup in reversed(GUARD_POPUPS):
                self.ctl.scenes.add_popup(popup, replace=True, first=True)
        cfg: CustomFlowConfig = self.config
        if not cfg.flow:
            raise ValueError("没有选择要运行的流程")
        try:
            self.flow = self.store_factory().get(cfg.flow)
        except FlowNotFound:
            raise ValueError(f"流程不存在：{cfg.flow}（可能已经删除）") from None
        if not self.flow.steps:
            raise ValueError(f"流程「{self.flow.name}」还没有步骤")
        missing = missing_templates(self.flow)
        if missing:
            raise ValueError(f"流程「{self.flow.name}」用到的模板不存在：{'、'.join(missing)}")

    def run(self) -> None:
        flow = self.flow
        ctl = self.ctl
        limit = flow.limits.max_minutes * 60
        timer = threading.Timer(limit, ctl.signal.abort, (TaskStatus.TIMEOUT,))
        timer.daemon = True
        timer.start()
        self.log.info("开始流程「%s」（%d 步，最多 %g 分钟、%d 次点击）", flow.name, len(flow.steps),
                      flow.limits.max_minutes, flow.limits.max_taps)
        runner = FlowRunner(ctl, flow, self.log, publish=self.events.publish if self.ctx.events else None)
        started = time.time()
        status, error, blocked = TaskStatus.SUCCEEDED, None, False
        try:
            runner.run()
        except FlowFailed as e:
            status, error, blocked = TaskStatus.FAILED, str(e), isinstance(e, FlowBlocked)
            raise
        except TaskAborted as e:
            status, error = e.status, str(e)
            if status is TaskStatus.TIMEOUT:
                self.log.warning("到了流程的最多运行时间（%g 分钟），停止", flow.limits.max_minutes)
            raise
        except Exception as e:
            status, error = TaskStatus.FAILED, str(e)
            raise
        finally:
            timer.cancel()
            self._record(runner.report, started, status, error, blocked)

    def _record(self, report: RunReport, started: float, status: TaskStatus, error: str | None,
                blocked: bool) -> None:
        d = self.ctx.data_dir
        entry = {
            "time": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
            "flow": self.flow.id,
            "name": self.flow.name,
            "status": status.value,
            "steps": report.steps,
            "taps": report.taps,
            "popups": report.popups,
            "seconds": round(time.time() - started, 1),
            "error": error,
            "message": report.message,
        }
        try:
            with (d / "history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            path = d / "stats.json"
            stats = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            stats["runs"] = stats.get("runs", 0) + 1
            stats["succeeded"] = stats.get("succeeded", 0) + (status is TaskStatus.SUCCEEDED)
            stats["taps"] = stats.get("taps", 0) + report.taps
            stats["blocked"] = stats.get("blocked", 0) + blocked
            per = stats.setdefault("flows", {}).setdefault(self.flow.id, {})
            per.update(name=self.flow.name, last=entry["time"], last_status=status.value)
            per["runs"] = per.get("runs", 0) + 1
            per["succeeded"] = per.get("succeeded", 0) + (status is TaskStatus.SUCCEEDED)
            path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            log.exception("写流程统计失败")


__all__ = ["CustomFlow", "CustomFlowConfig", "FlowBlocked", "FlowFailed", "FlowRunner"]
