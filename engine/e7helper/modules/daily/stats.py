"""日常收取的统计，写到模块数据目录：

- `history.jsonl`：每次运行追加一行（含 dry-run）
- `stats.json`：累计（只统计实跑：领取的邮件、精灵之森领取 / 照料、免费召唤次数）

按天的「做过没有」记在 `ledger.json`（见 ledger.py），不在这里。
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
class Mail:
    remaining: str  # 剩余时间原文
    count_after: int  # 领完后邮箱里的邮件数
    time: str = field(default_factory=now)


@dataclass
class Summon:
    times: int  # 1 或 10
    left_after: int | None  # 气泡里剩下的免费次数（读不出为 None）
    seconds: float
    time: str = field(default_factory=now)


@dataclass
class RunStats:
    dry_run: bool
    started: str = field(default_factory=now)
    ended: str | None = None
    items: dict[str, str] = field(default_factory=dict)  # 每项的结果
    mails: list[Mail] = field(default_factory=list)  # 邮件数减少 1 才算
    forest_claims: list[str] = field(default_factory=list)  # 卡片从「领取奖励」变成倒计时才算
    cares: int = 0  # 照料次数增加才算
    summons: list[Summon] = field(default_factory=list)  # 看到召唤结果、顶栏货币没变才算
    would: list[str] = field(default_factory=list)  # dry-run 时会做的事
    failures: int = 0

    @property
    def summon_times(self) -> int:
        return sum(s.times for s in self.summons)

    def summary(self) -> str:
        s = (f"邮件 {len(self.mails)} 封，精灵之森领取 {len(self.forest_claims)} 次"
             f"（{'、'.join(self.forest_claims) or '无'}），照料 {self.cares} 次，"
             f"免费召唤 {self.summon_times} 次，失败 {self.failures} 次；"
             + "；".join(f"{k}：{v}" for k, v in self.items.items()))
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
        total["mails"] += len(run.mails)
        total["forest_claims"] += len(run.forest_claims)
        total["cares"] += run.cares
        total["summons"] += run.summon_times
        total["updated"] = run.ended or now()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(total, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("统计写入失败：%s", data_dir)


def load_totals(data_dir: Path) -> dict:
    total = {"runs": 0, "mails": 0, "forest_claims": 0, "cares": 0, "summons": 0, "updated": None}
    path = data_dir / "stats.json"
    if path.exists():
        try:
            total.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("累计统计文件损坏，重新开始计数：%s", path)
    return total
