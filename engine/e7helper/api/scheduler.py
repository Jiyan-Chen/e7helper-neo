"""定时调度：按计划反复启动任务模块（B08）。

计划存在 `<数据目录>/schedules.json`。每条计划有三种触发方式：
- `interval`：每隔 N 分钟，从**上次结束**（或跳过）算起；新建 / 重新启用后立即跑第一次。
- `daily`：每天北京时间固定时刻（固定 UTC+8，中国没有夏令时；Windows 上 zoneinfo 还要另装 tzdata）。
- `module`：由模块的 `TaskModule.next_due()` 决定（例如 daily：重置后跑一次，精灵之森到时间再跑），
  两次运行之间至少隔 min_interval_minutes；连续失败时这个间隔按 2 的幂增大。

规则：
- 服务没开的时候错过的时刻，启动后只补跑一次（下一次从这次运行算起）。
- 到点时有任务在跑：`on_busy="queue"`（默认）排队，空闲后按入队先后启动；排队超过 max_wait_minutes 就放弃这一次。
  `on_busy="skip"` 直接跳过。每条计划最多排一个。
- 到点时设备没连上：先试着连一次，连不上就跳过。
- 计划的 config 是完整配置（新建时不给就复制模块保存的配置）；调度器不改 dry_run。
- 连续失败（failed / stuck / timeout）3 次自动停用这条计划；用户急停（stopped）不计。
- 总开关 pause / resume 只影响触发，不影响正在跑的任务。
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from e7helper.core.events import Topic
from e7helper.core.paths import data_dir, module_data_dir
from e7helper.core.runtime import TaskStatus

from .engine import ApiError, Engine, TaskRecord, _read_json, validation_detail, write_json_atomic

log = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8), "UTC+08:00")
MAX_FAILURES = 3
FAILED_STATUSES = {TaskStatus.FAILED.value, TaskStatus.STUCK.value, TaskStatus.TIMEOUT.value}


def utcnow() -> datetime:
    return datetime.now(UTC)


class IntervalTrigger(BaseModel):
    type: Literal["interval"] = "interval"
    minutes: float = Field(ge=1, le=7 * 24 * 60, description="间隔分钟数，从上次结束算起")


class DailyTrigger(BaseModel):
    type: Literal["daily"] = "daily"
    at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="每天的北京时间 HH:MM，例如 03:05")


class ModuleTrigger(BaseModel):
    type: Literal["module"] = "module"
    min_interval_minutes: float = Field(10, ge=1, le=24 * 60, description="两次运行之间的最短间隔（分钟）")


Trigger = Annotated[IntervalTrigger | DailyTrigger | ModuleTrigger, Field(discriminator="type")]


class ScheduleSpec(BaseModel):
    """用户可编辑的部分。"""

    model_config = ConfigDict(extra="forbid")

    module: str
    name: str = ""
    enabled: bool = True
    trigger: Trigger
    config: dict | None = Field(None, description="完整的模块配置；新建时不给就复制模块保存的配置")
    timeout: float | None = Field(None, gt=0, description="任务时限（秒）")
    on_busy: Literal["queue", "skip"] = "queue"
    max_wait_minutes: float = Field(30, ge=0, description="排队最多等多久，超过就放弃这一次")


class ScheduleState(BaseModel):
    """调度器维护的部分。时间都带时区（UTC）。"""

    created: datetime
    next_run: datetime | None = None
    last_attempt: datetime | None = None  # 上次运行结束或跳过的时间：下一次从这里算
    last_started: datetime | None = None
    last_ended: datetime | None = None
    last_status: str | None = None
    last_task: str | None = None
    last_success: datetime | None = None
    last_skip: str | None = None  # 上次跳过的原因
    failures: int = 0
    queued_since: datetime | None = None
    running_task: str | None = None


class Schedule(ScheduleSpec):
    id: str
    state: ScheduleState


def next_daily(at: str, after: datetime) -> datetime:
    """after 之后（不含）第一个北京时间 at，返回 UTC。"""
    hh, mm = (int(x) for x in at.split(":"))
    local = after.astimezone(BEIJING)
    cand = datetime.combine(local.date(), time(hh, mm), BEIJING)
    if cand <= local:
        cand += timedelta(days=1)
    return cand.astimezone(UTC)


class Scheduler:
    def __init__(self, engine: Engine, *, path: Path | None = None, clock: Callable[[], datetime] = utcnow,
                 tick: float = 1.0):
        self.engine = engine
        self.path = path or data_dir() / "schedules.json"
        self.clock = clock
        self.tick_interval = tick
        self._lock = threading.RLock()
        self.schedules: dict[str, Schedule] = {}
        self.paused = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load()

    # ------------------------------------------------------------ 持久化

    def _load(self) -> None:
        data = _read_json(self.path)
        if not isinstance(data, dict):
            return
        self.paused = bool(data.get("paused", False))
        for raw in data.get("schedules") or []:
            try:
                s = Schedule.model_validate(raw)
            except ValidationError as e:
                log.warning("计划文件里有一条不合法，忽略：%s", e)
                continue
            # 上次服务退出时还在跑 / 排队的，状态作废
            s.state.running_task = None
            s.state.queued_since = None
            self.schedules[s.id] = s

    def save(self) -> None:
        with self._lock:
            data = {"paused": self.paused,
                    "schedules": [s.model_dump(mode="json") for s in self.schedules.values()]}
        try:
            write_json_atomic(self.path, data)
        except OSError:
            log.exception("写计划文件失败：%s", self.path)

    # ------------------------------------------------------------ 线程

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="api:scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.tick_interval):
            try:
                self.tick()
            except Exception:
                log.exception("调度器出错")

    # ------------------------------------------------------------ 增删改查

    def _normalize(self, spec: ScheduleSpec) -> ScheduleSpec:
        cls = self.engine.get_task_module(spec.module)
        if spec.trigger.type == "module" and not cls.supports_next_due():
            raise ApiError(400, "trigger_unsupported", f"{spec.module} 没有提供下次运行时间，不能用「按模块时间」")
        cfg = (self.engine.validate_config(cls, spec.config) if spec.config is not None
               else self.engine.load_config(cls))
        return spec.model_copy(update={"config": cfg.model_dump(mode="json")})

    def snapshot(self) -> dict:
        with self._lock:
            self._refresh(self.clock())
            return {"paused": self.paused, "schedules": [self._out(s) for s in self.schedules.values()]}

    def get(self, sid: str) -> dict:
        with self._lock:
            return self._out(self._get(sid))

    def _get(self, sid: str) -> Schedule:
        s = self.schedules.get(sid)
        if s is None:
            raise ApiError(404, "unknown_schedule", f"没有这条计划：{sid}")
        return s

    def _out(self, s: Schedule) -> dict:
        d = s.model_dump(mode="json")
        cls = self.engine.modules.get(s.module)
        d["module_name"] = cls.name if cls else None
        return d

    def create(self, spec: ScheduleSpec) -> dict:
        spec = self._normalize(spec)
        now = self.clock()
        s = Schedule(**spec.model_dump(), id=uuid.uuid4().hex[:10], state=ScheduleState(created=now))
        with self._lock:
            self.schedules[s.id] = s
            self._refresh(now)
        self.save()
        self._publish(s, "created")
        return self.get(s.id)

    def update(self, sid: str, changes: dict) -> dict:
        with self._lock:
            s = self._get(sid)
            merged = {**s.model_dump(include=set(ScheduleSpec.model_fields)), **changes}
            if "module" in changes and changes["module"] != s.module and "config" not in changes:
                merged["config"] = None  # 换了模块：重新取那个模块保存的配置
            try:
                spec = ScheduleSpec.model_validate(merged)
            except ValidationError as e:
                raise ApiError(422, "invalid_schedule", "计划不合法", validation_detail(e)) from e
            spec = self._normalize(spec)
            was_enabled = s.enabled
            for k, v in spec.model_dump().items():
                setattr(s, k, getattr(spec, k) if k == "trigger" else v)
            if not was_enabled and s.enabled:
                s.state.failures = 0
            if not s.enabled:
                s.state.queued_since = None
            self._refresh(self.clock())
        self.save()
        self._publish(s, "updated")
        return self.get(sid)

    def delete(self, sid: str) -> None:
        with self._lock:
            s = self._get(sid)
            del self.schedules[sid]
        self.save()
        self._publish(s, "deleted")

    def set_paused(self, paused: bool) -> dict:
        with self._lock:
            self.paused = paused
            if paused:
                for s in self.schedules.values():
                    s.state.queued_since = None
        self.save()
        self.engine.bus.publish(Topic.SCHEDULE, {"action": "paused" if paused else "resumed"})
        log.info("调度器已%s", "暂停" if paused else "恢复")
        return self.snapshot()

    def run_now(self, sid: str) -> dict:
        """立即跑一次（不看触发时间）；有任务在跑返回 409。"""
        with self._lock:
            s = self._get(sid)
            if s.state.running_task:
                raise ApiError(409, "busy", "这条计划的任务正在运行")
            return self._start(s, self.clock(), manual=True)

    # ------------------------------------------------------------ 计算下次时间

    def _next_run(self, s: Schedule, now: datetime) -> datetime | None:
        if not s.enabled or s.state.running_task:
            return None
        st = s.state
        t = s.trigger
        if t.type == "interval":
            return st.created if st.last_attempt is None else st.last_attempt + timedelta(minutes=t.minutes)
        if t.type == "daily":
            return next_daily(t.at, st.last_attempt or st.created)
        cls = self.engine.modules.get(s.module)
        if cls is None:
            return None
        try:
            cfg = cls.config_model.model_validate(s.config or {})
            due = cls.next_due(cfg, module_data_dir(s.module), st.last_success)
        except Exception as e:  # noqa: BLE001
            log.warning("计划 %s：%s.next_due 出错：%s", s.id, s.module, e)
            return None
        if due is None:
            return None
        due = due.astimezone(UTC)
        if st.last_attempt is not None:
            gap = timedelta(minutes=t.min_interval_minutes * (2 ** min(st.failures, 4)))
            due = max(due, st.last_attempt + gap)
        return due

    def _refresh(self, now: datetime) -> None:
        for s in self.schedules.values():
            s.state.next_run = self._next_run(s, now)

    # ------------------------------------------------------------ 触发

    def tick(self) -> None:
        now = self.clock()
        with self._lock:
            self._refresh(now)
            if self.paused:
                return
            due = sorted(
                (s for s in self.schedules.values()
                 if s.state.next_run is not None and s.state.next_run <= now and not s.state.queued_since),
                key=lambda s: s.state.next_run,
            )
            for s in due:
                self._fire(s, now)
            queued = sorted((s for s in self.schedules.values() if s.state.queued_since),
                            key=lambda s: s.state.queued_since)
            for s in queued:
                if now - s.state.queued_since > timedelta(minutes=s.max_wait_minutes):
                    self._skip(s, now, f"排队超过 {s.max_wait_minutes:g} 分钟")
                elif not self.engine.busy:
                    s.state.queued_since = None
                    self._start(s, now)

    def _fire(self, s: Schedule, now: datetime) -> None:
        if self.engine.runtime is None:
            try:
                self.engine.connect()
            except ApiError as e:
                self._skip(s, now, e.message)
                return
        if self.engine.busy:
            if s.on_busy == "skip":
                self._skip(s, now, "有任务在运行")
            else:
                self._queue(s, now)
            return
        self._start(s, now)

    def _queue(self, s: Schedule, now: datetime) -> None:
        s.state.queued_since = now
        s.state.next_run = None
        log.info("计划 %s（%s）到点，有任务在运行，排队", s.id, s.module)
        self._publish(s, "queued")

    def _skip(self, s: Schedule, now: datetime, reason: str) -> None:
        s.state.queued_since = None
        s.state.last_attempt = now
        s.state.last_skip = reason
        s.state.next_run = self._next_run(s, now)
        log.info("计划 %s（%s）跳过：%s", s.id, s.module, reason)
        self.save()
        self._publish(s, "skipped", reason=reason)

    def _start(self, s: Schedule, now: datetime, manual: bool = False) -> dict:
        sid = s.id
        try:
            rec = self.engine.start_task(s.module, s.config, timeout=s.timeout, source=f"schedule:{sid}",
                                         on_done=lambda r: self._on_done(sid, r))
        except ApiError as e:
            if manual:
                raise
            if e.code == "busy" and s.on_busy == "queue":
                self._queue(s, now)
                return {}
            # 配置不合法、设备断了、setup 失败：按失败计
            s.state.last_status = TaskStatus.FAILED.value
            self._skip(s, now, e.message)
            self._count_failure(s)
            return {}
        s.state.running_task = rec["id"]
        s.state.last_started = now
        s.state.last_skip = None
        s.state.next_run = None
        self.save()
        self._publish(s, "started", task=rec["id"])
        return rec

    def _on_done(self, sid: str, rec: TaskRecord) -> None:
        with self._lock:
            s = self.schedules.get(sid)
            if s is None:
                return
            ended = self.clock()  # 用调度器自己的时钟（和 next_run 的计算一致）
            st = s.state
            st.running_task = None
            st.last_ended = ended
            st.last_attempt = ended
            st.last_status = rec.status
            st.last_task = rec.id
            if rec.status == TaskStatus.SUCCEEDED.value:
                st.last_success = ended
                st.failures = 0
            elif rec.status in FAILED_STATUSES:
                self._count_failure(s)
            st.next_run = self._next_run(s, self.clock())
        self.save()
        self._publish(s, "finished", task=rec.id, status=rec.status)

    def _count_failure(self, s: Schedule) -> None:
        s.state.failures += 1
        if s.state.failures >= MAX_FAILURES and s.enabled:
            s.enabled = False
            s.state.next_run = None
            log.warning("计划 %s（%s）连续失败 %d 次，已停用", s.id, s.module, s.state.failures)
            self.save()
            self._publish(s, "disabled", reason=f"连续失败 {s.state.failures} 次")

    def _publish(self, s: Schedule, action: str, **extra) -> None:
        self.engine.bus.publish(Topic.SCHEDULE, {
            "id": s.id, "module": s.module, "action": action,
            "next_run": s.state.next_run.isoformat() if s.state.next_run else None, **extra,
        })
