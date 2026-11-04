"""英雄数据联网更新（B13）：拉 Fribbels 和 e7.wiki 的数据，转换成 heroes.json + 详情 + 神器表。

Fribbels 优化器仓库 https://github.com/fribbels/Fribbels-Epic-7-Optimizer：
- `data/cache/herodata.json`：英文名 → 编号、属性、职业、星级、星座、满觉醒属性（我们只取这几项）；
- `data/cache/artifactdata.json`：神器英文名 → 编号；
- `data/locales/zh/translation.json`：英文名 → 简中名（英雄、神器；和国服一致，B13 用户确认）；
- `data/cachedimages/<编号>_s.png`：头像（112×112）。
国内直连 raw.githubusercontent.com 不稳定，依次试 GitHub 原地址和 jsDelivr 镜像。

e7.wiki（国服中文站，B13 审核后用户同意用它的公开数据）：
- `admin.e7.wiki/api/open/epicseven/hero/card-list`：全部英雄的中文名、昵称（含拼音）、更新时间；
- `assets2.e7.wiki/static/heroes/<slug>.json`：技能、角色奉献、专属装备等（转换见 hero_detail.py）；
  slug 就是 Fribbels 的 `_id`。角色列表里的更新时间没变就不重新下载。
e7.wiki 连不上时只更新 Fribbels 那部分，名字用 Fribbels 的简中名。

刚出的英雄 Fribbels 往往要晚几天才有（B14h：兔女郎名侦探茉萝），e7.wiki 角色列表里有、Fribbels 还没有的
`c` 开头英雄用 e7.wiki 详情里的英文名 / 属性补上（`UpdateResult.wiki_only`），头像用 e7.wiki 的
`static/avatar/<编号>_s.webp`（转成 PNG）；Fribbels 有了以后自动换成 Fribbels 的数据。

随包数据也用这里生成：`e7helper heroes --update --bundled`（开发用，写进 assets/data/heroes/）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from e7helper import __version__

from .hero_db import (
    ARTIFACTS_FILE, DATA_FILE, DETAIL_ICONS_DIR, DETAILS_DIR, ICONS_DIR, STAT_KEYS, Hero, HeroFile, dump_hero_file,
    name_key,
)
from .hero_detail import HeroDetail, convert_detail, icon_name

log = logging.getLogger(__name__)

MIRRORS = (
    "https://raw.githubusercontent.com/fribbels/Fribbels-Epic-7-Optimizer/main/",
    "https://cdn.jsdelivr.net/gh/fribbels/Fribbels-Epic-7-Optimizer@main/",
)
HERODATA_PATH = "data/cache/herodata.json"
ARTIFACTDATA_PATH = "data/cache/artifactdata.json"
ZH_PATH = "data/locales/zh/translation.json"
ICON_PATH = "data/cachedimages/{code}_s.png"
WIKI_CARDS_URL = "https://admin.e7.wiki/api/open/epicseven/hero/card-list"
WIKI_ASSETS = "https://assets2.e7.wiki"
WIKI_HERO_PATH = "/static/heroes/{slug}.json"
WIKI_AVATAR = WIKI_ASSETS + "/static/avatar/{code}_s.webp"
WIKI_ARTIFACTS_URL = "https://admin.e7.wiki/api/open/epicseven/artifact/artifact-list"
WIKI_ARTIFACT_ICON = WIKI_ASSETS + "/arts/assets/item_arti/{icon}.png"
STATS_KEY = "lv60SixStarFullyAwakened"
HERO_CODE_PREFIX = "c"  # 可以抽到的英雄；m 开头的是愚人节的怪物英雄
TIMEOUT = 20
WORKERS = 8
# 新数据比现有的少一成以上就当作来源出了问题，不覆盖
MIN_KEEP_RATIO = 0.9
# 头像连续失败这么多次就不再试，剩下的都记为失败（下次更新再补）
MAX_ICON_FAILS = 5

Fetch = Callable[[str], bytes]


class UpdateError(Exception):
    pass


class MirrorFetcher:
    """相对路径按顺序试几个镜像（记住上次成功的那个，后面的请求先试它）；以 https:// 开头的直接下载。"""

    def __init__(self, mirrors: Sequence[str] = MIRRORS, timeout: float = TIMEOUT):
        self.mirrors = list(mirrors)
        self.timeout = timeout
        self._lock = threading.Lock()

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": f"e7helper/{__version__}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def __call__(self, path: str) -> bytes:
        if path.startswith("https://"):
            try:
                return self._get(path)
            except Exception as e:  # noqa: BLE001
                raise UpdateError(f"下载失败（{path.split('/')[2]}：{e}）") from e
        errors = []
        with self._lock:
            mirrors = list(self.mirrors)
        for base in mirrors:
            try:
                data = self._get(base + path)
            except Exception as e:  # noqa: BLE001 —— 网络错误种类很多，换下一个镜像
                errors.append(f"{base.split('/')[2]}：{e}")
                continue
            with self._lock:
                if self.mirrors[0] != base and base in self.mirrors:
                    self.mirrors.remove(base)
                    self.mirrors.insert(0, base)
            return data
        raise UpdateError("下载失败（" + "；".join(errors) + "）")


