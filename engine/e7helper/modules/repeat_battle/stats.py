"""重复刷关的统计，写到模块数据目录：

- `history.jsonl`：每次运行追加一行（含 dry-run）
- `stats.json`：累计（只统计实跑：手动场次、托管结算/重开次数、行动力 / 光谱核心消耗、叶子和天空石补充）
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
    stage: str
    energy_before: int | None  # 持有行动力（异界：光谱核心）
    energy_after: int | None
    seconds: float
    time: str = field(default_factory=now)


@dataclass
class AutoRun:
    """一次托管：结算（claimed）或重开（started）。"""

    action: str  # claimed / started
    stage: str
    runs: int | None  # 结算：完成次数；重开：预计次数（份数 × 4）
    energy: int = 0  # 重开时用掉的行动力（按顶栏读数差）
    leaves: int = 0  # 重开时设置框显示将使用的叶子
    cores: int = 0  # 异界：重开时用掉的光谱核心（按顶栏读数差）
    time: str = field(default_factory=now)


@dataclass
class RunStats:
    dry_run: bool
    started: str = field(default_factory=now)
    ended: str | None = None
    stage: str = ""
    currency: str = "行动力"  # 这一关消耗的东西（异界是光谱核心）
    battles: list[Battle] = field(default_factory=list)  # 看到 CLEAR 和结算、且行动力没有多扣的场次
    autos: list[AutoRun] = field(default_factory=list)
    energy_spent: int = 0  # 手动战斗按读数差计（讨伐会掉落行动力，差值可能小于消耗）
    cores_spent: int = 0  # 异界手动战斗用掉的光谱核心（按读数差）
    leaf_refills: int = 0  # 确认行动力增加后才计
    skystone_refills: int = 0
    leaves_spent: int = 0  # 补充 + 托管设置框显示的叶子
    skystone_spent: int = 0  # 按顶栏读数差
    would: list[str] = field(default_factory=list)  # dry-run 时下一步会做的事
    failures: int = 0
    energy_start: int | None = None  # 持有行动力（异界：光谱核心）
    energy_end: int | None = None
    stop_reason: str = ""

    def summary(self) -> str:
        claimed = sum(a.action == "claimed" for a in self.autos)
        started = sum(a.action == "started" for a in self.autos)
        s = (f"{self.stage or '?'}：手动 {len(self.battles)} 场，托管结算 {claimed} 次、重开 {started} 次，"
             f"行动力消耗 {self.energy_spent}，光谱核心消耗 {self.cores_spent}，"
             f"补{self.currency} 叶子 {self.leaf_refills} 次 / 天空石 {self.skystone_refills} 次"
             f"（叶子 {self.leaves_spent}，天空石 {self.skystone_spent}），失败 {self.failures} 次，"
             f"{self.currency} {self.energy_start} → {self.energy_end}，停止原因：{self.stop_reason}")
        if self.dry_run:
            s = f"[dry-run] {s}；会做：{'；'.join(self.would) or '无'}"
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
        total["battles"] += len(run.battles)
        total["auto_claimed"] += sum(a.action == "claimed" for a in run.autos)
        total["auto_started"] += sum(a.action == "started" for a in run.autos)
        total["auto_runs_claimed"] += sum(a.runs or 0 for a in run.autos if a.action == "claimed")
        total["energy_spent"] += run.energy_spent + sum(a.energy for a in run.autos)
        total["cores_spent"] += run.cores_spent + sum(a.cores for a in run.autos)
        total["leaf_refills"] += run.leaf_refills
        total["skystone_refills"] += run.skystone_refills
        total["leaves_spent"] += run.leaves_spent
        total["skystone_spent"] += run.skystone_spent
        total["updated"] = run.ended or now()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(total, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("统计写入失败：%s", data_dir)


def load_totals(data_dir: Path) -> dict:
    total = {"runs": 0, "battles": 0, "auto_claimed": 0, "auto_started": 0, "auto_runs_claimed": 0,
             "energy_spent": 0, "cores_spent": 0, "leaf_refills": 0, "skystone_refills": 0, "leaves_spent": 0, "skystone_spent": 0,
             "updated": None}
    path = data_dir / "stats.json"
    if path.exists():
        try:
            total.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("累计统计文件损坏，重新开始计数：%s", path)
    return total
