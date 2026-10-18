import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { ActivityList } from "@/components/shell/ActivityList";
import { isDev } from "@/lib/env";
import type { LogRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

const LEVELS = { all: 0, warn: 30, error: 40 } as const;
const RANK: Record<string, number> = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };

/** 日志：玩家看「动态」，开发版可以切到全部（带来源）。可按级别和关键字筛选。 */
export function LogsPage() {
  const [mode, setMode] = useState<"activity" | "all">("activity");
  const [level, setLevel] = useState<keyof typeof LEVELS>("all");
  const [q, setQ] = useState("");
  const filter = useMemo(() => {
    const min = LEVELS[level];
    const needle = q.trim().toLowerCase();
    return (r: LogRecord) => (RANK[r.level] ?? 20) >= min && (!needle || r.message.toLowerCase().includes(needle) || r.name.includes(needle));
  }, [level, q]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 px-[22px] py-4">
      <div className="flex items-center gap-2">
        {isDev && (
          <>
            <button type="button" className={cn("tab", mode === "activity" && "active")} onClick={() => setMode("activity")}>动态</button>
            <button type="button" className={cn("tab", mode === "all" && "active")} onClick={() => setMode("all")}>全部（开发）</button>
            <span className="mx-2 h-4 w-px bg-white/15" />
          </>
        )}
        <button type="button" className={cn("tab", level === "all" && "active")} onClick={() => setLevel("all")}>全部级别</button>
        <button type="button" className={cn("tab", level === "warn" && "active")} onClick={() => setLevel("warn")}>警告和错误</button>
        <button type="button" className={cn("tab", level === "error" && "active")} onClick={() => setLevel("error")}>只看错误</button>
        <span className="flex-1" />
        <label className="relative">
          <Search className="absolute top-2.5 left-2.5 size-4 text-muted" />
          <input className="field w-56 pl-8" placeholder="搜索" value={q} onChange={(e) => setQ(e.target.value)} aria-label="搜索日志" />
        </label>
      </div>
      <section className="panel flex min-h-0 flex-1 flex-col px-3 py-2">
        <ActivityList mode={mode} filter={filter} limit={1000} className="flex-1" />
      </section>
    </div>
  );
}
