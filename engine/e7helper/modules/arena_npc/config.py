"""竞技场 NPC 的配置。

面向用户（GUI 表单）只有两项：是否用友情点数补旗、dry-run。其余字段是引擎内部接口，
不出现在 JSON Schema 里，但 `run -c '{...}'` 和测试仍然可以传。
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


class ArenaNpcConfig(BaseModel):
    buy_flags: bool = Field(
        False, description="旗帜用完后用友情点数补旗（100 友情点数换 5 面，每天限一次；绝不用天空石）",
    )
    dry_run: bool = Field(True, description="只导航和识别，不点「战斗开始」「快速对战」「购买」")

    # ---- 内部接口（不显示在表单里）
    max_battles: SkipJsonSchema[int] = Field(0, ge=0, description="最多打几场，0 表示打到旗帜用完")
    prefer_quick: SkipJsonSchema[bool] = Field(True, description="优先快速对战，当天次数用完后改打普通战斗")
    max_flag_buys: SkipJsonSchema[int] = Field(1, ge=0, le=1, description="每次运行最多补旗几次（游戏每天限一次）")
    friendship_keep: SkipJsonSchema[int] = Field(0, ge=0, description="友情点数保底：买完后不能低于这个数")
    max_failures: SkipJsonSchema[int] = Field(3, ge=1, le=20, description="连续失败这么多次就停止")
    battle_timeout: SkipJsonSchema[float] = Field(300.0, ge=30, description="一场普通战斗最长等待秒数")
    probe_dialogs: SkipJsonSchema[bool] = Field(
        False, description="dry-run 时打开补旗框核对内容，然后点取消（用于实机验证识别）",
    )
