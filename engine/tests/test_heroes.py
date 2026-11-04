"""B13：英雄数据库（离线：下载用假的 fetch，数据目录和随包目录都用临时目录）。"""

import json
import threading
import urllib.request

import pytest
from api_fakes import make_engine
from fastapi.testclient import TestClient

from e7helper.api import create_app
from e7helper.core import paths
from e7helper.core.data import hero_db as heroes_mod
from e7helper.core.data import hero_update, load_heroes, name_key
from e7helper.core.data.hero_update import ICON_PATH, UpdateError, convert, update_heroes
from e7helper.core.data.hero_db import HeroFile, dump_hero_file, read_hero_file

TOKEN = "test-token"
BASE = "http://127.0.0.1:47800"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def _fribbels(name: str, code: str, attribute="light", role="mage", rarity=5, spd=115) -> dict:
    return {
        "_id": name.lower(), "code": code, "name": name, "attribute": attribute, "role": role, "rarity": rarity,
        "zodiac": "bull", "skills": {}, "ex_equip": [],
        "calculatedStatus": {"lv60SixStarFullyAwakened": {"atk": 1039, "hp": 5299, "def": 673, "spd": spd,
                                                          "chc": 0.15, "cp": 22755}},
    }


HERODATA = {
    "Solitaria of the Snow": _fribbels("Solitaria of the Snow", "c2111"),
    "Arbiter Vildred": _fribbels("Arbiter Vildred", "c2007", attribute="dark", role="assassin", spd=127),
    "Vildred": _fribbels("Vildred", "c1007", attribute="wind", role="assassin"),
    "Mei Lin": _fribbels("Mei Lin", "c1191", attribute="fire", role="warrior"),
    "Ras": _fribbels("Ras", "c1001", attribute="fire", role="knight", rarity=3),
}
ZH = {"Solitaria of the Snow": "雪国的苏莉塔妮亚", "Arbiter Vildred": "执行官维德瑞", "Vildred": "维德瑞",
      "Ras": "拉斯", "Ram": "拉姆"}


class FakeFetch:
    def __init__(self, herodata=None, zh=None, icons: dict[str, bytes] | None = None):
        self.files = {hero_update.HERODATA_PATH: json.dumps(herodata or HERODATA).encode(),
                      hero_update.ZH_PATH: json.dumps(zh or ZH, ensure_ascii=False).encode()}
        for code in (herodata or HERODATA).values():
            self.files[ICON_PATH.format(code=code["code"])] = PNG
        self.files.update(icons or {})
        self.calls: list[str] = []

    def __call__(self, path: str) -> bytes:
        self.calls.append(path)
        if path not in self.files:
            raise UpdateError(f"404 {path}")
        return self.files[path]


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("E7_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(paths, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(heroes_mod, "_db", None)


def _bundled(tmp_path):
    return tmp_path / "assets" / "data" / "heroes"


def _user(tmp_path):
    return tmp_path / "data" / "data" / "heroes"


def _write(dir_, heroes, updated, overrides=None):
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "heroes.json").write_text(dump_hero_file(HeroFile(updated=updated, heroes=heroes)), encoding="utf-8")
    if overrides is not None:
        (dir_ / "overrides.json").write_text(json.dumps(overrides, ensure_ascii=False), encoding="utf-8")


HEROES, MISSING = convert(HERODATA, ZH)


# ---------------------------------------------------------------- 转换


def test_convert():
    by = {h.code: h for h in HEROES}
    assert [h.code for h in HEROES] == sorted(by)
    s = by["c2111"]
    assert (s.name, s.name_en, s.element, s.role, s.rarity, s.zodiac) == (
        "雪国的苏莉塔妮亚", "Solitaria of the Snow", "light", "mage", 5, "bull")
    assert s.stats == {"cp": 22755, "atk": 1039, "hp": 5299, "def": 673, "spd": 115, "chc": 0.15}
    assert isinstance(s.stats["spd"], int)
    # 没有中文名的先用英文名
    assert by["c1191"].name == "Mei Lin" and MISSING == ["Mei Lin"]


def test_convert_skips_broken_entries():
    data = {**HERODATA, "Broken": {"name": "Broken", "code": "c9999"}, "Junk": "x",
            "Mighty Scout": _fribbels("Mighty Scout", "m0063", rarity=2)}  # 愚人节的怪物英雄不要
    heroes, _ = convert(data, ZH)
    assert "c9999" not in {h.code for h in heroes} and len(heroes) == len(HERODATA)


def test_dump_roundtrip(tmp_path):
    _write(tmp_path, HEROES, "2026-10-20T00:00:00+00:00")
    text = (tmp_path / "heroes.json").read_text(encoding="utf-8")
    assert text.count("\n") == len(HEROES) + 2  # 一名英雄一行
    assert read_hero_file(tmp_path / "heroes.json").heroes == HEROES


# ---------------------------------------------------------------- 加载和查询


def test_load_prefers_newer(tmp_path):
    old = [h for h in HEROES if h.code != "c1191"]
    _write(_bundled(tmp_path), old, "2026-10-01T00:00:00+00:00")
    db = load_heroes()
    assert (db.origin, len(db)) == ("bundled", len(old))
    _write(_user(tmp_path), HEROES, "2026-10-20T00:00:00+00:00")
    db = load_heroes()
    assert (db.origin, len(db)) == ("user", len(HEROES))
    # 新版本随包的数据更新：随包的优先
    _write(_bundled(tmp_path), old, "2026-11-01T00:00:00+00:00")
    assert load_heroes().origin == "bundled"


