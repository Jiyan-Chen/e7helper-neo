"""B04 刷神秘商店：页面识别、决策、整个流程（用 fixtures + ShopSim 离线模拟）。"""

import json

import cv2
import pytest
from game_sim import DANGER, load_fixture
from shop_sim import BUY_PRICE, ShopSim

from e7helper.core.runtime import Humanize, Runtime, TaskStatus
from e7helper.core.scene import default_detector
from e7helper.core.vision import Vision
from e7helper.modules.secret_shop import SecretShopConfig, SecretShopModule, Target, page, stats
from e7helper.modules.secret_shop.page import Resources, ShopItem, decide, match_target, name_matches, near_miss

LIST_A_TOP = ["橄榄石龙", "铁血剑兵", "友情点数", "风云风獬兽"]
LIST_A_BOTTOM = ["友情点数", "风云风獬兽", "黑曜石龙", "破灭精髓宝珠"]
LIST_B_TOP = ["灿烂精髓长袍", "奥利哈钢重甲", "深渊龙兽骨刃剑", "深渊龙兽面具"]
LIST_B_BOTTOM = ["深渊龙兽骨刃剑", "深渊龙兽面具", "友情点数", "破灭精髓鞋子"]


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(scope="module")
def vision():
    return Vision.for_module("secret_shop")


def _frame(name, size=(1600, 900)):
    return load_fixture(name, size)


# ---------------------------------------------------------------- 页面识别


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
@pytest.mark.parametrize(("fixture", "names", "prices"), [
    ("secret_shop", LIST_A_TOP, [29_000, 29_000, 18_000, 29_000]),
    ("secret_shop_scrolled", LIST_A_BOTTOM, [18_000, 29_000, 29_000, 560_000]),
    ("secret_shop_relist", LIST_B_TOP, [360_000, 240_000, 540_000, 540_000]),
    ("secret_shop_relist_scrolled", LIST_B_BOTTOM, [540_000, 540_000, 18_000, 560_000]),
])
def test_scan_items(vision, size, fixture, names, prices):
    items = page.scan_items(vision, _frame(fixture, size))
    assert [i.name for i in items] == names
    assert [i.price for i in items] == prices
    assert all(i.gold for i in items)


def test_sold_row_is_not_listed(vision):
    """买过的行按钮变灰、显示 0/1：购买模板（max_diff）不命中，不会出现在可买列表里。"""
    frame = _frame("secret_shop_sold")
    assert [i.name for i in page.scan_items(vision, frame)] == ["深渊龙兽骨刃剑", "深渊龙兽面具", "破灭精髓鞋子"]
    assert all(abs(m.rect.y - 634) > 20 for m in vision.find_all(frame, "buy", threshold=0.5))
    assert page.read_resources(vision, frame) == Resources(19_891, 30_059_042)  # 买友情点数花了 18,000


def test_bought_toast_frame_is_not_trusted(vision):
    """刚买完时顶部飘过获得横幅，金币数字在滚动：这一帧顶栏读不出，被遮住的行判为非金币，都不会被采用。"""
    frame = _frame("secret_shop_bought_toast")
    assert page.read_resources(vision, frame) == Resources(None, None)
    items = {i.name: i for i in page.scan_items(vision, frame)}
    assert items["深渊龙兽骨刃剑"].gold is False
    assert decide(items["深渊龙兽骨刃剑"], [Target(name="深渊龙兽骨刃剑")], 10**8, 0).buy is False


