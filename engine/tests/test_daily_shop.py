"""B12b 日常收取 · 商店日常购买：界面识别（fixtures）、按周记账、整个流程（ShopSim 离线模拟）。"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from daily_shop_sim import DANGER, ShopSim, SimCard, default_pages
from game_sim import load_fixture

from e7helper.core.runtime import Humanize, Runtime, TaskStatus
from e7helper.core.runtime import controller as controller_mod
from e7helper.core.scene import default_detector
from e7helper.core.vision import Vision
from e7helper.modules.base import ModuleContext
from e7helper.modules.daily import DailyConfig, DailyModule, shop, shop_page
from e7helper.modules.daily.config import ShopItem
from e7helper.modules.daily.ledger import Ledger, game_week, next_week_reset
from e7helper.modules.daily.shop_page import Card, Currency, Layout


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


# ---------------------------------------------------------------- 场景 / 弹窗

@pytest.mark.parametrize(("fixture", "scene", "popup"), [
    ("daily_shop_featured", "shop", None),
    ("daily_shop_general", shop.STORE, None),
    ("daily_shop_general_bought", shop.STORE, None),
    ("daily_shop_legacy", shop.STORE, None),
    ("daily_shop_legacy_end", shop.STORE, None),
    ("daily_shop_exchange", shop.EXCHANGE, None),
    ("daily_shop_dlg_core", None, shop.POPUP_BUY),
    ("daily_shop_dlg_legacy_1of2", None, shop.POPUP_BUY),
    ("daily_shop_dlg_arena", None, shop.POPUP_BUY),
    ("daily_shop_dlg_free", None, shop.POPUP_BUY1),
    ("daily_shop_dlg_energy", None, shop.POPUP_BUY1),
    ("daily_shop_dlg_box", None, shop.POPUP_BUY1),
    ("daily_shop_reward", None, shop.POPUP_REWARD),
    ("daily_shop_reward_fx", None, shop.POPUP_REWARD),
])
def test_scenes(detector, fixture, scene, popup):
    state = detector.detect(load_fixture(fixture))
    assert state.popup == popup
    if scene is not None:
        assert state.is_(scene), state


def test_lobby_is_not_shop(detector):
    state = detector.detect(load_fixture("daily_lobby_ready"))
    assert state.is_("lobby")


# ---------------------------------------------------------------- 卡片

def _cards(vision, fixture):
    return {(c.name, c.currency): c for c in shop_page.scan_cards(vision, load_fixture(fixture))}


def test_scan_general(vision):
    cards = shop_page.scan_cards(vision, load_fixture("daily_shop_general"))
    names = [c.name for c in cards]
    # 第 5 列被截掉（下级神器强化石、混沌票券）不算
    assert names == ["普琳每日免费商品", "光谱核心", "80点行动力", "老练企鹅",
                     "40点行动力", "光谱核心", "5面旗帜", "亲密度献礼选择箱"]
    by = {(c.name, c.currency): c for c in cards}
    free = by["普琳每日免费商品", Currency.FREE]
    assert free.counter == (1, 1) and free.buyable and free.price == 0 and "每日" in free.label
    core = by["光谱核心", Currency.ENERGY]
    assert core.counter == (3, 3) and core.price == 160
    leaf_core = by["光谱核心", None]  # 用生命之叶买的那张：没有次数、价格图标认不出
    assert leaf_core.counter is None and leaf_core.buyable
    assert by["40点行动力", Currency.FRIENDSHIP].price == 100
    box = by["亲密度献礼选择箱", Currency.FRIENDSHIP]
    assert box.counter == (5, 10) and box.price == 6400 and "每周" in box.label


def test_scan_general_after_free_bought(vision):
    """买了普琳的免费商品后：它移到最后（被截掉的第 5 列），其他卡片往前挪。"""
    cards = shop_page.scan_cards(vision, load_fixture("daily_shop_general_bought"))
    assert [c.name for c in cards][:4] == ["40点行动力", "光谱核心", "5面旗帜", "亲密度献礼选择箱"]
    assert all(c.name != "普琳每日免费商品" for c in cards)


def test_scan_legacy(vision):
    mid = _cards(vision, "daily_shop_legacy_mid")
    for name, price, counter in (("上级精灵之花", 3, (1, 1)), ("装备炼制石选择箱", 15, (1, 1)),
                                 ("上级神器强化石", 9, (1, 1)), ("潜能开发碎片", 12, (2, 2)),
                                 ("下级神器强化石", 3, (3, 3)), ("2个下级饰品强化石", 5, (3, 3))):
        c = mid[name, Currency.CRYSTAL]
        assert (c.price, c.counter, c.buyable) == (price, counter, True), c
    start = _cards(vision, "daily_shop_legacy")
    assert start["魔罗戈拉", Currency.CRYSTAL].counter == (2, 2)
    # 账号限定（传承石买的）价格图标认不出
    assert start["残梦碎片", None].counter == (1, 5)


def test_scan_legacy_end_sold(vision):
    cards = {c.name: c for c in shop_page.scan_cards(vision, load_fixture("daily_shop_legacy_end"))}
    assert cards["2个上级饰品强化石"].buyable and cards["2个上级饰品强化石"].price == 15
    for name in ("逝神的思绪", "神启野心", "理智的钥匙", "灿烂荣耀"):
        assert not cards[name].buyable and cards[name].counter == (0, 5)
    assert cards["老练企鹅"].counter is None  # 不限购


def test_scan_exchange(vision):
    cards = _cards(vision, "daily_shop_exchange")
    energy = cards["40点行动力", Currency.ARENA]
    assert energy.counter == (3, 3) and energy.price == 30 and "每日" in energy.label


@pytest.mark.parametrize(("text", "frac"), [
    ("3/3", (3, 3)), ("1/1", (1, 1)), ("11", (1, 1)), ("5/10", (5, 10)), ("510", (5, 10)), ("0/5", (0, 5)),
    ("", None), ("V", None), ("31", None), ("1/", None),
])
def test_parse_counter(text, frac):
    assert shop_page.parse_counter(text) == frac


@pytest.mark.parametrize(("fixture", "tab", "selected"), [
    ("daily_shop_general", "shop/tab_general", True),
    ("daily_shop_general", "shop/tab_legacy", False),
    ("daily_shop_legacy", "shop/tab_legacy", True),
    ("daily_shop_legacy", "shop/tab_general", False),
    ("daily_shop_exchange", "shop/tab_arena", True),
    ("daily_shop_exchange", "shop/tab_general", None),
])
def test_tab_selected(vision, fixture, tab, selected):
    assert shop_page.tab_selected(vision, load_fixture(fixture), tab) is selected


# ---------------------------------------------------------------- 购买框 / 获得奖励 / 顶栏

@pytest.mark.parametrize(("fixture", "layout", "name", "remaining", "qty", "currency", "price"), [
    ("daily_shop_dlg_core", Layout.QTY, "光谱核心", 3, (1, 1), Currency.ENERGY, 160),
    ("daily_shop_dlg_legacy_1of2", Layout.QTY, "魔罗戈拉", 2, (1, 2), Currency.CRYSTAL, 15),
    ("daily_shop_dlg_legacy_2of2", Layout.QTY, "魔罗戈拉", 2, (2, 2), Currency.CRYSTAL, 30),
    ("daily_shop_dlg_arena", Layout.QTY, "40点行动力", 3, (3, 3), Currency.ARENA, 90),
    ("daily_shop_dlg_free", Layout.SINGLE, "普琳每日免费商品", 1, None, Currency.FREE, 0),
    ("daily_shop_dlg_energy", Layout.SINGLE, "40点行动力", 1, None, Currency.FRIENDSHIP, 100),
    ("daily_shop_dlg_box", Layout.RISING, "亲密度献礼选择箱", 5, None, Currency.FRIENDSHIP, 6400),
])
def test_read_dialog(vision, fixture, layout, name, remaining, qty, currency, price):
    d = shop_page.read_dialog(vision, load_fixture(fixture))
    assert d is not None
    assert (d.layout, d.name, d.remaining, d.qty, d.currency, d.price) == (layout, name, remaining, qty, currency, price)
    assert (d.max_btn is not None) is (layout is Layout.QTY)


@pytest.mark.parametrize("fixture", ["daily_shop_general", "daily_shop_reward", "daily_lobby_ready",
                                     "arena_buy_flags"])
def test_read_dialog_none_elsewhere(vision, fixture):
    assert shop_page.read_dialog(vision, load_fixture(fixture)) is None


def test_read_dialog_secret_shop_is_gold(vision):
    """秘密商店的购买框也是同一种「购买商品」框（金币价格）：认得出框，但价格货币认不出，核对时不会买。"""
    d = shop_page.read_dialog(vision, load_fixture("secret_shop_buy_confirm"))
    assert d is not None and d.currency is None


def test_is_reward(vision):
    assert shop_page.is_reward(vision, load_fixture("daily_shop_reward"))
    assert shop_page.is_reward(vision, load_fixture("daily_shop_reward_fx"))
    assert not shop_page.is_reward(vision, load_fixture("daily_shop_general"))


@pytest.mark.parametrize(("fixture", "skystone", "values"), [
    ("daily_shop_general", 15871, {Currency.FRIENDSHIP: 185_729, Currency.ENERGY: 209}),
    ("daily_shop_general_bought", 15871, {Currency.FRIENDSHIP: 185_729, Currency.ENERGY: 256}),
    ("daily_shop_legacy", 15871, {Currency.CRYSTAL: 5727}),
    ("daily_shop_exchange", 15871, {Currency.ARENA: 998}),
    ("daily_shop_dlg_core", 15871, {Currency.FRIENDSHIP: 185_729, Currency.ENERGY: 210}),
])
def test_read_top(vision, fixture, skystone, values):
    top = shop_page.read_top(vision, load_fixture(fixture))
    assert top.skystone == skystone and top.values == values


# ---------------------------------------------------------------- 认卡片

def _card(name, currency, counter, buyable=True, price=1):
    return Card(name, 600, 203, counter, "每日购买", buyable, currency if buyable else None, price)


def test_find_core_by_currency_and_limit():
    spec = shop.CATALOG[ShopItem.CORE]
    leaf = _card("光谱核心", None, None)
    energy = _card("光谱核心", Currency.ENERGY, (3, 3), price=160)
    assert shop._find([leaf, energy], spec) is energy
    sold = _card("光谱核心", Currency.ENERGY, (0, 3), buyable=False)
    assert shop._find([leaf, sold], spec) is sold
    assert shop._find([leaf], spec) is None
    # 买完的卡片次数读不出：光谱核心不认（可能是生命之叶那张），其他商品认
    grey = _card("光谱核心", None, None, buyable=False)
    assert shop._find([grey], spec) is None
    assert shop._find([_card("下级神器强化石", None, None, buyable=False)],
                      shop.CATALOG[ShopItem.ARTIFACT_LOW_GENERAL]) is not None
    # 次数读不出：能买、价格图标对就认
    unknown = _card("光谱核心", Currency.ENERGY, None, price=160)
    assert shop._find([leaf, unknown], spec) is unknown


def test_find_same_name_other_limit():
    """「下级神器强化石」一般页和传承石页都有；交易所的「40点行动力」限购 3、一般页的限购 1。"""
    spec = shop.CATALOG[ShopItem.ENERGY]
    assert shop._find([_card("40点行动力", Currency.ARENA, (3, 3), price=30)], spec) is None
    assert shop._find([_card("40点行动力", Currency.FRIENDSHIP, (1, 1), price=100)], spec) is not None


def test_catalog_matches_config():
    assert set(shop.CATALOG) == set(ShopItem)
    assert DailyConfig().shop_items == list(ShopItem)
    assert DailyConfig().shop is True


# ---------------------------------------------------------------- 按周记账

def test_game_week_and_reset():
    tue = datetime(2026, 10, 20, 6, 50, tzinfo=UTC)  # 北京时间周二 14:50
    assert game_week(tue).isoformat() == "2026-10-19"
    assert next_week_reset(tue) == datetime(2026, 10, 25, 19, 0, tzinfo=UTC)  # 北京时间周一 03:00
    assert game_week(datetime(2026, 10, 25, 18, 59, tzinfo=UTC)).isoformat() == "2026-10-19"
    assert game_week(datetime(2026, 10, 25, 19, 0, tzinfo=UTC)).isoformat() == "2026-10-26"


def test_ledger_week_done_resets_next_week(tmp_path):
    now = [datetime(2026, 10, 20, 6, 0, tzinfo=UTC)]
    lg = Ledger(tmp_path / "ledger.json", clock=lambda: now[0])
    lg.mark_week_done("shop:molagora")
    lg.mark_done("shop:free")
    now[0] = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)  # 第二天：每日的清空，每周的还在
    lg2 = Ledger(tmp_path / "ledger.json", clock=lambda: now[0])
    assert lg2.is_week_done("shop:molagora") and not lg2.is_done("shop:free")
    now[0] = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)  # 下一周
    assert not Ledger(tmp_path / "ledger.json", clock=lambda: now[0]).is_week_done("shop:molagora")


def test_timers_have_weekly_reset(tmp_path):
    timers = {t.key: t for t in DailyModule.timers(tmp_path)}
    assert "weekly" in timers and timers["weekly"].label == "每周重置"


# ---------------------------------------------------------------- 流程

@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(controller_mod, "SETTLE_TIME", 0.1)
    monkeypatch.setattr(shop, "LIST_STILL", 0.05)
    monkeypatch.setattr(shop, "TOP_SETTLE", 0.0)
    monkeypatch.setattr(shop, "POPUP_GRACE", 0.3)
    monkeypatch.setattr(shop, "REWARD_WAIT", 3.0)
    monkeypatch.setattr(shop, "DIALOG_EATEN", 1.0)
    monkeypatch.setattr(shop, "RESULT_GRACE", 0.3)


def _run(sim, tmp_path, monkeypatch, *, timeout=300, **cfg):
    monkeypatch.setattr(shop.page, "scan_cards", sim.fake_scan)
    monkeypatch.setattr(shop.page, "read_top", sim.fake_top)
    monkeypatch.setattr(shop.page, "read_dialog", sim.fake_dialog)
    config = DailyConfig(**{"mail": False, "forest": False, "covenant": False, "arena": False, **cfg})
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off(), debug_root=tmp_path / "debug",
                 seed=1) as rt:
        return rt.run_task(DailyModule, config, timeout=timeout)


def _data(tmp_path):
    return tmp_path / "data" / "modules" / "daily"


def _history(tmp_path):
    path = _data(tmp_path) / "history.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _ledger(tmp_path):
    return json.loads((_data(tmp_path) / "ledger.json").read_text(encoding="utf-8"))


def _bought(sim):
    return [(p.page, p.name, p.count) for p in sim.purchases]


def test_dry_run_reads_all_pages(tmp_path, monkeypatch, fast):
    sim = ShopSim()
    result = _run(sim, tmp_path, monkeypatch)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert DANGER not in sim.history and sim.purchases == [] and sim.dialogs_opened == 0
    would = _history(tmp_path)[-1]["would"]
    for label in ("40点行动力（竞技场点数）", "普琳每日免费商品", "40点行动力（友情点数）", "光谱核心",
                  "亲密度献礼选择箱", "下级神器强化石（一般）", "魔罗戈拉", "上级精灵之花", "潜能开发碎片",
                  "装备炼制石选择箱", "上级神器强化石", "2个上级饰品强化石", "下级神器强化石（传承石）",
                  "2个下级饰品强化石"):
        assert any(w.startswith(f"商店：{label} ×") for w in would), (label, would)
    assert not (_data(tmp_path) / "ledger.json").exists() or not _ledger(tmp_path).get("week_done")
    assert sim.screen == "daily_lobby_ready"


def test_dry_run_probe_dialogs_only_cancels(tmp_path, monkeypatch, fast):
    sim = ShopSim()
    result = _run(sim, tmp_path, monkeypatch, shop_probe_dialogs=True, shop_items=["core", "molagora", "free"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.purchases == [] and DANGER not in sim.history
    assert sim.dialogs_opened == 3 and sim.cancels == 3


def test_live_buys_everything(tmp_path, monkeypatch, fast):
    sim = ShopSim()
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert DANGER not in sim.history
    bought = _bought(sim)
    # 交易所先买（+120 行动力），免费商品和友情点数的 40 点行动力再 +80：209 + 200 = 409 → 光谱核心买得起 2 个
    assert bought[:3] == [("arena", "40点行动力", 3), ("general", "普琳每日免费商品", 1), ("general", "40点行动力", 1)]
    assert ("general", "光谱核心", 2) in bought
    assert bought.count(("general", "亲密度献礼选择箱", 1)) == 5
    assert ("general", "下级神器强化石", 3) in bought
    legacy = {(n, k) for p, n, k in bought if p == "legacy"}
    assert legacy == {("魔罗戈拉", 2), ("上级精灵之花", 1), ("潜能开发碎片", 2), ("装备炼制石选择箱", 1),
                      ("上级神器强化石", 1), ("2个上级饰品强化石", 1), ("下级神器强化石", 3), ("2个下级饰品强化石", 3)}
    assert sim.money[Currency.ENERGY] == 409 - 320 and sim.skystone == 15871
    lg = _ledger(tmp_path)
    assert {"shop:arena_energy", "shop:free", "shop:energy"} <= set(lg["done"])
    assert "shop:core" not in lg["done"]  # 还剩 1 个没买（行动力不够），下次再看
    assert {"shop:affinity_box", "shop:molagora", "shop:accessory_low", "shop:artifact_low_general"} <= set(lg["week_done"])
    run = _history(tmp_path)[-1]
    assert len(run["shop_buys"]) == len(bought)
    totals = json.loads((_data(tmp_path) / "stats.json").read_text(encoding="utf-8"))
    assert totals["shop_buys"] == len(bought)
    box_prices = sum(1000 + 900 * i for i in range(5))
    assert totals["friendship_spent"] == 100 + box_prices + 1500


def test_live_reward_popup_for_every_item(tmp_path, monkeypatch, fast):
    """有「获得奖励」框的商品也一样：点击关闭后按读数核对。"""
    sim = ShopSim(reward="all")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["arena_energy", "molagora", "free"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert _bought(sim) == [("arena", "40点行动力", 3), ("general", "普琳每日免费商品", 1), ("legacy", "魔罗戈拉", 2)]
    assert "daily_shop_reward" in sim.history


def test_live_free_without_reward_is_not_counted(tmp_path, monkeypatch, fast):
    """免费商品没有货币可核对：没看到获得奖励就不算买到。"""
    sim = ShopSim(reward="none")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["free"])
    assert DANGER not in sim.history and len(sim.purchases) == 1
    run = _history(tmp_path)[-1]
    assert run["shop_buys"] == [] and run["failures"] == 1
    assert result.status is TaskStatus.SUCCEEDED, result.error


def test_live_second_run_skips_by_ledger(tmp_path, monkeypatch, fast):
    sim = ShopSim(money={Currency.ENERGY: 2000})
    assert _run(sim, tmp_path, monkeypatch, dry_run=False).status is TaskStatus.SUCCEEDED
    assert ("general", "光谱核心", 3) in _bought(sim)
    sim2 = ShopSim()
    result = _run(sim2, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim2.history == ["daily_lobby_ready"] and sim2.taps == []
    assert _history(tmp_path)[-1]["items"]["shop"] == "要买的都买过了（账本）"


def test_live_affinity_box_stops_at_weekly_limit(tmp_path, monkeypatch, fast):
    pages = default_pages()
    box = next(c for c in pages["general"] if c.name == "亲密度献礼选择箱")
    box.left = 7  # 本周已经买了 3 次
    sim = ShopSim(pages=pages)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["affinity_box"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert _bought(sim) == [("general", "亲密度献礼选择箱", 1)] * 2 and box.left == 5
    assert "shop:affinity_box" in _ledger(tmp_path)["week_done"]


def test_live_affinity_box_already_at_limit(tmp_path, monkeypatch, fast):
    pages = default_pages()
    next(c for c in pages["general"] if c.name == "亲密度献礼选择箱").left = 5
    sim = ShopSim(pages=pages)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["affinity_box"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.purchases == [] and sim.dialogs_opened == 0


def test_live_sold_out_marks_ledger_without_opening(tmp_path, monkeypatch, fast):
    pages = default_pages()
    for c in pages["legacy"]:
        if c.name == "魔罗戈拉":
            c.left, c.sold = 0, True
    sim = ShopSim(pages=pages)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["molagora"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.dialogs_opened == 0 and "shop:molagora" in _ledger(tmp_path)["week_done"]


def test_live_not_enough_currency_skips(tmp_path, monkeypatch, fast):
    sim = ShopSim(money={Currency.CRYSTAL: 4, Currency.ENERGY: 100})
    result = _run(sim, tmp_path, monkeypatch, dry_run=False,
                  shop_items=["core", "molagora", "flower", "artifact_low"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert DANGER not in sim.history
    # 4 个银光传承石：先买上级精灵之花（3），剩 1 个，下级神器强化石（单价 3）买不起；行动力 100 买不起光谱核心
    assert _bought(sim) == [("legacy", "上级精灵之花", 1)]


def test_live_only_selected_items(tmp_path, monkeypatch, fast):
    sim = ShopSim()
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["free"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert _bought(sim) == [("general", "普琳每日免费商品", 1)]
    assert "daily_shop_exchange" not in sim.history and "daily_shop_legacy" not in sim.history


def test_live_max_buys(tmp_path, monkeypatch, fast):
    sim = ShopSim()
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_max_buys=2)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert len(sim.purchases) == 2


def test_live_skystone_change_is_anomaly(tmp_path, monkeypatch, fast):
    sim = ShopSim(skystone_leak=True)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.FAILED and "天空石变了" in result.error
    assert len(sim.purchases) == 1


def test_live_overcharge_is_anomaly(tmp_path, monkeypatch, fast):
    sim = ShopSim(overcharge=5)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False)
    assert result.status is TaskStatus.FAILED and "竞技场点数" in result.error
    assert len(sim.purchases) == 1


def test_live_eaten_buy_is_not_counted(tmp_path, monkeypatch, fast):
    sim = ShopSim(buy="eat")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["free", "energy"])
    assert DANGER not in sim.history and sim.purchases == []
    run = _history(tmp_path)[-1]
    assert run["shop_buys"] == [] and run["failures"] >= 2
    assert sim.cancels >= 2  # 购买框按规则点了取消
    assert result.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED)


def test_live_wrong_unit_price_never_buys(tmp_path, monkeypatch, fast):
    pages = default_pages()
    next(c for c in pages["legacy"] if c.name == "魔罗戈拉").price = 20  # 涨价了：和 CATALOG 的 15 不符
    sim = ShopSim(pages=pages)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, shop_items=["molagora"])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert sim.purchases == [] and sim.dialogs_opened == 0


def test_shop_runs_before_arena(tmp_path, monkeypatch):
    from e7helper.modules.daily import StopItem

    order = []

    def fake(key):
        def run(self):
            order.append(key)
            raise StopItem("跳过")
        return run

    for key in ("mail", "forest", "covenant", "shop", "arena"):
        monkeypatch.setattr(DailyModule, f"_{key}", fake(key))
    sim = ShopSim()
    config = DailyConfig()
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off(), debug_root=tmp_path / "debug") as rt:
        assert rt.run_task(DailyModule, config).status is TaskStatus.SUCCEEDED
    assert order == ["mail", "forest", "covenant", "shop", "arena"]


def test_sim_reorders_after_purchase():
    """模拟器自检：买完的卡片移到最后。"""
    sim = ShopSim()
    first = sim.cards_of("general")[0]
    first.left, first.sold = 0, True
    assert sim.cards_of("general")[-1] is first
    assert isinstance(SimCard("x", None, 1, None), SimCard)
