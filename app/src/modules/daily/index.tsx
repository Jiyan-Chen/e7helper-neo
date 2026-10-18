import { Gift, Mail, Sparkles, Trees } from "lucide-react";
import type { ModuleUI } from "../types";
import { Continuous, syncContinuous } from "./Continuous";

const ui: ModuleUI = {
  id: "daily",
  icon: Gift,
  order: 10,
  menuLabel: "日常收取",
  runLabel: "收一次菜",
  fieldIcons: { mail: Mail, forest: Trees, covenant: Sparkles },
  statLabels: {
    runs: "运行次数",
    mails: "领取邮件",
    forest_claims: "精灵之森领取",
    cares: "照料",
    summons: "免费召唤",
  },
  RunExtra: Continuous,
  onConfigSaved: (config) => void syncContinuous(config),
};

export default ui;