def _with_icon(fixture, icon, row_buy_y):
    """合成图：把用户提供的物品图标贴到某一行的物品图标位置（图标框中心约在购买按钮 y - 5）。"""
    from e7helper.core.imageio import read_image
    from e7helper.core.paths import module_assets_dir

    frame = _frame(fixture).copy()
    img = read_image(module_assets_dir("secret_shop") / "cn" / f"{icon}.png")
    h, w = img.shape[:2]
    cx, cy = 752, row_buy_y - 5
    frame[cy - h // 2:cy - h // 2 + h, cx - w // 2:cx - w // 2 + w] = img
    return frame


@pytest.mark.parametrize("icon", ["item/covenant", "item/mystic"])
def test_target_recognized_by_icon(vision, icon):
    """名字没对上（例如国服译名不同）时按物品图标认；其他行不受影响。价格核对照样生效。"""
    frame = _with_icon("secret_shop_relist", icon, 361)
    items = page.scan_items(vision, frame, ["item/covenant", "item/mystic"])
    assert [i.icons for i in items] == [frozenset(), frozenset({icon}), frozenset(), frozenset()]
    targets = SecretShopConfig().buy_targets()
    hit = items[1]
    assert match_target(hit, targets).icon == icon
    assert "不符" in decide(hit, targets, 10**8, 0).reason  # 这一行实际价格 240,000
    loose = [Target(name="某某书签", icon=icon)]
    assert decide(hit, loose, 10**8, 0).buy is True
    assert all(match_target(i, targets) is None for i in items if i is not hit)


@pytest.mark.parametrize("fixture", ["secret_shop_refresh_confirm", "secret_shop_buy_confirm"])
def test_no_items_under_dialog(vision, fixture):
    """弹窗压暗时购买按钮不命中（max_diff），不会在确认框下面误点商品。"""
    assert page.scan_items(vision, _frame(fixture)) == []


def test_scrolled_half_row_is_skipped(vision):
    """滑到底时最上面那行的名字被顶栏挡住，跳过它（顶部视图里已经完整识别过）。"""
    frame = _frame("secret_shop_scrolled")
    assert min(m.rect.y for m in vision.find_all(frame, "buy")) < 100
    assert min(i.y for i in page.scan_items(vision, frame)) > 200


def test_coin_icon_required(vision):
    """价格旁的金币图标被遮住（假设是别的货币）时 gold=False。"""
    frame = _frame("secret_shop").copy()
    cv2.rectangle(frame, (1330, 110), (1390, 165), (40, 40, 40), -1)
    items = page.scan_items(vision, frame)
    assert [i.gold for i in items] == [False, True, True, True]


@pytest.mark.parametrize("size", [(1600, 900), (1280, 720)])
@pytest.mark.parametrize(("fixture", "expected"), [
    ("secret_shop", Resources(19_891, 28_698_072)),
    ("secret_shop_relist", Resources(19_891, 30_077_042)),  # 顶栏布局不同（图标右移）
    ("secret_shop_sold", Resources(19_891, 30_059_042)),
])
def test_read_resources(vision, size, fixture, expected):
    assert page.read_resources(vision, _frame(fixture, size)) == expected


@pytest.mark.parametrize("fixture", ["secret_shop", "secret_shop_scrolled", "secret_shop_relist"])
def test_refresh_cost(vision, fixture):
    assert page.read_refresh_cost(vision, _frame(fixture)) == 3


def test_buy_dialog(vision):
    d = page.read_buy_dialog(vision, _frame("secret_shop_buy_confirm"))
    assert (d.name, d.price) == ("灿烂精髓长袍", 360_000)
    for other in ["secret_shop", "secret_shop_refresh_confirm", "lobby_exit_confirm"]:
        assert page.read_buy_dialog(vision, _frame(other)) is None


@pytest.fixture(scope="module")
def shop_detector():
    """注册了本模块弹窗的识别器（模拟 setup() 的效果）。"""
    det = default_detector()

    class _Ctl:
        scenes = det

    class _Ctx:
        controller = _Ctl()

    SecretShopModule.setup(type("M", (), {"ctx": _Ctx(), "ctl": _Ctl()})())
    return det


@pytest.mark.parametrize(("fixture", "popup"), [
    ("secret_shop_refresh_confirm", "shop_refresh"),
    ("secret_shop_buy_confirm", "shop_buy"),
    ("lobby_exit_confirm", "confirm"),  # 结束游戏框不能被认成刷新确认框
    ("secret_shop", None),
    ("secret_shop_relist", None),
    ("shop_chat_channel", "shop_chat"),  # B12 换频道：聊天面板 / 变更频道框按返回键关闭
    ("shop_chat_guild", "shop_chat"),
    ("shop_chat_change", "shop_chat_change"),
    ("shop_chat_typed", "shop_chat_change"),
])
def test_module_popups(shop_detector, fixture, popup):
    state = shop_detector.detect(_frame(fixture))
    assert state.popup == popup
    if popup is None:
        assert state.is_("secret_shop")


def test_module_popups_dismiss_with_cancel(shop_detector):
    for name in ("shop_refresh", "shop_buy"):
        assert shop_detector.popup(name).dismiss.target == "dialog/cancel"


# ---------------------------------------------------------------- 决策

BOOKMARK = Target(name="誓约书签", price=184_000)
MEDAL = Target(name="神秘奖牌", price=280_000)
ANY_PRICE = Target(name="友情点数")


def _item(name, price=184_000, gold=True):
    from e7helper.core.geometry import Rect
    from e7helper.core.vision import Match
    return ShopItem(name, price, gold, Match("buy", 1.0, Rect(1450, 180, 80, 44), 1.0, 0.0))


def test_name_matching():
    assert name_matches("誓约书签", "誓约书签")
    assert name_matches("誓约书签x5", "誓约书签")  # OCR 多读了字符
    assert name_matches("誓约 书签", "誓约书签")
    assert not name_matches("誓约书鉴", "誓约书签")  # 不做模糊匹配
    assert not name_matches("", "誓约书签")
    assert match_target("神秘奖牌", [BOOKMARK, MEDAL]) is MEDAL
    assert near_miss("誓约书鉴", [BOOKMARK, MEDAL]) is BOOKMARK
    assert near_miss("橄榄石龙", [BOOKMARK, MEDAL]) is None


@pytest.mark.parametrize(("item", "gold", "floor", "buy", "reason"), [
    (_item("誓约书签"), 1_000_000, 0, True, "目标"),
    (_item("橄榄石龙", 29_000), 1_000_000, 0, False, "不是目标"),
    (_item("誓约书签", None), 1_000_000, 0, False, "价格读不出"),
    (_item("誓约书签", gold=False), 1_000_000, 0, False, "价格不是金币"),
    (_item("誓约书签", 18_400), 1_000_000, 0, False, "不符"),  # 读错一位
    (_item("誓约书签"), None, 0, False, "金币读数未知"),
    (_item("誓约书签"), 1_000_000, 900_000, False, "下限"),
    (_item("誓约书签"), 1_084_000, 900_000, True, "目标"),  # 正好等于下限
    (_item("友情点数", 18_000), 1_000_000, 0, True, "目标"),  # 不设价格的目标
])
def test_decide(item, gold, floor, buy, reason):
    d = decide(item, [BOOKMARK, MEDAL, ANY_PRICE], gold, floor)
    assert d.buy is buy
    assert reason in d.reason


def test_config_schema_and_defaults():
    cfg = SecretShopConfig()
    assert cfg.dry_run is True  # 默认不花钱
    assert [(t.name, t.price, t.icon) for t in cfg.buy_targets()] == [
        ("誓约书签", 184_000, "item/covenant"), ("神秘奖牌", 280_000, "item/mystic")]
    assert cfg.skystone_budget is None and cfg.stop_after_misses == 0 and cfg.channel_after_misses == 0
    # 三种商品按固定顺序，和选的顺序无关
    picked = SecretShopConfig(items=["friendship", "covenant"]).buy_targets()
    assert [t.name for t in picked] == ["誓约书签", "友情点数"]
    assert SecretShopConfig(items=[]).buy_targets() == []
    assert SecretShopConfig(targets=[{"name": "灿烂精髓长袍"}]).buy_targets()[0].name == "灿烂精髓长袍"
    schema = SecretShopModule.config_schema()
    props = schema["properties"]
    assert set(props) == {"items", "max_refreshes", "stop_after_misses", "channel_after_misses", "dry_run",
                          "refresh_cost", "max_failures", "probe_dialogs"}
    assert props["items"]["x-enum-labels"] == {"covenant": "誓约书签", "mystic": "神秘奖牌", "friendship": "友情点数"}


def test_old_saved_config_migrated():
    """B12 之前 GUI 保存的配置带着旧默认值（targets 两项、预算 30）：读进来改用 items、不限预算；改过的保留。"""
    old = {"targets": [{"name": "誓约书签", "price": 184_000, "icon": "item/covenant"},
                       {"name": "神秘奖牌", "price": 280_000, "icon": "item/mystic"}],
           "max_refreshes": 50, "skystone_budget": 30, "skystone_keep": 0, "gold_floor": 0, "refresh_cost": 3,
           "max_failures": 3, "dry_run": True, "probe_dialogs": False}
    cfg = SecretShopConfig.model_validate(old)
    assert cfg.targets is None and cfg.skystone_budget is None and cfg.max_refreshes == 50
    assert [t.name for t in cfg.buy_targets()] == ["誓约书签", "神秘奖牌"]
    custom = SecretShopConfig.model_validate({**old, "targets": [{"name": "灿烂精髓长袍"}], "skystone_budget": 60})
    assert custom.targets[0].name == "灿烂精髓长袍" and custom.skystone_budget == 60
    # 新版保存的配置（带 items）不动
    again = SecretShopConfig.model_validate(cfg.model_dump(mode="json"))
    assert again.items == cfg.items and again.targets is None


def test_friendship_points_recognized(vision):
    """友情点数（B12 新增的第三种）：按名字和价格 18,000 认出，金币够就买；图标模板也能认出。"""
    targets = SecretShopConfig(items=["friendship"]).buy_targets()
    items = page.scan_items(vision, _frame("secret_shop"), page.target_icons(targets))
    hit = [i for i in items if match_target(i, targets) is not None]
    assert [(i.name, i.price) for i in hit] == [("友情点数", 18_000)]
    assert hit[0].icons == frozenset({"item/friendship"})
    assert decide(hit[0], targets, 10**6, 0).buy is True


# ---------------------------------------------------------------- 流程（ShopSim）


@pytest.fixture(autouse=True)
def _fast_waits(monkeypatch):
    """模拟器的画面是静止的，等待时间缩短不影响流程，只为让测试快一些。"""
    import e7helper.core.runtime.controller as controller
    import e7helper.modules.secret_shop as shop

    monkeypatch.setattr(controller, "SETTLE_TIME", 0.1)
    monkeypatch.setattr(controller, "POPUP_SETTLE", 0.1)
    monkeypatch.setattr(shop, "VERIFY_TIMEOUT", 1.0)
    monkeypatch.setattr(shop, "POPUP_GRACE", 0.3)


def _run(sim, tmp_path, monkeypatch=None, *, patch_resources=True, timeout=120, **cfg):
    if patch_resources:
        monkeypatch.setattr(SecretShopModule, "_read_resources", lambda self, frame: sim.resources())
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off(), debug_root=tmp_path / "debug",
                 seed=1) as rt:
        result = rt.run_task(SecretShopModule, SecretShopConfig(**cfg), timeout=timeout)
    return result


