import { CircleSlash, MessagesSquare, RefreshCw, ShoppingBag } from "lucide-react";
import type { ModuleUI } from "../types";
import { ItemPicker } from "./ItemPicker";

const ui: ModuleUI = {
  id: "secret_shop",
  icon: ShoppingBag,
  order: 20,
  menuLabel: "书签刷取",
  fieldIcons: { max_refreshes: RefreshCw, stop_after_misses: CircleSlash, channel_after_misses: MessagesSquare },
  fieldRenderers: { items: ItemPicker },
  // 核对用的内部参数：玩家不用管
  devFields: ["refresh_cost", "max_failures", "probe_dialogs"],
  statLabels: {
    runs: "运行次数",
    refreshes: "刷新次数",
    skystone_spent: "花费天空石",
    gold_spent: "花费金币",
    bought: "买到的商品",
    channel_switches: "换频道次数",
  },
};

export default ui;