def test_load_broken_or_missing(tmp_path):
    db = load_heroes()
    assert (db.origin, len(db), db.updated) == ("", 0, "")
    _write(_bundled(tmp_path), HEROES, "2026-10-01T00:00:00+00:00")
    _user(tmp_path).mkdir(parents=True, exist_ok=True)
    (_user(tmp_path) / "heroes.json").write_text("{坏的", encoding="utf-8")
    assert load_heroes().origin == "bundled"


def test_find_and_overrides(tmp_path):
    _write(_bundled(tmp_path), HEROES, "2026-10-01T00:00:00+00:00",
           overrides={"_说明": "按编号改名、加别名", "c2111": {"aliases": ["雪苏"]},
                      "c1191": {"name": "梅琳", "aliases": ["梅林"]}})
    db = load_heroes()
    assert db.get("c2111").aliases == ["雪苏"]
    assert db.get("c1191").name == "梅琳"
    assert db.file.heroes[[h.code for h in HEROES].index("c1191")].name == "Mei Lin"  # 原始数据不变
    for text in ("雪国的苏莉塔妮亚", " 雪国的 苏莉塔妮亚 ", "雪苏", "solitaria of the snow", "SOLITARIA OF THE SNOW"):
        assert db.find(text).code == "c2111", text
    assert db.find("梅林").code == "c1191"
    assert db.find("苏莉塔妮亚") is None  # find 只做精确匹配
    assert db.find("") is None


def test_name_key():
    assert name_key("Ａｒｂｉｔｅｒ　Vildred") == name_key("arbiter vildred")
    assert name_key("爱德华·爱力克") == name_key("爱德华・爱力克") == "爱德华爱力克"


def test_search_ranking(tmp_path):
    _write(_bundled(tmp_path), HEROES, "2026-10-01T00:00:00+00:00")
    db = load_heroes()
    # 完全一致 → 开头一致 → 包含
    assert [h.code for h in db.search("维德瑞")] == ["c1007", "c2007"]
    assert [h.code for h in db.search("vildred")] == ["c1007", "c2007"]
    assert [h.code for h in db.search("c21")] == ["c2111"]
    assert db.search("") == [] and db.search("没有这个") == []
    assert len(db.search("c", limit=2)) == 2


def test_icons(tmp_path):
    from e7helper.core.imageio import write_image
    import numpy as np

    _write(_bundled(tmp_path), HEROES, "2026-10-01T00:00:00+00:00")
    (_bundled(tmp_path) / "icons").mkdir()
    write_image(_bundled(tmp_path) / "icons" / "c2111.png", np.full((112, 112, 3), 200, np.uint8))
    db = load_heroes()
    assert db.icon_path("c2111").parent.parent == _bundled(tmp_path)
    assert db.icon("c2111").shape == (112, 112, 3)
    assert db.icon("c1001") is None
    # 用户目录里的优先
    (_user(tmp_path) / "icons").mkdir(parents=True, exist_ok=True)
    write_image(_user(tmp_path) / "icons" / "c2111.png", np.zeros((112, 112, 3), np.uint8))
    assert load_heroes().icon("c2111").max() == 0


# ---------------------------------------------------------------- 联网更新


def test_update_first_time_and_unchanged(tmp_path):
    fetch = FakeFetch()
    res = update_heroes(tmp_path, None, fetch=fetch)
    assert res.changed and res.total == len(HERODATA) and sorted(res.added) == sorted(h.code for h in HEROES)
    assert res.icons == len(HERODATA) and res.missing_names == ["Mei Lin"]
    file = read_hero_file(tmp_path / "heroes.json")
    assert file.updated == res.updated and file.heroes == HEROES
    # 再来一次：数据没变不写，头像已有不下
    fetch2 = FakeFetch()
    res2 = update_heroes(tmp_path, file, fetch=fetch2)
    assert not res2.changed and res2.icons == 0 and res2.updated == file.updated
    assert not any(c.endswith(".png") for c in fetch2.calls)


def test_update_diff_and_icon_dirs(tmp_path):
    current = HeroFile(updated="2026-10-01T00:00:00+00:00", heroes=[h for h in HEROES if h.code != "c1191"])
    bundled = tmp_path / "bundled"
    (bundled / "icons").mkdir(parents=True)
    for h in current.heroes:
        (bundled / "icons" / f"{h.code}.png").write_bytes(PNG)
    data = json.loads(json.dumps(HERODATA))
    data["Ras"]["calculatedStatus"]["lv60SixStarFullyAwakened"]["spd"] = 99
    del data["Vildred"]
    fetch = FakeFetch(data)
    target = tmp_path / "user"
    res = update_heroes(target, current, fetch=fetch, other_dirs=[bundled])
    assert (res.added, res.removed, res.modified) == (["c1191"], ["c1007"], ["c1001"])
    assert res.changed and res.updated > current.updated
    # 只下载随包没有的头像
    assert res.icons == 1 and [p.name for p in (target / "icons").iterdir()] == ["c1191.png"]