def _history(tmp_path):
    path = tmp_path / "data" / "modules" / "secret_shop" / "history.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _totals(tmp_path):
    path = tmp_path / "data" / "modules" / "secret_shop" / "stats.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_dry_run_from_lobby_never_taps_buy_or_refresh(tmp_path):
    """dry-run（默认）：从大厅进店，扫描顶部和底部，记下会买的商品，然后停止；只点了入口、只滑动。"""
    sim = ShopSim("lobby", first_list="B")
    result = _run(sim, tmp_path, patch_resources=False,  # 真的 OCR 读顶栏
                  targets=[{"name": "友情点数"}, {"name": "破灭精髓鞋子", "price": 560_000}])
    assert result.status is TaskStatus.SUCCEEDED, result.error
    assert DANGER not in sim.history and sim.confirms == 0
    assert len(sim.taps) == 1  # 只点了大厅入口
    assert sim.history.count("secret_shop_relist_scrolled") == 1
    run = _history(tmp_path)[-1]
    assert run["dry_run"] and run["refreshes"] == 0 and run["purchases"] == []
    assert [(p["name"], p["price"]) for p in run["would_buy"]] == [("友情点数", 18_000), ("破灭精髓鞋子", 560_000)]
    assert run["skystone_start"] == 19_891 and run["gold_start"] == 30_077_042
    assert "dry-run" in run["stop_reason"]
    assert _totals(tmp_path) is None  # dry-run 不计入累计


