"""鉴权：随机 token + Host 校验（B08 用户确认）。

为什么要鉴权：浏览器里任意网页都能请求 localhost，WebSocket 还不受 CORS 限制，
恶意网页理论上可以连上来启动任务。所以：
- 每次启动生成随机 token（或用 --token / E7_API_TOKEN 指定），写进 `<数据目录>/api.json`；
  HTTP 用 `Authorization: Bearer <token>`，也接受 `?token=`（方便 <img> 直接显示截图）；WebSocket 用 `?token=`。
- Host 头必须是本机名（localhost / 127.0.0.1 / ::1，加上 --allow-host 指定的），防 DNS rebinding。
- `GET /api/health`、`/docs`、`/openapi.json` 不需要 token（不含数据，GUI 用 health 探测服务是否起来）。
- 开发时可以 `--no-auth` 关掉 token（Host 校验仍然生效）。
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_bearer = HTTPBearer(auto_error=False, description="启动时生成的 token，见 <数据目录>/api.json")


def generate_token() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class AuthConfig:
    token: str | None  # None：不校验 token
    allowed_hosts: frozenset[str] = field(default=LOCAL_HOSTS)

    def check_token(self, given: str | None) -> bool:
        if self.token is None:
            return True
        return given is not None and secrets.compare_digest(given.encode(), self.token.encode())


_TOKEN_RE = re.compile(r"(token=)[^&\s\"']+")


class RedactTokenFilter(logging.Filter):
    """把日志里的 `token=xxx` 打码（uvicorn 会记录带 ?token= 的 WebSocket 地址）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "token=" in msg:
            record.msg = _TOKEN_RE.sub(r"\1***", msg)
            record.args = ()
        return True


def host_name(host_header: str) -> str:
    """Host 头去掉端口：`127.0.0.1:47800` → `127.0.0.1`，`[::1]:47800` → `::1`。"""
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


class HostCheckMiddleware:
    """纯 ASGI 中间件：HTTP 和 WebSocket 都校验 Host 头。"""

    def __init__(self, app, allowed_hosts: frozenset[str]):
        self.app = app
        self.allowed = allowed_hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        host = ""
        for k, v in scope.get("headers") or ():
            if k == b"host":
                host = v.decode("latin-1")
                break
        if host_name(host) in self.allowed:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"error": {"code": "bad_host", "message": f"不接受的 Host：{host}"}},
                          ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": 400,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def require_token(request: Request,
                  creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    auth: AuthConfig = request.app.state.auth
    given = creds.credentials if creds is not None else request.query_params.get("token")
    if not auth.check_token(given):
        raise HTTPException(401, detail="缺少或错误的 token", headers={"WWW-Authenticate": "Bearer"})


def websocket_authorized(ws: WebSocket) -> bool:
    auth: AuthConfig = ws.app.state.auth
    given = ws.query_params.get("token")
    if given is None:
        header = ws.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            given = header[7:].strip()
    return auth.check_token(given)
