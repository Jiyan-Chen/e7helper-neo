"""世界竞技场（RTA）选秀助手的引擎部分（B14 起），不依赖设备。

- `rules`：选秀规则（1-2-2-2-2-1、保护位、预禁 / 后禁）、段位、开战规则对照表；
- `battle`：官方战绩站的一场对局 → `Match`（国服 / 海外两种格式）；
- `official`：国服 / 海外战绩站接口客户端；
- `crawl`：开发用的对局采集（sqlite，断点续采），`report`：数据报告。
"""

from .battle import BadBattle, Match, Pick, Side, parse_battle
from .rules import GRADE_LABELS, GRADES, OPENING_RULES, PICK_ORDER

__all__ = ["GRADE_LABELS", "GRADES", "OPENING_RULES", "PICK_ORDER", "BadBattle", "Match", "Pick", "Side",
           "parse_battle"]
