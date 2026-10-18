import { useEffect, useMemo, useRef } from "react";
import { activitySource, friendlyMessage, isActivity } from "@/lib/labels";
import { useEngine } from "@/lib/store";
import { clock } from "@/lib/time";
import type { LogRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

const LEVEL_COLOR: Record<string, string> = { WARNING: "text-warn", ERROR: "text-bad", CRITICAL: "text-bad" };

/** 动态 / 日志列表。玩家看到的是「动态」（模块自己说的话、连接和计划、警告错误）；开发版可以看全部和来源。 */
export function ActivityList({
  mode, filter, className, limit = 400,
}: {
  mode: "activity" | "all";
  filter?: (r: LogRecord) => boolean;
  className?: string;
  limit?: number;
}) {
  const logs = useEngine((s) => s.logs);
  const items = useMemo(() => {
    let xs = mode === "activity" ? logs.filter(isActivity) : logs;
    if (filter) xs = xs.filter(filter);
    return xs.slice(-limit);
  }, [logs, mode, filter, limit]);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [items]);

  return (
    <div
      ref={box}
      className={cn("min-h-0 overflow-auto text-[12.5px] leading-[1.55] select-text", className)}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
    >
      {items.length === 0 && <p className="px-1.5 py-2 text-muted">还没有动态。</p>}
      {items.map((r, i) => (
        <div key={`${r.time}-${i}`} className="grid grid-cols-[60px_1fr] gap-1 rounded-md px-1.5 py-[3px] hover:bg-white/4">
          <span className="num text-gold-line">{clock(r.time)}</span>
          <span className={LEVEL_COLOR[r.level]}>
            {mode === "all" ? (
              <span className="mr-1.5 text-faint">{r.name.replace(/^e7helper\./, "")}</span>
            ) : (
              activitySource(r) && <span className="mr-1.5 text-gold">{activitySource(r)}</span>
            )}
            {friendlyMessage(r.message)}
          </span>
        </div>
      ))}
    </div>
  );
}
