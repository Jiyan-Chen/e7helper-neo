"""自定义流程的定义（B11）：步骤 + 条件分支 + 循环，嵌套积木结构。

一个流程存成 `<数据目录>/flows/<id>.json`，内容就是 `Flow.model_dump(mode="json", by_alias=True)`。

模板引用（字符串）：
- `名字`：玩家自己采集的模板（`<数据目录>/flows/templates/<名字>.png`）；
- `common:名字`：内置共用模板（只读，例如 `common:back`、`common:lobby/sanctuary`）。

坐标一律是 1600×900 基准。所有等待都有超时，所有循环都有最多次数，所以流程一定会结束。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from e7helper.core.geometry import BASE_HEIGHT, BASE_WIDTH

FLOW_VERSION = 1
COMMON_PREFIX = "common:"
MAX_DEPTH = 6  # 条件 / 循环最多嵌套几层
MAX_STEPS = 300  # 一个流程最多多少步（含嵌套）
MAX_WAIT = 300.0  # 单步最多等多久（秒）

# 「等待界面」能选的内置界面（core/scene/builtin.py 的 SCENES）
SCENE_NAMES: dict[str, str] = {
    "lobby": "大厅",
    "sanctuary": "圣域",
    "shop": "商店",
    "secret_shop": "秘密商店",
    "arena": "竞技场",
}

# 不允许流程直接点的内置模板：确认框的「确认」（一律点取消，用户确认）
FORBIDDEN_TAP_REFS = frozenset({"common:dialog/confirm"})

_REF_RE = re.compile(r"^(common:)?[\w\-]+(/[\w\-]+)*$")
_ID_RE = re.compile(r"^[a-z0-9_\-]{1,40}$")


def new_step_id() -> str:
    return uuid.uuid4().hex[:8]


def check_ref(ref: str) -> str:
    if not _REF_RE.match(ref):
        raise ValueError(f"模板引用不合法：{ref!r}")
    return ref


TemplateRef = Annotated[str, Field(min_length=1, max_length=120)]
OnMissing = Literal["stop", "skip"]
Coord = Annotated[int, Field(ge=0, le=BASE_WIDTH)]
CoordY = Annotated[int, Field(ge=0, le=BASE_HEIGHT)]
WaitSeconds = Annotated[float, Field(ge=0, le=MAX_WAIT)]


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(default_factory=new_step_id, max_length=40)
    note: str = Field("", max_length=200, description="备注（编辑器里显示）")


class Condition(BaseModel):
    """「模板出现 / 不出现」或「在某个内置界面」；最多等 wait 秒，期间一成立就算成立。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["template", "scene"] = "template"
    templates: list[TemplateRef] = Field(default_factory=list, max_length=8, description="任一出现就算出现")
    scene: str | None = None
    appear: bool = Field(True, description="true = 出现时成立；false = 不出现时成立")
    wait: WaitSeconds = Field(0.0, description="最多等多久（秒），0 = 只看当前画面")

    @field_validator("templates")
    @classmethod
    def _refs(cls, v: list[str]) -> list[str]:
        return [check_ref(r) for r in v]

    @model_validator(mode="after")
    def _complete(self) -> Condition:
        if self.kind == "template" and not self.templates:
            raise ValueError("条件里至少要选一个模板")
        if self.kind == "scene" and self.scene not in SCENE_NAMES:
            raise ValueError(f"不认识的界面：{self.scene!r}")
        return self


# ------------------------------------------------------------ 动作

class TapTemplate(_Step):
    """等模板出现（最多 timeout 秒）然后点它；模板设了点击区域时点点击区域。"""

    type: Literal["tap_template"] = "tap_template"
    template: TemplateRef
    timeout: WaitSeconds = 5.0
    on_missing: OnMissing = "stop"
    settle: bool = Field(True, description="点之前等画面静止（界面切换动画期间点击会被游戏忽略）")

    @field_validator("template")
    @classmethod
    def _ref(cls, v: str) -> str:
        check_ref(v)
        if v in FORBIDDEN_TAP_REFS:
            raise ValueError("不能点确认框的「确认」按钮（流程遇到确认框一律点取消）")
        return v


class TapPoint(_Step):
    type: Literal["tap_point"] = "tap_point"
    x: Coord
    y: CoordY


class Swipe(_Step):
    type: Literal["swipe"] = "swipe"
    x1: Coord
    y1: CoordY
    x2: Coord
    y2: CoordY
    duration: float = Field(0.4, ge=0.1, le=3.0)


class Back(_Step):
    """Android 返回键。"""

    type: Literal["back"] = "back"


class Wait(_Step):
    type: Literal["wait"] = "wait"
    seconds: float = Field(1.0, gt=0, le=MAX_WAIT)


class WaitStill(_Step):
    """等画面不再变化（静止 0.5 秒），最多 timeout 秒；一直在动就继续往下走。"""

    type: Literal["wait_still"] = "wait_still"
    timeout: WaitSeconds = 5.0


