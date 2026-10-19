"""流程执行器：按步骤操作游戏，全部经 `Controller`（基准坐标、急停、卡死检测、调试截图都复用 B03）。

步骤编号：顶层 1、2、3；「如果」里先编「那么」再接着编「否则」（2.1、2.2 | 2.3）；循环体 3.1、3.2。
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import numpy as np

from e7helper.core.flows import (
    COMMON_PREFIX,
    SCENE_NAMES,
    STEP_LABELS,
    Back,
    Break,
    Condition,
    End,
    Flow,
    If,
    Repeat,
    Swipe,
    TapPoint,
    TapTemplate,
    Wait,
    WaitScene,
    WaitStill,
    WaitTemplate,
)
from e7helper.core.geometry import Rect
from e7helper.core.runtime import Controller, TaskFailed
from e7helper.core.runtime.controller import SETTLE_FRAME_DIFF, SETTLE_TIME
from e7helper.core.runtime.stuck import thumb_diff, thumbnail
from e7helper.core.scene import SceneState
from e7helper.core.vision import Match, TemplateNotFound

from .guard import FORBIDDEN_BUTTONS, HANDLED_POPUPS

T = TypeVar("T")

POLL = 0.3  # 轮询间隔（秒）
TAP_MARGIN = 8  # 落点检查时外扩的像素（点击带随机抖动）
STEP_TOPIC = "custom_flow.step"


class FlowFailed(TaskFailed):
    """流程失败（找不到模板、循环跑满、走到「结束流程（失败）」……），任务记为失败。"""


class FlowBlocked(FlowFailed):
    """安全规则拦下了一次点击。"""


class _Break(Exception):
    pass


class _End(Exception):
    def __init__(self, success: bool, message: str):
        super().__init__(message)
        self.success = success
        self.message = message


@dataclass
class RunReport:
    steps: int = 0
    taps: int = 0
    popups: int = 0
    message: str = ""


def _plain(ref: str) -> str:
    return ref[len(COMMON_PREFIX):] if ref.startswith(COMMON_PREFIX) else ref


def _names(refs, label: Callable[[str], str]) -> str:
    return "或".join(f"「{label(r)}」" for r in refs)


def describe(step, label: Callable[[str], str] = _plain) -> str:
    """一步的中文描述（日志用）。label 把模板引用换成玩家看得懂的名字。"""
    name = STEP_LABELS.get(step.type, step.type)
    match step:
        case TapTemplate():
            return f"{name}{_names([step.template], label)}"
        case TapPoint():
            return f"{name} ({step.x}, {step.y})"
        case Swipe():
            return f"{name} ({step.x1}, {step.y1}) → ({step.x2}, {step.y2})"
        case Wait():
            return f"{name} {step.seconds:g} 秒"
        case WaitTemplate():
            return f"{name}{_names(step.templates, label)}{'出现' if step.appear else '消失'}"
        case WaitScene():
            return f"{name}「{SCENE_NAMES.get(step.scene, step.scene)}」"
        case If():
            return f"{name} {describe_condition(step.condition, label)}"
        case Repeat():
            if step.mode == "times":
                return f"{name} {step.count} 次"
            kind = "直到" if step.mode == "until" else "当"
            return f"{name}{kind} {describe_condition(step.condition, label)}（最多 {step.count} 轮）"
        case End():
            return f"{name}（{'成功' if step.success else '失败'}）"
    return name


def describe_condition(cond: Condition | None, label: Callable[[str], str] = _plain) -> str:
    if cond is None:
        return ""
    what = (f"在「{SCENE_NAMES.get(cond.scene, cond.scene)}」" if cond.kind == "scene"
            else f"{_names(cond.templates, label)}{'出现' if cond.appear else '不出现'}")
    if cond.kind == "scene" and not cond.appear:
        what = f"不{what}"
    return what + (f"（等 {cond.wait:g} 秒）" if cond.wait > 0 else "")


class FlowRunner:
    def __init__(self, ctl: Controller, flow: Flow, logger: logging.Logger | None = None,
                 publish: Callable[[str, dict], None] | None = None):
        self.ctl = ctl
        self.flow = flow
        self.log = logger or logging.getLogger(__name__)
        self.publish = publish
        self.report = RunReport()

    def label(self, ref: str) -> str:
        """模板引用 → 玩家看得懂的名字：玩家模板就是名字；内置模板用备注括号前那段（「大厅左侧「圣域」文字」）。"""
        if not ref.startswith(COMMON_PREFIX):
            return ref
        try:
            note = self.ctl.vision.template(ref).meta.note
        except (TemplateNotFound, ValueError):
            note = ""
        return re.split(r"[（(]", note)[0].strip() or _plain(ref)

    # ------------------------------------------------------------ 入口

    def run(self) -> RunReport:
        """跑完整个流程。失败抛 FlowFailed；急停 / 超时 / 卡死照常抛 TaskAborted。"""
        try:
            self._exec(self.flow.steps, "")
        except _Break:  # 结构校验保证 break 在循环里，这里只是兜底
            pass
        except _End as e:
            self.report.message = e.message
            if not e.success:
                raise FlowFailed(e.message or "流程走到「结束流程（失败）」") from None
            self.log.info("流程结束%s", f"：{e.message}" if e.message else "")
        return self.report

    def _exec(self, steps: list, prefix: str, start: int = 1) -> None:
        for i, step in enumerate(steps, start):
            path = f"{prefix}{i}"
            self.ctl.check()
            self.ctl.progress()  # 每一步都有自己的超时，流程整体有运行时间上限，不靠卡死检测
            self.report.steps += 1
            self.log.info("第 %s 步：%s", path, describe(step, self.label))
            if self.publish is not None:
                self.publish(STEP_TOPIC, {"flow": self.flow.id, "path": path, "id": step.id, "type": step.type})
            getattr(self, f"_do_{step.type}")(step, path)

    def _missing(self, step, path: str, what: str) -> None:
        if step.on_missing == "skip":
            self.log.info("第 %s 步：%s，跳过", path, what)
            return
        raise FlowFailed(f"第 {path} 步：{what}")

    # ------------------------------------------------------------ 画面 / 弹窗

    def _handle_popups(self, state: SceneState) -> bool:
        """当前画面有要自动处理的弹窗（断线重进、网络重试、确认框）就处理掉，返回是否处理了。"""
        if state.popup not in HANDLED_POPUPS:
            return False
        closed = self.ctl.dismiss_popups(state=state, only=HANDLED_POPUPS)
        self.report.popups += len(closed)
        return bool(closed)

    def _poll(self, probe: Callable[[np.ndarray, SceneState], T | None], timeout: float) -> T | None:
        """反复截图：先处理弹窗，再调 probe(frame, state)；返回非 None 的结果，超时返回 None。

        timeout=0 只看一次。处理弹窗时发生了断线重进，就重新计时。
        """
        deadline = time.monotonic() + timeout
        while True:
            frame = self.ctl.screenshot()
            state = self.ctl.detect(frame)
            reloads = self.ctl.reloads
            if self._handle_popups(state):
                if self.ctl.reloads != reloads:
                    deadline = max(deadline, time.monotonic() + timeout)
                continue
            result = probe(frame, state)
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                return None
            if timeout > 0:
                self.ctl.progress()
            self.ctl.sleep(POLL)

    def _frame(self) -> np.ndarray:
        """处理掉弹窗后的当前画面。"""
        return self._poll(lambda f, s: f, 0.0)

    def _settle(self, timeout: float) -> bool:
        """等画面静止（帧差 < SETTLE_FRAME_DIFF 持续 SETTLE_TIME 秒），返回是否等到了。"""
        deadline = time.monotonic() + timeout
        prev = thumbnail(self.ctl.screenshot())
        since: float | None = None
        while True:
            self.ctl.sleep(0.15)
            thumb = thumbnail(self.ctl.screenshot())
            now = time.monotonic()
            if thumb_diff(thumb, prev) < SETTLE_FRAME_DIFF:
                since = since or now
                if now - since >= SETTLE_TIME:
                    return True
            else:
                since = None
            prev = thumb
            if now >= deadline:
                return False

    def _find_any(self, frame: np.ndarray, refs: list[str]) -> Match | None:
        hits = [m for r in refs if (m := self.ctl.vision.find(frame, r)) is not None]
        return max(hits, key=lambda m: m.score, default=None)

    def _test(self, cond: Condition, frame: np.ndarray, state: SceneState) -> bool:
        hit = state.is_(cond.scene) if cond.kind == "scene" else self._find_any(frame, cond.templates) is not None
        return hit if cond.appear else not hit

    def _condition(self, cond: Condition) -> bool:
        """最多等 cond.wait 秒，期间成立就返回 True。"""
        return self._poll(lambda f, s: True if self._test(cond, f, s) else None, cond.wait) is True

    # ------------------------------------------------------------ 安全

    def _count_tap(self, path: str) -> None:
        limit = self.flow.limits.max_taps
        if self.report.taps >= limit:
            raise FlowFailed(f"第 {path} 步：已经点了 {limit} 次，到了最多点击次数，停止")
        self.report.taps += 1

    def _guard(self, frame: np.ndarray, area: Rect, path: str) -> None:
        """落点（area，基准坐标）碰到已知的「确认 / 购买」按钮就拦下。"""
        vision = self.ctl.scenes.vision
        target = area.expand(TAP_MARGIN)
        for ref, label in FORBIDDEN_BUTTONS.items():
            try:
                m = vision.find(frame, ref)
            except TemplateNotFound:
                continue
            if m is not None and _overlap(m.rect, target):
                self.log.warning("第 %s 步：落点在%s上，已拦下（流程不能点确认 / 购买）", path, label)
                raise FlowBlocked(f"第 {path} 步：要点的位置是{label}按钮，已拦下并停止流程")

    # ------------------------------------------------------------ 动作

    def _do_tap_template(self, step: TapTemplate, path: str) -> None:
        ref = step.template
        m = self._poll(lambda f, s: self.ctl.vision.find(f, ref), step.timeout)
        if m is None:
            return self._missing(step, path, f"等了 {step.timeout:g} 秒没找到{_names([ref], self.label)}")
        if step.settle and not self._settle(3.0):
            self.log.debug("第 %s 步：画面一直在动，照样点", path)
        frame = self._frame()
        fresh = self.ctl.vision.find(frame, ref)
        if fresh is None:
            fresh = self._poll(lambda f, s: self.ctl.vision.find(f, ref), 2.0)
            if fresh is None:
                return self._missing(step, path, f"{_names([ref], self.label)}找到后又不见了")
            frame = self.ctl.last_frame
        area = self.ctl.vision.template(ref).tap_area(fresh.rect)
        self._guard(frame, area, path)
        self._count_tap(path)
        self.ctl.tap_rect(area)

    def _do_tap_point(self, step: TapPoint, path: str) -> None:
        frame = self._frame()
        self._guard(frame, Rect(step.x, step.y, 1, 1), path)
        self._count_tap(path)
        self.ctl.tap(step.x, step.y)

    def _do_swipe(self, step: Swipe, path: str) -> None:
        frame = self._frame()
        self._guard(frame, Rect(step.x1, step.y1, 1, 1), path)
        self._count_tap(path)
        self.ctl.swipe(step.x1, step.y1, step.x2, step.y2, step.duration)

    def _do_back(self, step: Back, path: str) -> None:
        self._frame()
        self.ctl.back()

    def _do_wait(self, step: Wait, path: str) -> None:
        self.ctl.sleep(step.seconds)

    def _do_wait_still(self, step: WaitStill, path: str) -> None:
        if not self._settle(step.timeout):
            self.log.info("第 %s 步：%g 秒内画面一直在动，继续", path, step.timeout)

    def _do_wait_template(self, step: WaitTemplate, path: str) -> None:
        def probe(f, s):
            hit = self._find_any(f, step.templates) is not None
            return True if hit == step.appear else None

        if self._poll(probe, step.timeout) is None:
            what = "出现" if step.appear else "消失"
            self._missing(step, path, f"等了 {step.timeout:g} 秒{_names(step.templates, self.label)}没有{what}")

    def _do_wait_scene(self, step: WaitScene, path: str) -> None:
        start = time.monotonic()
        if self._poll(lambda f, s: True if s.is_(step.scene) else None, step.timeout) is None:
            name = SCENE_NAMES.get(step.scene, step.scene)
            return self._missing(step, path, f"等了 {step.timeout:g} 秒没有回到「{name}」")
        # 认出界面后再等画面静止（淡入、列表飞入期间点击会被游戏忽略）
        left = max(1.0, step.timeout - (time.monotonic() - start))
        self.ctl.wait_scene(step.scene, timeout=left, dismiss=False)

    # ------------------------------------------------------------ 控制

    def _do_end(self, step: End, path: str) -> None:
        raise _End(step.success, step.message)

    def _do_break(self, step: Break, path: str) -> None:
        raise _Break()

    def _do_if(self, step: If, path: str) -> None:
        ok = self._condition(step.condition)
        self.log.info("第 %s 步：条件%s", path, "成立" if ok else "不成立")
        if ok:
            self._exec(step.then, f"{path}.")
        else:
            self._exec(step.else_, f"{path}.", start=len(step.then) + 1)

    def _do_repeat(self, step: Repeat, path: str) -> None:
        done = step.mode == "times"
        for k in range(1, step.count + 1):
            if step.mode != "times":
                ok = self._condition(step.condition)
                if ok == (step.mode == "until"):
                    done = True
                    break
            self.log.info("第 %s 步：第 %d/%d 轮", path, k, step.count)
            try:
                self._exec(step.body, f"{path}.")
            except _Break:
                done = True
                break
        else:
            if step.mode != "times":
                # 最后一轮跑完再看一次条件
                ok = self._condition(step.condition.model_copy(update={"wait": 0.0}))
                done = ok == (step.mode == "until")
        if not done:
            msg = f"第 {path} 步：重复了 {step.count} 轮，条件仍然{'不成立' if step.mode == 'until' else '成立'}"
            if step.on_limit == "stop":
                raise FlowFailed(msg)
            self.log.info("%s，继续往下走", msg)


def _overlap(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom
