import { Clock, Gem, Leaf, MapPin, Mountain, Repeat, Swords, Target } from "lucide-react";
import type { ModuleUI } from "../types";

const ui: ModuleUI = {
  id: "repeat_battle",
  icon: Repeat,
  order: 40,
  menuLabel: "重复刷关",
  fieldIcons: {
    hunt: Target,
    tier: Mountain,
    start_here: MapPin,
    auto_battle: Clock,
    auto_leaves: Leaf,
    manual: Swords,
    manual_runs: Swords,
    refill_leaf: Leaf,
    max_leaf_refills: Leaf,
    refill_skystone: Gem,
    max_skystone_refills: Gem,
  },
  fieldDeps: {
    auto_leaves: "auto_battle",
    manual_runs: "manual",
    refill_leaf: "manual",
    max_leaf_refills: "refill_leaf",
    refill_skystone: "manual",
    max_skystone_refills: "refill_skystone",
  },
  statLabels: {
    runs: "运行次数",
    battles: "手动场数",
    auto_claimed: "托管结算",
    auto_started: "托管重开",
    auto_runs_claimed: "托管完成次数",
    energy_spent: "花费行动力",
    leaves_spent: "用掉生命之叶",
    skystone_spent: "花费天空石",
  },
  presets: [
    {
      name: "托管自动结算",
      description: "每 30 分钟检查一次托管：完成了就结算并在同一关重开，不手动刷",
      trigger: { type: "interval", minutes: 30 },
      config: { manual: false, auto_battle: true },
    },
  ],
};

export default ui;
