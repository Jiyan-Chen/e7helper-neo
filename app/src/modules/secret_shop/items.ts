// 书签刷取的三种商品（和引擎 secret_shop/config.py 的 CATALOG 对应）。
import covenant from "./icons/covenant.png";
import friendship from "./icons/friendship.png";
import mystic from "./icons/mystic.png";

export interface ShopItemInfo {
  id: string;
  /** 游戏里的商品名（运行记录里按名字记） */
  name: string;
  icon: string;
  /** 买一次得到几个（友情点数不显示个数） */
  units?: number;
}

export const ITEMS: readonly ShopItemInfo[] = [
  { id: "covenant", name: "誓约书签", icon: covenant, units: 5 },
  { id: "mystic", name: "神秘奖牌", icon: mystic, units: 50 },
  { id: "friendship", name: "友情点数", icon: friendship },
];
