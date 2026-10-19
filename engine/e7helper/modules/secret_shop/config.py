"""书签刷取（刷神秘商店）的配置。前端通过 JSON Schema 自动生成表单。

B12 用户意见：可买的商品固定为三种（誓约书签 / 神秘奖牌 / 友情点数），玩家只选买哪几种；
设置只留「刷新次数」「连续多少次没出就停止」「连续多少次没出就换世界频道」。
天空石预算 / 保底、金币下限等改成引擎内部接口（不出现在表单里，`run -c '{...}'` 和测试仍然可以传）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic.json_schema import SkipJsonSchema


class Target(BaseModel):
    name: str = Field(description="游戏里的商品名", title="商品")
    # 填了就要求价格读数一致才买（防止 OCR 认错商品）；不填只要求是金币价格
    price: int | None = Field(None, ge=1, description="商品的金币价格（可以不填）", title="金币价格")
    icon: str | None = Field(None, description="名字认不出时按这个图标认（如 item/covenant）", title="图标模板")


# 用注释不用 docstring：pydantic 会把枚举的 docstring 当成字段说明显示在 GUI 表单里。
class Item(StrEnum):
    COVENANT = "covenant"
    MYSTIC = "mystic"
    FRIENDSHIP = "friendship"


# 三种商品：名字、金币价格、图标模板（assets/secret_shop/cn/item/）。价格是实测的（B04 / B12）
CATALOG: dict[Item, Target] = {
    Item.COVENANT: Target(name="誓约书签", price=184_000, icon="item/covenant"),
    Item.MYSTIC: Target(name="神秘奖牌", price=280_000, icon="item/mystic"),
    Item.FRIENDSHIP: Target(name="友情点数", price=18_000, icon="item/friendship"),
}
ITEM_LABELS = {k.value: v.name for k, v in CATALOG.items()}


def default_targets() -> list[Target]:
    return [CATALOG[Item.COVENANT], CATALOG[Item.MYSTIC]]


class SecretShopConfig(BaseModel):
    items: list[Item] = Field(
        [Item.COVENANT, Item.MYSTIC], title="要买的商品",
        json_schema_extra={"x-enum-labels": ITEM_LABELS},
    )
    max_refreshes: int = Field(10, ge=0, le=10000, title="刷新次数")
    stop_after_misses: int = Field(0, ge=0, le=10000, description="0 表示不停", title="连续多少次没出就停止")
    channel_after_misses: int = Field(0, ge=0, le=10000, description="0 表示不换", title="连续多少次没出就换世界频道")
    dry_run: bool = Field(True, description="不真的购买和刷新", title="演练")

    # ---- 开发版字段（表单里只在开发版显示）
    refresh_cost: int = Field(3, ge=1, description="每次刷新花多少天空石", title="每次刷新的天空石")
    max_failures: int = Field(3, ge=1, le=20, description="连续失败几次就停", title="连续失败上限")
    probe_dialogs: bool = Field(False, description="演练时也打开确认框看一眼（会点取消）", title="核对确认框")

    # ---- 内部接口（不显示在表单里）
    targets: SkipJsonSchema[list[Target] | None] = Field(
        None, description="直接指定要买的商品（测试 / CLI 用）；不填按 items 从 CATALOG 取",
    )
    skystone_budget: SkipJsonSchema[int | None] = Field(None, ge=0, description="这次最多花多少天空石刷新，None 不限")
    skystone_keep: SkipJsonSchema[int] = Field(0, ge=0, description="天空石剩到这个数就不再刷新")
    gold_floor: SkipJsonSchema[int] = Field(0, ge=0, description="金币剩到这个数就不再买")
    probe_channel: SkipJsonSchema[bool] = Field(
        False, description="演练时换一次世界频道再换回来（用于实机验证换频道）",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_b12(cls, data: Any) -> Any:
        """B12 之前 GUI 保存的配置（`config.json`、计划里的配置快照）带着旧的默认值：
        targets = 誓约书签 + 神秘奖牌、skystone_budget = 30。原样读进来会盖掉新的商品选择、把刷新限制在 10 次，
        所以没有 items 的旧配置里，这两项是旧默认值就去掉（改用 items / 不限预算）。"""
        if not isinstance(data, dict) or "items" in data:
            return data
        data = dict(data)
        old = [{"name": "誓约书签", "price": 184_000, "icon": "item/covenant"},
               {"name": "神秘奖牌", "price": 280_000, "icon": "item/mystic"}]
        if data.get("targets") == old:
            data.pop("targets")
        if data.get("skystone_budget") == 30:
            data.pop("skystone_budget")
        return data

    def buy_targets(self) -> list[Target]:
        if self.targets is not None:
            return self.targets
        return [CATALOG[i] for i in Item if i in self.items]