def _aliases(card: dict | None, name: str) -> list[str]:
    if not card:
        return []
    out: list[str] = []
    for a in str(card.get("nicknames") or "").replace("，", ",").split(","):
        a = a.strip()
        if a and a != name and a not in out:
            out.append(a)
    return out


def convert(herodata: dict, zh: dict, cards: dict[str, dict] | None = None) -> tuple[list[Hero], list[str]]:
    """Fribbels 的 herodata + 简中翻译 + e7.wiki 角色列表（编号 → 卡片）→ 英雄列表（按编号排序）和没有中文名的英文名。

    中文名优先用 e7.wiki 的，其次 Fribbels 简中，都没有用英文名；别名来自 e7.wiki 的昵称。
    只收 c 开头的编号：m 开头的是愚人节活动的怪物英雄（侦查兵玛伊堤、野生安卡拉），不要（B13 用户意见）。
    """
    cards = cards or {}
    out: dict[str, Hero] = {}
    missing: list[str] = []
    for en, v in herodata.items():
        if not isinstance(v, dict) or not all(v.get(k) for k in ("code", "attribute", "role", "rarity")):
            log.warning("英雄数据缺字段，跳过：%s", en)
            continue
        if not v["code"].startswith(HERO_CODE_PREFIX):
            continue
        card = cards.get(v["code"])
        name = (card or {}).get("name") or zh.get(en)
        if not isinstance(name, str) or not name.strip():
            name = en
            missing.append(en)
        name = name.strip()
        raw_stats = (v.get("calculatedStatus") or {}).get(STATS_KEY) or {}
        stats = {k: raw_stats[k] for k in STAT_KEYS if isinstance(raw_stats.get(k), (int, float))}
        out[v["code"]] = Hero(
            code=v["code"], name=name, name_en=v.get("name") or en, aliases=_aliases(card, name),
            element=v["attribute"], role=v["role"], rarity=int(v["rarity"]), zodiac=v.get("zodiac") or "",
            stats=stats, slug=v.get("_id") or "",
        )
    return [out[c] for c in sorted(out)], missing


def wiki_hero(card: dict, raw: dict) -> Hero:
    """e7.wiki 角色列表的一张卡片 + 这名英雄的详情 JSON → Hero（Fribbels 还没有的新英雄用）。
    卡片的属性 / 职业 / 星级 / 星座 / slug 和 Fribbels 的叫法一样（B14h 核对过全部 389 名）；属性没有战斗力。"""
    name = str(card["name"]).strip()
    raw_stats = raw.get("stats") or {}
    return Hero(
        code=card["face_id"], name=name, name_en=str(raw.get("nameEn") or "").strip() or str(card["code"]),
        aliases=_aliases(card, name), element=card["attribute"], role=card["role"], rarity=int(card["rarity"]),
        zodiac=card.get("zodiac") or "", slug=str(card["code"]), source="wiki",
        stats={k: raw_stats[k] for k in STAT_KEYS if isinstance(raw_stats.get(k), (int, float))},
    )


