// 按 module id 收集 src/modules/<id>/index.tsx 的界面扩展（Vite 编译期 glob，新增目录即可）。
import { Puzzle } from "lucide-react";
import { isDev } from "@/lib/env";
import type { ModuleInfo } from "@/lib/types";
import type { ModuleUI } from "./types";

const found = import.meta.glob<{ default: ModuleUI }>("./*/index.tsx", { eager: true });

const registry: Record<string, ModuleUI> = {};
for (const mod of Object.values(found)) registry[mod.default.id] = mod.default;

export function moduleUI(id: string): ModuleUI {
  return registry[id] ?? { id, icon: Puzzle, order: 100 };
}

/** 菜单里显示的任务模块：按 order 排序；开发版专用的在正式版里藏起来。 */
export function visibleModules(modules: ModuleInfo[]): ModuleInfo[] {
  return modules
    .filter((m) => m.kind === "task" && (isDev || !moduleUI(m.id).devOnly))
    .sort((a, b) => moduleUI(a.id).order - moduleUI(b.id).order || a.name.localeCompare(b.name));
}
