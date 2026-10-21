"""游戏数据（B13 起）：不依赖设备，任务模块和助手模块都可以用。"""

from .hero_db import (
    ELEMENT_LABELS,
    ROLE_LABELS,
    SET_LABELS,
    STAT_LABELS,
    ZODIAC_LABELS,
    Hero,
    HeroDB,
    HeroFile,
    heroes,
    load_heroes,
    name_key,
    reload_heroes,
)
from .hero_detail import HeroDetail

__all__ = [
    "ELEMENT_LABELS", "ROLE_LABELS", "SET_LABELS", "STAT_LABELS", "ZODIAC_LABELS", "Hero", "HeroDB", "HeroDetail",
    "HeroFile", "heroes", "load_heroes", "name_key", "reload_heroes",
]
