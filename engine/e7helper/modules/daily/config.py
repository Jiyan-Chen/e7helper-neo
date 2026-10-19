"""日常收取的配置。

表单只有各项开关、竞技场的附加选项（补旗）和 dry-run；其余字段是引擎内部接口，不出现在 JSON Schema 里，
`run -c '{...}'` 和测试仍然可以传。
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


class DailyConfig(BaseModel):
    mail: bool = Field(True, description="领取快过期的邮件", title="邮件")
    forest: bool = Field(True, description="领取产出，照料魔罗戈拉", title="精灵之森")
    covenant: bool = Field(True, description="用掉当天的免费召唤", title="誓约召唤")
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
    force: SkipJsonSchema[bool] = Field(False, description="忽略按天记账（ledger），每项都进去看")
    max_failures: SkipJsonSchema[int] = Field(3, ge=1, le=20, description="同一项连续失败这么多次就放弃这一项")
