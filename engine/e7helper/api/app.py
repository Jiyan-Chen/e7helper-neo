"""FastAPI 应用：核心路由 + 模块子路由 + WebSocket（B08）。

    app = create_app(Engine(), token="...")      # e7helper serve 里调用

路由一览见 docs/architecture.md「API 层」一节，或服务起来后打开 /docs。
同步路由（def）在线程池里执行，所以可以直接调用 Engine 的阻塞方法（连接设备、截图）。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

import cv2
from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from e7helper import __version__
from e7helper.modules import Module, ModuleRegistryError

from .auth import LOCAL_HOSTS, AuthConfig, HostCheckMiddleware, require_token
from .capture import FrameCache, build_capture_router
from .flows import build_flows_router
from .engine import ApiError, Engine
from .heroes import build_heroes_router
from .rta import build_rta_router
from .scheduler import Scheduler, ScheduleSpec
from .ws import Hub, build_ws_router, encode_jpeg

log = logging.getLogger(__name__)

# 模块子路由不能占用的第一段路径（核心路由 /api/modules/{id}/... 用了）
RESERVED_MODULE_PATHS = frozenset({"", "config", "stats", "timers"})

# Tauri 2 在 Windows 上的页面源是 http://tauri.localhost；1420 是 Tauri + Vite 模板的开发端口
DEFAULT_CORS_ORIGINS = ("http://tauri.localhost", "https://tauri.localhost", "tauri://localhost",
                        "http://localhost:1420", "http://127.0.0.1:1420")


def quiet_connection_lost(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """事件循环的异常处理：忽略 Windows 上对端已断开时 asyncio 关连接的报错，其余照常交给默认处理。

    浏览器刷新 / 关页、GUI 重连时，对端已经把连接重置了，Proactor 在 `_call_connection_lost` 里
    再 `shutdown()` 这个 socket 会抛 ConnectionResetError（WinError 10054）。连接本来就要关，没有影响，
    但默认处理会记成 ERROR，经日志桥接出现在 GUI「动态」里（B12 反馈 4）。
    B12 反馈 7 起 `e7helper serve` 改用 Selector 事件循环，不会再走到这里；留着给用 Proactor 起服务的场合兜底。
    """
    exc = context.get("exception")
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)) and             "_call_connection_lost" in str(context.get("message", "")):
        log.debug("对端已断开，忽略关连接时的 %s", type(exc).__name__)
        return
    loop.default_exception_handler(context)


@dataclass
class Services:
    engine: Engine
    scheduler: Scheduler
    hub: Hub = field(init=False)

    def __post_init__(self) -> None:
        self.hub = Hub(self)

    def status(self) -> dict:
        e = self.engine
        sched = self.scheduler.snapshot()
        return {
            "version": __version__,
            "uptime": round(time.time() - e.started_at, 1),
            "device": e.device_info(),
            "task": e.current_task(),
            "assistants": e.assistants(),
            "scheduler": {"paused": sched["paused"], "schedules": len(sched["schedules"]),
                          "next": _next_schedule(sched["schedules"])},
        }


def _next_schedule(items: list[dict]) -> dict | None:
    pending = [s for s in items if s["state"]["next_run"]]
    if not pending:
        return None
    s = min(pending, key=lambda s: s["state"]["next_run"])
    return {"id": s["id"], "module": s["module"], "next_run": s["state"]["next_run"]}


# ---------------------------------------------------------------- 请求体


class ConnectBody(BaseModel):
    index: int | None = Field(None, ge=0, description="MuMu 实例序号；不给就用启动参数或第一个已启动的实例")


class StartTaskBody(BaseModel):
    module: str
    config: dict | None = Field(None, description="完整配置；不给就用保存的配置")
    timeout: float | None = Field(None, gt=0, description="任务时限（秒）")


class AttachBody(BaseModel):
    config: dict | None = None


class PausedBody(BaseModel):
    paused: bool


# ---------------------------------------------------------------- 应用


def create_app(
    engine: Engine,
    *,
    token: str | None,
    allowed_hosts: frozenset[str] | set[str] = LOCAL_HOSTS,
    cors_origins: tuple[str, ...] | list[str] = DEFAULT_CORS_ORIGINS,
    scheduler: Scheduler | None = None,
    start_scheduler: bool = True,
    autoconnect: bool = True,
    on_shutdown: list[Callable[[], None]] | None = None,
) -> FastAPI:
    """on_shutdown：服务关闭的最后一步调用（例如删除 api.json）。uvicorn 关闭后会重新抛出收到的信号，
    Windows 上 SIGBREAK 的默认处理是直接结束进程，所以清理不能放在 `server.run()` 之后。"""
    services = Services(engine, scheduler or Scheduler(engine))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(quiet_connection_lost)
        services.hub.start(loop)
        if autoconnect:
            threading.Thread(target=_autoconnect, args=(engine,), name="api:autoconnect", daemon=True).start()
        if start_scheduler:
            services.scheduler.start()
        try:
            yield
        finally:
            services.scheduler.stop()
            services.hub.close()
            await asyncio.to_thread(engine.close)
            for fn in on_shutdown or ():
                try:
                    fn()
                except Exception:
                    log.exception("关闭回调出错")

    app = FastAPI(title="e7helper", version=__version__, lifespan=lifespan,
                  description="第七史诗国服 · MuMu 助手引擎 API。除 /api/health 外都需要 token（见 <数据目录>/api.json）。")
    app.state.auth = AuthConfig(token, frozenset(allowed_hosts))
    app.state.services = services
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"],
                       allow_headers=["*"])
    app.add_middleware(HostCheckMiddleware, allowed_hosts=frozenset(allowed_hosts))

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status)

    @app.get("/api/health", tags=["基础"], summary="服务是否在运行（不需要 token）")
    def health() -> dict:
        return {"ok": True, "version": __version__, "uptime": round(time.time() - engine.started_at, 1),
                "auth": token is not None}

    app.include_router(_core_router(services), prefix="/api", dependencies=[Depends(require_token)])
    frames = FrameCache()
    app.include_router(build_capture_router(engine, frames), prefix="/api", dependencies=[Depends(require_token)])
    app.include_router(build_flows_router(engine, services.scheduler, frames), prefix="/api", dependencies=[Depends(require_token)])
    app.include_router(build_heroes_router(), prefix="/api", dependencies=[Depends(require_token)])
    app.include_router(build_rta_router(), prefix="/api", dependencies=[Depends(require_token)])
    _mount_module_routes(app, engine)
    app.include_router(build_ws_router(services))
    return app


def _autoconnect(engine: Engine) -> None:
    try:
        engine.connect()
    except ApiError as e:
        log.warning("启动时没有连上设备（可以稍后 POST /api/device/connect）：%s", e.message)


def _mount_module_routes(app: FastAPI, engine: Engine) -> None:
    for mid, cls in engine.modules.items():
        if cls.routes.__func__ is Module.routes.__func__:
            continue
        router = cls.routes()
        if router is None:
            continue
        for route in router.routes:
            first = getattr(route, "path", "").strip("/").split("/", 1)[0]
            if first in RESERVED_MODULE_PATHS or first.startswith("{"):
                raise ModuleRegistryError(f"模块 {mid} 的路由 {route.path!r} 占用了核心路由的路径")
        app.include_router(router, prefix=f"/api/modules/{mid}", tags=[f"模块：{cls.name}"],
                           dependencies=[Depends(require_token)])
        log.debug("挂载模块 %s 的子路由（%d 条）", mid, len(router.routes))


def _core_router(services: Services) -> APIRouter:
    engine = services.engine
    scheduler = services.scheduler
    r = APIRouter()

    # ------------------------------------------------------------ 状态 / 日志

    @r.get("/status", tags=["基础"], summary="设备、当前任务、助手、调度器概况（同 WS 的 hello）")
    def status() -> dict:
        return services.status()

    @r.post("/shutdown", tags=["基础"], status_code=202, summary="关闭服务（GUI 退出时关掉自己拉起的引擎）")
    def shutdown(request: Request) -> dict:
        fn = getattr(request.app.state, "request_shutdown", None)
        if fn is None:
            raise ApiError(501, "not_supported", "这个服务不能远程关闭")
        log.info("收到关闭请求")
        fn()
        return {"shutting_down": True}

    @r.get("/logs", tags=["基础"], summary="最近的日志")
    def logs(limit: int = Query(200, ge=0, le=2000), level: str = "INFO",
             since: float | None = Query(None, description="只要这个时间（unix 秒）之后的")) -> list[dict]:
        return engine.recent_logs(limit, level, since)

    # ------------------------------------------------------------ 设备

    @r.get("/device", tags=["设备"])
    def device() -> dict:
        return engine.device_info()

    @r.post("/device/connect", tags=["设备"])
    def device_connect(body: ConnectBody = Body(default_factory=ConnectBody)) -> dict:
        return engine.connect(body.index)

    @r.post("/device/disconnect", tags=["设备"], summary="断开设备（有任务在跑时 409）")
    def device_disconnect() -> dict:
        return engine.disconnect()

    @r.get("/device/instances", tags=["设备"], summary="MuMu 安装与实例列表")
    def device_instances() -> dict:
        return engine.list_instances()

    @r.get("/device/screenshot", tags=["设备"], summary="当前画面（只读）",
           response_class=Response, responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}})
    def screenshot(format: Literal["png", "jpeg"] = "png", scale: float = Query(1.0, gt=0.05, le=1.0),
                   quality: int = Query(80, ge=10, le=95)) -> Response:
        frame = engine.screenshot()
        if format == "jpeg":
            return Response(encode_jpeg(frame, scale, quality), media_type="image/jpeg")
        if scale < 1.0:
            h, w = frame.shape[:2]
            frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            raise ApiError(500, "encode_failed", "PNG 编码失败")
        return Response(buf.tobytes(), media_type="image/png")

    @r.get("/scene", tags=["设备"], summary="识别当前场景和弹窗（只读，不关弹窗）")
    def scene() -> dict:
        return engine.detect_scene()

    # ------------------------------------------------------------ 模块

    @r.get("/modules", tags=["模块"])
    def modules() -> list[dict]:
        return [engine.module_info(cls) for cls in engine.modules.values()]

    @r.get("/modules/{module_id}", tags=["模块"], summary="模块信息、配置 JSON Schema、保存的配置")
    def module(module_id: str) -> dict:
        cls = engine.get_module(module_id)
        return {**engine.module_info(cls), "config_schema": cls.config_schema(),
                "config": engine.load_config(cls).model_dump(mode="json")}

    @r.get("/modules/{module_id}/config", tags=["模块"], summary="保存的配置（没有就是默认值）")
    def get_config(module_id: str) -> dict:
        return engine.load_config(engine.get_module(module_id)).model_dump(mode="json")

    @r.put("/modules/{module_id}/config", tags=["模块"], summary="保存配置（整体替换，返回补全默认值后的配置）")
    def put_config(module_id: str, body: dict = Body(...)) -> dict:
        return engine.save_config(engine.get_module(module_id), body).model_dump(mode="json")

    @r.get("/modules/{module_id}/stats", tags=["模块"], summary="统计（stats.json）和最近的运行记录（history.jsonl）")
    def stats(module_id: str, limit: int = Query(20, ge=0, le=500)) -> dict:
        return engine.module_stats(engine.get_module(module_id), limit)

    @r.get("/modules/{module_id}/timers", tags=["模块"], summary="模块的计时（GUI 显示倒计时）")
    def timers(module_id: str) -> list[dict]:
        return engine.module_timers(engine.get_module(module_id))

    # ------------------------------------------------------------ 任务

    @r.post("/tasks", tags=["任务"], status_code=202, summary="启动任务（有任务在跑时 409）")
    def start_task(body: StartTaskBody) -> dict:
        return engine.start_task(body.module, body.config, timeout=body.timeout, source="api")

    @r.get("/tasks/current", tags=["任务"], summary="当前任务（没有为 null）")
    def current_task() -> dict | None:
        return engine.current_task()

    @r.post("/tasks/stop", tags=["任务"], summary="急停当前任务")
    def stop_task() -> dict:
        return {"stopped": engine.stop_task()}

    @r.get("/tasks/history", tags=["任务"], summary="经 API 启动的任务记录（新的在前）")
    def task_history(limit: int = Query(50, ge=0, le=200), module: str | None = None) -> list[dict]:
        return engine.task_history(limit, module)

    # ------------------------------------------------------------ 助手

    @r.get("/assistants", tags=["助手"])
    def assistants() -> list[dict]:
        return engine.assistants()

    @r.post("/assistants/{module_id}", tags=["助手"], summary="挂载助手模块")
    def attach(module_id: str, body: AttachBody = Body(default_factory=AttachBody)) -> dict:
        return engine.attach_assistant(module_id, body.config)

    @r.delete("/assistants/{module_id}", tags=["助手"], summary="卸下助手模块")
    def detach(module_id: str) -> dict:
        return {"detached": engine.detach_assistant(module_id)}

    # ------------------------------------------------------------ 调度

    @r.get("/schedules", tags=["调度"])
    def schedules() -> dict:
        return scheduler.snapshot()

    @r.post("/schedules", tags=["调度"], status_code=201, summary="新建计划")
    def create_schedule(spec: ScheduleSpec) -> dict:
        return scheduler.create(spec)

    @r.get("/schedules/{sid}", tags=["调度"])
    def get_schedule(sid: str) -> dict:
        return scheduler.get(sid)

    @r.patch("/schedules/{sid}", tags=["调度"], summary="修改计划（只传要改的字段，例如 {\"enabled\": false}）")
    def patch_schedule(sid: str, body: dict = Body(...)) -> dict:
        return scheduler.update(sid, body)

    @r.delete("/schedules/{sid}", tags=["调度"], status_code=204, response_class=Response)
    def delete_schedule(sid: str) -> Response:
        scheduler.delete(sid)
        return Response(status_code=204)

    @r.post("/schedules/{sid}/run", tags=["调度"], status_code=202, summary="立即跑一次（有任务在跑时 409）")
    def run_schedule(sid: str) -> dict:
        return scheduler.run_now(sid)

    @r.put("/scheduler", tags=["调度"], summary="暂停 / 恢复调度器")
    def set_paused(body: PausedBody) -> dict:
        return scheduler.set_paused(body.paused)

    return r
