"""国服 / 海外官方战绩站的接口客户端（B14a）。

两个站是同一套系统（接口同名），都是非公开接口，格式哪天变了这里要跟着改：
- 请求：`POST <地址><名字>?<参数>`，没有请求体；海外要带 `Content-Type: application/json`；
- 返回：国服 `{return_code, result_body}`，海外 `{code, message, value: {result_body, total_count}}`，
  `result_body` 里有时还有一层 `return_code`。统一由 `call()` 拆成 `result_body`。

只用标准库 urllib（同 B13）。每个客户端自己限速（两次请求的开始时间至少隔 interval 秒，外加随机抖动），
429 / 5xx / 网络错误按指数退避重试，其他 4xx 和非 0 返回码直接抛 `OfficialError`。
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

TIMEOUT = 20
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/139.0.0.0 Safari/537.36")


@dataclass(frozen=True)
class ServerInfo:
    name: str
    base: str
    lang: str
    origin: str
    json_header: bool = False
    pages: bool = True  # getBattleList 能不能往前翻页（海外每人只能看最近 100 场）


SERVERS: dict[str, ServerInfo] = {
    "cn": ServerInfo("cn", "https://e7stats.qyzlgame.com/gameApi/", "zh-CN", "https://e7.qyzlgame.com"),
    "global": ServerInfo("global", "https://e7api.onstove.com/gameApi/", "en", "https://epic7.onstove.com",
                         json_header=True, pages=False),
}
CN_WORLD = "world_zlong1"
BATTLES_PER_PAGE = 100

# (url, headers, timeout) → 响应体；出错时抛 urllib 的异常
Fetch = Callable[[str, dict[str, str], float], bytes]


class OfficialError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code


def _urlopen(url: str, headers: dict[str, str], timeout: float) -> bytes:
    req = urllib.request.Request(url, data=b"", method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class OfficialClient:
    def __init__(self, server: str, *, fetch: Fetch | None = None, interval: float = 1.0, jitter: float = 0.3,
                 retries: int = 3, backoff: float = 2.0, timeout: float = TIMEOUT,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 rng: Callable[[], float] = random.random):
        if server not in SERVERS:
            raise ValueError(f"未知服务器：{server}")
        self.info = SERVERS[server]
        self.server = server
        self._fetch = fetch or _urlopen
        self.interval, self.jitter, self.retries, self.backoff, self.timeout = interval, jitter, retries, backoff, timeout
        self._clock, self._sleep, self._rng = clock, sleep, rng
        self._lock = threading.Lock()
        self._next = 0.0
        self.requests = 0  # 实际发出的请求数（含重试）
        self.errors = 0

    # ---- 底层 ----
    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*", "Origin": self.info.origin,
             "Referer": self.info.origin + "/"}
        if self.info.json_header:
            h["Content-Type"] = "application/json;charset=UTF-8"
        return h

    def _wait_turn(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next - now
            start = max(now, self._next)
            self._next = start + self.interval + self.jitter * self._rng()
        if wait > 0:
            self._sleep(wait)

    def _unwrap(self, data: Any, name: str) -> Any:
        if not isinstance(data, dict):
            raise OfficialError(f"{name} 返回格式不对")
        if "value" in data and "code" in data:  # 海外
            if data.get("code") != 0:
                raise OfficialError(f"{name} 返回 {data.get('code')}：{data.get('message')}", code=data.get("code"))
            data = data.get("value") or {}
        code = data.get("return_code", 0)
        if code not in (0, None):
            raise OfficialError(f"{name} 返回码 {code}", code=code)
        if "result_body" not in data:
            raise OfficialError(f"{name} 没有 result_body")
        body = data["result_body"]
        if isinstance(body, dict) and body.get("return_code") not in (0, None):
            raise OfficialError(f"{name} 返回码 {body.get('return_code')}", code=body.get("return_code"))
        return body

    def call(self, name: str, **params: Any) -> Any:
        """调一个接口，返回 result_body。"""
        params = {"lang": self.info.lang, **{k: v for k, v in params.items() if v is not None}}
        url = self.info.base + name + "?" + urllib.parse.urlencode(params)
        delay = self.backoff
        for attempt in range(self.retries + 1):
            self._wait_turn()
            self.requests += 1
            try:
                raw = self._fetch(url, self._headers(), self.timeout)
            except urllib.error.HTTPError as e:
                self.errors += 1
                if e.code != 429 and e.code < 500:
                    raise OfficialError(f"{name} HTTP {e.code}", status=e.code) from None
                err: Exception = e
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                self.errors += 1
                err = e
            else:
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    self.errors += 1
                    raise OfficialError(f"{name} 返回的不是 JSON：{raw[:80]!r}") from None
                return self._unwrap(data, name)
            if attempt < self.retries:
                log.debug("%s %s 出错（%s），%.0f 秒后重试", self.server, name, err, delay)
                self._sleep(delay)
                delay *= 2
        raise OfficialError(f"{name} 重试 {self.retries} 次仍然失败：{err}",
                            status=getattr(err, "code", None))

    # ---- 接口 ----
    def seasons(self) -> list[dict]:
        """[{season_code, name, startDate, endDate, is_now_season}]，新的在前。"""
        body = self.call("getSeasonList")
        return list(body) if isinstance(body, list) else []

    def current_season(self) -> str:
        seasons = self.seasons()
        now = next((s for s in seasons if s.get("is_now_season") == 1), None) or (seasons[0] if seasons else None)
        if not now:
            raise OfficialError("取不到当前赛季")
        return now["season_code"]

    def recommend(self) -> list[dict]:
        """推荐的玩家（种子）：[{nick_no, world_code, ...}]。"""
        body = self.call("getRecommendList")
        if isinstance(body, dict):
            body = body.get("recommend_list") or []
        return [p for p in body if isinstance(p, dict) and p.get("nick_no")]

    def ranking(self, season: str, page: int = 1, world: str = "all") -> list[dict]:
        """排行榜（只有海外）：每页 10 名 [{season_rank, nick_no, world_code, season_tiercode, ...}]。"""
        if self.server != "global":
            return []
        body = self.call("getWorldUserRankingDetail", season_code=season, world_code=world, current_page=page)
        return list(body) if isinstance(body, list) else []

    def battles(self, nick_no: Any, world: str, season: str, page: int = 1) -> list[dict]:
        """一名玩家的对局（新的在前），每页 100 场。海外不能翻页（只返回最近 100 场）。"""
        params: dict[str, Any] = {"nick_no": nick_no, "world_code": world, "season_code": season}
        if self.info.pages:
            params.update(list_count=BATTLES_PER_PAGE, page_no=page)
        body = self.call("getBattleList", **params)
        return list(body.get("battle_list") or []) if isinstance(body, dict) else []

    def popular_hero(self, season: str, grade: str) -> list[dict]:
        body = self.call("getPopularHero", season_code=season, grade_code=grade)
        return list(body) if isinstance(body, list) else []

    def hero_analysis(self, hero: str, season: str, grade: str) -> dict:
        body = self.call("getHeroAnalysis", hero_code=hero, season_code=season, grade_code=grade)
        return body if isinstance(body, dict) else {}
