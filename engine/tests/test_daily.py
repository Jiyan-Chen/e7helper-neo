"""B07 日常收取：界面识别、按天记账、整个流程（用 fixtures + DailySim 离线模拟）。"""

import json
import logging
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from daily_sim import DANGER, DailySim
from game_sim import load_fixture

from e7helper.core.runtime import Humanize, Runtime, TaskStatus
from e7helper.core.scene import default_detector
from e7helper.core.vision import Vision
from e7helper.modules.base import ModuleContext
from e7helper.modules.daily import DailyConfig, DailyModule, ledger, page
from e7helper.modules.daily.ledger import Ledger, game_day


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(scope="module")
def vision():
    return Vision.for_module("daily")


@pytest.fixture(scope="module")
def detector(vision):
    det = default_detector(vision)
    ctx = ModuleContext(None, logging.getLogger("test"), Path("."), Path("."), vision=vision,
                        controller=SimpleNamespace(scenes=det))
    DailyModule(ctx)
    return det


def _frame(name, size=(1600, 900)):
    return load_fixture(name, size)


# ---------------------------------------------------------------- 场景识别


@pytest.mark.parametrize(("fixture", "scene", "popup"), [
    ("daily_lobby_ready", "lobby", None),
    ("lobby", "lobby", None),
    ("daily_sanctuary", "sanctuary", None),
    ("daily_sanctuary_night_dot", "sanctuary", None),  # 夜晚背景
    ("daily_mail_top", "daily_mail", None),
    ("daily_mail_top2", "daily_mail", None),
    ("daily_mail_scrolled", "daily_mail", None),
    ("daily_mail_open", "daily_mail", None),
    ("daily_mail_toast", "daily_mail", None),
    ("daily_mail_after_claim", "daily_mail", None),
    ("daily_mail_detail", None, "daily_mail_detail"),
    ("daily_forest_waiting", "daily_forest", None),
    ("daily_forest_ready", "daily_forest", None),
    ("daily_forest_after_claim", "daily_forest", None),
    ("daily_forest_care1", "daily_forest", None),
    ("daily_forest_popup_fadein", None, "daily_forest_reward"),
    ("daily_forest_popup", None, "daily_forest_reward"),
    ("daily_summon_main", "daily_summon", None),
    ("daily_summon_main_free", "daily_summon", None),
    ("daily_covenant_used", "daily_covenant", None),
    ("daily_covenant_free", "daily_covenant", None),
    ("daily_covenant_free11", "daily_covenant", None),
    ("daily_covenant_free1", "daily_covenant", None),
    ("daily_covenant_done", "daily_covenant", None),
    ("daily_summon_book", None, None),
    ("daily_summon_skip", "daily_summon_anim", None),
    ("daily_summon_hero", "daily_summon_hero", None),
    ("daily_summon_results_anim", "daily_summon_results", None),
    ("daily_summon_results", "daily_summon_results", None),
    ("daily_summon_result_single", "daily_summon_results", None),  # 单抽结果：只有「返回」
])
@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_scenes(detector, fixture, scene, popup, size):
    state = detector.detect(_frame(fixture, size))
    assert state.popup == popup, state
    if popup is None:
        assert state.scene == scene, state


@pytest.mark.parametrize("fixture", ["arena_defense_record", "rb_auto_settled"])
def test_other_click_to_close_popups_are_not_forest(detector, fixture):
    """「点击关闭」在别的弹窗里也有：精灵之森奖励框要求背景是精灵之森。"""
    assert detector.detect(_frame(fixture)).popup != "daily_forest_reward"


# ---------------------------------------------------------------- 邮件