def test_update_refuses_shrunk_data(tmp_path):
    many = HeroFile(heroes=[HEROES[0].model_copy(update={"code": f"c9{i:03}"}) for i in range(20)] + HEROES)
    with pytest.raises(UpdateError, match="没有覆盖"):
        update_heroes(tmp_path, many, fetch=FakeFetch())
    assert not (tmp_path / "heroes.json").exists()


def test_update_bad_payload(tmp_path):
    fetch = FakeFetch()
    fetch.files[hero_update.HERODATA_PATH] = b"<html>"
    with pytest.raises(UpdateError, match="不是 JSON"):
        update_heroes(tmp_path, None, fetch=fetch)


def test_update_icon_failures(tmp_path):
    fetch = FakeFetch(icons={ICON_PATH.format(code="c2111"): b"<html>not png"})
    del fetch.files[ICON_PATH.format(code="c1001")]
    res = update_heroes(tmp_path, None, fetch=fetch)
    assert res.changed and sorted(res.icon_failed) == ["c1001", "c2111"]
    assert res.icons == len(HERODATA) - 2


def test_update_icons_give_up_after_streak(tmp_path):
    data = {f"H{i}": _fribbels(f"H{i}", f"c9{i:03}") for i in range(12)}
    fetch = FakeFetch(data)
    for code in data.values():
        del fetch.files[ICON_PATH.format(code=code["code"])]
    res = update_heroes(tmp_path, None, fetch=fetch)
    assert len(res.icon_failed) == 12 and res.icons == 0
    assert sum(c.endswith(".png") for c in fetch.calls) == hero_update.MAX_ICON_FAILS


def test_mirror_fetcher_falls_back(monkeypatch):
    seen = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.append(req.full_url)
        if req.full_url.startswith("https://a/"):
            raise OSError("连不上")
        return Resp(b"ok")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    f = hero_update.MirrorFetcher(["https://a/", "https://b/"])
    assert f("x.json") == b"ok"
    assert f("y.json") == b"ok"  # 记住能用的镜像，先试它
    assert seen == ["https://a/x.json", "https://b/x.json", "https://b/y.json"]
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(OSError("断网")))
    with pytest.raises(UpdateError, match="下载失败"):
        f("z.json")


# ---------------------------------------------------------------- 随包数据


def test_bundled_data_is_complete(monkeypatch):
    monkeypatch.undo()  # 用真的 assets 目录
    bundled = paths.bundled_data_dir("heroes")
    file = read_hero_file(bundled / "heroes.json")
    assert file is not None and len(file.heroes) >= 385
    assert all(h.code.startswith("c") for h in file.heroes)  # 没有愚人节的怪物英雄
    codes = [h.code for h in file.heroes]
    assert len(set(codes)) == len(codes)
    assert {h.element for h in file.heroes} <= set(heroes_mod.ELEMENT_LABELS)
    assert {h.role for h in file.heroes} <= set(heroes_mod.ROLE_LABELS)
    assert {h.zodiac for h in file.heroes} <= set(heroes_mod.ZODIAC_LABELS)
    missing = [c for c in codes if not (bundled / "icons" / f"{c}.png").is_file()]
    assert missing == []
    by = {h.code: h for h in file.heroes}
    assert by["c2111"].name == "雪国的苏莉塔妮亚"  # 国服名（B13 用户确认）
    assert by["c1191"].name == "梅铃" and "梅林" in by["c1191"].aliases  # e7.wiki 的名字和昵称
    # 详情：每名都有，发布日期都有，引用的图标都在
    db = load_heroes(bundled_dir=bundled, user_dir=bundled)
    no_detail = [c for c in codes if db.detail(c) is None]
    assert no_detail == [], no_detail
    assert all(h.released for h in file.heroes)
    missing_icons = {name for c in codes if (d := db.detail(c))
                     for name in [s.icon for s in d.skills] + [e.icon for s in d.skills for e in s.effects]
                     if name and db.detail_icon_path(name) is None}
    assert not missing_icons
    assert db.artifacts()["efm19"]["name"] == "噩梦童话"


# ---------------------------------------------------------------- 接口


@pytest.fixture
def client(tmp_path):
    _write(_bundled(tmp_path), HEROES, "2026-10-01T00:00:00+00:00", overrides={"c1191": {"name": "梅琳"}})
    (_bundled(tmp_path) / "icons").mkdir()
    (_bundled(tmp_path) / "icons" / "c2111.png").write_bytes(PNG)
    engine = make_engine(tmp_path, detector=None)
    app = create_app(engine, token=TOKEN, start_scheduler=False, autoconnect=False)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        yield c


def test_api_needs_token(client):
    assert client.get("/api/heroes", headers={"Authorization": ""}).status_code == 401


