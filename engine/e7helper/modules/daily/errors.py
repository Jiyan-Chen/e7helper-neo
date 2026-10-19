"""日常收取各项共用的异常（单独放一个文件，竞技场 `arena.py` 也要用）。"""

from __future__ import annotations


class StopItem(Exception):
    """这一项正常结束（做完了 / 没有可做的 / dry-run），继续下一项。"""


class ItemFailed(Exception):
    """这一项没做成（点了没反应、认不出界面），放弃这一项，继续下一项；任务最后记为失败。"""


class DailyAnomaly(RuntimeError):
    """核对不通过（可能花了资源），立即停止整个任务，任务记为失败。"""
