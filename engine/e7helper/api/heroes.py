"""英雄数据库接口（B13，GUI「英雄图鉴」页用）。要 token。

| 路由 | 说明 |
|---|---|
| `GET /heroes` | 全部英雄 + 数据来源 / 更新时间 + 属性、职业、星座、套装、属性类型的中文名 |
| `GET /heroes/{code}` | 一名英雄；没有 404 `unknown_hero` |
| `GET /heroes/{code}/icon` | 头像 PNG（`<img>` 用 `?token=`）；没有 404 `no_icon` |
| `GET /heroes/{code}/detail` | 技能、角色奉献、专属装备；没有 404 `no_detail` |
| `GET /heroes/{code}/builds?refresh=` | Fribbels 配装统计（联网，缓存一天）；下载失败 502 `builds_failed` |
| `GET /hero-icons/{name}` | 技能 / 效果 / 专属装备图标（文件名见详情）；没有 404 `no_icon` |
| `GET /artifacts/{code}/icon` | 神器图标（第一次用时下载并缓存：先官方指南站，没有再 e7.wiki）；都失败 502 `icon_failed` |
| `POST /heroes/update` | 联网更新（几秒到几分钟）；正在更新 409 `busy`，下载失败 502 `update_failed` |
"""

from __future__ import annotations

import re
import threading

from fastapi import APIRouter
from fastapi.responses import FileResponse

from e7helper.core.data import (
    ELEMENT_LABELS, ROLE_LABELS, SET_LABELS, STAT_LABELS, ZODIAC_LABELS, Hero, heroes, reload_heroes,
)
from e7helper.core.data import hero_builds, hero_update
from e7helper.core.data.hero_db import DATA_NAME, PERCENT_STATS
from e7helper.core.paths import user_data_dir

from .engine import ApiError

ARTIFACT_ICON_URL = "https://static.smilegatemegaport.com/event/live/epic7/guide/wearingStatus/images/artifact/{code}_ico.png"
_SAFE = re.compile(r"^[A-Za-z0-9_\-]+$")
CACHED = {"Cache-Control": "max-age=86400"}


def _hero_dict(h: Hero, has_icon: bool) -> dict:
    return {**h.model_dump(), "icon": has_icon}


def _cached_download(path, url: str, magic: tuple[bytes, ...], code: str, what: str):
    """有缓存直接用，否则下载、校验文件头后存下来。"""
    if not path.is_file():
        try:
            data = hero_update.MirrorFetcher()(url)
        except hero_update.UpdateError as e:
            raise ApiError(502, code, f"{what}下载失败：{e}") from e
        if not data.startswith(magic):
            raise ApiError(502, code, f"{what}下载失败：文件不对")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path


def build_heroes_router() -> APIRouter:
    r = APIRouter(tags=["英雄数据库"])
    updating = threading.Lock()

    def get_hero(code: str) -> Hero:
        h = heroes().get(code)
        if h is None:
            raise ApiError(404, "unknown_hero", f"没有这名英雄：{code}")
        return h

    @r.get("/heroes", summary="全部英雄")
    def list_heroes() -> dict:
        db = heroes()
        return {
            "source": db.source, "origin": db.origin, "updated": db.updated, "count": len(db),
            "labels": {"element": ELEMENT_LABELS, "role": ROLE_LABELS, "zodiac": ZODIAC_LABELS, "set": SET_LABELS,
                       "stat": STAT_LABELS, "percent_stats": sorted(PERCENT_STATS)},
            "heroes": [_hero_dict(h, db.icon_path(h.code) is not None) for h in db],
        }

    @r.get("/heroes/{code}", summary="一名英雄")
    def get_one(code: str) -> dict:
        h = get_hero(code)
        return _hero_dict(h, heroes().icon_path(code) is not None)

    @r.get("/heroes/{code}/icon", summary="头像 PNG")
    def icon(code: str):
        get_hero(code)
        p = heroes().icon_path(code)
        if p is None:
            raise ApiError(404, "no_icon", f"没有这名英雄的头像：{code}")
        return FileResponse(p, media_type="image/png", headers=CACHED)

    @r.get("/heroes/{code}/detail", summary="技能、角色奉献、专属装备")
    def detail(code: str) -> dict:
        get_hero(code)
        det = heroes().detail(code)
        if det is None:
            raise ApiError(404, "no_detail", f"没有这名英雄的详情：{code}")
        return det.model_dump()

    @r.get("/heroes/{code}/builds", summary="Fribbels 配装统计")
    def builds(code: str, refresh: bool = False) -> dict:
        h = get_hero(code)
        db = heroes()
        try:
            return hero_builds.get_builds(h, user_data_dir(DATA_NAME) / "builds", db.artifacts(), refresh=refresh)
        except hero_builds.BuildsError as e:
            raise ApiError(502, "builds_failed", str(e)) from e

    @r.get("/hero-icons/{name}", summary="技能 / 效果 / 专属装备图标")
    def detail_icon(name: str):
        p = heroes().detail_icon_path(name)
        if p is None:
            raise ApiError(404, "no_icon", f"没有这个图标：{name}")
        return FileResponse(p, media_type="image/webp" if p.suffix == ".webp" else "image/png", headers=CACHED)

    @r.get("/artifacts/{code}/icon", summary="神器图标")
    def artifact_icon(code: str):
        if not _SAFE.match(code):
            raise ApiError(404, "no_icon", f"没有这个神器：{code}")
        # 先试官方指南站；新神器那里没有（403），再用 e7.wiki 的（神器表里存了它的图标名）
        urls = [ARTIFACT_ICON_URL.format(code=code)]
        icon = (heroes().artifacts().get(code) or {}).get("icon", "")
        if icon and _SAFE.match(icon):
            urls.append(hero_update.WIKI_ARTIFACT_ICON.format(icon=icon))
        path = user_data_dir(DATA_NAME) / "artifacts" / f"{code}.png"
        for i, url in enumerate(urls):
            try:
                path = _cached_download(path, url, (b"\x89PNG",), "icon_failed", "神器图标")
                break
            except ApiError:
                if i == len(urls) - 1:
                    raise
        return FileResponse(path, media_type="image/png", headers=CACHED)

    @r.post("/heroes/update", summary="联网更新英雄数据")
    def update() -> dict:
        if not updating.acquire(blocking=False):
            raise ApiError(409, "busy", "正在更新")
        try:
            db = heroes()
            target = user_data_dir(DATA_NAME)
            try:
                res = hero_update.update_heroes(target, db.file, fetch=hero_update.MirrorFetcher(),
                                                other_dirs=[d for d in db.dirs if d != target])
            except hero_update.UpdateError as e:
                raise ApiError(502, "update_failed", str(e)) from e
            if res.changed or res.icons or res.details or res.detail_icons:
                db = reload_heroes()
            return {**res.to_dict(), "count": len(db), "origin": db.origin}
        finally:
            updating.release()

    return r