def test_dry_run_skips_wrong_price(tmp_path, caplog):
    sim = ShopSim("shop", first_list="B")
    with caplog.at_level("INFO"):
        result = _run(sim, tmp_path, patch_resources=False, targets=[{"name": "友情点数", "price": 18_400}])
    assert result.ok
    assert _history(tmp_path)[-1]["would_buy"] == []
    assert "与预期 18,400 不符" in caplog.text


def test_dry_run_probe_dialogs_only_cancels(tmp_path, monkeypatch, caplog):
    """probe_dialogs：打开购买和刷新确认框核对内容，然后都点取消。"""
    sim = ShopSim("shop", first_list="B")
    with caplog.at_level("INFO"):
        result = _run(sim, tmp_path, monkeypatch, probe_dialogs=True,
                      targets=[{"name": "灿烂精髓长袍", "price": BUY_PRICE}])
    assert result.ok, result.error
    assert DANGER not in sim.history and sim.confirms == 0
    assert "secret_shop_buy_confirm" in sim.history and "secret_shop_refresh_confirm" in sim.history
    assert "购买确认框核对通过" in caplog.text and "刷新确认框核对通过" in caplog.text
    assert (sim.skystone, sim.gold) == (1000, 10_000_000)


def test_live_buys_and_refreshes_counted_by_resources(tmp_path, monkeypatch):
    """实跑：每页买目标，刷新 3 次后停止；次数和花费按读数差计。"""
    sim = ShopSim("lobby", first_list="B", confirm="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=3,
                  targets=[{"name": "灿烂精髓长袍", "price": BUY_PRICE}])
    assert result.ok, result.error
    # 列表 B → A → B → A：第 0、2 页有目标
    run = _history(tmp_path)[-1]
    assert run["refreshes"] == 3 and run["skystone_spent"] == 9
    assert [(p["name"], p["page"]) for p in run["purchases"]] == [("灿烂精髓长袍", 0), ("灿烂精髓长袍", 2)]
    assert run["gold_spent"] == 2 * BUY_PRICE
    assert run["pages"] == 4 and run["failures"] == 0
    assert "最多刷新次数" in run["stop_reason"]
    assert (sim.skystone, sim.gold) == (1000 - 9, 10_000_000 - 2 * BUY_PRICE)
    assert sim.confirms == 5  # 3 次刷新 + 2 次购买，没有多点
    # 从大厅进店列表在顶部；每页只滑到底 1 次；刷新后列表自动回到顶部，不再滑回
    assert [y2 > y1 for _, y1, _, y2, _ in sim.swipes] == [False] * 4
    totals = _totals(tmp_path)
    assert totals["refreshes"] == 3 and totals["bought"] == {"灿烂精髓长袍": 2}