class WaitTemplate(_Step):
    """等模板出现（appear=true）或消失（appear=false）。"""

    type: Literal["wait_template"] = "wait_template"
    templates: list[TemplateRef] = Field(min_length=1, max_length=8, description="任一出现就算出现")
    appear: bool = True
    timeout: WaitSeconds = 10.0
    on_missing: OnMissing = "stop"

    @field_validator("templates")
    @classmethod
    def _refs(cls, v: list[str]) -> list[str]:
        return [check_ref(r) for r in v]


class WaitScene(_Step):
    """等到某个内置界面（途中照常处理断线重进、网络重试），并等画面静止。"""

    type: Literal["wait_scene"] = "wait_scene"
    scene: str
    timeout: WaitSeconds = 15.0
    on_missing: OnMissing = "stop"

    @field_validator("scene")
    @classmethod
    def _scene(cls, v: str) -> str:
        if v not in SCENE_NAMES:
            raise ValueError(f"不认识的界面：{v!r}")
        return v


# ------------------------------------------------------------ 控制

class End(_Step):
    """结束流程：success=true 记成功，false 记失败。"""

    type: Literal["end"] = "end"
    success: bool = True
    message: str = Field("", max_length=200)


class Break(_Step):
    """跳出最内层的循环。"""

    type: Literal["break"] = "break"


class If(_Step):
    type: Literal["if"] = "if"
    condition: Condition
    then: list[Step] = Field(default_factory=list)
    else_: list[Step] = Field(default_factory=list, alias="else")


class Repeat(_Step):
    """循环。

    - times：重复 count 次；
    - until：每轮开始前看条件，成立就停（「重复直到大厅出现」），最多 count 轮；
    - while：每轮开始前看条件，不成立就停（「模板出现时一直重复」），最多 count 轮。
    until 跑满 count 轮条件仍不成立时，按 on_limit 处理：stop = 流程失败，continue = 接着往下走。
    """

    type: Literal["repeat"] = "repeat"
    mode: Literal["times", "until", "while"] = "times"
    count: int = Field(3, ge=1, le=999, description="次数 / 最多几轮")
    condition: Condition | None = None
    on_limit: Literal["stop", "continue"] = "stop"
    body: list[Step] = Field(default_factory=list)

    @model_validator(mode="after")
    def _need_condition(self) -> Repeat:
        if self.mode != "times" and self.condition is None:
            raise ValueError("「重复直到 / 当…时重复」需要条件")
        return self


Step = Annotated[
    TapTemplate | TapPoint | Swipe | Back | Wait | WaitStill | WaitTemplate | WaitScene | End | Break | If | Repeat,
    Field(discriminator="type"),
]

If.model_rebuild()
Repeat.model_rebuild()


class FlowLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_minutes: float = Field(10.0, ge=0.5, le=120.0, description="最多运行多久（分钟），到了就停止")
    max_taps: int = Field(200, ge=1, le=5000, description="最多点击 / 滑动多少次，到了就停止")


class Flow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int = FLOW_VERSION
    id: str = ""
    name: str = Field(min_length=1, max_length=40)
    description: str = Field("", max_length=500)
    limits: FlowLimits = Field(default_factory=FlowLimits)
    steps: list[Step] = Field(default_factory=list)
    created: float | None = None
    updated: float | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if v and not _ID_RE.match(v):
            raise ValueError(f"流程 id 不合法：{v!r}")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("流程名不能为空")
        return v

    @model_validator(mode="after")
    def _structure(self) -> Flow:
        count = 0
        for step, depth, in_loop in walk(self.steps):
            count += 1
            if depth > MAX_DEPTH:
                raise ValueError(f"条件 / 循环最多嵌套 {MAX_DEPTH} 层")
            if isinstance(step, Break) and not in_loop:
                raise ValueError("「跳出循环」只能放在循环里")
        if count > MAX_STEPS:
            raise ValueError(f"一个流程最多 {MAX_STEPS} 步（现在 {count} 步）")
        return self

    def dump(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)

    def template_refs(self) -> set[str]:
        """流程用到的全部模板引用。"""
        refs: set[str] = set()
        for step, _, _ in walk(self.steps):
            if isinstance(step, TapTemplate):
                refs.add(step.template)
            elif isinstance(step, WaitTemplate):
                refs.update(step.templates)
            cond = getattr(step, "condition", None)
            if cond is not None and cond.kind == "template":
                refs.update(cond.templates)
        return refs


def walk(steps: list, depth: int = 1, in_loop: bool = False) -> Iterator[tuple[object, int, bool]]:
    """深度优先遍历全部步骤：(步骤, 嵌套深度, 是否在循环里)。"""
    for step in steps:
        yield step, depth, in_loop
        if isinstance(step, If):
            yield from walk(step.then, depth + 1, in_loop)
            yield from walk(step.else_, depth + 1, in_loop)
        elif isinstance(step, Repeat):
            yield from walk(step.body, depth + 1, True)


STEP_LABELS: dict[str, str] = {
    "tap_template": "点击模板",
    "tap_point": "点击坐标",
    "swipe": "滑动",
    "back": "返回键",
    "wait": "等待",
    "wait_still": "等画面静止",
    "wait_template": "等模板",
    "wait_scene": "等界面",
    "end": "结束流程",
    "break": "跳出循环",
    "if": "如果",
    "repeat": "重复",
}
