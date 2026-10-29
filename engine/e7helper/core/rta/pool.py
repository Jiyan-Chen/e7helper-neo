"""RTA 英雄池（B14d1）：玩家自己有哪些英雄，可选填每名的速度。

存在 `<数据目录>/modules/rta_draft/pool.json`（`rta_draft` 是 B14f 画面识别模块的编号，数据先放在它的目录下）：
`{"format": 1, "updated": "...", "heroes": [{"code": "c1168", "speed": 335}, {"code": "c2007"}]}`。
选秀推荐（advise / preban）请求里没传 pool 时用这里的英雄；先动概率里我方英雄用这里填的速度。
空的英雄池 = 不限制（还没设置时推荐全部英雄）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger(__name__)

MODULE_ID = "rta_draft"
POOL_FILE = "pool.json"
FORMAT = 1
SPEED_RANGE = (50, 400)


class PoolHero(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    speed: int | None = Field(None, description="面板速度；不填 = 按段位的常见速度算")

    @field_validator("speed")
    @classmethod
    def _speed(cls, v: int | None) -> int | None:
        if v is not None and not SPEED_RANGE[0] <= v <= SPEED_RANGE[1]:
            raise ValueError(f"速度要在 {SPEED_RANGE[0]}–{SPEED_RANGE[1]} 之间")
        return v


class Pool(BaseModel):
    format: int = FORMAT
    updated: str = ""
    heroes: list[PoolHero] = Field(default_factory=list)

    @field_validator("heroes")
    @classmethod
    def _unique(cls, v: list[PoolHero]) -> list[PoolHero]:
        seen: dict[str, PoolHero] = {}
        for h in v:  # 同一名英雄出现多次时留最后一次
            seen.pop(h.code, None)
            seen[h.code] = h
        return list(seen.values())

    @property
    def codes(self) -> list[str]:
        return [h.code for h in self.heroes]

    @property
    def speeds(self) -> dict[str, int]:
        return {h.code: h.speed for h in self.heroes if h.speed}

    def limit(self) -> list[str] | None:
        """给推荐用的英雄池：空 = None（不限制）。"""
        return self.codes or None


def default_path() -> Path:
    from e7helper.core.paths import module_data_dir

    return module_data_dir(MODULE_ID) / POOL_FILE


def load(path: Path | None = None) -> Pool:
    """读英雄池；没有文件或文件坏了返回空的。"""
    path = path or default_path()
    if not path.is_file():
        return Pool()
    try:
        return Pool.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as e:
        log.warning("英雄池文件读不了，当成空的：%s", e)
        return Pool()


def save(pool: Pool, path: Path | None = None) -> Pool:
    path = path or default_path()
    pool = pool.model_copy(update={"updated": time.strftime("%Y-%m-%dT%H:%M:%S")})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(pool.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return pool