def test_live_budget_stops_before_overspending(tmp_path, monkeypatch):
    sim = ShopSim("shop", first_list="A", confirm="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=10, skystone_budget=7, targets=[])
    assert result.ok
    run = _history(tmp_path)[-1]
    assert run["refreshes"] == 2 and run["skystone_spent"] == 6
    assert "预算" in run["stop_reason"]


def test_live_skystone_keep(tmp_path, monkeypatch):
    sim = ShopSim("shop", first_list="A", confirm="ok", skystone=10)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, skystone_keep=5, targets=[])
    assert result.ok
    assert _history(tmp_path)[-1]["refreshes"] == 1  # 10 → 7，再刷会变成 4 < 5
    assert sim.skystone == 7


def test_live_gold_floor_skips_purchase(tmp_path, monkeypatch):
    sim = ShopSim("shop", first_list="B", confirm="ok", gold=400_000)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=1, gold_floor=100_000,
                  targets=[{"name": "灿烂精髓长袍"}])
    assert result.ok
    run = _history(tmp_path)[-1]
    assert run["purchases"] == [] and sim.gold == 400_000
    assert run["refreshes"] == 1  # 目标没设价格，金币下限不阻止刷新


def test_live_swallowed_confirms_are_not_counted(tmp_path, monkeypatch):
    """点了确认但没扣费（点击被吞/请求失败）：不计数，连续失败 3 次后停止。"""
    sim = ShopSim("shop", first_list="A", confirm="eat")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, targets=[])
    assert result.ok
    run = _history(tmp_path)[-1]
    assert run["refreshes"] == 0 and run["skystone_spent"] == 0
    assert run["failures"] == 3 and "连续失败 3 次" in run["stop_reason"]
    assert sim.confirms == 3


