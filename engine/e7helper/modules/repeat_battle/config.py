"""重复刷关（讨伐）的配置。

表单字段：目标（讨伐 + 难度，或从当前准备界面开始）、托管战斗、手动刷关、补行动力、dry-run。
其余字段是引擎内部接口，不出现在 JSON Schema 里，但 `run -c '{...}'` 和测试仍然可以传。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


# 讨伐列表里的地下城（值是名字「讨伐」之后的部分，列表顺序）。
# 列表里还有 阿吉玛纳克 / 卡戴斯 / 食人魔，但它们只有「讨伐异界」难度，暂不支持（见 Tier）。
# 用注释不用 docstring：pydantic 会把枚举的 docstring 当成字段说明显示在 GUI 表单里。
class Hunt(StrEnum):

    WYVERN = "双足飞龙"
    GOLEM = "魔像"
    BANSHEE = "报丧妖"


# 难度。「讨伐异界」消耗的是异界专用代币而不是行动力，补充方式也不同，暂不支持（B06 用户确认）。
class Tier(StrEnum):

    MID = "中级"
    HIGH = "上级"
    HELL = "地狱级"


class RepeatBattleConfig(BaseModel):
    hunt: Hunt = Field(Hunt.WYVERN, title="讨伐目标")
    tier: Tier = Field(Tier.HELL, title="难度")
    start_here: bool = Field(
        False, description="刷你已经打开的这一关（不用选讨伐）", title="从当前准备界面开始",
    )
    auto_battle: bool = Field(True, description="结算完成的托管，并重开这一关", title="托管战斗")
    auto_leaves: int = Field(
        0, ge=0, le=100, description="0 表示只用行动力", title="托管最多用几片叶子",
    )
    manual: bool = Field(True, description="反复打这一关", title="手动刷关")
    manual_runs: int = Field(0, ge=0, description="0 表示打到行动力用完", title="手动最多打几场")
    # 行动力不够时补充：生命之叶 1 片换 80，天空石 30 换 60，叶子优先；托管 1 片叶子打 4 次
    refill_leaf: bool = Field(False, title="用生命之叶补行动力")
    max_leaf_refills: int = Field(1, ge=0, le=50, title="叶子最多补几次")
    refill_skystone: bool = Field(False, title="用天空石补行动力")
    max_skystone_refills: int = Field(1, ge=0, le=20, title="天空石最多补几次")
    dry_run: bool = Field(True, description="不真的结算、开战和补充行动力", title="演练")

    # ---- 内部接口（不显示在表单里）
    auto_prefer_energy: SkipJsonSchema[bool] = Field(True, description="托管时勾选「优先使用持有的行动力」")
    auto_max_units: SkipJsonSchema[int] = Field(
        0, ge=0, le=100, description="重开托管最多几份（1 份 4 次），0 表示不限（行动力能凑几份就几份）",
    )
    skystone_keep: SkipJsonSchema[int] = Field(0, ge=0, description="天空石保底：补完后不能低于这个数")
    max_failures: SkipJsonSchema[int] = Field(3, ge=1, le=20, description="连续失败这么多次就停止")
    battle_timeout: SkipJsonSchema[float] = Field(600.0, ge=30, description="一场战斗最长等待秒数")
    probe_dialogs: SkipJsonSchema[bool] = Field(
        False, description="dry-run 时行动力不够也点「战斗开始」打开补充框核对，然后点取消（用于实机验证识别）",
    )
