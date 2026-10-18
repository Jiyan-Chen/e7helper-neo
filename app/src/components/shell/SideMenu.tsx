import { BarChart3, CalendarClock, Crop, History, ScrollText, Settings } from "lucide-react";
import { NavLink } from "react-router";
import { Ornament } from "@/components/ui/Ornament";
import { isDev } from "@/lib/env";
import { useModules, useSchedules } from "@/lib/hooks";
import { useEngine } from "@/lib/store";
import { cn } from "@/lib/utils";
import { moduleUI, visibleModules } from "@/modules/registry";

const PAGES = [
  { to: "/schedules", label: "计划", icon: CalendarClock },
  { to: "/history", label: "运行记录", icon: History },
  { to: "/stats", label: "统计", icon: BarChart3 },
  { to: "/logs", label: "日志", icon: ScrollText },
  { to: "/settings", label: "设置", icon: Settings },
];

/** 左侧菜单（仿竞技场菜单）：上面是功能，下面是记录和设置。 */
export function SideMenu() {
  const { data: modules } = useModules();
  const { data: schedules } = useSchedules();
  const running = useEngine((s) => s.status?.task?.module);
  const list = visibleModules(modules ?? []);

  return (
    <nav className="flex flex-col overflow-auto bg-[#0a1020]/66 backdrop-blur-[6px]" aria-label="主菜单">
      {list.map((m) => {
        const ui = moduleUI(m.id);
        const Icon = ui.icon;
        const scheduled = schedules?.schedules.some((s) => s.module === m.id && s.enabled);
        return (
          <NavLink key={m.id} to={`/m/${m.id}`} className={({ isActive }) => cn("menu-item", isActive && "active")}>
            {running === m.id && <span className="dot absolute top-3 left-2.5" aria-label="运行中" />}
            <Icon className="size-6 flex-none" />
            <span className="truncate">{ui.menuLabel ?? m.name}</span>
            {running === m.id ? (
              <span className="ml-auto text-xs font-normal text-glow">运行中</span>
            ) : scheduled ? (
              <span className="ml-auto text-xs font-normal text-gold">计划中</span>
            ) : null}
          </NavLink>
        );
      })}
      <Ornament className="mx-[18px] my-2.5" />
      {PAGES.map((p) => (
        <NavLink key={p.to} to={p.to} className={({ isActive }) => cn("menu-item minor", isActive && "active")}>
          <p.icon className="size-[19px] flex-none" />
          {p.label}
        </NavLink>
      ))}
      {isDev && (
        <NavLink to="/capture" className={({ isActive }) => cn("menu-item minor", isActive && "active")}>
          <Crop className="size-[19px] flex-none" />
          模板采集
          <span className="ml-auto rounded border border-gold-line px-1.5 text-[11px] text-gold">开发</span>
        </NavLink>
      )}
    </nav>
  );
}
