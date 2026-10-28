"""RTA 选秀推荐接口（B14c，给 B14e 的选秀助手页面用）。要 token。胜率一律是「我方」的。

| 路由 | 说明 |
|---|---|
| `GET /rta/model` | 随包模型、第二个模型、数据先验的信息；没有模型 503 `no_model` |
| `POST /rta/advise` | 当前局面：轮到我方 → `recommend`（5–8 个，两手回合另有按英雄的 `heroes`）；轮到对手 → `opponent`（可能怎么选、威胁）；选完 10 手 → `ban`（4 × 4 矩阵、推荐、纳什混合）；后禁也完了 → 只有胜率。局面不合法 422 `invalid_state`（detail 是中文问题列表） |
| `POST /rta/preban` | 预禁推荐（先后手可以不知道、可以固定一名） |

局面的格式和 `DraftState.to_dict()` 一样，按先手方 F / 后手方 S 分：`prebans`、`picks`（这一方按顺序的选人）、
`banned`（F = 先手方被禁的那名）、`grades`（[先手方, 后手方]）、`rule`（`"unknown"` = 国服不知道，null = 没有规则，
其余是 opening_rule_desc_tid）。`side` 是我方是先手还是后手。搜索一次 2–4 秒（`budget` 秒封顶，到时间返回浅一层的
结果，`stats.truncated`）；同一局面的结果有缓存。
"""

from __future__ import annotations

import threading
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from e7helper.core.rta import encode, search

from .engine import ApiError

Side = Literal["F", "S"]


class StateIn(BaseModel):
    prebans: dict[Side, list[str]] = Field(default_factory=lambda: {"F": [], "S": []})
    picks: dict[Side, list[str]] = Field(default_factory=lambda: {"F": [], "S": []})
    banned: dict[Side, str | None] = Field(default_factory=dict)
    grades: list[str | None] = Field(default_factory=lambda: [None, None], min_length=2, max_length=2)
    rule: str | None = encode.UNKNOWN_RULE
    rule_category: str | None = None

    def to_state(self) -> encode.DraftState:
        return encode.DraftState.from_dict(self.model_dump())


class AdviseIn(BaseModel):
    side: Side = Field(description="我方是先手 F 还是后手 S")
    state: StateIn = Field(default_factory=StateIn)
    pool: list[str] | None = Field(None, description="我的英雄池（编号）；不传 = 不限制")
    top: int = Field(8, ge=1, le=16, description="推荐几个")
    budget: float = Field(5.0, ge=0, le=20, description="最多算几秒")


class PrebanIn(BaseModel):
    side: Side | None = Field(None, description="我方是先手 F / 后手 S；不知道就不传")
    grades: list[str | None] = Field(default_factory=lambda: [None, None], min_length=2, max_length=2,
                                     description="[我方, 对方] 的段位")
    rule: str | None = encode.UNKNOWN_RULE
    rule_category: str | None = None
    fixed: str | None = Field(None, description="固定预禁这一名，只推荐另一名")
    top: int = Field(8, ge=1, le=16)
    budget: float = Field(4.0, ge=0, le=20)


def build_rta_router() -> APIRouter:
    r = APIRouter(tags=["RTA 选秀"])
    loading = threading.Lock()

    def advisor() -> search.Advisor:
        if not search.available():
            raise ApiError(503, "no_model", "没有随包的 RTA 模型")
        with loading:  # 第一次用时读模型（约 0.2 秒）
            return search.load()

    @r.get("/rta/model", summary="模型信息")
    def model_info() -> dict:
        return advisor().info()

    @r.post("/rta/advise", summary="选秀推荐")
    def advise(body: AdviseIn) -> dict:
        adv = advisor()
        try:
            return adv.advise(body.state.to_state(), body.side, pool=body.pool, top=body.top, budget=body.budget)
        except ValueError as e:
            problems = e.args[0] if e.args and isinstance(e.args[0], list) else [str(e)]
            raise ApiError(422, "invalid_state", "；".join(problems), detail=problems) from e

    @r.post("/rta/preban", summary="预禁推荐")
    def preban(body: PrebanIn) -> dict:
        adv = advisor()
        try:
            return adv.preban(body.side, grades=(body.grades[0], body.grades[1]), rule=body.rule,
                              rule_category=body.rule_category, fixed=body.fixed, top=body.top, budget=body.budget)
        except ValueError as e:
            problems = e.args[0] if e.args and isinstance(e.args[0], list) else [str(e)]
            raise ApiError(422, "invalid_state", "；".join(problems), detail=problems) from e

    return r
