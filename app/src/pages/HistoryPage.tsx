import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { STATUS_COLOR } from "@/components/module/RecentRuns";
import { api } from "@/lib/api";
import { isDev } from "@/lib/env";
import { useModules } from "@/lib/hooks";
import { FLOW_MODULE } from "@/lib/flow";
import { useFlowNames } from "@/lib/flowHooks";
import { friendlyError, moduleName, sourceLabel, statusLabel } from "@/lib/labels";
import { qk } from "@/lib/query";
import { isDryRun } from "@/lib/run";
import { dayTime, formatElapsed } from "@/lib/time";
import { cn } from "@/lib/utils";
import { moduleUI, visibleModules } from "@/modules/registry";

/** 运行记录：经助手启动的任务（手动或计划），新的在前。 */
export function HistoryPage() {
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const { data: modules } = useModules();
  const { data, isLoading } = useQuery({ queryKey: qk.history(filter), queryFn: () => api().history(100, filter) });
  const list = visibleModules(modules ?? []);
  const flowNames = useFlowNames();

  return (
    <div className="h-full overflow-auto px-[22px] py-4">
      <div className="mb-3 flex flex-wrap gap-1.5">
        <button type="button" className={cn("tab", !filter && "active")} onClick={() => setFilter(undefined)}>全部</button>
        {list.map((m) => (
          <button key={m.id} type="button" className={cn("tab", filter === m.id && "active")} onClick={() => setFilter(m.id)}>
            {moduleUI(m.id).menuLabel ?? m.name}
          </button>
        ))}
      </div>
      <section className="panel px-4 py-2">
        {isLoading && <p className="py-3 text-muted">加载中…</p>}
        {data?.length === 0 && <p className="py-3 text-muted">还没有记录。</p>}
        {data?.map((r) => {
          const err = friendlyError(r.error);
          return (
            <div key={r.id} className="grid grid-cols-[130px_110px_50px_1fr] items-baseline gap-3 border-t border-white/6 py-2 text-sm first:border-t-0">
              <span className="text-muted">{dayTime(r.started)}</span>
              <span className="truncate font-semibold" title={r.module === FLOW_MODULE ? "自定义流程" : undefined}>
                {r.module === FLOW_MODULE ? `流程「${flowNames[String(r.config.flow)] ?? "已删除"}」` : moduleName(r.module)}
              </span>
              <span className="text-muted">{sourceLabel(r.source)}</span>
              <span>
                <span className={STATUS_COLOR[r.status]}>{statusLabel(r.status)}</span>
                <span className="text-muted">，{formatElapsed(r.duration ?? r.elapsed)}</span>
                {isDev && isDryRun(r.config) && <span className="ml-2 text-xs text-muted">演练</span>}
                {err && <span className="block text-xs text-bad select-text">{err}</span>}
                {isDev && r.debug_dir && <span className="block text-xs text-faint select-text">调试信息：{r.debug_dir}</span>}
              </span>
            </div>
          );
        })}
      </section>
    </div>
  );
}