def test_api_list_and_get(client):
    d = client.get("/api/heroes").json()
    assert (d["count"], d["origin"], d["source"]) == (len(HEROES), "bundled", "fribbels")
    assert d["labels"]["element"]["wind"] == "木" and d["labels"]["role"]["manauser"] == "精灵师"
    by = {h["code"]: h for h in d["heroes"]}
    assert by["c2111"]["icon"] is True and by["c1001"]["icon"] is False
    assert by["c1191"]["name"] == "梅琳"
    h = client.get("/api/heroes/c2111").json()
    assert h["name"] == "雪国的苏莉塔妮亚" and h["stats"]["spd"] == 115
    r = client.get("/api/heroes/c0000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_hero"


def test_api_icon(client):
    r = client.get(f"/api/heroes/c2111/icon?token={TOKEN}", headers={"Authorization": ""})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == PNG
    assert client.get("/api/heroes/c1001/icon").json()["error"]["code"] == "no_icon"
    assert client.get("/api/heroes/c0000/icon").json()["error"]["code"] == "unknown_hero"


def test_api_update(client, tmp_path, monkeypatch):
    data = {**HERODATA, "Ram": _fribbels("Ram", "c1200", attribute="ice")}
    monkeypatch.setattr(hero_update, "MirrorFetcher", lambda: FakeFetch(data))
    r = client.post("/api/heroes/update")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["changed"] and d["added"] == ["c1200"] and d["origin"] == "user" and d["count"] == len(HEROES) + 1
    assert d["icons"] == len(HERODATA)  # 随包只有 c2111 的头像
    assert (_user(tmp_path) / "heroes.json").is_file()
    lst = client.get("/api/heroes").json()
    assert lst["origin"] == "user" and {h["code"]: h for h in lst["heroes"]}["c1200"]["name"] == "拉姆"
    assert client.get("/api/heroes/c1200/icon").status_code == 200
    # 套用 overrides 不受更新影响
    assert client.get("/api/heroes/c1191").json()["name"] == "梅琳"
    # 再更新一次：没变化
    d2 = client.post("/api/heroes/update").json()
    assert not d2["changed"] and d2["icons"] == 0


def test_api_update_errors(client, monkeypatch):
    def broken():
        f = FakeFetch()
        f.files.pop(hero_update.HERODATA_PATH)
        return f

    monkeypatch.setattr(hero_update, "MirrorFetcher", broken)
    r = client.post("/api/heroes/update")
    assert r.status_code == 502 and r.json()["error"]["code"] == "update_failed"

    started, release = threading.Event(), threading.Event()

    def slow():
        f = FakeFetch()
        inner = f.__call__

        def call(path):
            started.set()
            release.wait(5)
            return inner(path)

        return call

    monkeypatch.setattr(hero_update, "MirrorFetcher", slow)
    t = threading.Thread(target=lambda: client.post("/api/heroes/update"))
    t.start()
    assert started.wait(5)
    r = client.post("/api/heroes/update")
    assert r.status_code == 409 and r.json()["error"]["code"] == "busy"
    release.set()
    t.join(5)


# ---------------------------------------------------------------- e7.wiki 详情、配装（B13 审核后加）

from e7helper.core.data import hero_builds  # noqa: E402
from e7helper.core.data.hero_builds import BuildsError, full_sets, get_builds, summarize  # noqa: E402
from e7helper.core.data.hero_detail import convert_detail  # noqa: E402
from e7helper.api.heroes import ARTIFACT_ICON_URL as ARTIFACT_URL  # noqa: E402

WEBP = b"RIFF\x10\0\0\0WEBPVP8 " + b"\0" * 16
WIKI_RAW = {
    "code": "solitaria-of-the-snow", "subtitle": "等待命中注定相遇的\n冰之城堡的主人", "releaseDate": "2021-04-15",
    "detailImageUrl": "/static/detailImage/c2111_su.webp",
    "selfDevotion": {"type": "acc", "grades": {"b": 0.09, "a": 0.14, "s": 0.19, "ss": 0.23, "sss": 0.27, "z": 0.0}},
    "devotion": {"type": "max_hp_rate", "grades": {"sss": 0.12, "c": 0.0}},
    "exclusiveEquipment": {
        "name": "魔神之瞳", "iconUrl": "/static/exclusive/icon_eq_exclusive_c2111.webp",
        "mainStat": {"type": "att_rate", "min": 0.07, "max": 0.14},
        "description": [[{"text": "专属装备说明"}]],
        "skills": [{"slot": 2, "index": 1, "description": [[{"text": "二技能效果 A"}]]},
                   {"slot": 2, "index": 2, "description": [[{"text": "二技能效果 B"}]]}],
    },
    "skills": [
        {"slot": 1, "name": "咻呜呜", "iconUrl": "/static/skills/sk_c2111_1.webp", "soulGain": 1, "cooldown": [],
         "description": [[{"text": "用手杖攻击，若处于"}, {"text": "妄想", "bold": True, "color": "#D76D0C"},
                          {"text": "状态"}], [{"text": ""}]],
         "effects": [{"name": "晕眩", "type": "debuff", "iconUrl": "/static/effects/stic_stun.webp",
                      "description": [[{"text": "无法行动。"}]]}],
         "enhancements": [{"level": 1, "description": [[{"text": "伤害量提升5%"}]]}],
         "multipliers": [{"label": "技能倍率", "items": [{"label": "基础倍率", "value": "0.7", "key": "att_rate"}]}],
         "soulBurn": None},
        {"slot": 2, "name": "我要回房间了", "iconUrl": "/static/skills/sk_c2111_2.webp", "soulGain": 0,
         "description": [[{"text": "被动"}]], "effects": [
             {"name": "晕眩", "type": "debuff", "iconUrl": "/static/effects/stic_stun.webp", "description": []}]},
        {"slot": 3, "name": "星光", "iconUrl": "/static/skills/sk_c2111_3.webp", "soulGain": 3,
         "cooldown": [[{"text": "冷却时间"}, {"text": "4(3)", "bold": True}, {"text": "回合"}]],
         "description": [[{"text": "攻击"}]], "soulBurn": {"cost": 10, "description": [[{"text": "伤害量提升。"}]]}},
        {"slot": 4, "name": "多出来的"},
    ],
}
CARDS = [
    {"face_id": "c2111", "code": "solitaria-of-the-snow", "name": "雪国的苏莉塔妮亚", "nicknames": "星法,xingfa",
     "update_time": "2026-05-03 23:15:50"},
    {"face_id": "c1191", "code": "mei-lin", "name": "梅铃", "nicknames": "meiling,梅林,梅铃",
     "update_time": "2026-10-09 22:47:24"},
]
ARTIFACTDATA = {"Fairy Tale for a Nightmare": {"code": "efm19", "name": "Fairy Tale for a Nightmare"},
                "Abyssal Crown": {"code": "efm05"}}
ZH_ART = {**ZH, "Fairy Tale for a Nightmare": "噩梦童话"}
WIKI_ICONS = ("/static/exclusive/icon_eq_exclusive_c2111.webp", "/static/skills/sk_c2111_1.webp",
              "/static/skills/sk_c2111_2.webp", "/static/skills/sk_c2111_3.webp", "/static/effects/stic_stun.webp")


def _wiki_fetch(herodata=None, cards=None):
    f = FakeFetch(herodata, ZH_ART)
    f.files[hero_update.WIKI_CARDS_URL] = json.dumps({"code": 1000, "data": cards or CARDS}, ensure_ascii=False).encode()
    f.files[hero_update.ARTIFACTDATA_PATH] = json.dumps(ARTIFACTDATA).encode()
    # e7.wiki 神器列表：英文名大小写 / 标点不同也能对上
    f.files[hero_update.WIKI_ARTIFACTS_URL] = json.dumps({"data": [
        {"name": "深渊王冠", "name_en": "abyssal crown", "icon": "icon_art5_5"}]}, ensure_ascii=False).encode()
    for c in cards or CARDS:
        f.files[hero_update.WIKI_ASSETS + f"/static/heroes/{c['code']}.json"] = json.dumps(
            WIKI_RAW, ensure_ascii=False).encode()
    for u in WIKI_ICONS:
        f.files[hero_update.WIKI_ASSETS + u] = WEBP
    return f


def _herodata_with_slugs():
    data = json.loads(json.dumps(HERODATA))
    for c in CARDS:
        next(v for v in data.values() if v["code"] == c["face_id"])["_id"] = c["code"]
    return data


def test_convert_detail():
    det, icons = convert_detail("c2111", WIKI_RAW, "2026-05-03 23:15:50")
    assert det.subtitle == "等待命中注定相遇的冰之城堡的主人"
    assert det.self_devotion.grades == {"b": 0.09, "a": 0.14, "s": 0.19, "ss": 0.23, "sss": 0.27}
    assert det.devotion.type == "max_hp_rate"
    assert len(det.skills) == 3  # 只取前三个
    s1, s2, s3 = det.skills
    assert s1.description == [[{"text": "用手杖攻击，若处于"}, {"text": "妄想", "hl": True}, {"text": "状态"}]]
    assert s1.icon == "sk_c2111_1.webp" and s1.effects[0].icon == "stic_stun.webp"
    assert s1.enhancements == [[[{"text": "伤害量提升5%"}]]]
    assert s1.multipliers[0].items == [{"label": "基础倍率", "value": "0.7"}]
    assert s2.exclusive == [[[{"text": "二技能效果 A"}]], [[{"text": "二技能效果 B"}]]] and s1.exclusive == []
    assert s3.soul_burn.cost == 10
    assert s3.cooldown == [[{"text": "冷却时间"}, {"text": "4(3)", "hl": True}, {"text": "回合"}]]
    assert det.exclusive.name == "魔神之瞳" and det.exclusive.main_stat["type"] == "att_rate"
    assert [(e.index, e.slot) for e in det.exclusive.effects] == [(1, 2), (2, 2)]
    assert det.exclusive.effects[1].description == [[{"text": "二技能效果 B"}]]
    assert icons == ["/static/exclusive/icon_eq_exclusive_c2111.webp", "/static/skills/sk_c2111_1.webp",
                     "/static/effects/stic_stun.webp", "/static/skills/sk_c2111_2.webp", "/static/skills/sk_c2111_3.webp"]


def test_update_with_wiki(tmp_path):
    fetch = _wiki_fetch(_herodata_with_slugs())
    res = update_heroes(tmp_path, None, fetch=fetch)
    assert res.wiki_error == "" and res.missing_names == []
    by = {h.code: h for h in read_hero_file(tmp_path / "heroes.json").heroes}
    assert by["c1191"].name == "梅铃" and by["c1191"].aliases == ["meiling", "梅林"]  # 和名字一样的昵称不要
    assert by["c2111"].aliases == ["星法", "xingfa"] and by["c2111"].slug == "solitaria-of-the-snow"
    assert by["c1001"].name == "拉斯" and by["c1001"].aliases == []  # e7.wiki 没有的用 Fribbels 简中
    assert by["c2111"].released == "2021-04-15" and by["c1001"].released == ""  # 发布日期来自详情
    assert res.details == 2 and res.detail_icons == 5 and res.detail_failed == []
    arts = json.loads((tmp_path / "artifacts.json").read_text(encoding="utf-8"))
    assert arts == {"efm05": {"name": "Abyssal Crown", "name_en": "Abyssal Crown", "icon": "icon_art5_5"},
                    "efm19": {"name": "噩梦童话", "name_en": "Fairy Tale for a Nightmare"}}
    db = load_heroes(bundled_dir=tmp_path / "none", user_dir=tmp_path)
    assert db.detail("c2111").skills[2].name == "星光" and db.detail("c1001") is None
    assert db.detail_icon_path("stic_stun.webp").is_file()
    assert db.detail_icon_path("../heroes.json") is None
    assert db.artifacts()["efm19"]["name"] == "噩梦童话"
    assert db.find("梅林").code == "c1191" and db.search("xingfa")[0].code == "c2111"

    # 再更新：e7.wiki 更新时间没变的不重新下载
    file = read_hero_file(tmp_path / "heroes.json")
    fetch2 = _wiki_fetch(_herodata_with_slugs())
    res2 = update_heroes(tmp_path, file, fetch=fetch2)
    assert not res2.changed and res2.details == 0 and res2.detail_icons == 0
    assert not any("/static/" in c for c in fetch2.calls)
    # 只有梅铃的更新时间变了：只重下这一份
    cards = [dict(CARDS[0]), {**CARDS[1], "update_time": "2026-10-20 00:00:00"}]
    fetch3 = _wiki_fetch(_herodata_with_slugs(), cards=cards)
    res3 = update_heroes(tmp_path, file, fetch=fetch3)
    assert res3.details == 1
    assert [c for c in fetch3.calls if "/static/heroes/" in c] == [hero_update.WIKI_ASSETS + "/static/heroes/mei-lin.json"]


def test_update_wiki_down_keeps_names(tmp_path):
    update_heroes(tmp_path, None, fetch=_wiki_fetch(_herodata_with_slugs()))
    file = read_hero_file(tmp_path / "heroes.json")
    res = update_heroes(tmp_path, file, fetch=FakeFetch(_herodata_with_slugs()))  # 没有 e7.wiki
    assert res.wiki_error and not res.changed and res.missing_names == []
    assert {h.code: h.name for h in read_hero_file(tmp_path / "heroes.json").heroes}["c1191"] == "梅铃"


MORO_CARD = {"face_id": "c2187", "code": "bunny-girl-great-detective-moro", "name": "兔女郎名侦探茉萝",
             "nicknames": "moluo,茉萝", "attribute": "light", "role": "assassin", "rarity": 5, "zodiac": "maiden",
             "update_time": "2026-10-30 14:26:23"}


def _moro_fetch(herodata=None):
    """e7.wiki 有、Fribbels 还没有的新英雄（B14h）：详情里有英文名 / 属性 / 发布日期，头像只有 e7.wiki 的 webp。"""
    import cv2
    import numpy as np

    f = _wiki_fetch(herodata or _herodata_with_slugs(), cards=[*CARDS, MORO_CARD])
    f.files[hero_update.WIKI_ASSETS + "/static/heroes/bunny-girl-great-detective-moro.json"] = json.dumps(
        {**WIKI_RAW, "code": MORO_CARD["code"], "nameEn": "Bunny Girl Great Detective Moro", "releaseDate": "2026-10-29",
         "stats": {"atk": 1075, "chc": 0.15, "def": 487, "hp": 5562, "spd": 128, "unknown": 1}},
        ensure_ascii=False).encode()
    ok, webp = cv2.imencode(".webp", np.full((112, 112, 4), 200, np.uint8))
    f.files[hero_update.WIKI_AVATAR.format(code="c2187")] = webp.tobytes()
    return f


def test_update_wiki_only_hero(tmp_path):
    res = update_heroes(tmp_path, None, fetch=_moro_fetch())
    assert res.wiki_only == ["c2187"] and "c2187" in res.added and res.icon_failed == []
    moro = {h.code: h for h in read_hero_file(tmp_path / "heroes.json").heroes}["c2187"]
    assert (moro.name, moro.name_en, moro.element, moro.role, moro.rarity, moro.zodiac) == (
        "兔女郎名侦探茉萝", "Bunny Girl Great Detective Moro", "light", "assassin", 5, "maiden")
    assert moro.stats == {"atk": 1075, "hp": 5562, "def": 487, "spd": 128, "chc": 0.15}  # 没有战斗力
    assert moro.released == "2026-10-29" and moro.aliases == ["moluo", "茉萝"]
    assert moro.slug == MORO_CARD["code"] and moro.source == "wiki"
    assert (tmp_path / "icons" / "c2187.png").read_bytes().startswith(b"\x89PNG")  # webp 转成了 PNG

    # e7.wiki 没连上：以前补上的新英雄留着
    file = read_hero_file(tmp_path / "heroes.json")
    res2 = update_heroes(tmp_path, file, fetch=FakeFetch(_herodata_with_slugs()))
    assert res2.wiki_error and not res2.changed and res2.wiki_only == ["c2187"]

    # Fribbels 有了：换成 Fribbels 的数据（有战斗力）
    data = _herodata_with_slugs()
    data["Bunny Girl Great Detective Moro"] = {**_fribbels("Bunny Girl Great Detective Moro", "c2187",
                                                           role="assassin"), "_id": MORO_CARD["code"]}
    res3 = update_heroes(tmp_path, file, fetch=_moro_fetch(data))
    assert res3.wiki_only == [] and res3.modified == ["c2187"]
    moro = {h.code: h for h in read_hero_file(tmp_path / "heroes.json").heroes}["c2187"]
    assert moro.name == "兔女郎名侦探茉萝" and moro.stats["cp"] == 22755 and moro.source == ""


def test_update_keeps_release_without_detail(tmp_path):
    update_heroes(tmp_path, None, fetch=_wiki_fetch(_herodata_with_slugs()))
    file = read_hero_file(tmp_path / "heroes.json")
    (tmp_path / "details" / "c2111.json").unlink()  # 详情没了（比如这次下载失败）：沿用现有的发布日期
    fetch = _wiki_fetch(_herodata_with_slugs())
    fetch.files.pop(hero_update.WIKI_ASSETS + "/static/heroes/solitaria-of-the-snow.json")
    res = update_heroes(tmp_path, file, fetch=fetch)
    assert res.detail_failed == ["c2111"] and not res.changed
    assert {h.code: h.released for h in read_hero_file(tmp_path / "heroes.json").heroes}["c2111"] == "2021-04-15"


def test_search_orders_by_release():
    heroes = [HEROES[0].model_copy(update={"code": "c9001", "name": "甲一", "released": "2020-01-01"}),
              HEROES[0].model_copy(update={"code": "c9002", "name": "甲二", "released": "2026-01-01"}),
              HEROES[0].model_copy(update={"code": "c9003", "name": "甲三", "released": ""})]
    from e7helper.core.data import HeroDB
    db = HeroDB(HeroFile(heroes=heroes))
    assert [h.code for h in db.search("甲")] == ["c9002", "c9001", "c9003"]


def test_update_detail_failure(tmp_path):
    fetch = _wiki_fetch(_herodata_with_slugs())
    fetch.files[hero_update.WIKI_ASSETS + "/static/heroes/mei-lin.json"] = b"<html>"
    res = update_heroes(tmp_path, None, fetch=fetch)
    assert res.details == 1 and res.detail_failed == ["c1191"]


def test_full_sets():
    assert full_sets({"set_speed": "4", "set_acc": "2"}) == {"set_speed": 4, "set_acc": 2}
    assert full_sets({"set_speed": "3", "set_acc": "3"}) == {"set_acc": 2}  # 四件套只有 3 件不算
    assert full_sets({"set_immune": 6}) == {"set_immune": 6}
    assert full_sets({"set_cri": 5, "set_x": "?"}) == {"set_cri": 4}


ROWS = [
    {"artifactCode": "efm19", "sets": {"set_speed": "4", "set_acc": "2"}, "spd": 250, "atk": 1800, "gs": 450,
     "createDate": "2026-07-01"},
    {"artifactCode": "efm19", "sets": {"set_acc": "2", "set_speed": "4"}, "spd": 240, "atk": "1900", "gs": 440,
     "createDate": "2026-10-20"},
    {"artifactCode": "efm05", "sets": {"set_speed": "4", "set_immune": "2"}, "spd": 230, "atk": 2000, "gs": 430},
]


def test_summarize():
    s = summarize([dict(r) for r in ROWS], {"efm19": {"name": "噩梦童话"}})
    assert s["total"] == 3 and s["latest"] == "2026-10-20" and s["stats"]["spd"] == 240
    c0 = s["combos"][0]
    assert c0["sets"] == [{"set": "set_speed", "pieces": 4}, {"set": "set_acc", "pieces": 2}]
    assert (c0["count"], c0["share"], c0["stats"]["spd"], c0["stats"]["atk"]) == (2, 0.6667, 245, 1850)
    assert c0["artifacts"] == [{"code": "efm19", "name": "噩梦童话", "count": 2, "share": 1.0}]
    assert s["artifacts"][1] == {"code": "efm05", "name": "", "count": 1, "share": 0.3333}
    assert c0["stats"]["gear"] == 74.2  # 装备均分 = (450 + 440) / 2 / 6
    assert c0["speed_set"] and c0["tiers"] == []  # 份数太少不分档


def test_summarize_tiers_and_median():
    # 不带速度套：按速度三等分；属性用中位数（一份极端配置不影响）
    rows = [{"sets": {"set_counter": "4", "set_immune": "2"}, "spd": spd, "hp": 20000 + spd, "gs": 420}
            for spd in (100, 110, 120, 130, 140, 150, 160, 170, 180)]
    rows.append({"sets": {"set_counter": "4", "set_immune": "2"}, "spd": 400, "hp": 1, "gs": 420})
    s = summarize(rows, {})
    c = s["combos"][0]
    assert not c["speed_set"]
    assert [(t["tier"], t["count"]) for t in c["tiers"]] == [("fast", 3), ("mid", 4), ("slow", 3)]
    assert [t["stats"]["spd"] for t in c["tiers"]] == [180, 145, 110]  # 快速档 400/180/170 的中位数是 180
    assert c["stats"]["hp"] == 20135 and c["stats"]["gear"] == 70.0  # 那份 hp=1 的极端配置不会把中位数拉低多少
    # 份数太少不分档
    assert summarize(rows[:5], {})["combos"][0]["tiers"] == []


def test_summarize_speed_set_tops():
    # 带速度套：前 10% / 前 25%（按速度最快的那些配装）/ 全部
    rows = [{"sets": {"set_speed": "4", "set_acc": "2"}, "spd": 200 + i, "hp": 30000 - i, "gs": 420} for i in range(20)]
    c = summarize(rows, {})["combos"][0]
    assert c["speed_set"]
    assert [(t["tier"], t["count"]) for t in c["tiers"]] == [("top10", 2), ("top25", 5), ("all", 20)]
    assert [t["stats"]["spd"] for t in c["tiers"]] == [218, 217, 210]  # 中位数：218.5 / 217 / 209.5 四舍五入


def test_get_builds_cache(tmp_path):
    hero = HEROES[0]
    calls = []

    def fetch(name):
        calls.append(name)
        return json.dumps({"data": ROWS}).encode()

    a = get_builds(hero, tmp_path, {}, fetch=fetch, now=1000)
    assert a["total"] == 3 and a["fetched"] == 1000 and calls == [hero.name_en]
    # 旧格式的缓存作废
    old = json.loads((tmp_path / f"{hero.code}.json").read_text(encoding="utf-8"))
    (tmp_path / f"{hero.code}.json").write_text(json.dumps({**old, "format": 1}), encoding="utf-8")
    assert get_builds(hero, tmp_path, {}, fetch=fetch, now=1000)["format"] == hero_builds.CACHE_FORMAT and len(calls) == 2
    calls.pop()
    assert get_builds(hero, tmp_path, {}, fetch=fetch, now=1000 + 3600)["fetched"] == 1000  # 一天内用缓存
    assert len(calls) == 1
    get_builds(hero, tmp_path, {}, fetch=fetch, now=2000, refresh=True)
    assert len(calls) == 2

    def broken(name):
        raise BuildsError("断网")

    stale = get_builds(hero, tmp_path, {}, fetch=broken, now=10 ** 6)  # 过期又下载失败：用旧的
    assert stale["stale"] is True and stale["total"] == 3
    with pytest.raises(BuildsError):
        get_builds(HEROES[1], tmp_path, {}, fetch=broken)
    with pytest.raises(BuildsError, match="格式"):
        get_builds(HEROES[1], tmp_path, {}, fetch=lambda n: b'{"rows": 1}')


@pytest.fixture
def wiki_client(tmp_path):
    update_heroes(_bundled(tmp_path), None, fetch=_wiki_fetch(_herodata_with_slugs()))
    engine = make_engine(tmp_path, detector=None)
    app = create_app(engine, token=TOKEN, start_scheduler=False, autoconnect=False)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        yield c


def test_api_detail_and_icons(wiki_client):
    d = wiki_client.get("/api/heroes").json()
    assert d["labels"]["set"]["set_speed"] == "速度" and d["labels"]["stat"]["acc"] == "效果命中"
    det = wiki_client.get("/api/heroes/c2111/detail").json()
    assert det["skills"][0]["name"] == "咻呜呜" and det["self_devotion"]["type"] == "acc"
    assert wiki_client.get("/api/heroes/c1001/detail").json()["error"]["code"] == "no_detail"
    r = wiki_client.get(f"/api/hero-icons/sk_c2111_1.webp?token={TOKEN}", headers={"Authorization": ""})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and r.content == WEBP
    assert wiki_client.get("/api/hero-icons/nope.webp").json()["error"]["code"] == "no_icon"
    assert wiki_client.get("/api/hero-icons/..%2Fheroes.json").status_code == 404


def test_api_builds(wiki_client, monkeypatch):
    monkeypatch.setattr(hero_builds, "post_builds", lambda name: json.dumps({"data": ROWS}).encode())
    d = wiki_client.get("/api/heroes/c2111/builds").json()
    assert d["total"] == 3 and d["combos"][0]["artifacts"][0]["name"] == "噩梦童话"

    def broken(name):
        raise BuildsError("配装数据下载失败：断网")

    monkeypatch.setattr(hero_builds, "post_builds", broken)
    r = wiki_client.get("/api/heroes/c1001/builds")
    assert r.status_code == 502 and r.json()["error"]["code"] == "builds_failed"


def test_api_artifact_icon(wiki_client, tmp_path, monkeypatch):
    got = []

    class Fetcher:
        def __call__(self, url):
            got.append(url)
            if url.endswith("efm19_ico.png") or url.endswith("item_arti/icon_art5_5.png"):
                return PNG
            raise UpdateError("403")

    monkeypatch.setattr(hero_update, "MirrorFetcher", Fetcher)
    assert wiki_client.get("/api/artifacts/efm19/icon").content == PNG
    assert wiki_client.get("/api/artifacts/efm19/icon").content == PNG and len(got) == 1  # 第二次用缓存
    assert (_user(tmp_path) / "artifacts" / "efm19.png").is_file()
    # 官方指南站没有的新神器：用神器表里的 e7.wiki 图标名去 e7.wiki 取
    got.clear()
    assert wiki_client.get("/api/artifacts/efm05/icon").content == PNG
    assert got == [ARTIFACT_URL.format(code="efm05"), hero_update.WIKI_ARTIFACT_ICON.format(icon="icon_art5_5")]
    r = wiki_client.get("/api/artifacts/efm99/icon")
    assert r.status_code == 502 and r.json()["error"]["code"] == "icon_failed"
    assert wiki_client.get("/api/artifacts/a.b/icon").status_code == 404