def test_live_network_retry_counts_once(tmp_path, monkeypatch):
    """确认后出现网络异常：自动点重试，按读数差计一次。"""
    sim = ShopSim("shop", first_list="B", confirm="network")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=2,
                  targets=[{"name": "灿烂精髓长袍", "price": BUY_PRICE}])
    assert result.ok, result.error
    run = _history(tmp_path)[-1]
    assert run["refreshes"] == 2 and run["skystone_spent"] == 6
    assert [p["page"] for p in run["purchases"]] == [0, 2]  # 列表 B → A → B
    assert sim.history.count("lobby_network_error") == 4 and sim.confirms == 4


def test_live_double_charge_is_anomaly(tmp_path, monkeypatch):
    """扣费是预期的两倍（例如重试导致重复请求）：立即停止，任务失败，统计里记实际花费。"""
    sim = ShopSim("shop", first_list="A", confirm="double")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, targets=[])
    assert result.status is TaskStatus.FAILED
    assert "预期 3" in result.error
    run = _history(tmp_path)[-1]
    assert run["refreshes"] == 0 and run["skystone_spent"] == 6
    assert sim.confirms == 1
    assert result.debug_dir is not None


def test_live_refresh_cost_mismatch_stops(tmp_path, monkeypatch):
    sim = ShopSim("shop", first_list="A", confirm="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, refresh_cost=5, targets=[])
    assert result.ok
    assert sim.confirms == 0
    assert "刷新消耗读数 3" in _history(tmp_path)[-1]["stop_reason"]


def test_stop_signal_saves_stats(tmp_path, monkeypatch):
    sim = ShopSim("shop", first_list="A", confirm="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=100, timeout=2, targets=[])
    assert result.status is TaskStatus.TIMEOUT
    run = _history(tmp_path)[-1]
    assert "TaskTimeout" in run["stop_reason"] and run["ended"]


def test_resources_waits_for_ticker(tmp_path, monkeypatch):
    """金币数字滚动时连续两帧读数不同：等到两帧一致才采用。"""
    sim = ShopSim("shop", first_list="A")
    seq = iter([Resources(3, 30_063_509), Resources(3, 30_060_000), Resources(3, 30_059_042),
                Resources(3, 30_059_042)])
    monkeypatch.setattr(SecretShopModule, "_read_resources", lambda self, frame: next(seq))
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off()) as rt:
        ctl = rt.make_controller(Vision.for_module("secret_shop"))
        mod = SecretShopModule.__new__(SecretShopModule)
        mod.ctx = type("Ctx", (), {"controller": ctl})()
        assert mod._resources() == Resources(3, 30_059_042)


def test_list_left_scrolled_is_scanned_from_top(tmp_path, monkeypatch):
    """任务开始时已经在商店里、列表被滑到了底部：先滑到顶部，顶部才有的商品也要扫到。"""
    sim = ShopSim("shop", first_list="B")
    sim.scrolled = True
    sim._show_list()
    result = _run(sim, tmp_path, monkeypatch, targets=[{"name": "灿烂精髓长袍", "price": BUY_PRICE}])
    assert result.ok, result.error
    assert [p["name"] for p in _history(tmp_path)[-1]["would_buy"]] == ["灿烂精髓长袍"]
    assert sim.swipes[0][3] > sim.swipes[0][1]  # 第一次滑动是向上回到顶部


def _bare_module(ctl):
    mod = SecretShopModule.__new__(SecretShopModule)
    mod.ctx = type("Ctx", (), {"controller": ctl})()
    return mod


def test_settle_list_waits_for_motion(tmp_path):
    """列表区域还在变（滑动惯性/飞入动画）时不返回，停稳后才返回。"""
    sim = ShopSim("shop", first_list="A")
    sim.animating = 8  # 接下来 8 帧亮度跳动
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off()) as rt:
        frame = _bare_module(rt.make_controller(Vision.for_module("secret_shop")))._settle_list()
    assert sim.animating == 0
    assert frame is not None


def test_settle_list_lets_closing_dialog_fade(tmp_path):
    """确认框正在自己关闭（例如刚点了确认）：先等它消失，不去点取消。"""
    sim = ShopSim("shop", first_list="A")
    sim._go("secret_shop_refresh_confirm")
    sim.then = (2, "secret_shop")
    with Runtime(sim, scenes=default_detector(), humanize=Humanize.off()) as rt:
        _bare_module(rt.make_controller(Vision.for_module("secret_shop")))._settle_list()
    assert sim.taps == [] and sim.backs == 0