@pytest.mark.parametrize(("text", "hours"), [
    ("剩余6天", 144), ("剩余1天", 24), ("剩余23小时", 23), ("剩余 5 小时", 5), ("剩余30分", 0.5),
    ("剩余1小时30分", 1.5), ("剩余45秒", 45 / 3600), ("无限制", math.inf), ("", None), ("剩余", None),
])
def test_parse_remaining(text, hours):
    got = page.parse_remaining(text)
    assert got == pytest.approx(hours) if hours is not None else got is None


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
@pytest.mark.parametrize(("fixture", "count", "texts"), [
    ("daily_mail_top", 9, ["剩余6天", "剩余6天", "无限制", "无限制"]),
    ("daily_mail_scrolled", 9, ["无限制"] * 4),
    ("daily_mail_top2", 11, ["剩余6天", "剩余6天", "剩余6天", "无限制"]),
    ("daily_mail_toast", 10, ["剩余6天", "剩余6天", "无限制", "无限制"]),  # 物品提示还在
    ("daily_mail_after_claim", 10, ["剩余6天", "剩余6天", "无限制", "无限制"]),
])
def test_scan_mail(vision, fixture, count, texts, size):
    frame = _frame(fixture, size)
    assert page.read_mail_count(vision, frame) == count
    rows = page.scan_mail(vision, frame)
    assert [r.text for r in rows] == texts
    assert [r.y for r in rows] == sorted(r.y for r in rows)


def test_scan_mail_none_elsewhere(vision):
    assert page.scan_mail(vision, _frame("daily_lobby_ready")) == []


# ---------------------------------------------------------------- 精灵之森


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_read_forest(vision, size):
    f = page.read_forest(vision, _frame("daily_forest_ready", size))
    assert [(c.ready, c.seconds) for c in f.cards] == [(True, None), (True, None), (False, 149 * 3600 + 5 * 60 + 6)]
    assert (f.care.done, f.care.total, f.care.seconds, f.care.available) == (0, 3, 5 * 3600 + 5 * 60 + 6, False)
    assert f.next_seconds() == 0

    f = page.read_forest(vision, _frame("daily_forest_after_claim", size))
    assert [c.ready for c in f.cards] == [False, True, False]
    assert f.cards[0].seconds == 10 * 3600 + 11 * 60 + 52

    f = page.read_forest(vision, _frame("daily_forest_waiting", size))
    assert not f.ready and f.care is None  # 魔罗戈拉休息期没有照料
    assert f.next_seconds() == 8 * 3600 + 41 * 60 + 54


def test_read_forest_care_once(vision):
    """照料过一次（1/3）后：照料行显示下次的倒计时。"""
    f = page.read_forest(vision, _frame("daily_forest_care1"))
    assert [c.ready for c in f.cards] == [True, False, False]
    assert f.cards[1].seconds == 6 * 3600 + 8 * 60 + 2
    assert (f.care.done, f.care.total, f.care.seconds, f.care.available) == (1, 3, 13 * 3600 + 53 * 60 + 16, False)


@pytest.mark.parametrize(("text", "seconds"), [("08:41:54", 31314), ("149:05:06", 536706), ("(休息期)", None)])
def test_parse_timer(text, seconds):
    assert page.parse_timer(text) == seconds


def test_care_available_and_next():
    m = SimpleNamespace()
    assert page.Care(0, 3, None, m).available
    assert not page.Care(0, 3, 100, m).available
    assert not page.Care(3, 3, None, m).available
    cards = [page.Card("a", None, False, 500), page.Card("b", None, False, 300)]
    assert page.Forest(cards, page.Care(1, 3, 200, m)).next_seconds() == 200
    assert page.Forest(cards, page.Care(3, 3, 100, m)).next_seconds() == 300  # 照料满了不算
    assert page.Forest(cards, page.Care(0, 3, None, m)).next_seconds() == 0


# ---------------------------------------------------------------- 誓约召唤


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
@pytest.mark.parametrize(("fixture", "free1", "free10", "left"), [
    ("daily_covenant_free", True, True, (21, 21)),
    ("daily_covenant_free11", True, True, (11, 21)),
    ("daily_covenant_free1", True, False, (1, 21)),  # 只剩单抽：气泡移到「1次召唤」上方，十连要 50 书签
    ("daily_covenant_11_sparkle", True, True, (11, 21)),
    ("daily_covenant_1_sparkle", True, False, (1, 21)),
    ("daily_covenant_used", False, False, None),
    ("daily_covenant_done", False, False, None),  # 当天免费用完
    ("daily_summon_main", False, False, None),  # 限时池
    ("daily_summon_main_free", False, False, None),
    ("daily_summon_results", False, False, None),  # 结果页的「免费 再召唤一次」不算
])
def test_read_covenant(vision, fixture, free1, free10, left, size):
    c = page.read_covenant(vision, _frame(fixture, size))
    assert (c.free_1 is not None, c.free_10 is not None, c.left) == (free1, free10, left)


