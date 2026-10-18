"""按天记账：`data_dir/ledger.json`。

- 「游戏日」以服务器每日重置为界：GMT-7 中午 12 点 = UTC 19:00 = 北京时间凌晨 3 点（用户确认）。
  全部按 UTC 计算，和本机时区无关。
- `done`：当天已经做完的项（目前只有誓约免费召唤），日期变了自动清空。账上记了做完就不再进去看。
- `forest_next`：精灵之森下一次有东西可领 / 可照料的时间（按界面上的倒计时算），不受日期影响。
  没到时间就不进精灵之森。

账本只用来省导航；能不能领、领没领到，都以画面为准（见各项的核对规则）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

RESET_UTC_HOUR = 19  # GMT-7 12:00


def utcnow() -> datetime:
    return datetime.now(UTC)


def game_day(t: datetime) -> date:
    """t 所在的游戏日，用北京时间的日期命名：凌晨 3 点（UTC 19:00）之前算前一天。

    例：北京时间 10-17 02:59 → 10-16；10-17 03:00 → 10-17。
    """
    return (t.astimezone(UTC) + timedelta(hours=24 - RESET_UTC_HOUR)).date()


def next_reset(t: datetime) -> datetime:
    """t 之后（不含 t）的下一次每日重置（UTC 19:00），带时区。"""
    t = t.astimezone(UTC)
    reset = t.replace(hour=RESET_UTC_HOUR, minute=0, second=0, microsecond=0)
    return reset if reset > t else reset + timedelta(days=1)


class Ledger:
    def __init__(self, path: Path, clock: Callable[[], datetime] = utcnow):
        self.path = path
        self.clock = clock
        self.day = game_day(clock()).isoformat()
        self.done: dict[str, dict] = {}
        self.forest_next: datetime | None = None
        self._load()

    @classmethod
    def open(cls, data_dir: Path, clock: Callable[[], datetime] = utcnow) -> Ledger:
        return cls(data_dir / "ledger.json", clock)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("账本文件损坏，重新开始：%s", self.path)
            return
        if data.get("day") == self.day:
            self.done = dict(data.get("done") or {})
        if data.get("forest_next"):
            try:
                self.forest_next = datetime.fromisoformat(data["forest_next"])
            except ValueError:
                self.forest_next = None

    def is_done(self, item: str) -> bool:
        return item in self.done

    def mark_done(self, item: str, **info) -> None:
        self.done[item] = {"time": self.clock().isoformat(timespec="seconds"), **info}
        self.save()

    def forest_due(self) -> bool:
        return self.forest_next is None or self.clock() >= self.forest_next

    def set_forest_next(self, seconds: float | None) -> None:
        """seconds：距离下一次可领 / 可照料的秒数；None 表示不知道（下次照常进去看）。"""
        self.forest_next = None if seconds is None else self.clock() + timedelta(seconds=seconds)
        self.save()

    def save(self) -> None:
        data = {
            "day": self.day,
            "done": self.done,
            "forest_next": self.forest_next.isoformat(timespec="seconds") if self.forest_next else None,
            "updated": self.clock().isoformat(timespec="seconds"),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.exception("账本写入失败：%s", self.path)