# ---------------------------------------------------------------- 没出就停 / 换世界频道（B12）

NOTHING = [{"name": "不存在的商品"}]  # 每页都「没出」


def _assert_chat_safe(sim):
    assert DANGER not in sim.history  # 从没点底部发消息的输入框 / 「输入」
    assert sim.chat is None and sim.in_list  # 聊天关掉了，回到商店列表


def test_stop_after_misses(tmp_path, monkeypatch):
    sim = ShopSim(confirm="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=10, stop_after_misses=2, targets=NOTHING)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    run = _history(tmp_path)[-1]
    assert run["refreshes"] == 1 and run["pages"] == 2 and run["max_misses"] == 2
    assert "连续 2 页没出" in run["stop_reason"]


def test_hit_resets_miss_count(tmp_path, monkeypatch):
    """灿烂精髓长袍只在列表 B：B（出）→ A（没出 1）→ B（出，清零）→ A（没出 1）…… 连续 2 页才停，所以不会停。"""
    sim = ShopSim(confirm="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=4, stop_after_misses=2,
                  targets=[{"name": "灿烂精髓长袍", "price": BUY_PRICE + 1}])  # 价格不符：出了但不买
    assert result.status is TaskStatus.SUCCEEDED, result.error
    run = _history(tmp_path)[-1]
    assert run["refreshes"] == 4 and run["max_misses"] == 1 and run["purchases"] == []


def test_channel_switch_after_misses(tmp_path, monkeypatch):
    """连续 2 页没出：第 2 页（刷新 1 次后）换到下一个频道 69 → 70，再接着刷。"""
    sim = ShopSim(confirm="ok")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=1, channel_after_misses=2,
                  targets=NOTHING)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_chat_safe(sim)
    assert sim.channel_history == [70] and sim.channel == 70
    run = _history(tmp_path)[-1]
    assert [(c["old"], c["new"], c["page"]) for c in run["channel_switches"]] == [(69, 70, 1)]
    assert run["refreshes"] == 1 and run["failures"] == 0
    assert _totals(tmp_path)["channel_switches"] == 1


def test_channel_switch_from_guild_tab(tmp_path, monkeypatch):
    """聊天停在骑士团页签：先点左边的「频道」再换（用户提醒）。"""
    sim = ShopSim(confirm="ok", chat_tab="guild")
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=0, channel_after_misses=1,
                  targets=NOTHING)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_chat_safe(sim)
    assert "shop_chat_guild" in sim.history and sim.chat_tab == "channel" and sim.channel_history == [70]


def test_channel_typing_failed_does_not_submit(tmp_path, monkeypatch):
    """打字没进输入框：不点「输入」，关掉聊天，记一次失败，接着刷商店。"""
    sim = ShopSim(confirm="ok", type_text=False)
    result = _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=0, channel_after_misses=1,
                  targets=NOTHING)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_chat_safe(sim)
    assert sim.channel == 69 and sim.channel_history == []
    run = _history(tmp_path)[-1]
    assert run["failures"] == 1 and run["channel_switches"] == []


def test_dry_run_probe_channel_switches_back(tmp_path, monkeypatch):
    """dry-run + probe_channel：换到 70 再换回 69（用于实机验证），不计入统计，不点购买和刷新。"""
    sim = ShopSim()
    result = _run(sim, tmp_path, monkeypatch, probe_channel=True)
    assert result.status is TaskStatus.SUCCEEDED, result.error
    _assert_chat_safe(sim)
    assert sim.channel_history == [70, 69] and sim.confirms == 0
    assert _history(tmp_path)[-1]["channel_switches"] == []


# ---------------------------------------------------------------- 刷取历史（B12c）


def _rec(started, *, dry=False, refreshes=0, sky=0, gold=0, pages=1, buys=(), switches=0, reason="达到最多刷新次数 3",
         **extra):
    r = {"dry_run": dry, "started": started, "ended": started, "refreshes": refreshes, "skystone_spent": sky,
         "gold_spent": gold, "pages": pages, "purchases": [{"name": n, "price": 1, "page": p, "time": started} for n, p in buys],
         "would_buy": [], "failures": 0, "max_misses": 2, "channel_switches": [{"old": 1, "new": 2, "page": 0}] * switches,
         "stop_reason": reason}
    r.update(extra)
    return r