def test_currency_sparkle_ignored():
    """誓约页背景的星星光效会飘进顶栏区域（单帧几十个像素）：前后各两帧、两两都变才算（10-18 实跑误报过 80 个像素）。"""
    p = lambda n: page.currency_patch(_frame(n))  # noqa: E731
    before = [p("daily_covenant_11_a"), p("daily_covenant_11_sparkle")]
    after = [p("daily_covenant_1_a"), p("daily_covenant_1_sparkle")]
    assert page.changed_pixels(before[1], after[1]) > 0  # 单帧比较有光效
    assert page.changed_pixels_all(before, after) == 0
    real = [p("daily_covenant_used"), p("daily_covenant_used")]  # 数字真的不一样
    assert page.changed_pixels_all(before, real) > page.CURRENCY_CHANGED_PIXELS * 10


def test_covenant_prefers_ten(vision):
    c = page.read_covenant(vision, _frame("daily_covenant_free"))
    assert c.free is c.free_10


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
def test_currency_patch(size):
    a = page.currency_patch(_frame("daily_covenant_free", size))
    assert a.shape[:2] == (page.TOP_CURRENCY.h, page.TOP_CURRENCY.w)
    assert page.changed_pixels(a, page.currency_patch(_frame("daily_covenant_free11", size))) <= 5  # 召唤前后
    one = page.currency_patch(_frame("daily_covenant_free1", size))  # 实跑：最后一次免费单抽前后
    assert page.changed_pixels(one, page.currency_patch(_frame("daily_covenant_done", size))) <= 5
    assert page.changed_pixels(a, page.currency_patch(_frame("daily_covenant_used", size))) \
        > page.CURRENCY_CHANGED_PIXELS * 10


# ---------------------------------------------------------------- 账本


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


def test_game_day_resets_at_beijing_3am():
    assert game_day(_utc(2026, 10, 16, 18, 59)).isoformat() == "2026-10-16"  # 北京 10-17 02:59
    assert game_day(_utc(2026, 10, 16, 19, 0)).isoformat() == "2026-10-17"  # 北京 10-17 03:00
    assert game_day(_utc(2026, 10, 17, 14, 0)).isoformat() == "2026-10-17"  # 北京 10-17 22:00
    local = datetime(2026, 10, 17, 2, 59, tzinfo=UTC).astimezone()  # 与本机时区无关
    assert game_day(local) == game_day(datetime(2026, 10, 17, 2, 59, tzinfo=UTC))


def test_ledger_done_resets_next_day(tmp_path):
    now = [_utc(2026, 10, 17, 10, 0)]
    lg = Ledger.open(tmp_path, clock=lambda: now[0])
    lg.mark_done("covenant", summons=21)
    lg.set_forest_next(3600)
    assert Ledger.open(tmp_path, clock=lambda: now[0]).is_done("covenant")
    now[0] = _utc(2026, 10, 17, 18, 59)
    again = Ledger.open(tmp_path, clock=lambda: now[0])
    assert again.is_done("covenant") and again.forest_due()  # 同一游戏日；精灵之森的时间已经过了
    now[0] = _utc(2026, 10, 17, 19, 0)
    nxt = Ledger.open(tmp_path, clock=lambda: now[0])
    assert not nxt.is_done("covenant") and nxt.day == "2026-10-18"


def test_ledger_forest_due(tmp_path):
    now = [_utc(2026, 10, 17, 10, 0)]
    lg = Ledger.open(tmp_path, clock=lambda: now[0])
    assert lg.forest_due()
    lg.set_forest_next(600)
    now[0] += timedelta(seconds=599)
    assert not Ledger.open(tmp_path, clock=lambda: now[0]).forest_due()
    now[0] += timedelta(seconds=1)
    assert Ledger.open(tmp_path, clock=lambda: now[0]).forest_due()
    lg.set_forest_next(None)
    assert Ledger.open(tmp_path, clock=lambda: now[0]).forest_due()


