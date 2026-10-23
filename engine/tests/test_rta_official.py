"""B14a：官方战绩站客户端（假 fetch，不联网）。"""

import io
import json
import urllib.error
import urllib.parse

import pytest

from e7helper.core.rta.official import OfficialClient, OfficialError


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(round(s, 3))
        self.now += s


class FakeFetch:
    """按接口名返回准备好的响应；值是 bytes / dict（转 JSON）/ 异常 / 它们的列表（依次返回）。"""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, headers: dict, timeout: float) -> bytes:
        parsed = urllib.parse.urlparse(url)
        name = parsed.path.rsplit("/", 1)[-1]
        self.calls.append((name, dict(urllib.parse.parse_qsl(parsed.query)), headers))
        resp = self.routes[name]
        if isinstance(resp, list):
            resp = resp.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp if isinstance(resp, bytes) else json.dumps(resp).encode()


def client(server, routes, **kw):
    clock = FakeClock()
    fetch = FakeFetch(routes)
    c = OfficialClient(server, fetch=fetch, clock=clock, sleep=clock.sleep, rng=lambda: 0.0, **kw)
    return c, fetch, clock


def _http(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b""))


def test_cn_and_global_wrappers():
    c, fetch, _ = client("cn", {"getSeasonList": {"result_body": [
        {"season_code": "pvp_rta_ss21", "is_now_season": 1}, {"season_code": "pvp_rta_ss20", "is_now_season": 0}],
        "return_code": 0}})
    assert c.current_season() == "pvp_rta_ss21"
    name, query, headers = fetch.calls[0]
    assert name == "getSeasonList" and query == {"lang": "zh-CN"}
    assert "Content-Type" not in headers and headers["Origin"] == "https://e7.qyzlgame.com"

    g, gfetch, _ = client("global", {"getWorldUserRankingDetail": {"code": 0, "message": "SUCCESS", "value": {
        "result_body": [{"season_rank": 1, "nick_no": 5, "world_code": "world_kor"}], "total_count": 100}}})
    assert g.ranking("pvp_rta_ss21", 2) == [{"season_rank": 1, "nick_no": 5, "world_code": "world_kor"}]
    _, query, headers = gfetch.calls[0]
    assert query == {"lang": "en", "season_code": "pvp_rta_ss21", "world_code": "all", "current_page": "2"}
    assert headers["Content-Type"].startswith("application/json")


def test_battles_paging_only_on_cn():
    body = {"result_body": {"battle_list": [{"battle_seq": "1"}], "return_code": 0}, "return_code": 0}
    c, fetch, _ = client("cn", {"getBattleList": body})
    assert c.battles(11, "world_zlong1", "pvp_rta_ss21", page=3) == [{"battle_seq": "1"}]
    assert fetch.calls[0][1]["page_no"] == "3" and fetch.calls[0][1]["list_count"] == "100"
    g, gfetch, _ = client("global", {"getBattleList": {"code": 0, "value": body}})
    assert g.battles(11, "world_eu", "pvp_rta_ss21", page=3) == [{"battle_seq": "1"}]
    assert "page_no" not in gfetch.calls[0][1]


def test_recommend_both_shapes():
    c, _, _ = client("cn", {"getRecommendList": {"result_body": {"recommend_list": [
        {"nick_no": "1", "world_code": "world_zlong1"}, {"nick_no": ""}]}, "return_code": 0}})
    assert c.recommend() == [{"nick_no": "1", "world_code": "world_zlong1"}]
    g, _, _ = client("global", {"getRecommendList": {"code": 0, "value": {"result_body": [{"nick_no": 2}]}}})
    assert g.recommend() == [{"nick_no": 2}]


@pytest.mark.parametrize("resp,match", [
    ({"return_code": -10002, "result_body": None}, "返回码 -10002"),
    ({"code": 500, "message": "FAIL", "value": {}}, "返回 500"),
    ({"result_body": {"return_code": -9}, "return_code": 0}, "返回码 -9"),
    ({"return_code": 0}, "没有 result_body"),
    (b"<html>", "不是 JSON"),
])
def test_errors(resp, match):
    c, _, _ = client("cn", {"getSeasonList": resp})
    with pytest.raises(OfficialError, match=match):
        c.seasons()


def test_client_error_is_not_retried():
    c, fetch, _ = client("cn", {"getBattleList": _http(405)})
    with pytest.raises(OfficialError) as e:
        c.battles("x", "world_zlong1", "s")
    assert e.value.status == 405 and len(fetch.calls) == 1


def test_retry_with_backoff():
    ok = {"return_code": 0, "result_body": []}
    c, fetch, clock = client("cn", {"getSeasonList": [_http(503), urllib.error.URLError("reset"), ok]},
                             interval=0.0, backoff=2.0)
    assert c.seasons() == []
    assert len(fetch.calls) == 3 and clock.sleeps == [2.0, 4.0]
    assert c.requests == 3 and c.errors == 2

    c, fetch, _ = client("cn", {"getSeasonList": [_http(429)] * 3}, interval=0.0, retries=2)
    with pytest.raises(OfficialError, match="重试 2 次"):
        c.seasons()
    assert len(fetch.calls) == 3


def test_rate_limit():
    ok = {"return_code": 0, "result_body": []}
    c, _, clock = client("cn", {"getSeasonList": ok}, interval=1.0, jitter=0.0)
    for _ in range(3):
        c.seasons()
    assert clock.sleeps == [1.0, 1.0]
    clock.now += 10  # 隔了很久就不用等
    c.seasons()
    assert clock.sleeps == [1.0, 1.0]
