import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useModules } from "@/lib/hooks";
import { qk } from "@/lib/query";
import { dayTime } from "@/lib/time";
import type { ModuleInfo } from "@/lib/types";
import { moduleUI, visibleModules } from "@/modules/registry";

/** 统计：各功能的累计数字（只算实际执行的，不含演练）。 */
export function StatsPage() {
  const { data: modules } = useModules();
  const list = visibleModules(modules ?? []).filter((m) => moduleUI(m.id).statLabels);
  return (
    <div className="h-full overflow-auto px-[22px] py-4">
      <p className="mb-3 text-muted">各功能累计做了多少事。演练不计入。</p>
      <div className="grid grid-cols-2 gap-3.5 max-[1180px]:grid-cols-1">
        {list.map((m) => <StatCard key={m.id} module={m} />)}
      </div>
    </div>
  );
}

function StatCard({ module }: { module: ModuleInfo }) {
  const ui = moduleUI(module.id);
  const { data, isLoading } = useQuery({ queryKey: qk.stats(module.id), queryFn: () => api().stats(module.id, 0) });
  const stats = data?.stats;
  const Icon = ui.icon;
  return (
    <section className="panel px-4 py-3.5">
      <h3 className="panel-title mb-3">
        <Icon className="size-5" />
        {ui.menuLabel ?? module.name}
        {typeof stats?.updated === "string" && <span className="ml-auto text-xs font-normal text-muted">最近 {dayTime(stats.updated)}</span>}
      </h3>
      {!stats ? (
        <p className="text-sm text-muted">{isLoading ? "加载中…" : "还没有数据。"}</p>
      ) : (
        <div className="grid grid-cols-3 gap-2.5">
          {Object.entries(ui.statLabels ?? {}).map(([key, label]) => {
            const v = stats[key];
            if (v && typeof v === "object") {
              const entries = Object.entries(v as Record<string, number>);
              return (
                <div key={key} className="col-span-3 rounded-[10px] bg-black/25 px-3 py-2">
                  <div className="text-xs text-muted">{label}</div>
                  {entries.length === 0 ? <div className="text-sm text-muted">无</div> : (
                    <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1">
                      {entries.map(([name, n]) => (
                        <span key={name}>{name} <b className="num text-lg">{n}</b></span>
                      ))}
                    </div>
                  )}
                </div>
              );
            }
            return (
              <div key={key} className="rounded-[10px] bg-black/25 px-3 py-2">
                <div className="text-xs text-muted">{label}</div>
                <div className="num text-[22px] font-semibold">{typeof v === "number" ? v.toLocaleString("zh-CN") : "—"}</div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