def _wiki_only(cards: dict[str, dict], known: set[str], fetch: Fetch) -> list[Hero]:
    """e7.wiki 有、Fribbels 还没有的英雄（只收 c 开头的）；详情下载失败的这次先不加。"""
    out = []
    for code, card in sorted(cards.items()):
        if code in known or not code.startswith(HERO_CODE_PREFIX):
            continue
        if not all(card.get(k) for k in ("name", "code", "attribute", "role", "rarity")):
            continue
        try:
            raw = json.loads(fetch(WIKI_ASSETS + WIKI_HERO_PATH.format(slug=card["code"])))
            out.append(wiki_hero(card, raw if isinstance(raw, dict) else {}))
        except (UpdateError, ValueError, KeyError, TypeError) as e:
            log.warning("e7.wiki 新英雄 %s 的详情下载失败，这次先不加：%s", code, e)
    return out


def convert_artifacts(artifactdata: dict, zh: dict, wiki: list[dict] | None = None) -> dict[str, dict]:
    """Fribbels 的神器数据 + 简中翻译 → 编号 → {name, name_en, icon?}。

    icon 是 e7.wiki 神器列表里的图标名（例如 icon_art0243），按英文名对，对不上再按中文名对；
    官方指南站没有新神器的图标，显示时用它从 e7.wiki 取（见 api/heroes.py）。
    """
    by_en, by_zh = {}, {}
    for a in wiki or []:
        if isinstance(a, dict) and a.get("icon"):
            by_en.setdefault(name_key(str(a.get("name_en") or "")), a["icon"])
            by_zh.setdefault(name_key(str(a.get("name") or "")), a["icon"])
    out = {}
    for en, v in artifactdata.items():
        if isinstance(v, dict) and v.get("code"):
            name = zh.get(en)
            name = name.strip() if isinstance(name, str) and name.strip() else en
            row = {"name": name, "name_en": en}
            icon = by_en.get(name_key(en)) or by_zh.get(name_key(name))
            if icon:
                row["icon"] = icon
            out[v["code"]] = row
    return dict(sorted(out.items()))


@dataclass
class UpdateResult:
    changed: bool  # heroes.json 是否写了新内容
    total: int
    added: list[str] = field(default_factory=list)  # 新英雄的编号
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)  # 数据有变化的编号
    icons: int = 0  # 新下载的头像数
    icon_failed: list[str] = field(default_factory=list)
    missing_names: list[str] = field(default_factory=list)  # 没有中文名、先用英文名的
    wiki_only: list[str] = field(default_factory=list)  # Fribbels 还没有、用 e7.wiki 数据补上的（B14h）
    details: int = 0  # 新下载 / 更新的详情数
    detail_icons: int = 0
    detail_failed: list[str] = field(default_factory=list)
    wiki_error: str = ""  # e7.wiki 角色列表下载失败的原因（这次没更新详情）
    updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _exists(rel: str, dirs: Iterable[Path]) -> bool:
    return any((d / rel).is_file() for d in dirs)


def _read_detail(rel: str, dirs: Iterable[Path]) -> HeroDetail | None:
    best = None
    for d in dirs:
        p = d / rel
        if p.is_file():
            try:
                det = HeroDetail.model_validate_json(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if best is None or det.source_updated > best.source_updated:
                best = det
    return best


def _fetch_cards(fetch: Fetch) -> dict[str, dict]:
    raw = json.loads(fetch(WIKI_CARDS_URL))
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list) or not data:
        raise UpdateError("e7.wiki 角色列表格式不对")
    return {c["face_id"]: c for c in data if isinstance(c, dict) and c.get("face_id")}


