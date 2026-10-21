import { Gift, Mail, ShoppingCart, Sparkles, Swords, Trees } from "lucide-react";
import type { ModuleUI } from "../types";
import { Continuous, syncContinuous } from "./Continuous";
import { ShopItemPicker } from "./ShopItemPicker";

const ui: ModuleUI = {
  id: "daily",
  icon: Gift,
  order: 10,
  menuLabel: "日常收取",
  runLabel: "收一次菜",
  fieldIcons: { mail: Mail, forest: Trees, covenant: Sparkles, shop: ShoppingCart, arena: Swords },
  subFields: { arena_buy_flags: "arena" },
  fieldDeps: { shop_items: "shop" },
  fieldRenderers: { shop_items: ShopItemPicker },
  RunExtra: Continuous,
  onConfigSaved: (config) => void syncContinuous(config),
};

export default ui;
