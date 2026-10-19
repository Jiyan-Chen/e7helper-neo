import { Clock, Gem, Leaf, MapPin, Mountain, Repeat, Swords, Target } from "lucide-react";
import type { ModuleUI } from "../types";

// 只有异界难度的地下城（和引擎 config.OTHERWORLD_ONLY 一致）
const OTHERWORLD_ONLY = ["食人魔"];

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
    auto_max_units: Clock,
    auto_leaves: Leaf,
    manual: Swords,
    manual_runs: Swords,
    refill_leaf: Leaf,
    max_leaf_refills: Leaf,
    refill_skystone: Gem,
    max_skystone_refills: Gem,
  },
  fieldLocks: (config) => (OTHERWORLD_ONLY.includes(String(config.hunt)) ? { tier: "异界" } : {}),
  fieldDeps: {
    auto_max_units: "auto_battle",
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
    cores_spent: "花费光谱核心",
    leaves_spent: "用掉生命之叶",
    skystone_spent: "花费天空石",
  },
  presets: [
    {
      name: "托管自动结算",
      description: "每 30 分钟结算并重开托管",
      trigger: { type: "interval", minutes: 30 },
      config: { manual: false, auto_battle: true },
    },
  ],
};

export default ui;
