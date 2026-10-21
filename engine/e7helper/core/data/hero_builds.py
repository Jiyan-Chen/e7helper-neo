"""英雄配装方案（B13 审核后加）：Fribbels 配装库（fribbels.github.io/e7/hero-library）的玩家配装统计。

接口按英雄英文名返回玩家上传的全部配装（几百到几千条，热门英雄约 700KB；只收高分装备，装备分相差不大），这里汇总成：
套装组合（按件数换算成完整套装）的占比、属性中位数、组合里常用的神器，以及全部配装的神器占比。
属性用中位数不用平均值：同一个组合里既有配一速的也有配慢速的，平均值两头都不像（B13 审核意见）。
- 带速度套的组合：用速度套的都在追速度，看「前 10% / 前 25% / 全部」三行（按速度最快的那部分配装，各给份数和属性中位数，冲一速时参考）；
- 不带速度套的组合：按速度三等分成快速 / 中速 / 慢速三档，每档各给份数和属性中位数（份数太少不分档）。
装备分数换算成装备均分（6 件的平均分）。
打开「配装方案」时才联网取，汇总结果缓存在 `<数据目录>/data/heroes/builds/<编号>.json`，一天内不重复下载。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

from e7helper import __version__

from .hero_db import FOUR_PIECE_SETS, Hero

log = logging.getLogger(__name__)

BUILDS_URL = "https://krivpfvxi0.execute-api.us-west-2.amazonaws.com/dev/getBuilds"
TIMEOUT = 40
CACHE_TTL = 24 * 3600
TOP_COMBOS = 8
TOP_ARTIFACTS = 8
COMBO_ARTIFACTS = 3
STAT_FIELDS = ("atk", "def", "hp", "spd", "chc", "chd", "eff", "efr", "gear")
SPEED_SET = "set_speed"
TIER_MIN = 9  # 少于这么多份不分档
TIERS = ("fast", "mid", "slow")
SPEED_TOPS = (("top10", 0.10), ("top25", 0.25))
CACHE_FORMAT = 3  # 汇总格式变了就让旧缓存作废

PostFetch = Callable[[str], bytes]  # 请求体是英雄英文名


class BuildsError(Exception):
    pass


def post_builds(name_en: str) -> bytes:
    req = urllib.request.Request(BUILDS_URL, data=name_en.encode("utf-8"), method="POST",
                                 headers={"User-Agent": f"e7helper/{__version__}", "Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except Exception as e:  # noqa: BLE001
        raise BuildsError(f"配装数据下载失败：{e}") from e


def full_sets(sets: dict) -> dict[str, int]:
    """每种套装的件数 → 生效的完整套装（同 Fribbels 网页的 convertToFullSets）。"""
    out: dict[str, int] = {}
    for key, n in (sets or {}).items():
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if key in FOUR_PIECE_SETS:
            if n >= 4:
                out[key] = 4
        elif n >= 6:
            out[key] = 6
        elif n >= 4:
            out[key] = 4
        elif n >= 2:
            out[key] = 2
    return out


def _combo_key(sets: dict[str, int]) -> str:
    # 四件套在前，同件数按名字
    return ",".join(f"{k}:{v}" for k, v in sorted(sets.items(), key=lambda kv: (-kv[1], kv[0])))


def _median(vals: list[float]) -> float:
    vals = sorted(vals)
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _medians(rows: list[dict]) -> dict[str, float]:
    out = {}
    for f in STAT_FIELDS:
        vals = [r[f] for r in rows if isinstance(r.get(f), (int, float))]
        if vals:
            m = _median(vals)
            out[f] = round(m, 1) if f == "gear" else round(m)
    return out


def _tiers(members: list[dict]) -> list[dict]:
    """按速度从快到慢三等分。"""
    ranked = sorted((r for r in members if isinstance(r.get("spd"), (int, float))), key=lambda r: -r["spd"])
    if len(ranked) < TIER_MIN:
        return []
    n = len(ranked)
    cuts = [0, round(n / 3), round(n * 2 / 3), n]
    return [{"tier": t, "count": cuts[i + 1] - cuts[i], "stats": _medians(ranked[cuts[i]:cuts[i + 1]])}
            for i, t in enumerate(TIERS)]


def _speed_tiers(members: list[dict]) -> list[dict]:
    """带速度套：速度最快的前 10% / 前 25%，再加全部，每行份数 + 属性中位数。"""
    ranked = sorted((r for r in members if isinstance(r.get("spd"), (int, float))), key=lambda r: -r["spd"])
    if len(ranked) < TIER_MIN:
        return []
    rows = []
    for tier, q in SPEED_TOPS:
        top = ranked[:max(1, round(len(ranked) * q))]
        rows.append({"tier": tier, "count": len(top), "stats": _medians(top)})
    rows.append({"tier": "all", "count": len(members), "stats": _medians(members)})
    return rows


def _share(n: int, total: int) -> float:
    return round(n / total, 4) if total else 0.0


def _artifact_list(counter: Counter, total: int, artifacts: dict[str, dict], limit: int) -> list[dict]:
    return [{"code": code, "name": (artifacts.get(code) or {}).get("name", ""), "count": n, "share": _share(n, total)}
            for code, n in counter.most_common(limit)]


def summarize(rows: list[dict], artifacts: dict[str, dict]) -> dict:
    rows = [r for r in rows if isinstance(r, dict)]
    for r in rows:
        for f in STAT_FIELDS[:-1]:
            try:
                r[f] = int(float(r.get(f)))
            except (TypeError, ValueError):
                r.pop(f, None)
        try:
            r["gear"] = float(r.get("gs")) / 6  # 装备分是 6 件的总分，换算成均分
        except (TypeError, ValueError):
            r.pop("gear", None)
    total = len(rows)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[_combo_key(full_sets(r.get("sets") or {}))].append(r)
    combos = []
    for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:TOP_COMBOS]:
        sets = [{"set": k, "pieces": int(v)} for k, v in (p.split(":") for p in key.split(",") if p)]
        arts = Counter(r.get("artifactCode") for r in members if r.get("artifactCode"))
        speed_set = any(x["set"] == SPEED_SET for x in sets)
        combos.append({"sets": sets, "count": len(members), "share": _share(len(members), total),
                       "speed_set": speed_set, "stats": _medians(members),
                       "tiers": _speed_tiers(members) if speed_set else _tiers(members),
                       "artifacts": _artifact_list(arts, len(members), artifacts, COMBO_ARTIFACTS)})
    arts = Counter(r.get("artifactCode") for r in rows if r.get("artifactCode"))
    dates = sorted(str(r.get("createDate")) for r in rows if r.get("createDate"))
    return {"total": total, "combos": combos, "artifacts": _artifact_list(arts, total, artifacts, TOP_ARTIFACTS),
            "stats": _medians(rows), "latest": dates[-1] if dates else ""}


def get_builds(hero: Hero, cache_dir: Path, artifacts: dict[str, dict], *, refresh: bool = False,
               fetch: PostFetch | None = None, now: float | None = None) -> dict:
    """汇总后的配装方案；缓存没过期且不要求刷新时直接用缓存。下载失败但有旧缓存时返回旧的（带 stale）。"""
    now = time.time() if now is None else now
    path = cache_dir / f"{hero.code}.json"
    cached = None
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
    if cached and cached.get("format") != CACHE_FORMAT:
        cached = None
    if cached and not refresh and now - cached.get("fetched", 0) < CACHE_TTL:
        return cached
    try:
        raw = json.loads((fetch or post_builds)(hero.name_en))
        rows = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            raise BuildsError("配装数据格式不对")
    except (BuildsError, ValueError) as e:
        if cached:
            log.warning("配装数据下载失败，用旧的缓存：%s", e)
            return {**cached, "stale": True}
        raise BuildsError(str(e)) from e
    out = {"code": hero.code, "format": CACHE_FORMAT, "fetched": now, **summarize(rows, artifacts)}
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return out