def test_ledger_corrupt_file(tmp_path):
    (tmp_path / "ledger.json").write_text("{oops", encoding="utf-8")
    assert not Ledger.open(tmp_path).is_done("covenant")


def test_config_schema_only_switches():
    assert set(DailyConfig.model_json_schema()["properties"]) == {"mail", "forest", "covenant", "shop", "shop_items",
                                                                  "arena", "arena_buy_flags", "dry_run"}
    cfg = DailyConfig()
    assert cfg.dry_run and cfg.arena and not cfg.arena_buy_flags and cfg.arena_prefer_quick
    assert DailyConfig(arena_max_battles=2).arena_max_battles == 2  # 内部字段仍然可以传


# ---------------------------------------------------------------- 流程


def _run(sim, tmp_path, *, timeout=300, **cfg):
    """DailySim 不模拟竞技场和商店：这两项默认关掉（流程测试在 test_daily_arena.py / test_daily_shop.py）。"""
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off(), debug_root=tmp_path / "debug",
                 seed=1) as rt:
        return rt.run_task(DailyModule, DailyConfig(**{"arena": False, "shop": False, **cfg}), timeout=timeout)


def _data(tmp_path):
    return tmp_path / "data" / "modules" / "daily"


def _history(tmp_path):
    path = _data(tmp_path) / "history.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _ledger(tmp_path):
    return json.loads((_data(tmp_path) / "ledger.json").read_text(encoding="utf-8"))


def _totals(tmp_path):
    path = _data(tmp_path) / "stats.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _assert_safe(sim):
    assert DANGER not in sim.history


def test_dry_run_all_from_lobby(tmp_path):
    """dry-run（默认）：三项都进去看、都回到大厅，不点领取 / 召唤；不写「做完」。"""
    sim = DailySim()
    result = _run(sim, tmp_path)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert (sim.mail_claims, sim.forest_claims, sim.summons) == (0, [], 0)
    assert sim.screen == "daily_lobby_ready"
    run = _history(tmp_path)[-1]
    assert run["dry_run"] and run["would"] == ["领取企鹅巢穴", "领取精灵之泉", "免费召唤 10 次（剩余免费 21/21）"]
    assert "24 小时" in run["items"]["mail"]
    assert _totals(tmp_path) is None
    lg = _ledger(tmp_path) if (_data(tmp_path) / "ledger.json").exists() else {"done": {}, "forest_next": None}
    assert lg["done"] == {} and lg["forest_next"] is None  # dry-run 看到可领的，不推迟下次


def test_real_run_all(tmp_path):
    """实跑：放宽邮件阈值领 1 封；精灵之森两张都领；誓约免费十连 1 次。"""
    sim = DailySim()
    result = _run(sim, tmp_path, dry_run=False, mail_max_hours=168, mail_max_claims=1, covenant_max=10)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert (sim.mail_claims, sim.forest_claims, sim.summons) == (1, ["penguin", "well"], 1)
    run = _history(tmp_path)[-1]
    assert [m["count_after"] for m in run["mails"]] == [10]
    assert run["forest_claims"] == ["企鹅巢穴", "精灵之泉"]
    assert [(s["times"], s["left_after"]) for s in run["summons"]] == [(10, 11)]
    totals = _totals(tmp_path)
    assert {k: totals[k] for k in ("runs", "mails", "forest_claims", "cares", "summons", "battles")} == {
        "runs": 1, "mails": 1, "forest_claims": 2, "cares": 0, "summons": 10, "battles": 0}
    # 领完后精灵之森都在倒计时：按最短的倒计时记下次时间（企鹅巢穴 8:41:54）
    nxt = datetime.fromisoformat(_ledger(tmp_path)["forest_next"])
    assert timedelta(hours=8, minutes=40) < nxt - datetime.now(UTC) < timedelta(hours=8, minutes=43)
    assert sim.screen == "daily_lobby_ready"


