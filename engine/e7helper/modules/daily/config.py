"""日常收取的配置。

表单只有三个开关和 dry-run；其余字段是引擎内部接口，不出现在 JSON Schema 里，
`run -c '{...}'` 和测试仍然可以传。
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


class DailyConfig(BaseModel):
    mail: bool = Field(True, description="领取剩余时间不到一天的邮件（逐封领取，不点「全部领取」）")
    forest: bool = Field(True, description="精灵之森：领取企鹅巢穴 / 精灵之泉 / 魔罗戈拉的产出，有「照料」就照料")
    covenant: bool = Field(True, description="誓约召唤：用完当天的免费召唤（优先免费十连；只点显示「免费」的按钮）")
    dry_run: bool = Field(True, description="只导航和识别，不点领取、照料、召唤")

    # ---- 内部接口（不显示在表单里）
    mail_max_hours: SkipJsonSchema[float] = Field(
        24.0, gt=0, description="剩余时间小于这么多小时的邮件才领（「剩余1天」按 24 小时算，不领）",
    )
    mail_max_claims: SkipJsonSchema[int] = Field(0, ge=0, description="每次最多领几封，0 表示不限")
    covenant_max: SkipJsonSchema[int] = Field(0, ge=0, description="每次最多点几次免费召唤，0 表示用完为止")
    force: SkipJsonSchema[bool] = Field(False, description="忽略按天记账（ledger），每项都进去看")
    max_failures: SkipJsonSchema[int] = Field(3, ge=1, le=20, description="同一项连续失败这么多次就放弃这一项")
