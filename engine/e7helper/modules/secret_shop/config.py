"""刷神秘商店的配置。前端通过 JSON Schema 自动生成表单。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Target(BaseModel):
    name: str = Field(description="商品名（以游戏内 OCR 为准）")
    price: int | None = Field(
        None, ge=1,
        description="预期金币价格。设置后价格读数必须一致才买（防止 OCR 认错商品）；不设置则只要求是金币价格",
    )
    icon: str | None = Field(
        None, description="物品图标模板（assets/secret_shop/cn/ 下，如 item/covenant）。名字没对上时按图标认",
    )


def default_targets() -> list[Target]:
    return [
        Target(name="誓约书签", price=184_000, icon="item/covenant"),
        Target(name="神秘奖牌", price=280_000, icon="item/mystic"),
    ]


class SecretShopConfig(BaseModel):
    targets: list[Target] = Field(default_factory=default_targets, description="要买的商品")
    max_refreshes: int = Field(10, ge=0, le=1000, description="最多刷新次数")
    skystone_budget: int = Field(30, ge=0, description="本次最多花多少天空石刷新")
    skystone_keep: int = Field(0, ge=0, description="天空石保底：刷新后不能低于这个数")
    gold_floor: int = Field(0, ge=0, description="金币下限：买完后金币不能低于这个数")
    refresh_cost: int = Field(3, ge=1, description="每次刷新消耗的天空石；界面读数与此不符时停止")
    max_failures: int = Field(3, ge=1, le=20, description="连续失败这么多次就停止（刷新/购买没有扣费、确认框没出现等）")
    dry_run: bool = Field(True, description="只识别和决策，不点购买和刷新")
    probe_dialogs: bool = Field(
        False, description="dry-run 时打开购买/刷新确认框核对内容，然后点取消（用于实机验证识别）",
    )
