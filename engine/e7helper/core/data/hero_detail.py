"""英雄详情（B13 审核后加）：技能、角色奉献、专属装备等中文资料，来自 e7.wiki 的公开英雄数据。

每名英雄一个文件 `details/<编号>.json`，技能 / 效果 / 专属装备图标放 `details/icons/`（文件名沿用 e7.wiki 的）。
文字是「富文本」：段落列表，每段是片段列表 `{"text": ..., "hl": true}`，hl 是游戏里高亮（橙色加粗）的词。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

RichText = list[list[dict]]


class Effect(BaseModel):
    name: str
    type: str = ""  # buff / debuff
    icon: str = ""
    description: RichText = Field(default_factory=list)


class SoulBurn(BaseModel):
    cost: int
    description: RichText = Field(default_factory=list)


class Multiplier(BaseModel):
    label: str
    items: list[dict] = Field(default_factory=list)  # {"label", "value"}


class Skill(BaseModel):
    slot: int
    name: str
    icon: str = ""
    soul_gain: int = 0
    cooldown: RichText = Field(default_factory=list)
    description: RichText = Field(default_factory=list)
    soul_burn: SoulBurn | None = None
    effects: list[Effect] = Field(default_factory=list)
    enhancements: list[RichText] = Field(default_factory=list)  # 第 1–N 级
    multipliers: list[Multiplier] = Field(default_factory=list)
    exclusive: list[RichText] = Field(default_factory=list)  # 专属装备对这个技能的效果（多选一）


class Devotion(BaseModel):
    type: str
    grades: dict[str, float] = Field(default_factory=dict)  # (d / c) / b / a / s / ss / sss，0 的不存（五星没有 C 级）


class ExclusiveEffect(BaseModel):
    index: int  # 游戏里的第几个选项（三选一）
    slot: int  # 作用于第几个技能
    description: RichText = Field(default_factory=list)


class ExclusiveEquipment(BaseModel):
    name: str
    icon: str = ""
    main_stat: dict = Field(default_factory=dict)  # {"type", "min", "max"}
    effects: list[ExclusiveEffect] = Field(default_factory=list)  # 道具背景说明不存（用户意见：只显示效果）


class HeroDetail(BaseModel):
    code: str
    slug: str = ""
    subtitle: str = ""
    release_date: str = ""
    self_devotion: Devotion | None = None
    devotion: Devotion | None = None  # 群阵（给全队）
    devotion_slot: str = ""  # 群阵影响的位置，例如 "14"：1 右、2 下、3 上、4 左（游戏里四个菱形的图示）
    skills: list[Skill] = Field(default_factory=list)
    exclusive: ExclusiveEquipment | None = None
    source_updated: str = ""  # e7.wiki 角色列表里的 update_time，没变就不重新下载


# ---------------------------------------------------------------- e7.wiki → 我们的格式


def _rich(raw) -> RichText:
    out: RichText = []
    for para in raw or []:
        segs = []
        for seg in para or []:
            text = seg.get("text", "") if isinstance(seg, dict) else ""
            if not text:
                continue
            segs.append({"text": text, "hl": True} if seg.get("bold") or seg.get("color") else {"text": text})
        if segs:
            out.append(segs)
    return out


def icon_name(url: str) -> str:
    """e7.wiki 的图标路径 → 文件名（/static/skills/sk_c2111_1.webp → sk_c2111_1.webp）。"""
    return url.rsplit("/", 1)[-1] if url else ""


def _devotion(raw) -> Devotion | None:
    if not isinstance(raw, dict) or not raw.get("type"):
        return None
    grades = {k: v for k, v in (raw.get("grades") or {}).items() if k in ("d", "c", "b", "a", "s", "ss", "sss") and v}
    return Devotion(type=raw["type"], grades=grades)


def convert_detail(code: str, raw: dict, source_updated: str = "") -> tuple[HeroDetail, list[str]]:
    """e7.wiki 的英雄 JSON → HeroDetail 和要下载的图标路径（e7.wiki 上的 URL 路径）。"""
    icons: list[str] = []

    def icon(url: str) -> str:
        if url:
            icons.append(url)
        return icon_name(url)

    excl_by_slot: dict[int, list[RichText]] = {}
    ex = raw.get("exclusiveEquipment")
    exclusive = None
    if isinstance(ex, dict) and ex.get("name"):
        effects = [ExclusiveEffect(index=int(s.get("index") or i + 1), slot=int(s.get("slot", 0)),
                                   description=_rich(s.get("description")))
                   for i, s in enumerate(ex.get("skills") or [])]
        exclusive = ExclusiveEquipment(name=ex["name"], icon=icon(ex.get("iconUrl", "")),
                                       main_stat=ex.get("mainStat") or {}, effects=sorted(effects, key=lambda e: e.index))
        for e in exclusive.effects:
            excl_by_slot.setdefault(e.slot, []).append(e.description)

    skills = []
    for s in (raw.get("skills") or [])[:3]:
        sb = s.get("soulBurn")
        skills.append(Skill(
            slot=int(s.get("slot", 0)), name=s.get("name", ""), icon=icon(s.get("iconUrl", "")),
            soul_gain=int(s.get("soulGain") or 0), cooldown=_rich(s.get("cooldown")),
            description=_rich(s.get("description")),
            soul_burn=SoulBurn(cost=int(sb.get("cost") or 0), description=_rich(sb.get("description")))
            if isinstance(sb, dict) else None,
            effects=[Effect(name=e.get("name", ""), type=e.get("type", ""), icon=icon(e.get("iconUrl", "")),
                            description=_rich(e.get("description"))) for e in s.get("effects") or []],
            enhancements=[_rich(e.get("description")) for e in s.get("enhancements") or []],
            multipliers=[Multiplier(label=m.get("label", ""),
                                    items=[{"label": i.get("label", ""), "value": i.get("value", "")}
                                           for i in m.get("items") or []])
                         for m in s.get("multipliers") or []],
            exclusive=excl_by_slot.get(int(s.get("slot", 0)), []),
        ))
    detail = HeroDetail(
        code=code, slug=raw.get("code", ""), subtitle=(raw.get("subtitle") or "").replace("\n", ""),
        release_date=raw.get("releaseDate") or "", self_devotion=_devotion(raw.get("selfDevotion")),
        devotion=_devotion(raw.get("devotion")), devotion_slot="".join(sorted(str(raw.get("devotionSlot") or ""))),
        skills=skills, exclusive=exclusive, source_updated=source_updated,
    )
    return detail, list(dict.fromkeys(icons))