def update_heroes(target: Path, current: HeroFile | None, *, fetch: Fetch | None = None,
                  other_dirs: Sequence[Path] = (), icons: bool = True, details: bool = True) -> UpdateResult:
    """拉最新数据，和 current 比对，有变化就写进 target/heroes.json；再补下载 target 和 other_dirs 里都没有的
    头像、详情（e7.wiki 更新时间变了的重新下载）和详情图标；神器表有变化就写 target/artifacts.json。

    current 是现在在用的原始数据（不含 overrides），可能来自随包目录（这时 other_dirs 里有随包目录）。
    """
    fetch = fetch or MirrorFetcher()
    try:
        herodata = json.loads(fetch(HERODATA_PATH))
        zh = json.loads(fetch(ZH_PATH))
    except ValueError as e:
        raise UpdateError(f"下载的数据不是 JSON：{e}") from e
    if not isinstance(herodata, dict) or not isinstance(zh, dict):
        raise UpdateError("下载的数据格式不对")
    dirs = [target, *other_dirs]

    cards: dict[str, dict] = {}
    wiki_error = ""
    if details:
        try:
            cards = _fetch_cards(fetch)
        except (UpdateError, ValueError, KeyError, TypeError) as e:
            wiki_error = str(e)
            log.warning("e7.wiki 角色列表下载失败，这次只更新 Fribbels 的数据：%s", e)

    heroes, missing = convert(herodata, zh, cards)
    old = {h.code: h for h in (current.heroes if current else [])}
    n_old = sum(h.source != "wiki" for h in old.values())  # 和现有的 Fribbels 数据比（e7.wiki 补的不算）
    if not heroes or len(heroes) < n_old * MIN_KEEP_RATIO:
        raise UpdateError(f"下载的数据只有 {len(heroes)} 名英雄（现有 {n_old} 名），没有覆盖")
    fribbels = {h.code for h in heroes}
    if cards:
        heroes += _wiki_only(cards, fribbels, fetch)
    elif old:
        # e7.wiki 没连上：沿用现有的中文名和昵称，别因为这次缺数据把它们改回 Fribbels 的；
        # 以前从 e7.wiki 补上的新英雄（Fribbels 还没有）也留着
        heroes = [h.model_copy(update={"name": old[h.code].name, "aliases": old[h.code].aliases})
                  if h.code in old else h for h in heroes]
        heroes += [h for c, h in old.items() if c not in fribbels and h.source == "wiki"]
        missing = [en for en in missing if not any(h.name_en == en and h.name != en for h in heroes)]
    heroes.sort(key=lambda h: h.code)

    res = UpdateResult(changed=False, total=len(heroes), missing_names=missing, wiki_error=wiki_error,
                       updated=current.updated if current else "",
                       wiki_only=[h.code for h in heroes if h.source == "wiki"])
    # 详情先更新：发布日期来自详情，要写进 heroes.json（列表按发布日期排序，不用读详情文件）
    if cards:
        _update_details(target, dirs, fetch, heroes, cards, res, icons)
    heroes = [_with_release(h, dirs, old.get(h.code)) for h in heroes]

    new = {h.code: h for h in heroes}
    res.added = [c for c in new if c not in old]
    res.removed = [c for c in old if c not in new]
    res.modified = [c for c in new if c in old and new[c] != old[c]]
    if res.added or res.removed or res.modified or current is None:
        res.updated = datetime.now(UTC).replace(microsecond=0).isoformat()
        file = HeroFile(updated=res.updated, heroes=heroes)
        _write_atomic(target / DATA_FILE, dump_hero_file(file).encode("utf-8"))
        res.changed = True
        log.info("英雄数据已更新：%d 名（新增 %d、删除 %d、变化 %d）", res.total, len(res.added),
                 len(res.removed), len(res.modified))

    _update_artifacts(target, dirs, fetch, zh, wiki=bool(cards))
    if icons:
        _update_icons(target, dirs, fetch, heroes, res)
    return res


def _with_release(h: Hero, dirs: Sequence[Path], old: Hero | None) -> Hero:
    """发布日期取详情里的（e7.wiki 的 releaseDate）；没有详情时沿用现有的。"""
    det = _read_detail(f"{DETAILS_DIR}/{h.code}.json", dirs)
    released = det.release_date if det and det.release_date else (old.released if old else "")
    return h.model_copy(update={"released": released}) if released != h.released else h


def _update_artifacts(target: Path, dirs: Sequence[Path], fetch: Fetch, zh: dict, wiki: bool) -> None:
    wiki_list = None
    if wiki:
        try:
            raw = json.loads(fetch(WIKI_ARTIFACTS_URL))
            wiki_list = raw.get("data") if isinstance(raw, dict) else None
        except (UpdateError, ValueError) as e:
            log.warning("e7.wiki 神器列表下载失败，图标名沿用现有的：%s", e)
    try:
        arts = convert_artifacts(json.loads(fetch(ARTIFACTDATA_PATH)), zh, wiki_list)
    except (UpdateError, ValueError, AttributeError) as e:
        log.warning("神器数据下载失败：%s", e)
        return
    merged: dict = {}
    for d in reversed(dirs):
        p = d / ARTIFACTS_FILE
        if p.is_file():
            try:
                merged.update(json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                pass
    for k, v in arts.items():  # e7.wiki 这次没拿到的，沿用现有的图标名
        if "icon" not in v and (merged.get(k) or {}).get("icon"):
            v["icon"] = merged[k]["icon"]
    if arts and arts != {k: merged.get(k) for k in arts}:
        rows = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in arts.items())
        _write_atomic(target / ARTIFACTS_FILE, ("{\n" + rows + "\n}\n").encode("utf-8"))  # 一件一行
        log.info("神器表已更新：%d 件", len(arts))


