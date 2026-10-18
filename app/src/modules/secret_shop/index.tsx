import { Coins, Gem, RefreshCw, ShieldAlert, ShoppingBag } from "lucide-react";
import type { ModuleUI } from "../types";

const ui: ModuleUI = {
  id: "secret_shop",
  icon: ShoppingBag,
  order: 20,
  menuLabel: "神秘商店",
  fieldIcons: { max_refreshes: RefreshCw, skystone_budget: Gem, skystone_keep: ShieldAlert, gold_floor: Coins },
  // 核对用的内部参数：玩家不用管
  devFields: ["refresh_cost", "max_failures", "probe_dialogs"],
  devSubFields: ["targets.icon"],
  statLabels: {
    runs: "运行次数",
    refreshes: "刷新次数",
    skystone_spent: "花费天空石",
    gold_spent: "花费金币",
    bought: "买到的商品",
  },
};

export default ui;
