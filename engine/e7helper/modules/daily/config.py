"""日常收取的配置。

表单只有各项开关、商店要买的商品（B12b）、竞技场的附加选项（补旗）和 dry-run；其余字段是引擎内部接口，
不出现在 JSON Schema 里，`run -c '{...}'` 和测试仍然可以传。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


# 商店日常购买的商品（B12b 用户圈定）。用注释不用 docstring：pydantic 会把枚举的 docstring 当成字段说明。
# 名字、价格、限购等在 shop.py 的 CATALOG 里。
class ShopItem(StrEnum):
    ARENA_ENERGY = "arena_energy"  # 交易所 › 竞技场：40点行动力
    FREE = "free"  # 商店 › 一般：普琳每日免费商品
    ENERGY = "energy"  # 一般：40点行动力（友情点数）
    CORE = "core"  # 一般：光谱核心（行动力）
    AFFINITY_BOX = "affinity_box"  # 一般：亲密度献礼选择箱
    ARTIFACT_LOW_GENERAL = "artifact_low_general"  # 一般：下级神器强化石
    MOLAGORA = "molagora"  # 商店 › 传承石：魔罗戈拉
    FLOWER = "flower"  # 传承石：上级精灵之花
    POTENTIAL = "potential"  # 传承石：潜能开发碎片
    CATALYST_BOX = "catalyst_box"  # 传承石：装备炼制石选择箱
    ARTIFACT_HIGH = "artifact_high"  # 传承石：上级神器强化石
    ACCESSORY_HIGH = "accessory_high"  # 传承石：2个上级饰品强化石
    ARTIFACT_LOW = "artifact_low"  # 传承石：下级神器强化石
    ACCESSORY_LOW = "accessory_low"  # 传承石：2个下级饰品强化石


SHOP_ITEM_LABELS = {
    ShopItem.ARENA_ENERGY: "40点行动力（竞技场点数）",
    ShopItem.FREE: "普琳每日免费商品",
    ShopItem.ENERGY: "40点行动力（友情点数）",
    ShopItem.CORE: "光谱核心",
    ShopItem.AFFINITY_BOX: "亲密度献礼选择箱",
    ShopItem.ARTIFACT_LOW_GENERAL: "下级神器强化石（一般）",
    ShopItem.MOLAGORA: "魔罗戈拉",
    ShopItem.FLOWER: "上级精灵之花",
    ShopItem.POTENTIAL: "潜能开发碎片",
    ShopItem.CATALYST_BOX: "装备炼制石选择箱",
    ShopItem.ARTIFACT_HIGH: "上级神器强化石",
    ShopItem.ACCESSORY_HIGH: "2个上级饰品强化石",
    ShopItem.ARTIFACT_LOW: "下级神器强化石（传承石）",
    ShopItem.ACCESSORY_LOW: "2个下级饰品强化石",
}


class DailyConfig(BaseModel):
    mail: bool = Field(True, description="领取快过期的邮件", title="邮件")
    forest: bool = Field(True, description="领取产出，照料魔罗戈拉", title="精灵之森")
    covenant: bool = Field(True, description="用掉当天的免费召唤", title="誓约召唤")
    shop: bool = Field(True, description="买掉商店里每天、每周限购的商品", title="商店")
    shop_items: list[ShopItem] = Field(
        list(ShopItem), title="要买的商品", json_schema_extra={"x-enum-labels": {k.value: v for k, v in SHOP_ITEM_LABELS.items()}},
    )
    arena: bool = Field(True, description="用旗帜挑战 NPC", title="竞技场")
    # 竞技场的附加选项（GUI 里画在「竞技场」那一行，只显示名字）：旗帜用完后用 100 友情点数换 5 面，
    # 每天限一次，绝不用天空石
    arena_buy_flags: bool = Field(False, title="用友情点数补充旗帜")
    dry_run: bool = Field(True, description="不真的领取、召唤、开战", title="演练")

    # ---- 内部接口（不显示在表单里）
    mail_max_hours: SkipJsonSchema[float] = Field(
        24.0, gt=0, description="剩余时间小于这么多小时的邮件才领（「剩余1天」按 24 小时算，不领）",
    )
    mail_max_claims: SkipJsonSchema[int] = Field(0, ge=0, description="每次最多领几封，0 表示不限")
    covenant_max: SkipJsonSchema[int] = Field(0, ge=0, description="每次最多点几次免费召唤，0 表示用完为止")
    arena_max_battles: SkipJsonSchema[int] = Field(0, ge=0, description="竞技场最多打几场，0 表示打到旗帜用完")
    arena_prefer_quick: SkipJsonSchema[bool] = Field(True, description="优先快速对战，当天次数用完后改打普通战斗")
    arena_friendship_keep: SkipJsonSchema[int] = Field(0, ge=0, description="友情点数保底：补旗后不能低于这个数")
    arena_battle_timeout: SkipJsonSchema[float] = Field(300.0, ge=30, description="一场普通战斗最长等待秒数")
    arena_probe_dialogs: SkipJsonSchema[bool] = Field(
        False, description="dry-run 时打开补旗框核对内容，然后点取消（用于实机验证识别）",
    )
    shop_affinity_weekly: SkipJsonSchema[int] = Field(
        5, ge=0, le=10, description="亲密度献礼选择箱每周最多买几次（越买越贵，B12b 用户意见：只买 5 次）",
    )
    shop_max_buys: SkipJsonSchema[int] = Field(0, ge=0, description="商店每次最多买几次（0 不限），控制实跑规模用")
    shop_probe_dialogs: SkipJsonSchema[bool] = Field(
        False, description="dry-run 时打开购买框核对内容，然后点取消（用于实机验证识别）",
    )
    force: SkipJsonSchema[bool] = Field(False, description="忽略按天记账（ledger），每项都进去看")
    max_failures: SkipJsonSchema[int] = Field(3, ge=1, le=20, description="同一项连续失败这么多次就放弃这一项")
