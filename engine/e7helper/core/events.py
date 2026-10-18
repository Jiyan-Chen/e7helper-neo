"""事件总线：进程内的发布/订阅。

用途：
- 帧事件（Topic.FRAME）：任务截图时发布，AssistantModule.on_frame 通过它拿帧，可以和任务并行；
- 日志 / 任务状态 / 场景变化事件：B08 的 WebSocket 会订阅它们推给前端。

同步订阅在发布者线程里直接调用，适合轻量回调；耗时的订阅者（例如助手模块的识别）用
`threaded=True`，在自己的工作线程里处理，队列满时丢弃最旧的事件，不会拖慢发布者。
订阅者抛出的异常只记日志，不会影响发布者和其他订阅者。
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

WILDCARD = "*"


class Topic:
    """内置主题。模块也可以发布自定义主题，建议用 `<module_id>.<name>` 命名。"""

    FRAME = "frame"  # data: np.ndarray（BGR 帧，订阅者不得修改）
    LOG = "log"  # data: dict（level / name / message / time）
    TASK = "task"  # data: dict（module / status / error …）
    SCENE = "scene"  # data: dict（scene / popup / obscured）
    ASSISTANT = "assistant"  # data: dict（module / state）
    # B08（API 服务发布）
    DEVICE = "device"  # data: dict（connected / name / resolution / backend / error）
    SCHEDULE = "schedule"  # data: dict（id / module / action / reason …）
    STATS = "stats"  # data: dict（module）：该模块的统计文件可能变了，客户端自己重新拉


@dataclass(frozen=True)
class Event:
    topic: str
    data: Any = None
    time: float = field(default_factory=time.time)


Callback = Callable[[Event], None]


class _Worker:
    """threaded 订阅者的工作线程：有界队列，满了丢最旧的。"""

    def __init__(self, name: str, callback: Callback, maxsize: int):
        self.callback = callback
        self.queue: deque[Event] = deque(maxlen=maxsize)
        self.cond = threading.Condition()
        self.closed = False
        self.dropped = 0
        self.thread = threading.Thread(target=self._loop, name=f"events:{name}", daemon=True)
        self.thread.start()

    def put(self, event: Event) -> None:
        with self.cond:
            if self.closed:
                return
            if len(self.queue) == self.queue.maxlen:
                self.dropped += 1
            self.queue.append(event)
            self.cond.notify()

    def close(self, timeout: float | None = 2.0) -> None:
        with self.cond:
            self.closed = True
            self.queue.clear()
            self.cond.notify()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout)

    def _loop(self) -> None:
        while True:
            with self.cond:
                while not self.queue and not self.closed:
                    self.cond.wait()
                if self.closed:
                    return
                event = self.queue.popleft()
            _safe_call(self.callback, event)


def _safe_call(callback: Callback, event: Event) -> None:
    try:
        callback(event)
    except Exception:
        if event.topic == Topic.LOG:
            # 日志订阅者出错时不能再写日志：日志又会变成 LOG 事件交给它，形成循环
            traceback.print_exc()
        else:
            log.exception("事件订阅者处理 %s 时出错：%r", event.topic, callback)


class Subscription:
    def __init__(self, bus: EventBus, sub_id: int, topic: str, name: str, worker: _Worker | None):
        self._bus = bus
        self.id = sub_id
        self.topic = topic
        self.name = name
        self._worker = worker

    @property
    def dropped(self) -> int:
        """threaded 订阅者因队列满被丢弃的事件数。"""
        return self._worker.dropped if self._worker else 0

    def unsubscribe(self) -> None:
        self._bus._remove(self)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *exc) -> None:
        self.unsubscribe()

    def __repr__(self) -> str:
        return f"Subscription({self.topic!r}, {self.name!r})"


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, dict[int, tuple[Callback, Subscription]]] = {}
        self._ids = itertools.count(1)

    def subscribe(self, topic: str, callback: Callback, *, threaded: bool = False,
                  maxsize: int = 1, name: str | None = None) -> Subscription:
        """订阅主题（`*` 表示全部）。

        threaded=True 时回调在独立线程里执行；maxsize 是该订阅者的队列长度，
        帧这类只关心最新值的事件用默认的 1，日志这类不想丢的事件给大一些。
        """
        name = name or getattr(callback, "__qualname__", repr(callback))
        sub_id = next(self._ids)
        worker = _Worker(name, callback, maxsize) if threaded else None
        sub = Subscription(self, sub_id, topic, name, worker)
        with self._lock:
            self._subs.setdefault(topic, {})[sub_id] = (callback, sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            subs = self._subs.get(sub.topic)
            if subs is None or subs.pop(sub.id, None) is None:
                return
            if not subs:
                del self._subs[sub.topic]
        if sub._worker:
            sub._worker.close()

    def has_subscribers(self, topic: str) -> bool:
        with self._lock:
            return bool(self._subs.get(topic) or self._subs.get(WILDCARD))

    def publish(self, topic: str, data: Any = None) -> Event:
        event = Event(topic, data)
        with self._lock:
            targets = list(self._subs.get(topic, {}).values())
            if topic != WILDCARD:
                targets += self._subs.get(WILDCARD, {}).values()
        for callback, sub in targets:
            if sub._worker:
                sub._worker.put(event)
            else:
                _safe_call(callback, event)
        return event

    def close(self) -> None:
        """取消全部订阅并停止工作线程。"""
        with self._lock:
            subs = [s for d in self._subs.values() for _, s in d.values()]
            self._subs.clear()
        for s in subs:
            if s._worker:
                s._worker.close()


class LogBridge(logging.Handler):
    """把 logging 记录转成 Topic.LOG 事件。"""

    def __init__(self, bus: EventBus, level: int = logging.INFO):
        super().__init__(level)
        self.bus = bus
        self._local = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._local, "busy", False):
            return  # 同步订阅者里又打了日志：丢弃，避免递归
        self._local.busy = True
        try:
            self.bus.publish(Topic.LOG, {
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
                "time": record.created,
                "thread": record.threadName,
            })
        except Exception:
            self.handleError(record)
        finally:
            self._local.busy = False


__all__ = ["WILDCARD", "Event", "EventBus", "LogBridge", "Subscription", "Topic"]
