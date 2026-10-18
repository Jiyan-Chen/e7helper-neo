"""WebSocket（B08）。

`/ws`：控制 + 事件频道（JSON 文本帧）
- 连上后服务端先发 `{"type":"hello", "data": <同 GET /api/status>}`。
- 客户端请求：`{"id": 1, "op": "<操作>", ...}`，每个请求都有回复
  `{"type":"reply","id":1,"ok":true,"data":...}` 或 `{"type":"reply","id":1,"ok":false,"error":{"code","message"}}`。
  操作：ping / status / subscribe(topics, log_level) / unsubscribe(topics) /
  start_task(module, config?, timeout?) / stop_task / run_schedule(id) / pause_scheduler / resume_scheduler。
- 订阅后推送事件：`{"type":"event","topic":"task","time":<unix 秒>,"data":{...}}`。
  主题：log / task / scene / assistant / device / schedule / stats，以及模块自定义的 `<module_id>.<name>`；
  `*` 表示全部（不含帧）。日志按 log_level 过滤（默认 INFO）。
- 每个客户端的事件队列最多 1000 条，满了丢最旧的；回复不会被丢。

`/ws/frames?fps=2&scale=0.5&quality=70`：帧频道（二进制 JPEG）
- 有任务时转发任务的截图（Topic.FRAME），按 fps 节流；任务超过 1 秒没截图时由这里自己截图（只读）。
- 设备没连上时不发帧，每秒发一条文本 `{"type":"status","connected":false}`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from e7helper.core.events import WILDCARD, Event, Topic

from .auth import websocket_authorized
from .engine import LOG_LEVELS, ApiError

if TYPE_CHECKING:
    from .app import Services

log = logging.getLogger(__name__)

EVENT_QUEUE = 1000


def _dumps(msg: dict) -> str:
    return json.dumps(msg, ensure_ascii=False, default=str)


class Client:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.topics: set[str] = set()
        self.log_level = LOG_LEVELS["INFO"]
        self.events: deque[dict] = deque(maxlen=EVENT_QUEUE)
        self.replies: deque[dict] = deque()
        self.dropped = 0
        self.wake = asyncio.Event()

    def wants(self, event: Event) -> bool:
        if event.topic not in self.topics and WILDCARD not in self.topics:
            return False
        if event.topic == Topic.LOG and isinstance(event.data, dict):
            return LOG_LEVELS.get(event.data.get("level", "INFO"), 20) >= self.log_level
        return True

    # 以下方法只在事件循环线程里调用
    def offer(self, msg: dict) -> None:
        if len(self.events) == self.events.maxlen:
            self.dropped += 1
        self.events.append(msg)
        self.wake.set()

    def reply(self, msg: dict) -> None:
        self.replies.append(msg)
        self.wake.set()

    async def sender(self) -> None:
        while True:
            await self.wake.wait()
            self.wake.clear()
            while self.replies or self.events:
                msg = self.replies.popleft() if self.replies else self.events.popleft()
                await self.ws.send_text(_dumps(msg))


class Hub:
    """把事件总线（各线程同步发布）转到每个 WebSocket 客户端（事件循环里发送）。"""

    def __init__(self, services: Services):
        self.services = services
        self.clients: set[Client] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._sub = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self._sub = self.services.engine.bus.subscribe(WILDCARD, self._on_event, name="api:ws_hub")

    def close(self) -> None:
        if self._sub is not None:
            self._sub.unsubscribe()
            self._sub = None

    def _on_event(self, event: Event) -> None:
        # 在发布者线程里调用：只做筛选，发送交给事件循环
        if event.topic == Topic.FRAME or not self.clients or self.loop is None:
            return
        targets = [c for c in list(self.clients) if c.wants(event)]
        if not targets:
            return
        msg = {"type": "event", "topic": event.topic, "time": event.time, "data": event.data}
        try:
            self.loop.call_soon_threadsafe(self._deliver, targets, msg)
        except RuntimeError:
            pass  # 事件循环已关闭

    def _deliver(self, targets: list[Client], msg: dict) -> None:
        for c in targets:
            if c in self.clients:
                c.offer(msg)

    # ------------------------------------------------------------ 请求

    async def handle(self, client: Client, msg: Any) -> dict:
        if not isinstance(msg, dict):
            return {"type": "reply", "id": None, "ok": False,
                    "error": {"code": "bad_request", "message": "消息必须是 JSON 对象"}}
        mid = msg.get("id")
        op = msg.get("op")
        fn = self._ops().get(op)
        if fn is None:
            return {"type": "reply", "id": mid, "ok": False,
                    "error": {"code": "unknown_op", "message": f"未知操作：{op}"}}
        try:
            data = await fn(client, msg)
        except ApiError as e:
            return {"type": "reply", "id": mid, "ok": False, "error": e.to_dict()}
        except Exception as e:  # noqa: BLE001
            log.exception("WebSocket 操作 %s 出错", op)
            return {"type": "reply", "id": mid, "ok": False, "error": {"code": "internal", "message": str(e)}}
        return {"type": "reply", "id": mid, "ok": True, "data": data}

    def _ops(self) -> dict[str, Callable]:
        return {
            "ping": self._ping,
            "status": self._status,
            "subscribe": self._subscribe,
            "unsubscribe": self._unsubscribe,
            "start_task": self._start_task,
            "stop_task": self._stop_task,
            "run_schedule": self._run_schedule,
            "pause_scheduler": self._pause,
            "resume_scheduler": self._resume,
        }

    async def _ping(self, client, msg):
        return {"time": time.time()}

    async def _status(self, client, msg):
        return await asyncio.to_thread(self.services.status)

    async def _subscribe(self, client, msg):
        topics = msg.get("topics") or []
        if isinstance(topics, str):
            topics = [topics]
        if not all(isinstance(t, str) for t in topics):
            raise ApiError(400, "bad_request", "topics 必须是字符串列表")
        client.topics.update(topics)
        if "log_level" in msg:
            level = str(msg["log_level"]).upper()
            if level not in LOG_LEVELS:
                raise ApiError(400, "bad_request", f"未知日志级别：{msg['log_level']}")
            client.log_level = LOG_LEVELS[level]
        return {"topics": sorted(client.topics),
                "log_level": next(k for k, v in LOG_LEVELS.items() if v == client.log_level)}

    async def _unsubscribe(self, client, msg):
        topics = msg.get("topics")
        if topics is None:
            client.topics.clear()
        else:
            client.topics.difference_update([topics] if isinstance(topics, str) else topics)
        return {"topics": sorted(client.topics)}

    async def _start_task(self, client, msg):
        module = msg.get("module")
        if not isinstance(module, str):
            raise ApiError(400, "bad_request", "缺少 module")
        config = msg.get("config")
        if config is not None and not isinstance(config, dict):
            raise ApiError(400, "bad_request", "config 必须是对象")
        timeout = msg.get("timeout")
        if timeout is not None and (not isinstance(timeout, int | float) or timeout <= 0):
            raise ApiError(400, "bad_request", "timeout 必须是正数")
        return await asyncio.to_thread(self.services.engine.start_task, module, config,
                                       timeout=timeout, source="ws")

    async def _stop_task(self, client, msg):
        return {"stopped": self.services.engine.stop_task()}

    async def _run_schedule(self, client, msg):
        return await asyncio.to_thread(self.services.scheduler.run_now, str(msg.get("schedule")))

    async def _pause(self, client, msg):
        return await asyncio.to_thread(self.services.scheduler.set_paused, True)

    async def _resume(self, client, msg):
        return await asyncio.to_thread(self.services.scheduler.set_paused, False)


def encode_jpeg(frame: np.ndarray, scale: float, quality: int) -> bytes:
    if scale < 1.0:
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("JPEG 编码失败")
    return buf.tobytes()


def build_ws_router(services: Services) -> APIRouter:
    router = APIRouter()
    hub = services.hub

    @router.websocket("/ws")
    async def control(ws: WebSocket):
        if not websocket_authorized(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        client = Client(ws)
        hub.clients.add(client)
        client.reply({"type": "hello", "data": await asyncio.to_thread(services.status)})
        sender = asyncio.create_task(client.sender())
        try:
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                except ValueError:
                    client.reply({"type": "reply", "id": None, "ok": False,
                                  "error": {"code": "bad_json", "message": "不是合法的 JSON"}})
                    continue
                client.reply(await hub.handle(client, msg))
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(client)
            sender.cancel()

    @router.websocket("/ws/frames")
    async def frames(ws: WebSocket, fps: float = 2.0, scale: float = 0.5, quality: int = 70):
        if not websocket_authorized(ws):
            await ws.close(code=1008)
            return
        fps = min(max(fps, 0.2), 15.0)
        scale = min(max(scale, 0.1), 1.0)
        quality = min(max(quality, 10), 95)
        await ws.accept()
        engine = services.engine
        latest: dict[str, Any] = {"frame": None, "seq": 0, "at": 0.0}

        def on_frame(e: Event) -> None:
            latest["frame"] = e.data
            latest["seq"] += 1
            latest["at"] = time.monotonic()

        sub = engine.bus.subscribe(Topic.FRAME, on_frame, name="api:ws_frames")
        receiver = asyncio.create_task(_drain(ws))
        sent_seq = 0
        try:
            while not receiver.done():
                t0 = time.monotonic()
                frame = None
                if latest["seq"] != sent_seq and t0 - latest["at"] < 1.0:
                    frame, sent_seq = latest["frame"], latest["seq"]
                elif engine.runtime is not None:
                    try:
                        frame = await asyncio.to_thread(engine.screenshot)
                    except Exception as e:  # noqa: BLE001 —— 断开、截图失败：下一轮再试
                        log.debug("帧频道截图失败：%s", e)
                if frame is not None:
                    data = await asyncio.to_thread(encode_jpeg, frame, scale, quality)
                    await ws.send_bytes(data)
                    delay = 1.0 / fps
                else:
                    await ws.send_text(_dumps({"type": "status", "connected": engine.runtime is not None}))
                    delay = 1.0
                await asyncio.wait([receiver], timeout=max(0.0, delay - (time.monotonic() - t0)))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sub.unsubscribe()
            receiver.cancel()

    return router


async def _drain(ws: WebSocket) -> None:
    """帧频道不需要客户端发消息；收到断开就结束。"""
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
    except (WebSocketDisconnect, RuntimeError):
        return
