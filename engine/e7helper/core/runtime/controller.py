"""Controller：任务模块操作游戏的统一入口（模块里是 `self.ctl`）。

- 坐标一律是 1600x900 基准，换算到设备坐标在这一层完成；
- 点击带随机偏移、随机按压时长和点击后的随机等待（见 humanize.Humanize）；
- 每次截图/点击/等待前都检查急停、超时和卡死，触发时抛出 TaskAborted 的子类；
- 截图会发布 Topic.FRAME 事件（助手模块因此能和任务并行拿到帧），并喂给卡死检测；
- 场景识别和弹窗处理：detect / dismiss_popups / wait_scene。断线弹窗会自动关闭并等游戏重新进来（B10a）。
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Collection, Iterable
from typing import TypeVar

import numpy as np

from e7helper.core.events import EventBus, Topic
from e7helper.core.geometry import Rect, Scaler
from e7helper.core.scene import OBSCURED, DismissKind, Popup, SceneDetector, SceneState
from e7helper.core.vision import Match, TemplateNotFound, Vision
from e7helper.device import Device

from .errors import PopupError, TaskStatus, TaskStopped, TaskStuck, TaskTimeout, WaitTimeout
from .humanize import Humanize
from .stuck import StuckDetector, thumb_diff, thumbnail

T = TypeVar("T")

DEFAULT_INTERVAL = 0.3  # 轮询间隔（秒）
POPUP_SETTLE = 0.8  # 关闭弹窗后等动画结束
# 界面稳定：连续截图的缩略图平均差 < SETTLE_FRAME_DIFF，且持续 SETTLE_TIME 秒。
# 实测（B03）：进秘密商店时帧间差 79→54→18→10→13→8→1，约 1.7 秒后静止，2 秒后才响应点击；
# 大厅/商店待机动画的帧间差 ≤ 3.8。
SETTLE_FRAME_DIFF = 5.0
SETTLE_TIME = 0.5
# 关闭 reload 弹窗后等游戏重新加载的上限。实测（B10a）：关断线框 → 公告窗 → 标题画面「连接中」约 15 秒 →
# 点「轻触画面开始」→ 黑屏约 16 秒 → 大厅
RELOAD_TIMEOUT = 120.0
# 关闭后这么久内还认出同一个弹窗，当成它在淡出，继续等；超过了才认为没点到、交回去重新关闭
RELOAD_FADE = 3.0


class AbortSignal:
    """急停信号。event 就是 ModuleContext.stop_event；reason 区分是用户急停还是超时。"""

    def __init__(self, event: threading.Event | None = None):
        self.event = event or threading.Event()
        self.reason: TaskStatus | None = None

    def abort(self, reason: TaskStatus = TaskStatus.STOPPED) -> None:
        if self.reason is None:
            self.reason = reason
        self.event.set()

    @property
    def aborted(self) -> bool:
        return self.event.is_set()


class Controller:
    def __init__(
        self,
        device: Device,
        vision: Vision,
        scenes: SceneDetector,
        *,
        bus: EventBus | None = None,
        signal: AbortSignal | None = None,
        humanize: Humanize | None = None,
        stuck: StuckDetector | None = None,
        rng: random.Random | None = None,
        logger: logging.Logger | None = None,
    ):
        self.device = device
        self.vision = vision
        self.scenes = scenes
        self.bus = bus
        self.signal = signal or AbortSignal()
        self.humanize = humanize or Humanize()
        self.stuck = stuck or StuckDetector()
        self.rng = rng or random.Random()
        self.log = logger or logging.getLogger(__name__)
        self.last_frame: np.ndarray | None = None
        self.last_state: SceneState | None = None
        self.reloads = 0  # 游戏重新加载（断线重进）的次数，wait_scene / tap_until 据此放宽超时

    @property
    def scaler(self) -> Scaler:
        return Scaler(*self.device.resolution)

    # ------------------------------------------------------------ 急停 / 等待

    def check(self) -> None:
        """急停、超时、卡死时抛出对应的 TaskAborted。"""
        if self.signal.aborted:
            if self.signal.reason is TaskStatus.TIMEOUT:
                raise TaskTimeout("任务超时")
            raise TaskStopped("收到停止信号")
        reason = self.stuck.reason
        if reason:
            raise TaskStuck(reason)

    def sleep(self, seconds: float) -> None:
        """可被急停打断的 sleep。"""
        self.check()
        if seconds > 0:
            self.signal.event.wait(seconds)
        self.check()

    def progress(self) -> None:
        """任务取得了进展：清零卡死检测的计数。"""
        self.stuck.reset()

    # ------------------------------------------------------------ 截图 / 识别

    def screenshot(self) -> np.ndarray:
        self.check()
        frame = self.device.screenshot()
        self.last_frame = frame
        self.stuck.feed_frame(frame)
        if self.bus is not None:
            self.bus.publish(Topic.FRAME, frame)
        return frame

    def find(self, ref, frame: np.ndarray | None = None, region: Rect | None = None,
             threshold: float | None = None) -> Match | None:
        return self.vision.find(self.screenshot() if frame is None else frame, ref, region, threshold)

    def exists(self, ref, frame: np.ndarray | None = None, region: Rect | None = None) -> bool:
        return self.find(ref, frame, region) is not None

    def wait_until(self, probe: Callable[[np.ndarray], T | None], timeout: float = 10.0,
                   interval: float = DEFAULT_INTERVAL, what: str = "条件") -> T:
        """反复截图调用 probe(frame)，直到返回非 None 值；超时抛 WaitTimeout。"""
        deadline = time.monotonic() + timeout
        while True:
            result = probe(self.screenshot())
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                raise WaitTimeout(f"等待{what}超时（{timeout:.0f} 秒）")
            self.sleep(interval)

    def wait(self, ref, timeout: float = 10.0, region: Rect | None = None,
             interval: float = DEFAULT_INTERVAL) -> Match:
        """等模板出现，返回命中。"""
        return self.wait_until(lambda f: self.vision.find(f, ref, region), timeout, interval, f"模板 {ref}")

    def wait_gone(self, ref, timeout: float = 10.0, region: Rect | None = None,
                  interval: float = DEFAULT_INTERVAL) -> None:
        self.wait_until(lambda f: True if self.vision.find(f, ref, region) is None else None,
                        timeout, interval, f"模板 {ref} 消失")

    def detect(self, frame: np.ndarray | None = None) -> SceneState:
        state = self.scenes.detect(self.screenshot() if frame is None else frame)
        self.stuck.feed_scene(f"{state.scene}|{state.popup}")
        prev = self.last_state
        self.last_state = state
        if prev is None or (prev.scene, prev.popup) != (state.scene, state.popup):
            self.log.debug("场景：%s", state)
            if self.bus is not None:
                self.bus.publish(Topic.SCENE, {"scene": state.scene, "popup": state.popup, "obscured": state.obscured})
        return state

    # ------------------------------------------------------------ 弹窗 / 场景

    def dismiss_popups(self, max_rounds: int = 6, state: SceneState | None = None, *,
                       only: Collection[str] | None = None) -> list[str]:
        """关闭当前所有可自动关闭的弹窗，返回关掉的弹窗名。

        遇到 auto=False 的弹窗，或关了 max_rounds 次仍有弹窗时抛 PopupError。
        only（B11 自定义流程用）：只关闭这些弹窗；遇到别的弹窗或遮罩时直接返回，不按返回键兜底。
        """
        closed: list[str] = []
        for _ in range(max_rounds):
            state = state or self.detect()
            if only is not None:
                if state.popup is None or state.popup not in only:
                    return closed
            else:
                if state.popup == OBSCURED:
                    state = self._confirm_obscured()
                if state.clear:
                    return closed
            popup = self.scenes.popup(state.popup)
            if not popup.auto:
                raise PopupError(popup.name, f"弹窗 {popup.name} 不能自动关闭，需要任务处理")
            self._dismiss(popup, state)
            closed.append(popup.name)
            if popup.reload:
                state = self._wait_reload(popup)
                continue
            self.sleep(POPUP_SETTLE)
            state = None
        state = self.detect()
        if only is not None:
            if state.popup in only:
                raise PopupError(state.popup, f"连续关闭 {max_rounds} 次后仍有弹窗：{state.popup}（已关闭 {closed}）")
            return closed
        if state.popup == OBSCURED:
            state = self._confirm_obscured()
        if not state.clear:
            raise PopupError(state.popup, f"连续关闭 {max_rounds} 次后仍有弹窗：{state.popup}（已关闭 {closed}）")
        return closed

    def _confirm_obscured(self, max_wait: float = 3.0) -> SceneState:
        """复核遮罩兜底：界面切换的淡入淡出也会让画面短暂变暗，只有压暗且画面静止才算未知弹窗。

        连续截图，直到不再是 OBSCURED，或压暗且静止持续 SETTLE_TIME 秒；返回复核后的状态。
        一直在动、超过 max_wait 秒时按仍有遮罩返回。
        """
        deadline = time.monotonic() + max_wait
        prev = thumbnail(self.last_frame)
        stable_since: float | None = None
        while True:
            t = time.monotonic()
            self.sleep(0.15)
            state = self.detect()
            if state.popup != OBSCURED:
                return state
            thumb = thumbnail(self.last_frame)
            now = time.monotonic()
            if thumb_diff(thumb, prev) < SETTLE_FRAME_DIFF:
                stable_since = stable_since or t
                if now - stable_since >= SETTLE_TIME:
                    return state
            else:
                stable_since = None
            prev = thumb
            if now >= deadline:
                return state

    def _wait_reload(self, popup: Popup, timeout: float | None = None) -> SceneState:
        """关闭 reload 弹窗后等游戏重新加载：直到认出场景，或出现下一个弹窗（公告窗、标题画面……）。

        加载中（标题画面「连接中」、黑屏）既没有场景也没有弹窗；期间不断清零卡死计数，超时抛 PopupError。
        """
        self.log.warning("%s：等待游戏重新加载", popup.note or popup.name)
        timeout = RELOAD_TIMEOUT if timeout is None else timeout
        self.reloads += 1
        start = time.monotonic()
        while True:
            self.progress()
            self.sleep(DEFAULT_INTERVAL)
            state = self.detect()
            elapsed = time.monotonic() - start
            fading = state.popup == popup.name and elapsed < RELOAD_FADE
            if not fading and (state.scene is not None or state.popup is not None):
                if state.clear:
                    self.log.info("游戏重新加载完成（%.0f 秒）：%s", elapsed, state)
                return state
            if elapsed >= timeout:
                raise PopupError(popup.name, f"关闭 {popup.name} 后 {timeout:.0f} 秒游戏仍未加载完，当前：{state}")

    def _dismiss(self, popup: Popup, state: SceneState) -> None:
        d = popup.dismiss
        self.log.info("关闭弹窗 %s：%s", popup.name, d)
        if d.kind is DismissKind.TAP:
            m = state.matches.get(d.target) or self.find(d.target, self.last_frame)
            if m is None:
                raise PopupError(popup.name, f"弹窗 {popup.name} 的关闭按钮 {d.target} 没找到")
            self.tap_match(m, ref=d.target)
        elif d.kind is DismissKind.POINT:
            self.tap(*d.point)
        elif d.kind is DismissKind.BACK:
            self.back()
        else:
            raise PopupError(popup.name, f"弹窗 {popup.name} 没有自动关闭方式")

    def wait_scene(self, scenes: str | Iterable[str], timeout: float = 15.0, *, dismiss: bool = True,
                   settle: bool = True, interval: float = DEFAULT_INTERVAL) -> SceneState:
        """等到指定场景之一（且没有弹窗）。

        dismiss=True 时顺手关闭途中出现的弹窗。
        settle=True 时还要等界面静止：切换界面有淡入、列表飞入等动画，标题出现后 1–2 秒内点击会被忽略。
        要求连续截图的画面变化 < SETTLE_FRAME_DIFF 且持续 SETTLE_TIME 秒（待机动画的变化低于这个阈值）。
        """
        names = (scenes,) if isinstance(scenes, str) else tuple(scenes)
        deadline = time.monotonic() + timeout
        prev_thumb: np.ndarray | None = None
        stable_since: float | None = None
        while True:
            state = self.detect()
            now = time.monotonic()
            if state.is_(*names):
                thumb = thumbnail(self.last_frame)
                if not settle:
                    return state
                if prev_thumb is not None and thumb_diff(thumb, prev_thumb) < SETTLE_FRAME_DIFF:
                    if stable_since is None:
                        stable_since = prev_at
                    if now - stable_since >= SETTLE_TIME:
                        return state
                else:
                    stable_since = None
                prev_thumb, prev_at = thumb, now
            else:
                prev_thumb, stable_since = None, None
                if dismiss and not state.clear and self.scenes.popup(state.popup).auto:
                    reloads = self.reloads
                    self.dismiss_popups(state=state)
                    if self.reloads != reloads:
                        # 断线重进游戏花了几十秒，重新计时
                        deadline = max(deadline, time.monotonic() + timeout)
                    continue
            if now >= deadline:
                raise WaitTimeout(f"等待场景 {'/'.join(names)} 超时（{timeout:.0f} 秒），当前：{state}")
            self.sleep(interval)

    def tap_until(self, target: str | Match | Rect | tuple[int, int], scenes: str | Iterable[str],
                  timeout: float = 20.0, *, retry_after: float = 6.0, max_taps: int = 3,
                  settle: bool = True) -> SceneState:
        """导航用：点击 target，直到进入 scenes 之一（等待期间自动关闭弹窗，如网络异常重试）。

        进商店这类操作要等服务器响应，网络慢时几秒内画面没有任何变化。retry_after 秒后若仍停在
        点击前的场景（且没有弹窗），就再点一次，最多 max_taps 次。
        只能用于重复点击无害的导航；刷新、购买等有消耗的操作不要用它。
        target：模板引用（每次点击前重新查找）、Match、Rect 或基准坐标 (x, y)。
        settle=False：目标界面一直有动画（例如战后界面的战斗场景背景）时不等画面静止。
        """
        names = (scenes,) if isinstance(scenes, str) else tuple(scenes)
        origin = self.detect()
        if origin.is_(*names):
            return origin
        deadline = time.monotonic() + timeout
        taps = 0
        while True:
            self._tap_target(target)
            taps += 1
            retry_at = time.monotonic() + retry_after
            reloads = self.reloads
            try:
                return self.wait_scene(names, timeout=max(0.0, min(retry_at, deadline) - time.monotonic()),
                                       settle=settle)
            except WaitTimeout:
                state = self.last_state
                if self.reloads != reloads:
                    # 等待途中断线重进了游戏：重新计时；回到了点击前的场景就按下面的规则补点
                    deadline = max(deadline, time.monotonic() + timeout)
                if time.monotonic() >= deadline or taps >= max_taps:
                    raise WaitTimeout(f"点击 {target} 后没有进入 {'/'.join(names)}（点了 {taps} 次），当前：{state}") from None
                if not (state.clear and state.scene == origin.scene):
                    # 画面已经变了（在加载/过渡），不再重复点击，只继续等
                    return self.wait_scene(names, timeout=max(0.0, deadline - time.monotonic()), settle=settle)
                self.log.info("点击 %s 后 %.0f 秒仍在 %s，重新点击", target, retry_after, state)

    def _tap_target(self, target: str | Match | Rect | tuple[int, int]) -> None:
        if isinstance(target, Match):
            self.tap_match(target)
        elif isinstance(target, Rect):
            self.tap_rect(target)
        elif isinstance(target, tuple):
            self.tap(*target)
        else:
            self.tap_template(target, timeout=3.0)

    # ------------------------------------------------------------ 输入（基准坐标）

    def tap(self, x: float, y: float, *, jitter: float | None = None, delay: bool = True) -> tuple[int, int]:
        """点击基准坐标 (x, y)，带小幅随机抖动；返回实际点击的基准坐标。"""
        bx, by = self.humanize.jitter(x, y, self.rng, jitter)
        self._tap_base(bx, by, delay)
        return bx, by

    def tap_rect(self, rect: Rect, *, delay: bool = True) -> tuple[int, int]:
        """在矩形（基准坐标）内随机取点点击。"""
        bx, by = self.humanize.point_in(rect, self.rng)
        self._tap_base(bx, by, delay)
        return bx, by

    def tap_match(self, match: Match, *, ref=None, delay: bool = True) -> tuple[int, int]:
        """点击命中的模板。模板 json 设了 tap（可点区域与识别区域不一致）时点 tap 区域。

        ref 是查找时用的模板引用；省略时按 match.name 在本模块和 common 里找。
        """
        try:
            area = self.vision.template(ref if ref is not None else match.name).tap_area(match.rect)
        except TemplateNotFound:
            area = match.rect
        return self.tap_rect(area, delay=delay)

    def tap_template(self, ref, timeout: float = 0.0, region: Rect | None = None) -> Match:
        """找到模板并点击。timeout > 0 时先等它出现；找不到抛 WaitTimeout。"""
        m = self.wait(ref, timeout, region) if timeout > 0 else self.find(ref, region=region)
        if m is None:
            raise WaitTimeout(f"没找到 {ref}")
        self.tap_match(m, ref=ref)
        return m

    def _tap_base(self, bx: int, by: int, delay: bool) -> None:
        self.check()
        dx, dy = self.scaler.to_device(bx, by)
        self.log.debug("tap (%d, %d) → 设备 (%d, %d)", bx, by, dx, dy)
        self.device.tap(dx, dy, self.humanize.press_time(self.rng))
        if delay:
            self.sleep(self.humanize.delay_time(self.rng))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration: float = 0.4,
              *, delay: bool = True) -> None:
        h = self.humanize
        p1 = h.jitter(x1, y1, self.rng, h.swipe_jitter_px)
        p2 = h.jitter(x2, y2, self.rng, h.swipe_jitter_px)
        dur = duration * self.rng.uniform(*h.swipe_stretch)
        self.check()
        s = self.scaler
        self.device.swipe(*s.to_device(*p1), *s.to_device(*p2), dur)
        if delay:
            self.sleep(h.delay_time(self.rng))

    def back(self, *, delay: bool = True) -> None:
        """Android 返回键。"""
        self.check()
        self.device.back()
        if delay:
            self.sleep(self.humanize.delay_time(self.rng))

    def input_text(self, text: str, *, delay: bool = True) -> None:
        """往当前获得焦点的输入框里打字（先点输入框）。"""
        self.check()
        self.device.input_text(text)
        if delay:
            self.sleep(self.humanize.delay_time(self.rng))