def _update_icons(target: Path, dirs: Sequence[Path], fetch: Fetch, heroes: list[Hero], res: UpdateResult) -> None:
    streak = 0  # 连续失败次数：网络断了就别每个都等超时
    for h in heroes:
        if _exists(f"{ICONS_DIR}/{h.code}.png", dirs):
            continue
        if streak >= MAX_ICON_FAILS:
            res.icon_failed.append(h.code)
            continue
        try:
            png = fetch(ICON_PATH.format(code=h.code))
        except UpdateError as e:
            log.warning("头像下载失败 %s：%s", h.code, e)
            png = b""
        if not png.startswith(b"\x89PNG"):  # Fribbels 还没有（刚出的英雄）：用 e7.wiki 的
            png = _wiki_avatar(fetch, h.code)
        if not png.startswith(b"\x89PNG"):
            res.icon_failed.append(h.code)
            streak += 1
            continue
        streak = 0
        _write_atomic(target / ICONS_DIR / f"{h.code}.png", png)
        res.icons += 1


def _wiki_avatar(fetch: Fetch, code: str) -> bytes:
    """e7.wiki 的头像（webp，112×112）→ PNG；没有 / 解不开返回 b""。"""
    import cv2
    import numpy as np

    try:
        data = fetch(WIKI_AVATAR.format(code=code))
    except UpdateError as e:
        log.warning("e7.wiki 头像下载失败 %s：%s", code, e)
        return b""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return b""
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else b""


def _update_details(target: Path, dirs: Sequence[Path], fetch: Fetch, heroes: list[Hero],
                    cards: dict[str, dict], res: UpdateResult, icons: bool) -> None:
    todo = []
    for h in heroes:
        card = cards.get(h.code)
        if not card or not h.slug:
            continue
        cur = _read_detail(f"{DETAILS_DIR}/{h.code}.json", dirs)
        if cur is None or cur.source_updated != str(card.get("update_time") or ""):
            todo.append((h, str(card.get("update_time") or "")))

    def one(item: tuple[Hero, str]) -> tuple[str, HeroDetail | None, list[str]]:
        h, updated = item
        try:
            raw = json.loads(fetch(WIKI_ASSETS + WIKI_HERO_PATH.format(slug=h.slug)))
            det, need = convert_detail(h.code, raw, updated)
        except (UpdateError, ValueError, AttributeError, TypeError) as e:
            log.warning("详情下载失败 %s：%s", h.code, e)
            return h.code, None, []
        _write_atomic(target / DETAILS_DIR / f"{h.code}.json",
                      (det.model_dump_json(exclude_defaults=True) + "\n").encode("utf-8"))
        return h.code, det, need

    need_icons: list[str] = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for code, det, need in pool.map(one, todo):
            if det is None:
                res.detail_failed.append(code)
            else:
                res.details += 1
                need_icons += need
    if res.details:
        log.info("英雄详情已更新：%d 名", res.details)
    if not icons:
        return
    missing = [u for u in dict.fromkeys(need_icons) if not _exists(f"{DETAIL_ICONS_DIR}/{icon_name(u)}", dirs)]

    def icon(url: str) -> bool:
        try:
            data = fetch(WIKI_ASSETS + url)
        except UpdateError as e:
            log.warning("图标下载失败 %s：%s", url, e)
            return False
        if not (data.startswith(b"RIFF") or data.startswith(b"\x89PNG")):
            return False
        _write_atomic(target / DETAIL_ICONS_DIR / icon_name(url), data)
        return True

    with ThreadPoolExecutor(WORKERS) as pool:
        res.detail_icons = sum(pool.map(icon, missing))
