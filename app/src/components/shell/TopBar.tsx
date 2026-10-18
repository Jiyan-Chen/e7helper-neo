import { CalendarClock, MapPin, Square } from "lucide-react";
import { Link, useLocation } from "react-router";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useModules, useNow } from "@/lib/hooks";
import { sceneLabel } from "@/lib/labels";
import { useEngine } from "@/lib/store";
import { dayTime, formatDuration, secondsUntil } from "@/lib/time";
import { moduleUI } from "@/modules/registry";

export const PAGE_TITLES: Record<string, string> = {
  "/schedules": "计划",
  "/history": "运行记录",
  "/stats": "统计",
  "/logs": "日志",
  "/settings": "设置",
  "/capture": "模板采集",
};

/** 顶栏：标题在左，右边像游戏的资源栏一样列出模拟器、当前画面、下一个计划，最右是急停。 */
export function TopBar() {
  const { pathname } = useLocation();
  const { data: modules } = useModules();
  const status = useEngine((s) => s.status);
  const scene = useEngine((s) => s.scene);
  const socket = useEngine((s) => s.socket);
  const now = useNow();

  const moduleId = pathname.startsWith("/m/") ? pathname.slice(3) : null;
  const title = moduleId
    ? moduleUI(moduleId).menuLabel ?? modules?.find((m) => m.id === moduleId)?.name ?? moduleId
    : PAGE_TITLES[pathname] ?? "";
  const device = status?.device;
  const next = status?.scheduler.next;
  const nextName = next ? moduleUI(next.module).menuLabel ?? modules?.find((m) => m.id === next.module)?.name : null;
  const nextLeft = next ? secondsUntil(next.next_run, now) : null;
  const task = status?.task;

  const stop = async () => {
    try {
      await api().stopTask();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  return (
    <header className="flex h-[60px] items-center gap-6 border-b border-white/8 bg-[#080c18]/55 pr-4 pl-5 backdrop-blur-[4px]">
      <h1 className="text-[22px] font-bold tracking-wide">{title}</h1>
      <span className="flex-1" />

      {socket !== "open" ? (
        <span className="flex items-center gap-2 text-sm text-warn">
          <span className="size-2.5 rounded-full bg-warn" />和助手的连接断开了，正在重连…
        </span>
      ) : (
        <Link to="/settings" className="flex items-center gap-2 text-[15px] font-semibold text-ink no-underline" title="模拟器设置">
          <span className={`size-2.5 rounded-full ${device?.connected ? "bg-[#5fd35a] shadow-[0_0_8px_#5fd35a]" : "bg-bad"}`} />
          {device?.connected ? (device.name?.split(" ")[0] ?? "模拟器") : "模拟器未连接"}
        </Link>
      )}

      {device?.connected && (
        <span className="flex items-center gap-1.5 text-[15px] font-semibold" title="当前游戏画面">
          <MapPin className="size-[18px] text-gold" />
          {sceneLabel(scene?.scene, scene?.popup)}
        </span>
      )}

      {next && !status?.scheduler.paused && (
        <Link to="/schedules" className="flex items-center gap-1.5 text-ink no-underline" title={`下一个计划：${nextName ?? ""} ${dayTime(next.next_run)}`}>
          <CalendarClock className="size-[18px] text-gold" />
          <span className="num text-[17px] font-semibold">{nextLeft !== null && nextLeft > 0 ? formatDuration(nextLeft) : "马上"}</span>
          <span className="text-xs text-muted">{nextName}</span>
        </Link>
      )}

      <button
        type="button"
        className="btn btn-real h-9 rounded-lg px-4"
        disabled={!task}
        onClick={stop}
        title={task ? "立刻停止正在运行的任务" : "没有任务在运行"}
      >
        <Square className="size-3.5 fill-current" />
        停止
      </button>
    </header>
  );
}
