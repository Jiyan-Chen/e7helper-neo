import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { isDev } from "@/lib/env";
import { sourceLabel, statusLabel } from "@/lib/labels";
import { qk } from "@/lib/query";
import { isDryRun } from "@/lib/run";
import { ago, formatElapsed } from "@/lib/time";
import { cn } from "@/lib/utils";

export const STATUS_COLOR: Record<string, string> = {
  succeeded: "text-ok",
  failed: "text-bad",
  timeout: "text-bad",
  stuck: "text-bad",
  stopped: "text-warn",
  running: "text-glow",
};

/** 这个功能最近几次运行（经 GUI / 计划启动的）。 */
export function RecentRuns({ moduleId, limit = 6 }: { moduleId: string; limit?: number }) {
  const { data } = useQuery({ queryKey: qk.history(moduleId), queryFn: () => api().history(limit, moduleId) });
  if (!data) return null;
  if (data.length === 0) return <p className="py-1 text-sm text-muted">还没有运行过。</p>;
  return (
    <div className="flex flex-col text-[13px]">
      {data.map((r) => (
        <div key={r.id} className="grid grid-cols-[84px_40px_1fr_auto] items-baseline gap-2 border-t border-white/6 py-1.5 first:border-t-0">
          <span className="text-muted">{ago(r.started)}</span>
          <span className="text-muted">{sourceLabel(r.source)}</span>
          <span className={cn(STATUS_COLOR[r.status])} title={r.error ?? undefined}>
            {statusLabel(r.status)}
            {r.duration !== null && <span className="text-muted">，{formatElapsed(r.duration)}</span>}
          </span>
          {isDev && isDryRun(r.config) ? <span className="text-xs text-muted">演练</span> : <span />}
        </div>
      ))}
    </div>
  );
}
