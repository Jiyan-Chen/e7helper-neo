import { CircleSlash, MessagesSquare, RefreshCw, ShoppingBag } from "lucide-react";
import type { ModuleUI } from "../types";
import { ShopHistory } from "./ShopHistory";
import { ItemPicker } from "./ItemPicker";

const ui: ModuleUI = {
  id: "secret_shop",
  icon: ShoppingBag,
  order: 20,
  menuLabel: "书签刷取",
  fieldIcons: { max_refreshes: RefreshCw, stop_after_misses: CircleSlash, channel_after_misses: MessagesSquare },
  fieldRenderers: { items: ItemPicker },
  RunsPanel: ShopHistory,
  // 核对用的内部参数：玩家不用管
  devFields: ["refresh_cost", "max_failures", "probe_dialogs"],
};

export default ui;
