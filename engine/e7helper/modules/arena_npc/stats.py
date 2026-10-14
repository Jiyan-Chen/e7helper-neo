"""竞技场 NPC 的统计，写到模块数据目录：

- `history.jsonl`：每次运行追加一行（含 dry-run）
- `stats.json`：累计（只统计实跑：场次、胜场、消耗旗帜、补旗次数），以及最近一次补旗的时间
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Battle:
    mode: str  # quick / battle
    victory: bool
    flags_after: int | None
    seconds: float
    time: str = field(default_factory=now)


@dataclass
class RunStats:
    dry_run: bool
    started: str = field(default_factory=now)
    ended: str | None = None
    battles: list[Battle] = field(default_factory=list)  # 看到结算、且旗帜读数减少 1 的场次
    flags_spent: int = 0  # 按旗帜读数差计，不按点击次数
    flag_buys: int = 0  # 确认旗帜增加后才计
    friendship_spent: int = 0
    would: list[str] = field(default_factory=list)  # dry-run 时下一步会做的事
    failures: int = 0
    flags_start: int | None = None
    flags_end: int | None = None
    stop_reason: str = ""

    @property
    def wins(self) -> int:
        return sum(b.victory for b in self.battles)

    def summary(self) -> str:
        quick = sum(b.mode == "quick" for b in self.battles)
        s = (f"打了 {len(self.battles)} 场（快速 {quick}，胜 {self.wins}），消耗旗帜 {self.flags_spent}，"
             f"补旗 {self.flag_buys} 次（友情点数 {self.friendship_spent}），失败 {self.failures} 次，"
             f"旗帜 {self.flags_start} → {self.flags_end}，停止原因：{self.stop_reason}")
        if self.dry_run:
            s = f"[dry-run] {s}；会做：{'；'.join(self.would) or '无'}"
        return s


def save(data_dir: Path, run: RunStats) -> None:
    """追加运行记录并更新累计统计。写失败只记日志，不影响任务结果。"""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        rec = asdict(run)
        with (data_dir / "history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if run.dry_run:
            return
        path = data_dir / "stats.json"
        total = load_totals(data_dir)
        total["runs"] += 1
        total["battles"] += len(run.battles)
        total["quick_battles"] += sum(b.mode == "quick" for b in run.battles)
        total["wins"] += run.wins
        total["flags_spent"] += run.flags_spent
        total["flag_buys"] += run.flag_buys
        total["friendship_spent"] += run.friendship_spent
        if run.flag_buys:
            total["last_flag_buy"] = run.ended or now()
        total["updated"] = run.ended or now()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(total, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("统计写入失败：%s", data_dir)


def load_totals(data_dir: Path) -> dict:
    total = {"runs": 0, "battles": 0, "quick_battles": 0, "wins": 0, "flags_spent": 0, "flag_buys": 0,
             "friendship_spent": 0, "last_flag_buy": None, "updated": None}
    path = data_dir / "stats.json"
    if path.exists():
        try:
            total.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("累计统计文件损坏，重新开始计数：%s", path)
    return total