def test_mail_default_threshold_claims_nothing(tmp_path):
    sim = DailySim()
    result = _run(sim, tmp_path, dry_run=False, forest=False, covenant=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.mail_claims == 0 and len(sim.taps) == 2  # 只点了邮件图标和返回


def test_mail_claims_until_none_left(tmp_path):
    """阈值 168 小时、不限封数：领完链上的一封后，再点没反应（模拟器链走完）→ 连续失败 3 次放弃这一项。"""
    sim = DailySim()
    result = _run(sim, tmp_path, dry_run=False, forest=False, covenant=False, mail_max_hours=168)
    assert result.status is TaskStatus.FAILED
    _assert_safe(sim)
    run = _history(tmp_path)[-1]
    assert len(run["mails"]) == 1 and run["failures"] == 3 and "连续失败 3 次" in run["items"]["mail"]


def test_read_mail_detail(vision):
    assert page.read_mail_detail_remaining(vision, _frame("daily_mail_detail")) == "剩余6天"


def test_mail_detail_receive(tmp_path):
    """有些邮件点领取后弹出详情框：核对剩余时间一致后点「收信」，按邮件数核对。"""
    sim = DailySim(mail_detail=True)
    result = _run(sim, tmp_path, dry_run=False, forest=False, covenant=False, mail_max_hours=168, mail_max_claims=1)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.mail_claims == 1 and sim.detail_closes == 0
    assert [m["count_after"] for m in _history(tmp_path)[-1]["mails"]] == [10]
    _assert_safe(sim)


def test_mail_detail_mismatch_closes(tmp_path, monkeypatch):
    """详情框里的剩余时间和那一行不一致：点关闭，不收信，这一项失败。"""
    import e7helper.modules.daily as daily

    monkeypatch.setattr(daily.page, "read_mail_detail_remaining", lambda vision, frame: "剩余1天")
    sim = DailySim(mail_detail=True)
    result = _run(sim, tmp_path, dry_run=False, forest=False, covenant=False, mail_max_hours=168)
    assert result.status is TaskStatus.FAILED
    assert sim.mail_claims == 0 and sim.detail_closes == 1
    assert "不收信" in _history(tmp_path)[-1]["items"]["mail"]
    assert sim.screen == "daily_lobby_ready"


def test_mail_tap_eaten(tmp_path):
    sim = DailySim(mail="eat")
    result = _run(sim, tmp_path, dry_run=False, forest=False, covenant=False, mail_max_hours=168)
    assert result.status is TaskStatus.FAILED
    assert sim.mail_claims == 0 and _history(tmp_path)[-1]["mails"] == []


def test_mail_unsorted_does_not_claim(tmp_path, monkeypatch):
    sim = DailySim()
    orig = DailyModule.ctl

    class NoSort:
        def __init__(self, ctl):
            self._ctl = ctl

        def __getattr__(self, name):
            return getattr(self._ctl, name)

        def exists(self, ref, *a, **kw):
            return False if ref == "mail/sort_remain" else self._ctl.exists(ref, *a, **kw)

    monkeypatch.setattr(DailyModule, "ctl", property(lambda self: NoSort(orig.fget(self))))
    result = _run(sim, tmp_path, dry_run=False, forest=False, covenant=False, mail_max_hours=168)
    assert result.status is TaskStatus.FAILED
    assert sim.mail_claims == 0 and "排序" in _history(tmp_path)[-1]["items"]["mail"]


def test_forest_waiting_records_next_and_skips(tmp_path):
    """都在倒计时：记下次时间；下次运行没到时间就不进精灵之森。"""
    sim = DailySim(forest="waiting")
    assert _run(sim, tmp_path, dry_run=False, mail=False, covenant=False).status is TaskStatus.SUCCEEDED
    assert _ledger(tmp_path)["forest_next"] is not None
    sim2 = DailySim(forest="ready")
    assert _run(sim2, tmp_path, dry_run=False, mail=False, covenant=False).status is TaskStatus.SUCCEEDED
    assert sim2.forest_claims == [] and "daily_sanctuary_night_dot" not in sim2.history
    assert "还没到时间" in _history(tmp_path)[-1]["items"]["forest"]
    sim3 = DailySim(forest="ready")  # force 忽略账本
    assert _run(sim3, tmp_path, dry_run=False, mail=False, covenant=False, force=True).status is TaskStatus.SUCCEEDED
    assert sim3.forest_claims == ["penguin", "well"]


def test_forest_claim_eaten(tmp_path):
    sim = DailySim(forest_claim="eat")
    result = _run(sim, tmp_path, dry_run=False, mail=False, covenant=False)
    assert result.status is TaskStatus.FAILED
    assert "奖励框没出现" in _history(tmp_path)[-1]["items"]["forest"]
    assert sim.screen == "daily_lobby_ready"


def _care_only(monkeypatch, sim, *, count_up=False):
    """只看照料：卡片一律当作不可领（模拟器的「可照料」是把倒计时涂掉做出来的）。

    count_up=True 时照料后把次数换成点击次数（模拟器画不出新的次数）。
    """
    import e7helper.modules.daily as daily

    orig = page.read_forest

    def read_forest(vision, frame):
        f = orig(vision, frame)
        for c in f.cards:
            c.ready, c.seconds = False, c.seconds or 3600
        if count_up and f.care is not None and sim.care_taps:
            f.care = page.Care(sim.care_taps, 3, 3600, f.care.button)
        return f

    monkeypatch.setattr(daily.page, "read_forest", read_forest)


def test_forest_care_dry_run(tmp_path, monkeypatch):
    sim = DailySim(forest="after", care_ready=True)
    _care_only(monkeypatch, sim)
    assert _run(sim, tmp_path, mail=False, covenant=False).status is TaskStatus.SUCCEEDED
    assert sim.care_taps == 0
    assert _history(tmp_path)[-1]["would"] == ["照料魔罗戈拉（0/3）"]


def test_forest_care_count_unchanged(tmp_path, monkeypatch):
    """点了照料、次数没变 → 这一项失败（不重复点）。"""
    sim = DailySim(forest="after", care_ready=True)
    _care_only(monkeypatch, sim)
    result = _run(sim, tmp_path, dry_run=False, mail=False, covenant=False)
    assert result.status is TaskStatus.FAILED
    assert sim.care_taps == 1 and "照料" in _history(tmp_path)[-1]["items"]["forest"]


def test_forest_care_success(tmp_path, monkeypatch):
    sim = DailySim(forest="after", care_ready=True)
    _care_only(monkeypatch, sim, count_up=True)
    result = _run(sim, tmp_path, dry_run=False, mail=False, covenant=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.care_taps == 1 and _history(tmp_path)[-1]["cares"] == 1


def test_forest_care_not_ready_not_tapped(tmp_path, monkeypatch):
    sim = DailySim(forest="after")  # 照料在倒计时
    _care_only(monkeypatch, sim)
    assert _run(sim, tmp_path, dry_run=False, mail=False, covenant=False).status is TaskStatus.SUCCEEDED
    assert sim.care_taps == 0


def test_covenant_uses_all_free(tmp_path):
    """方案 A：21 次免费 = 十连 → 十连 → 单抽（只剩单抽时十连按钮不免费，点了是 DANGER），然后记为当天做完。"""
    sim = DailySim()
    result = _run(sim, tmp_path, dry_run=False, mail=False, forest=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_safe(sim)
    assert sim.summon_times == [10, 10, 1]
    run = _history(tmp_path)[-1]
    assert [(s["times"], s["left_after"]) for s in run["summons"]] == [(10, 11), (10, 1), (1, None)]
    assert _ledger(tmp_path)["done"]["covenant"]["summons"] == 21
    assert _totals(tmp_path)["summons"] == 21
    assert sim.screen == "daily_lobby_ready"


def test_covenant_used_marks_done_and_skips(tmp_path):
    sim = DailySim(covenant=("daily_covenant_used",))
    assert _run(sim, tmp_path, dry_run=False, mail=False, forest=False).status is TaskStatus.SUCCEEDED
    _assert_safe(sim)
    assert sim.summons == 0 and "covenant" in _ledger(tmp_path)["done"]
    sim2 = DailySim()
    assert _run(sim2, tmp_path, dry_run=False, mail=False, forest=False).status is TaskStatus.SUCCEEDED
    assert sim2.summons == 0 and "daily_summon_main_free" not in sim2.history
    assert "账本" in _history(tmp_path)[-1]["items"]["covenant"]


def test_covenant_dry_run_does_not_mark_done(tmp_path):
    sim = DailySim(covenant=("daily_covenant_used",))
    _run(sim, tmp_path, mail=False, forest=False)
    path = _data(tmp_path) / "ledger.json"
    assert not path.exists() or _ledger(tmp_path)["done"] == {}


def test_covenant_currency_changed_is_anomaly(tmp_path):
    """召唤后顶栏货币变了（回来是 used 页）：立即停止，任务失败。"""
    sim = DailySim(covenant=("daily_covenant_free", "daily_covenant_used"))
    result = _run(sim, tmp_path, dry_run=False, mail=False, forest=False)
    assert result.status is TaskStatus.FAILED and "DailyAnomaly" in result.error
    assert sim.summons == 1
    _assert_safe(sim)


def test_covenant_left_mismatch_is_anomaly(tmp_path):
    """剩余免费次数没有减少（21 → 21）：立即停止。"""
    sim = DailySim(covenant=("daily_covenant_free", "daily_covenant_free"))
    result = _run(sim, tmp_path, dry_run=False, mail=False, forest=False)
    assert result.status is TaskStatus.FAILED and "免费次数" in result.error
    assert sim.summons == 1


def test_covenant_tap_eaten(tmp_path):
    sim = DailySim(summon="eat")
    result = _run(sim, tmp_path, dry_run=False, mail=False, forest=False)
    assert result.status is TaskStatus.FAILED
    assert sim.summons == 0 and _history(tmp_path)[-1]["failures"] == 3
    _assert_safe(sim)


def test_anomaly_stops_remaining_items(tmp_path):
    """誓约召唤出异常时整个任务停止（排在最后）；前面的项照常完成。"""
    sim = DailySim(covenant=("daily_covenant_free", "daily_covenant_used"))
    result = _run(sim, tmp_path, dry_run=False, mail_max_hours=168, mail_max_claims=1)
    assert result.status is TaskStatus.FAILED
    assert sim.mail_claims == 1 and sim.forest_claims == ["penguin", "well"]


@pytest.mark.parametrize("start", ["daily_forest_ready", "daily_mail_top2", "daily_summon_results",
                                   "daily_summon_skip", "daily_covenant_free11", "daily_sanctuary_night_dot"])
def test_start_anywhere_returns_to_lobby(tmp_path, start):
    """先回到大厅再做（这里只开邮件的 dry-run）。"""
    sim = DailySim(start, covenant=("daily_covenant_free11",))
    result = _run(sim, tmp_path, forest=False, covenant=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.screen == "daily_lobby_ready"
    _assert_safe(sim)


def test_real_run_720p(tmp_path):
    sim = DailySim(size=(1280, 720))
    result = _run(sim, tmp_path, dry_run=False, mail_max_hours=168, mail_max_claims=1, covenant_max=10)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert (sim.mail_claims, sim.forest_claims, sim.summons) == (1, ["penguin", "well"], 1)
    _assert_safe(sim)


def test_utcnow_used_for_ledger(tmp_path, monkeypatch):
    """模块用 ledger.utcnow 计时（测试可以替换）：换到下一个游戏日后誓约召唤会重新进去看。"""
    now = [datetime(2026, 10, 17, 10, 0, tzinfo=UTC)]
    monkeypatch.setattr(ledger, "utcnow", lambda: now[0])
    _run(DailySim(covenant=("daily_covenant_used",)), tmp_path, dry_run=False, mail=False, forest=False)
    now[0] = datetime(2026, 10, 17, 19, 1, tzinfo=UTC)
    sim = DailySim(covenant=("daily_covenant_used",))
    _run(sim, tmp_path, dry_run=False, mail=False, forest=False)
    assert "daily_covenant_used" in sim.history
