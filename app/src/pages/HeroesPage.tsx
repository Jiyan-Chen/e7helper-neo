// 英雄图鉴（B13）：全部英雄的头像网格，搜索、按属性 / 职业 / 星级筛选，点开看详情（HeroDetailDialog）；可以联网更新数据。
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { HeroDetailDialog } from "@/components/heroes/HeroDetailDialog";
import { HeroFilters, HeroGrid } from "@/components/heroes/HeroGrid";
import { toast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "@/lib/api";
import { filterHeroes, type Hero, type HeroFilter } from "@/lib/heroes";
import { qk } from "@/lib/query";
import { dayTime } from "@/lib/time";
import { cn } from "@/lib/utils";

export function HeroesPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: qk.heroes, queryFn: () => api().heroes(), staleTime: Infinity });
  const [filter, setFilter] = useState<HeroFilter>({ query: "", element: null, role: null, rarity: null });
  const [open, setOpen] = useState<Hero | null>(null);
  const [updating, setUpdating] = useState(false);
  const shown = useMemo(() => (data ? filterHeroes(data.heroes, filter) : []), [data, filter]);
  const set = (patch: Partial<HeroFilter>) => setFilter((f) => ({ ...f, ...patch }));

  const update = async () => {
    setUpdating(true);
    try {
      const res = await api().updateHeroes();
      if (res.added.length) toast(`已更新，新增 ${res.added.length} 名英雄`);
      else if (res.changed) toast("已更新");
      else if (res.icons) toast(`已补齐 ${res.icons} 个头像`);
      else toast("已经是最新的了");
      if (res.icon_failed.length) toast(`有 ${res.icon_failed.length} 个头像没下载下来，稍后再试`, "error");
      await qc.invalidateQueries({ queryKey: qk.heroes });
    } catch (e) {
      toast(e instanceof ApiError && e.code === "update_failed" ? "更新失败：连不上数据源，稍后再试" : errorMessage(e), "error");
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="flex h-full flex-col gap-3 px-[22px] py-4">
      <div className="flex items-center gap-3">
        <p className="min-w-0 flex-1 truncate text-muted">查看全部英雄的属性、职业和基础数据。</p>
        {data?.updated && <span className="whitespace-nowrap text-xs text-faint">数据更新于 {dayTime(data.updated)}</span>}
        <button type="button" className="btn btn-sm btn-bronze" disabled={updating} onClick={() => void update()}>
          <RefreshCw className={cn("size-4", updating && "animate-spin")} />
          {updating ? "更新中…" : "检查更新"}
        </button>
      </div>

      <section className="panel flex flex-col gap-2 px-4 py-3">
        {data ? (
          <HeroFilters data={data} filter={filter} onChange={set}>
            <span className="text-sm text-muted">{`${shown.length} / ${data.count} 名`}</span>
          </HeroFilters>
        ) : (
          <div className="h-[34px]" />
        )}
      </section>

      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading && <p className="text-muted">加载中…</p>}
        {data?.count === 0 && <p className="text-muted">没有英雄数据，点「检查更新」下载。</p>}
        {data && data.count > 0 && shown.length === 0 && <p className="text-muted">没有符合条件的英雄。</p>}
        {data && <HeroGrid heroes={shown} data={data} onPick={setOpen} />}
      </div>

      {data && <HeroDetailDialog hero={open} data={data} onClose={() => setOpen(null)} />}
    </div>
  );
}
