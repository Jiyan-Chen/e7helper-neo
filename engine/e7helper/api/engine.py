"""API 服务的后台状态：设备连接、Runtime、任务记录、保存的模块配置、日志缓存。

与 HTTP 无关（路由、WebSocket、调度器都只调用这里），方便单独测试。所有方法线程安全；
连接设备、截图这类阻塞操作由调用方放到线程里执行（FastAPI 的同步路由本来就在线程池里跑）。

文件：
- `<数据目录>/tasks.jsonl`：每个经 API 启动的任务结束后追加一行（来源、状态、时长、错误……）
- `<数据目录>/modules/<id>/config.json`：GUI 保存的模块配置；启动任务不带配置时用它
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ValidationError

from e7helper.core.events import EventBus, LogBridge, Topic
from e7helper.core.paths import data_dir, module_data_dir
from e7helper.core.runtime import Runtime, RuntimeBusy, TaskHandle, TaskResult, TaskStatus
from e7helper.device import Backend, Device, MuMuManager, connect, find_install
from e7helper.modules import AssistantModule, Module, TaskModule, discover

log = logging.getLogger(__name__)

LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

DeviceFactory = Callable[[int | None], Device]


class ApiError(Exception):
    """带 HTTP 状态码和错误码的异常；路由和 WebSocket 都按它回复错误。"""

    def __init__(self, status: int, code: str, message: str, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.detail is not None:
            d["detail"] = self.detail
        return d


def default_device_factory(mumu_root: str | None = None) -> DeviceFactory:
    def factory(index: int | None) -> Device:
        return connect(index, Backend.AUTO, mumu_root)
    return factory


@dataclass
class TaskRecord:
    id: str
    module: str
    source: str  # "api" / "ws" / "schedule:<id>"
    status: str
    started: float
    config: dict
    ended: float | None = None
    duration: float | None = None
    error: str | None = None
    debug_dir: str | None = None
    timeout: float | None = None

    def finish(self, result: TaskResult) -> None:
        self.status = result.status.value
        self.ended = result.ended
        self.duration = round(result.duration, 2)
        self.error = result.error
        self.debug_dir = str(result.debug_dir) if result.debug_dir else None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Running:
    record: TaskRecord
    handle: TaskHandle
    on_done: list[Callable[[TaskRecord], None]] = field(default_factory=list)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warning("读取 %s 失败：%s", path, e)
        return None


def _tail_jsonl(path: Path, limit: int) -> list[dict]:
    if limit <= 0 or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        log.warning("读取 %s 失败：%s", path, e)
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def validation_detail(e: ValidationError) -> list[dict]:
    return [{"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in e.errors()]


class Engine:
    def __init__(
        self,
        *,
        modules: dict[str, type[Module]] | None = None,
        device_factory: DeviceFactory | None = None,
        index: int | None = None,
        runtime_kwargs: dict | None = None,
        history_size: int = 200,
        log_size: int = 2000,
    ):
        self.modules = modules if modules is not None else discover()
        self.device_factory = device_factory or default_device_factory()
        self.index = index
        self.runtime_kwargs = runtime_kwargs or {}
        self.bus = EventBus()
        self.started_at = time.time()

        self._lock = threading.RLock()
        self.device: Device | None = None
        self.runtime: Runtime | None = None
        self.device_error: str | None = None
        self._running: _Running | None = None
        self._last: TaskRecord | None = None  # 最近结束的任务（wait_task 用）
        self._closed = False

        self.tasks_file = data_dir() / "tasks.jsonl"
        self.history: deque[dict] = deque(_tail_jsonl(self.tasks_file, history_size), maxlen=history_size)

        # 日志：服务自己桥接（设备断开时也要有日志），Runtime 不再重复桥接
        self.logs: deque[dict] = deque(maxlen=log_size)
        self._subs = [self.bus.subscribe(Topic.LOG, lambda e: self.logs.append(e.data), name="engine:logs")]
        self._bridge = LogBridge(self.bus, logging.DEBUG)
        logging.getLogger().addHandler(self._bridge)

    # ------------------------------------------------------------ 生命周期

    def close(self, timeout: float = 10.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            running = self._running
        if running is not None:
            running.handle.stop()
            running.handle.wait(timeout)
        with self._lock:
            self._close_device()
        logging.getLogger().removeHandler(self._bridge)
        for s in self._subs:
            s.unsubscribe()
        self.bus.close()

    # ------------------------------------------------------------ 设备

    def connect(self, index: int | None = None) -> dict:
        """连接设备并建 Runtime。已连接且序号相同时直接返回；序号不同则在空闲时重连。"""
        with self._lock:
            if self._closed:
                raise ApiError(503, "closed", "服务正在关闭")
            want = index if index is not None else self.index
            if self.runtime is not None:
                current = getattr(getattr(self.device, "info", None), "index", None)
                if index is None or current is None or current == index:
                    return self.device_info()
                self._require_idle("切换实例")
                self._close_device()
            try:
                device = self.device_factory(want)
            except Exception as e:  # noqa: BLE001 —— 任何连接错误都报给前端
                self.device_error = str(e) or type(e).__name__
                self._publish_device()
                raise ApiError(503, "no_device", f"连接设备失败：{self.device_error}") from e
            try:
                runtime = Runtime(device, bus=self.bus, bridge_logs=False, **self.runtime_kwargs)
            except Exception as e:
                device.close()
                self.device_error = str(e)
                self._publish_device()
                raise ApiError(503, "no_device", f"创建运行时失败：{e}") from e
            self.device, self.runtime, self.device_error = device, runtime, None
            if index is not None:
                self.index = index
            log.info("已连接 %s（%dx%d）", device.name, *device.resolution)
            self._publish_device()
            return self.device_info()

    def disconnect(self) -> dict:
        with self._lock:
            self._require_idle("断开设备")
            if self.runtime is not None:
                self._close_device()
                log.info("已断开设备")
                self._publish_device()
            return self.device_info()

    def _close_device(self) -> None:
        if self.runtime is not None:
            for mid in list(self.runtime.assistants):
                self.runtime.detach_assistant(mid)
            self.runtime.close()
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                log.exception("关闭设备出错")
        self.runtime = None
        self.device = None

    def device_info(self) -> dict:
        dev = self.device
        if dev is None:
            return {"connected": False, "error": self.device_error, "index": self.index}
        info = getattr(dev, "info", None)
        return {
            "connected": True,
            "name": dev.name,
            "resolution": list(dev.resolution),
            "backend": getattr(dev, "active_backend", None),
            "index": getattr(info, "index", self.index),
            "error": None,
        }

    def _publish_device(self) -> None:
        self.bus.publish(Topic.DEVICE, self.device_info())

    def list_instances(self) -> dict:
        """MuMu 安装和实例列表（`doctor` 的前半部分）。"""
        try:
            install = find_install()
            manager = MuMuManager(install)
            instances = manager.instances()
            version = manager.version()
        except Exception as e:  # noqa: BLE001
            raise ApiError(503, "mumu_unavailable", f"读取 MuMu 实例失败：{e}") from e
        return {
            "root": str(install.root),
            "version": version,
            "instances": [
                {"index": i.index, "name": i.name, "android_version": i.android_version,
                 "started": i.android_started, "adb": i.adb_serial}
                for i in instances
            ],
        }

    def _require_runtime(self) -> Runtime:
        rt = self.runtime
        if rt is None:
            raise ApiError(503, "no_device", "设备未连接")
        return rt

    def screenshot(self) -> np.ndarray:
        """只读截图（和任务共用设备锁）。设备掉线（例如 MuMu 被关）时报 503 device_error。"""
        rt = self._require_runtime()
        try:
            return rt.device.screenshot()
        except Exception as e:  # noqa: BLE001
            raise ApiError(503, "device_error", f"截图失败：{e}") from e

    def detect_scene(self) -> dict:
        rt = self._require_runtime()
        t0 = time.perf_counter()
        frame = self.screenshot()
        state = rt.scenes.detect(frame)
        return {
            "scene": state.scene, "popup": state.popup, "obscured": state.obscured, "clear": state.clear,
            "matches": sorted(state.matches), "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    # ------------------------------------------------------------ 模块与配置

    def get_module(self, module_id: str) -> type[Module]:
        cls = self.modules.get(module_id)
        if cls is None:
            raise ApiError(404, "unknown_module", f"未知模块：{module_id}")
        return cls

    def get_task_module(self, module_id: str) -> type[TaskModule]:
        cls = self.get_module(module_id)
        if not issubclass(cls, TaskModule):
            raise ApiError(400, "not_task", f"{module_id} 不是任务模块")
        return cls

    @staticmethod
    def module_info(cls: type[Module]) -> dict:
        return {
            "id": cls.id,
            "name": cls.name,
            "kind": cls.kind.value,
            "description": cls.description,
            "has_routes": cls.routes.__func__ is not Module.routes.__func__,
            "supports_next_due": issubclass(cls, TaskModule) and cls.supports_next_due(),
        }

    def config_path(self, module_id: str) -> Path:
        return module_data_dir(module_id) / "config.json"

    def validate_config(self, cls: type[Module], data: dict | None) -> BaseModel:
        try:
            return cls.config_model.model_validate(data or {})
        except ValidationError as e:
            raise ApiError(422, "invalid_config", f"{cls.id} 的配置不合法", validation_detail(e)) from e

    def load_config(self, cls: type[Module]) -> BaseModel:
        """保存的配置；没有或已不合法（例如模块升级改了字段）时用默认值。"""
        data = _read_json(self.config_path(cls.id))
        if isinstance(data, dict):
            try:
                return cls.config_model.model_validate(data)
            except ValidationError as e:
                log.warning("%s 保存的配置不合法，改用默认值：%s", cls.id, e)
        return cls.config_model()

    def save_config(self, cls: type[Module], data: dict) -> BaseModel:
        cfg = self.validate_config(cls, data)
        write_json_atomic(self.config_path(cls.id), cfg.model_dump(mode="json"))
        return cfg

    def module_stats(self, cls: type[Module], limit: int = 20) -> dict:
        d = module_data_dir(cls.id)
        return {
            "module": cls.id,
            "stats": _read_json(d / "stats.json"),
            "history": _tail_jsonl(d / "history.jsonl", limit),
        }

    def module_timers(self, cls: type[Module]) -> list[dict]:
        try:
            timers = cls.timers(module_data_dir(cls.id))
        except Exception as e:  # noqa: BLE001
            raise ApiError(500, "timers_failed", f"{cls.id} 读取计时失败：{e}") from e
        return [
            {"key": t.key, "label": t.label, "at": t.at.isoformat() if t.at else None, "note": t.note}
            for t in timers
        ]

    # ------------------------------------------------------------ 任务

    def _require_idle(self, action: str) -> None:
        if self._running is not None:
            raise ApiError(409, "busy", f"有任务在运行（{self._running.record.module}），不能{action}")

    @property
    def busy(self) -> bool:
        return self._running is not None

    def start_task(self, module_id: str, config: dict | None = None, *, timeout: float | None = None,
                   source: str = "api", on_done: Callable[[TaskRecord], None] | None = None) -> dict:
        """启动任务（不等结束）。config 为 None 时用保存的配置。"""
        cls = self.get_task_module(module_id)
        cfg = self.validate_config(cls, config) if config is not None else self.load_config(cls)
        with self._lock:
            if self._closed:
                raise ApiError(503, "closed", "服务正在关闭")
            rt = self._require_runtime()
            if self._running is not None:
                raise ApiError(409, "busy", f"设备上已有任务在运行：{self._running.record.module}")
            try:
                handle = rt.start_task(cls, cfg, timeout=timeout)
            except RuntimeBusy as e:
                raise ApiError(409, "busy", str(e)) from e
            except Exception as e:  # noqa: BLE001 —— 模块 setup 失败等
                raise ApiError(500, "start_failed", f"启动 {module_id} 失败：{e}") from e
            record = TaskRecord(
                id=uuid.uuid4().hex[:12], module=module_id, source=source, status=TaskStatus.RUNNING.value,
                started=handle.started, config=cfg.model_dump(mode="json"), timeout=timeout,
            )
            running = _Running(record, handle, [on_done] if on_done else [])
            self._running = running
        threading.Thread(target=self._watch, args=(running,), name=f"api:watch:{module_id}", daemon=True).start()
        log.info("经 API 启动任务 %s（来源 %s，任务 %s）", module_id, source, record.id)
        return record.to_dict()

    def _watch(self, running: _Running) -> None:
        result = None
        while result is None:
            result = running.handle.wait(1.0)
        record = running.record
        record.finish(result)
        with self._lock:
            if self._running is running:
                self._running = None
            self._last = record
            self.history.append(record.to_dict())
        try:
            with self.tasks_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            log.exception("写任务记录失败")
        self.bus.publish(Topic.STATS, {"module": record.module, "task": record.id})
        for cb in running.on_done:
            try:
                cb(record)
            except Exception:
                log.exception("任务结束回调出错")

    def current_task(self) -> dict | None:
        running = self._running
        if running is None:
            return None
        d = running.record.to_dict()
        d["elapsed"] = round(time.time() - running.record.started, 1)
        return d

    def stop_task(self) -> bool:
        running = self._running
        if running is None:
            return False
        running.handle.stop()
        log.info("经 API 急停任务 %s", running.record.module)
        return True

    def wait_task(self, timeout: float | None = None) -> dict | None:
        """测试 / CLI 用：等当前任务结束，返回它的记录；没有任务在跑时返回最近结束的那个。"""
        end = None if timeout is None else time.monotonic() + timeout
        while self._running is not None:
            if end is not None and time.monotonic() > end:
                return None
            time.sleep(0.02)
        return self._last.to_dict() if self._last else None

    def task_history(self, limit: int = 50, module: str | None = None) -> list[dict]:
        items = [r for r in self.history if module is None or r.get("module") == module]
        return list(reversed(items[-limit:])) if limit > 0 else []

    # ------------------------------------------------------------ 助手

    def assistants(self) -> list[dict]:
        rt = self.runtime
        if rt is None:
            return []
        return [{"id": mid, "name": h.module.name} for mid, h in rt.assistants.items()]

    def attach_assistant(self, module_id: str, config: dict | None = None) -> dict:
        cls = self.get_module(module_id)
        if not issubclass(cls, AssistantModule):
            raise ApiError(400, "not_assistant", f"{module_id} 不是助手模块")
        cfg = self.validate_config(cls, config) if config is not None else self.load_config(cls)
        with self._lock:
            rt = self._require_runtime()
            try:
                rt.attach_assistant(cls, cfg)
            except RuntimeBusy as e:
                raise ApiError(409, "busy", str(e)) from e
        return {"id": module_id, "name": cls.name}

    def detach_assistant(self, module_id: str) -> bool:
        rt = self.runtime
        if rt is None or module_id not in rt.assistants:
            return False
        rt.detach_assistant(module_id)
        return True

    # ------------------------------------------------------------ 日志

    def recent_logs(self, limit: int = 200, level: str = "INFO", since: float | None = None) -> list[dict]:
        floor = LOG_LEVELS.get(level.upper(), 20)
        items = [r for r in list(self.logs)
                 if LOG_LEVELS.get(r.get("level", "INFO"), 20) >= floor and (since is None or r["time"] > since)]
        return items[-limit:] if limit > 0 else []
