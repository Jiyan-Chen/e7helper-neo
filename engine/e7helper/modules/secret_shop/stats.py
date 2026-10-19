"""刷商店的统计，写到模块数据目录：

- `history.jsonl`：每次运行追加一行（含 dry-run）
- `stats.json`：累计（只统计实跑：刷新次数、花费、买到的商品、换频道次数）
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
class Purchase:
    name: str
    price: int
    page: int  # 第几页（0 是进店时的列表，之后每刷新一次 +1）
    time: str = field(default_factory=now)


@dataclass
class ChannelSwitch:
    old: int
    new: int
    page: int
    time: str = field(default_factory=now)


@dataclass
class RunStats:
    dry_run: bool
    started: str = field(default_factory=now)
    ended: str | None = None
    refreshes: int = 0  # 确认扣费成功的刷新次数
    skystone_spent: int = 0  # 按天空石读数差计，不按点击次数
    gold_spent: int = 0  # 按金币读数差计
    pages: int = 0  # 扫描过的列表页数
    purchases: list[Purchase] = field(default_factory=list)
    would_buy: list[Purchase] = field(default_factory=list)  # dry-run 时决定要买的
    failures: int = 0  # 失败总次数（不只是连续的）
    max_misses: int = 0  # 最长连续几页没出要买的商品
    channel_switches: list[ChannelSwitch] = field(default_factory=list)
    skystone_start: int | None = None
    gold_start: int | None = None
    skystone_end: int | None = None
    gold_end: int | None = None
    stop_reason: str = ""

    def summary(self) -> str:
        bought = "、".join(f"{p.name}(第{p.page}页)" for p in self.purchases) or "无"
        s = (f"刷新 {self.refreshes} 次，花费天空石 {self.skystone_spent}、金币 {self.gold_spent:,}，"
             f"扫描 {self.pages} 页，买到：{bought}，最长连续 {self.max_misses} 页没出，换频道 {len(self.channel_switches)} 次，"
             f"失败 {self.failures} 次，停止原因：{self.stop_reason}")
        if self.dry_run:
            would = "、".join(f"{p.name}(第{p.page}页)" for p in self.would_buy) or "无"
            s = f"[dry-run] {s}；会买：{would}"
        return s


def save(data_dir: Path, run: RunStats) -> None:
    """追加运行记录并更新累计统计。写失败只记日志，不影响任务结果。"""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with (data_dir / "history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(run), ensure_ascii=False) + "\n")
        if run.dry_run:
            return
        path = data_dir / "stats.json"
        total = load_totals(data_dir)
        total["runs"] += 1
        total["refreshes"] += run.refreshes
        total["skystone_spent"] += run.skystone_spent
        total["gold_spent"] += run.gold_spent
        total["channel_switches"] += len(run.channel_switches)
        for p in run.purchases:
            total["bought"][p.name] = total["bought"].get(p.name, 0) + 1
        total["updated"] = run.ended or now()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(total, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("统计写入失败：%s", data_dir)


def load_totals(data_dir: Path) -> dict:
    total = {"runs": 0, "refreshes": 0, "skystone_spent": 0, "gold_spent": 0, "bought": {}, "channel_switches": 0,
             "updated": None}
    path = data_dir / "stats.json"
    if path.exists():
        try:
            total.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("累计统计文件损坏，重新开始计数：%s", path)
    return total
