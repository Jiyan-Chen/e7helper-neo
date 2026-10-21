"""英雄数据库（B13）：编号、国服中文名、属性、职业、星级、头像等，不依赖设备。

数据来自 Fribbels 优化器（herodata.json + 简中翻译）和 e7.wiki（中文名、昵称、技能等详情），转换见 `hero_update.py`：
- 随包：`assets/data/heroes/` 下 `heroes.json`（列表）+ `icons/<编号>.png`（头像）+ `details/<编号>.json`
  （技能等，见 `hero_detail.py`）+ `details/icons/`（技能 / 效果图标）+ `artifacts.json`（神器中文名）；
- 联网更新：`<数据目录>/data/heroes/` 下同样的结构，`updated` 比随包的新时优先用；新下载的头像、详情也放这里；
- 随包的 `overrides.json`：按编号改中文名、加别名（国服名对不上 / 常见昵称），加载时套用，联网更新不会冲掉。

用法（助手模块只读帧，也可以直接用）：
    from e7helper.core.data import heroes
    db = heroes()
    db.get("c2111").name      # 雪国的苏莉塔妮亚
    db.find("苏莉塔妮亚")      # 中文名 / 英文名 / 别名精确匹配（忽略空格、全半角、大小写、「·」），OCR 结果可以直接查
    db.search("雪国")          # 包含关系，按匹配程度排序
    db.icon("c2111")          # 头像 BGR uint8，没有时返回 None
    db.detail("c2111")        # 技能、角色奉献、专属装备（HeroDetail），没有时返回 None
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field, ValidationError

from e7helper.core.imageio import read_image
from e7helper.core.paths import bundled_data_dir, user_data_dir
from e7helper.core.vision.ocr import normalize_text

from .hero_detail import HeroDetail

log = logging.getLogger(__name__)

DATA_NAME = "heroes"
DATA_FILE = "heroes.json"
OVERRIDES_FILE = "overrides.json"
ARTIFACTS_FILE = "artifacts.json"
ICONS_DIR = "icons"
DETAILS_DIR = "details"
DETAIL_ICONS_DIR = "details/icons"
FORMAT = 1

# 国服叫法
ELEMENT_LABELS = {"fire": "火", "ice": "冰", "wind": "木", "light": "光", "dark": "暗"}
ROLE_LABELS = {
    "warrior": "战士", "knight": "骑士", "assassin": "盗贼",
    "ranger": "射手", "mage": "魔导士", "manauser": "精灵师",
}
ZODIAC_LABELS = {
    "ram": "白羊座", "bull": "金牛座", "twins": "双子座", "crab": "巨蟹座", "lion": "狮子座", "maiden": "处女座",
    "scales": "天秤座", "scorpion": "天蝎座", "archer": "射手座", "goat": "摩羯座", "waterbearer": "水瓶座",
    "fish": "双鱼座",
}
STAT_KEYS = ("cp", "atk", "hp", "def", "spd", "chc", "chd", "eff", "efr", "dac")
# 角色奉献、专属装备主属性的类型（e7.wiki 的叫法 → 国服）
STAT_LABELS = {
    "att": "攻击力", "att_rate": "攻击力", "def": "防御力", "def_rate": "防御力", "max_hp": "生命值",
    "max_hp_rate": "生命值", "speed": "速度", "cri": "暴击率", "cri_dmg": "暴击伤害", "acc": "效果命中",
    "res": "效果抗性", "coop": "夹攻率",
}
PERCENT_STATS = {"att_rate", "def_rate", "max_hp_rate", "cri", "cri_dmg", "acc", "res", "coop"}
# 套装（Fribbels 配装数据里的键 → 国服叫法，2026-10-21 对照游戏背包的套装筛选核对过），四件套以外都是两件套
SET_LABELS = {
    "set_att": "攻击", "set_def": "防御", "set_max_hp": "生命值", "set_speed": "速度", "set_cri": "暴击",
    "set_cri_dmg": "破灭", "set_acc": "命中", "set_res": "抵抗", "set_vampire": "吸血", "set_counter": "反击",
    "set_coop": "夹攻", "set_immune": "免疫", "set_rage": "愤怒", "set_penetrate": "穿透", "set_revenge": "憎恨",
    "set_scar": "伤口", "set_shield": "守护", "set_torrent": "激流", "set_revenant": "逆袭", "set_riposte": "回击",
    "set_opener": "开战", "set_chase": "追击", "set_weak": "弱化", "set_might": "全力",
}
FOUR_PIECE_SETS = {"set_speed", "set_att", "set_cri_dmg", "set_vampire", "set_counter", "set_rage", "set_revenge",
                   "set_scar", "set_shield", "set_revenant", "set_riposte"}


class Hero(BaseModel):
    code: str = Field(description="游戏里的英雄编号，例如 c2111")
    name: str = Field(description="国服中文名")
    name_en: str
    aliases: list[str] = Field(default_factory=list, description="别名 / 常见昵称（搜索、识别用）")
    element: str = Field(description="fire / ice / wind / light / dark")
    role: str = Field(description="warrior / knight / assassin / ranger / mage / manauser")
    rarity: int = Field(description="初始星级")
    zodiac: str = ""
    stats: dict[str, int | float] = Field(default_factory=dict, description="60 级 6 星满觉醒的基础属性（不含装备）")
    slug: str = Field("", description="Fribbels / e7.wiki 用的英文 id，例如 solitaria-of-the-snow")
    released: str = Field("", description="发布日期 YYYY-MM-DD（e7.wiki 详情的 releaseDate），没有的为空")


class HeroFile(BaseModel):
    format: int = FORMAT
    source: str = "fribbels"
    updated: str = Field("", description="内容最后一次变化的时间（UTC，ISO 格式）")
    heroes: list[Hero] = Field(default_factory=list)


def dump_hero_file(file: HeroFile) -> str:
    """写盘格式：一名英雄一行，方便看 git diff。"""
    head = json.dumps(file.model_dump(exclude={"heroes"}), ensure_ascii=False)[:-1]
    rows = ",\n".join("  " + json.dumps(h.model_dump(), ensure_ascii=False) for h in file.heroes)
    return f'{head}, "heroes": [\n{rows}\n]}}\n'


def name_key(text: str) -> str:
    """名字比对用的键：去空白、全角转半角、忽略大小写和间隔号。"""
    return normalize_text(text).casefold().translate(_SEPARATORS)


_SEPARATORS = str.maketrans("", "", "·・•.-'’")


def parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class HeroDB:
    """一份已加载的英雄数据（只读）。`file` 是原始数据（不含 overrides），更新时拿它比对。"""

    def __init__(self, file: HeroFile, *, origin: str = "", dirs: Sequence[Path] = (),
                 overrides: dict[str, dict] | None = None):
        """dirs：数据目录，先找的在前（用户数据目录、随包目录）；头像、详情、图标都按这个顺序找。"""
        self.file = file
        self.origin = origin  # bundled / user / ""（没有数据）
        self.dirs = list(dirs)
        self._artifacts: dict[str, dict] | None = None
        self.heroes: list[Hero] = [_apply(h, (overrides or {}).get(h.code)) for h in file.heroes]
        self._by_code = {h.code: h for h in self.heroes}
        self._by_key: dict[str, Hero] = {}
        for h in self.heroes:
            for text in (h.name, h.name_en, *h.aliases):
                key = name_key(text)
                if key and self._by_key.setdefault(key, h) is not h:
                    log.debug("英雄名重复：%s（%s / %s）", text, self._by_key[key].code, h.code)

    @property
    def updated(self) -> str:
        return self.file.updated

    @property
    def source(self) -> str:
        return self.file.source

    def __len__(self) -> int:
        return len(self.heroes)

    def __iter__(self) -> Iterator[Hero]:
        return iter(self.heroes)

    def get(self, code: str) -> Hero | None:
        return self._by_code.get(code)

    def find(self, text: str) -> Hero | None:
        """按中文名 / 英文名 / 别名精确查找。"""
        return self._by_key.get(name_key(text))

    def search(self, text: str, limit: int | None = None) -> list[Hero]:
        """名字、英文名、别名、编号里包含 text 的英雄：完全一致 → 开头一致 → 包含，同档按发布日期新的在前（同 GUI）。"""
        key = name_key(text)
        if not key:
            return []
        scored: list[tuple[int, Hero]] = []
        for h in self.heroes:
            best = None
            for k in (name_key(t) for t in (h.name, h.name_en, h.code, *h.aliases)):
                if k == key:
                    best = 0
                    break
                if k.startswith(key):
                    best = 1 if best is None else min(best, 1)
                elif key in k and best is None:
                    best = 2
            if best is not None:
                scored.append((best, h))
        scored.sort(key=lambda t: t[1].code, reverse=True)
        scored.sort(key=lambda t: t[1].released, reverse=True)  # 没有日期的（空串）排在最后
        scored.sort(key=lambda t: t[0])
        out = [h for _, h in scored]
        return out[:limit] if limit else out

    @property
    def icon_dirs(self) -> list[Path]:
        return [d / ICONS_DIR for d in self.dirs]

    def _first(self, rel: str) -> Path | None:
        for d in self.dirs:
            p = d / rel
            if p.is_file():
                return p
        return None

    def icon_path(self, code: str) -> Path | None:
        return self._first(f"{ICONS_DIR}/{code}.png")

    def icon(self, code: str) -> np.ndarray | None:
        p = self.icon_path(code)
        if p is None:
            return None
        try:
            return read_image(p)
        except (OSError, ValueError):
            log.warning("头像读不了：%s", p)
            return None

    def detail(self, code: str) -> HeroDetail | None:
        """技能等详情；几个目录都有时用 e7.wiki 更新时间较新的一份。"""
        best: HeroDetail | None = None
        for d in self.dirs:
            p = d / DETAILS_DIR / f"{code}.json"
            if not p.is_file():
                continue
            try:
                det = HeroDetail.model_validate_json(p.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError) as e:
                log.warning("英雄详情读不了（%s）：%s", p, e)
                continue
            if best is None or det.source_updated > best.source_updated:
                best = det
        return best

    def detail_icon_path(self, name: str) -> Path | None:
        """技能 / 效果 / 专属装备图标（文件名见 HeroDetail）。"""
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        return self._first(f"{DETAIL_ICONS_DIR}/{name}")

    def artifacts(self) -> dict[str, dict]:
        """神器编号 → {"name"（中文）, "name_en"}。"""
        if self._artifacts is None:
            merged: dict[str, dict] = {}
            for d in reversed(self.dirs):  # 随包的打底，联网更新的覆盖
                p = d / ARTIFACTS_FILE
                if not p.is_file():
                    continue
                try:
                    merged.update(json.loads(p.read_text(encoding="utf-8")))
                except (OSError, ValueError) as e:
                    log.warning("神器表读不了（%s）：%s", p, e)
            self._artifacts = merged
        return self._artifacts


def _apply(h: Hero, override: dict | None) -> Hero:
    if not override:
        return h
    changes: dict = {}
    if override.get("name"):
        changes["name"] = str(override["name"])
    if override.get("aliases"):
        changes["aliases"] = [*h.aliases, *(str(a) for a in override["aliases"] if str(a) not in h.aliases)]
    return h.model_copy(update=changes)


def read_hero_file(path: Path) -> HeroFile | None:
    if not path.is_file():
        return None
    try:
        data = HeroFile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as e:
        log.warning("英雄数据读不了（%s）：%s", path, e)
        return None
    if data.format != FORMAT:
        log.warning("英雄数据格式版本不认识（%s）：%s", path, data.format)
        return None
    return data


def read_overrides(path: Path) -> dict[str, dict]:
    """overrides.json：`{"c2111": {"name": "...", "aliases": [...]}}`，以 _ 开头的键是说明，跳过。"""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("英雄名修正表读不了（%s）：%s", path, e)
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


def _newer(a: HeroFile, b: HeroFile) -> bool:
    """a 是否不比 b 旧（时间读不了的算旧）。"""
    ta, tb = parse_time(a.updated), parse_time(b.updated)
    if ta is None:
        return False
    return tb is None or ta >= tb


def load_heroes(bundled_dir: Path | None = None, user_dir: Path | None = None) -> HeroDB:
    """读随包和用户数据目录里的 heroes.json，用较新的一份；头像先找用户目录再找随包的。"""
    bundled_dir = bundled_dir or bundled_data_dir(DATA_NAME)
    user_dir = user_dir or user_data_dir(DATA_NAME)
    bundled = read_hero_file(bundled_dir / DATA_FILE)
    user = read_hero_file(user_dir / DATA_FILE)
    if user is not None and (bundled is None or _newer(user, bundled)):
        file, origin = user, "user"
    elif bundled is not None:
        file, origin = bundled, "bundled"
    else:
        log.warning("没有英雄数据（%s、%s 都没有 %s）", bundled_dir, user_dir, DATA_FILE)
        file, origin = HeroFile(), ""
    return HeroDB(file, origin=origin, dirs=[user_dir, bundled_dir], overrides=read_overrides(bundled_dir / OVERRIDES_FILE))


_db: HeroDB | None = None
_lock = threading.Lock()


def heroes() -> HeroDB:
    """当前的英雄数据（进程内缓存，第一次调用时加载）。"""
    global _db
    with _lock:
        if _db is None:
            _db = load_heroes()
        return _db


def reload_heroes() -> HeroDB:
    """联网更新后重新加载。"""
    global _db
    db = load_heroes()
    with _lock:
        _db = db
    return db