def test_report_skips_dry_run_and_groups_by_day():
    records = [
        _rec("2026-10-14T21:04:07", dry=True, refreshes=5, buys=[("誓约书签", 0)]),
        _rec("2026-10-15T00:55:47", refreshes=3, sky=9, pages=4),
        _rec("2026-10-15T23:59:00", refreshes=3, sky=9, gold=464000, pages=4, buys=[("神秘奖牌", 1), ("誓约书签", 3)],
             switches=1),
        _rec("2026-10-17T08:00:00", refreshes=10, sky=30, gold=184000, pages=11, buys=[("誓约书签", 7)]),
    ]
    rep = stats.report(records)
    assert rep["run_count"] == 3
    assert [d["date"] for d in rep["days"]] == ["2026-10-15", "2026-10-17"]
    d15 = rep["days"][0]
    assert (d15["runs"], d15["refreshes"], d15["skystone_spent"], d15["gold_spent"], d15["pages"]) == (2, 6, 18, 464000, 8)
    assert d15["bought"] == {"神秘奖牌": 1, "誓约书签": 1} and d15["channel_switches"] == 1
    # 明细新的在前，带每次买到的商品和第几页
    assert [r["started"] for r in rep["runs"]] == ["2026-10-17T08:00:00", "2026-10-15T23:59:00", "2026-10-15T00:55:47"]
    assert rep["runs"][1]["purchases"] == [{"name": "神秘奖牌", "page": 1}, {"name": "誓约书签", "page": 3}]
    assert rep["runs"][1]["bought"] == {"神秘奖牌": 1, "誓约书签": 1}
    assert stats.report(records, runs_limit=1)["runs"][0]["started"] == "2026-10-17T08:00:00"
    assert stats.report(records, runs_limit=1)["run_count"] == 3


def test_report_old_records_and_stop_reasons():
    old = _rec("2026-10-15T01:17:43", reason="TaskStopped：stopped")
    del old["max_misses"], old["channel_switches"]  # B04 时期的记录
    rep = stats.report([
        old,
        _rec("2026-10-16T01:00:00", reason="TaskTimeout：timeout"),
        _rec("2026-10-16T02:00:00", reason="ShopAnomaly：天空石读数差 6"),
        _rec("2026-10-16T03:00:00", reason="连续 5 页没出要买的商品"),
        {"dry_run": False},  # 坏记录跳过
    ])
    reasons = {r["started"]: r["stop_reason"] for r in rep["runs"]}
    assert reasons == {"2026-10-15T01:17:43": "手动停止", "2026-10-16T01:00:00": "超过时限",
                       "2026-10-16T02:00:00": "出错：天空石读数差 6", "2026-10-16T03:00:00": "连续 5 页没出要买的商品"}
    first = rep["runs"][-1]
    assert first["channel_switches"] == 0 and first["max_misses"] == 0


def test_load_history_skips_bad_lines(tmp_path):
    (tmp_path / "history.jsonl").write_text('{"dry_run": false, "started": "2026-10-15T01:00:00"}\n坏行\n[1]\n',
                                            encoding="utf-8")
    assert len(stats.load_history(tmp_path)) == 1
    assert stats.load_history(tmp_path / "nope") == []


def test_live_run_shows_in_report(tmp_path, monkeypatch):
    """实跑写进 history.jsonl 后，report 能读到；dry-run 的不出现。"""
    target = [{"name": "灿烂精髓长袍", "price": BUY_PRICE}]
    _run(ShopSim("lobby", first_list="B"), tmp_path, monkeypatch, targets=target)  # dry-run
    sim = ShopSim("lobby", first_list="B", confirm="ok")
    assert _run(sim, tmp_path, monkeypatch, dry_run=False, max_refreshes=3, targets=target).ok
    assert len(_history(tmp_path)) == 2
    rep = stats.report(stats.load_history(tmp_path / "data" / "modules" / "secret_shop"))
    assert rep["run_count"] == 1
    run = rep["runs"][0]
    assert (run["refreshes"], run["skystone_spent"], run["bought"]) == (3, 9, {"灿烂精髓长袍": 2})
    assert [d["refreshes"] for d in rep["days"]] == [3]
