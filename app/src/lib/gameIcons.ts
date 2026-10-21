// 游戏里截图裁出来的小图标（B13 审核后加，用户选择）：属性 element_<键>、职业 role_<键>、套装 <套装键>（如 set_speed）。
// 放进 src/assets/game/ 就自动用上；没有的图标由调用方退回文字 / 色块。
const files = import.meta.glob<string>("../assets/game/*.png", { eager: true, import: "default" });

const byName: Record<string, string> = Object.fromEntries(
  Object.entries(files).map(([path, url]) => [path.slice(path.lastIndexOf("/") + 1, -4), url]),
);

export function gameIcon(name: string): string | undefined {
  return byName[name];
}
