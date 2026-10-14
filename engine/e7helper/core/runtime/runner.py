"""Runtime：一台设备上的模块调度。

- TaskModule：同一时间只跑一个（第二个 start_task 抛 RuntimeBusy），在独立线程里运行；
  支持急停（handle.stop()）、超时（timeout 秒后自动急停，状态记为 timeout）和卡死检测。
  失败 / 超时 / 卡死时把调试信息（最后一帧、当前画面、异常、最近日志）存到 <数据目录>/debug/。
- AssistantModule：可以挂多个，和任务并行；它们订阅 Topic.FRAME，在各自线程里收帧（只保留最新一帧）。
  任务在截图时会发布帧；任务没在截图时由帧泵按 frame_interval 补帧。
- 一台设备只能有一个 Runtime（进程内）。

用法：
    with Runtime(device) as rt:
        result = rt.run_task(SomeTask, SomeTask.config_model(...), timeout=600)
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from e7helper.core.events import EventBus, LogBridge, Topic
from e7helper.core.imageio import write_image
from e7helper.core.paths import debug_dir, module_assets_dir, module_data_dir
from e7helper.core.scene import SceneDetector, default_detector
from e7helper.core.vision import Vision
from e7helper.device import Device
from e7helper.modules.base import AssistantModule, ModuleContext, TaskModule

from .controller import AbortSignal, Controller
from .device import ReadOnlyDevice, SharedDevice
from .errors import RuntimeBusy, TaskAborted, TaskStatus
from .humanize import Humanize
from .stuck import StuckConfig, StuckDetector

log = logging.getLogger(__name__)

_claimed: set[str] = set()
_claimed_lock = threading.Lock()

DEBUG_STATUSES = (TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.STUCK)


@dataclass
class TaskResult:
    module_id: str
    status: TaskStatus
    started: float
    ended: float
    error: str | None = None
    debug_dir: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status is TaskStatus.SUCCEEDED

    @property
    def duration(self) -> float:
        return self.ended - self.started


class TaskHandle:
    def __init__(self, module: TaskModule, controller: Controller, signal: AbortSignal):
        self.module = module
        self.module_id = module.id
        self.controller = controller
        self.signal = signal
        self.started = time.time()
        self.result: TaskResult | None = None
        self._done = threading.Event()
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return not self._done.is_set()

    def stop(self) -> None:
        """急停：任务在下一次截图/点击/sleep 时退出。"""
        self.signal.abort(TaskStatus.STOPPED)

    def wait(self, timeout: float | None = None) -> TaskResult | None:
        """等任务结束；timeout 内没结束返回 None。"""
        self._done.wait(timeout)
        return self.result


class AssistantHandle:
    def __init__(self, runtime: Runtime, module: AssistantModule):
        self.runtime = runtime
        self.module = module
        self.module_id = module.id
        self.subscription = None

    def detach(self) -> None:
        self.runtime.detach_assistant(self.module_id)


class Runtime:
    def __init__(
        self,
        device: Device,
        *,
        bus: EventBus | None = None,
        scenes: SceneDetector | None = None,
        humanize: Humanize | None = None,
        stuck: StuckConfig | None = None,
        frame_interval: float = 0.5,
        debug_root: Path | None = None,
        seed: int | None = None,
    ):
        name = device.name
        with _claimed_lock:
            if name in _claimed:
                raise RuntimeBusy(f"设备 {name} 已被另一个 Runtime 占用")
            _claimed.add(name)
        self._device_name = name
        self.device = SharedDevice(device)
        self._own_bus = bus is None
        self.bus = bus or EventBus()
        self.scenes = scenes or default_detector()
        self.humanize = humanize or Humanize()
        self.stuck_config = stuck or StuckConfig()
        self.frame_interval = frame_interval
        self.debug_root = debug_root
        self._seed = seed

        self._lock = threading.Lock()
        self._task: TaskHandle | None = None
        self._assistants: dict[str, AssistantHandle] = {}
        self._closed = threading.Event()
        self._pump: threading.Thread | None = None
        self._last_frame_at = 0.0

        # 最近的日志，失败时写进调试目录
        self.recent_logs: deque[dict] = deque(maxlen=300)
        self._subs = [
            self.bus.subscribe(Topic.LOG, lambda e: self.recent_logs.append(e.data), name="runtime:recent_logs"),
            self.bus.subscribe(Topic.FRAME, self._on_frame, name="runtime:frame_clock"),
        ]
        self._log_bridge = LogBridge(self.bus, logging.DEBUG)
        logging.getLogger().addHandler(self._log_bridge)

    # ------------------------------------------------------------ 生命周期

    def close(self, timeout: float = 5.0) -> None:
        if self._closed.is_set():
            return
        task = self._task
        if task is not None and task.running:
            task.stop()
            task.wait(timeout)
        for mid in list(self._assistants):
            self.detach_assistant(mid)
        self._closed.set()
        if self._pump is not None:
            self._pump.join(timeout)
        logging.getLogger().removeHandler(self._log_bridge)
        for s in self._subs:
            s.unsubscribe()
        if self._own_bus:
            self.bus.close()
        with _claimed_lock:
            _claimed.discard(self._device_name)

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ 任务

    @property
    def current_task(self) -> TaskHandle | None:
        t = self._task
        return t if t is not None and t.running else None

    def _context(self, module_id: str, device: Device, signal: AbortSignal | None,
                 controller: Controller | None, vision: Vision) -> ModuleContext:
        return ModuleContext(
            device=device,
            logger=logging.getLogger(f"module.{module_id}"),
            assets_dir=module_assets_dir(module_id),
            data_dir=module_data_dir(module_id),
            stop_event=signal.event if signal else threading.Event(),
            vision=vision,
            events=self.bus,
            controller=controller,
        )

    def make_controller(self, vision: Vision | None = None, signal: AbortSignal | None = None,
                        logger: logging.Logger | None = None) -> Controller:
        """不经过任务调度、直接拿一个 Controller（CLI 调试用）。注意不受任务互斥保护。"""
        return Controller(
            self.device,
            vision or self.scenes.vision,
            self.scenes,
            bus=self.bus,
            signal=signal or AbortSignal(),
            humanize=self.humanize,
            stuck=StuckDetector(self.stuck_config),
            rng=random.Random(self._seed),
            logger=logger,
        )

    def start_task(self, cls: type[TaskModule], config: BaseModel | None = None,
                   *, timeout: float | None = None) -> TaskHandle:
        if not (isinstance(cls, type) and issubclass(cls, TaskModule)):
            raise TypeError(f"{cls!r} 不是 TaskModule")
        with self._lock:
            if self._closed.is_set():
                raise RuntimeError("Runtime 已关闭")
            if self._task is not None and self._task.running:
                raise RuntimeBusy(f"设备上已有任务在运行：{self._task.module_id}")
            signal = AbortSignal()
            vision = Vision.for_module(cls.id)
            logger = logging.getLogger(f"module.{cls.id}")
            controller = self.make_controller(vision, signal, logger)
            ctx = self._context(cls.id, self.device, signal, controller, vision)
            module = cls(ctx, config)  # 配置错误、setup 失败在这里同步抛出
            handle = TaskHandle(module, controller, signal)
            self._task = handle
        timer = None
        if timeout is not None:
            timer = threading.Timer(timeout, signal.abort, (TaskStatus.TIMEOUT,))
            timer.daemon = True
            timer.start()
        handle.thread = threading.Thread(target=self._run_task, args=(handle, timer, timeout),
                                         name=f"task:{cls.id}", daemon=True)
        handle.thread.start()
        return handle

    def run_task(self, cls: type[TaskModule], config: BaseModel | None = None,
                 *, timeout: float | None = None) -> TaskResult:
        """阻塞运行一个任务。Ctrl+C 会急停任务并等它退出。"""
        handle = self.start_task(cls, config, timeout=timeout)
        try:
            while handle.wait(0.2) is None:
                pass
        except KeyboardInterrupt:
            handle.stop()
            handle.wait()
        return handle.result

    def stop_task(self) -> None:
        task = self._task
        if task is not None and task.running:
            task.stop()

    def _run_task(self, handle: TaskHandle, timer: threading.Timer | None, timeout: float | None) -> None:
        try:
            self._run_task_inner(handle, timer, timeout)
        finally:
            if handle.result is None:  # 收尾代码本身出错
                handle.result = TaskResult(handle.module_id, TaskStatus.FAILED, handle.started, time.time(),
                                           "运行时内部错误")
            handle._done.set()

    def _run_task_inner(self, handle: TaskHandle, timer: threading.Timer | None, timeout: float | None) -> None:
        mid = handle.module_id
        mlog = handle.module.log
        self.bus.publish(Topic.TASK, {"module": mid, "status": TaskStatus.RUNNING.value})
        mlog.info("任务开始")
        error = None
        try:
            handle.module.run()
            # 模块自己轮询 self.stopped 后正常返回的，也按急停原因记
            status = (handle.signal.reason or TaskStatus.STOPPED) if handle.signal.aborted else TaskStatus.SUCCEEDED
        except TaskAborted as e:
            status = e.status
            error = str(e)
        except Exception as e:
            status = TaskStatus.FAILED
            error = "".join(traceback.format_exception(e))
        finally:
            if timer is not None:
                timer.cancel()
        if status is TaskStatus.TIMEOUT and not error:
            error = f"超过时限 {timeout} 秒"

        debug = None
        if status in DEBUG_STATUSES:
            try:
                debug = self._dump_debug(handle, status, error)
            except Exception:
                log.exception("保存调试信息失败")
        handle.result = TaskResult(mid, status, handle.started, time.time(), error, debug)

        msg = f"任务结束：{status.value}（{handle.result.duration:.1f} 秒）"
        if status in (TaskStatus.SUCCEEDED, TaskStatus.STOPPED):
            mlog.info(msg)
        else:
            mlog.error("%s：%s", msg, error.strip().splitlines()[-1] if error else "")
            if debug:
                mlog.error("调试信息已保存到 %s", debug)
        self.bus.publish(Topic.TASK, {
            "module": mid, "status": status.value, "error": error,
            "debug_dir": str(debug) if debug else None, "duration": handle.result.duration,
        })

    def _dump_debug(self, handle: TaskHandle, status: TaskStatus, error: str | None) -> Path:
        root = self.debug_root or debug_dir()
        out = root / f"{datetime.now():%Y%m%d-%H%M%S}_{handle.module_id}_{status.value}"
        out.mkdir(parents=True, exist_ok=True)
        ctl = handle.controller
        if ctl.last_frame is not None:
            write_image(out / "last_frame.png", ctl.last_frame)
        try:
            write_image(out / "screen.png", self.device.screenshot())
        except Exception as e:
            log.warning("调试截图失败：%s", e)
        state = ctl.last_state
        info = {
            "module": handle.module_id,
            "status": status.value,
            "started": datetime.fromtimestamp(handle.started).isoformat(timespec="seconds"),
            "config": handle.module.config.model_dump(mode="json"),
            "scene": state.scene if state else None,
            "popup": state.popup if state else None,
            "device": self.device.name,
            "resolution": list(self.device.resolution),
        }
        (out / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "error.txt").write_text(error or "", encoding="utf-8")
        lines = [
            f"{datetime.fromtimestamp(r['time']):%H:%M:%S.%f}"[:-3] + f" {r['level']:<7} {r['name']}: {r['message']}"
            for r in list(self.recent_logs)
        ]
        (out / "log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    # ------------------------------------------------------------ 助手

    @property
    def assistants(self) -> dict[str, AssistantHandle]:
        return dict(self._assistants)

    def attach_assistant(self, cls: type[AssistantModule], config: BaseModel | None = None) -> AssistantHandle:
        if not (isinstance(cls, type) and issubclass(cls, AssistantModule)):
            raise TypeError(f"{cls!r} 不是 AssistantModule")
        with self._lock:
            if self._closed.is_set():
                raise RuntimeError("Runtime 已关闭")
            if cls.id in self._assistants:
                raise RuntimeBusy(f"助手 {cls.id} 已经在运行")
            vision = Vision.for_module(cls.id)
            ctx = self._context(cls.id, ReadOnlyDevice(self.device.inner, self.device.lock), None, None, vision)
            module = cls(ctx, config)
            handle = AssistantHandle(self, module)
            handle.subscription = self.bus.subscribe(
                Topic.FRAME, lambda e: module.on_frame(e.data), threaded=True, maxsize=1, name=f"assistant:{cls.id}"
            )
            self._assistants[cls.id] = handle
            self._ensure_pump()
        self.bus.publish(Topic.ASSISTANT, {"module": cls.id, "state": "attached"})
        module.log.info("助手已挂载")
        return handle

    def detach_assistant(self, module_id: str) -> None:
        with self._lock:
            handle = self._assistants.pop(module_id, None)
        if handle is None:
            return
        handle.subscription.unsubscribe()
        handle.module.ctx.stop_event.set()
        self.bus.publish(Topic.ASSISTANT, {"module": module_id, "state": "detached"})

    def _on_frame(self, _event) -> None:
        self._last_frame_at = time.monotonic()

    def _ensure_pump(self) -> None:
        if self._pump is None or not self._pump.is_alive():
            self._pump = threading.Thread(target=self._pump_loop, name="runtime:frame_pump", daemon=True)
            self._pump.start()

    def _pump_loop(self) -> None:
        """有助手时，若最近 frame_interval 内没有帧（任务没在截图），就自己截一帧发出去。"""
        while not self._closed.wait(self.frame_interval / 2):
            if not self._assistants:
                continue
            if time.monotonic() - self._last_frame_at < self.frame_interval:
                continue
            try:
                frame = self.device.screenshot()
            except Exception as e:
                log.warning("帧泵截图失败：%s", e)
                self._closed.wait(1.0)
                continue
            self.bus.publish(Topic.FRAME, frame)
