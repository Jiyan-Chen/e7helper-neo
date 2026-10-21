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


# ---------------------------------------------------------------- 历史统计（B12c，GUI 书签刷取页的「刷取历史」）

# 任务被中断时 stop_reason 是「异常类名：消息」，换成玩家看得懂的说法
_ABORT_REASONS = {"TaskStopped": "手动停止", "TaskTimeout": "超过时限", "TaskStuck": "画面卡住"}


def load_history(data_dir: Path) -> list[dict]:
    """读 history.jsonl 的全部记录；坏行跳过。"""
    path = data_dir / "history.jsonl"
    if not path.exists():
        return []
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        log.exception("运行记录读取失败：%s", path)
        return []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            records.append(r)
    return records


def _reason(text: str) -> str:
    name, sep, msg = (text or "").partition("：")
    if sep and name in _ABORT_REASONS:
        return _ABORT_REASONS[name]
    if sep and name.isidentifier() and name[:1].isupper():  # 其他异常：只留消息
        return f"出错：{msg}" if msg else "出错"
    return text or ""


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def report(records: list[dict], runs_limit: int = 500) -> dict:
    """实跑记录（dry-run 不算）按天汇总 + 每次运行的明细（新的在前，最多 runs_limit 条）。

    天按开始时间的本地日期（记录里的时间就是本地时间）。B04 时期的旧记录没有 max_misses / channel_switches，按 0 算。
    """
    days: dict[str, dict] = {}
    runs: list[dict] = []
    for r in records:
        if r.get("dry_run", True) is not False:
            continue
        started = r.get("started")
        if not isinstance(started, str) or len(started) < 10:
            continue
        purchases = [p for p in r.get("purchases") or [] if isinstance(p, dict) and isinstance(p.get("name"), str)]
        bought: dict[str, int] = {}
        for p in purchases:
            bought[p["name"]] = bought.get(p["name"], 0) + 1
        switches = r.get("channel_switches")
        run = {
            "started": started,
            "ended": r.get("ended"),
            "refreshes": _int(r.get("refreshes")),
            "skystone_spent": _int(r.get("skystone_spent")),
            "gold_spent": _int(r.get("gold_spent")),
            "pages": _int(r.get("pages")),
            "bought": bought,
            "purchases": [{"name": p["name"], "page": _int(p.get("page"))} for p in purchases],
            "channel_switches": len(switches) if isinstance(switches, list) else 0,
            "max_misses": _int(r.get("max_misses")),
            "failures": _int(r.get("failures")),
            "stop_reason": _reason(str(r.get("stop_reason") or "")),
        }
        runs.append(run)
        day = days.setdefault(started[:10], {
            "date": started[:10], "runs": 0, "refreshes": 0, "skystone_spent": 0, "gold_spent": 0, "pages": 0,
            "bought": {}, "channel_switches": 0,
        })
        day["runs"] += 1
        for k in ("refreshes", "skystone_spent", "gold_spent", "pages", "channel_switches"):
            day[k] += run[k]
        for name, n in bought.items():
            day["bought"][name] = day["bought"].get(name, 0) + n
    runs.sort(key=lambda x: x["started"], reverse=True)
    return {
        "days": [days[k] for k in sorted(days)],
        "runs": runs[:max(0, runs_limit)],
        "run_count": len(runs),
    }
