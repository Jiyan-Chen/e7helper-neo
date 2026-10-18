import { Flag, Swords } from "lucide-react";
import type { ModuleUI } from "../types";

const ui: ModuleUI = {
  id: "arena_npc",
  icon: Swords,
  order: 30,
  menuLabel: "竞技场",
  runLabel: "开始挑战",
  fieldIcons: { buy_flags: Flag },
  statLabels: {
    runs: "运行次数",
    battles: "战斗场数",
    quick_battles: "快速对战",
    wins: "胜场",
    flags_spent: "用掉旗帜",
    flag_buys: "补旗次数",
    friendship_spent: "花费友情点数",
  },
};

export default ui;
