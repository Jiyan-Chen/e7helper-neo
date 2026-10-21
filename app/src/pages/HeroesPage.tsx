// 英雄图鉴（B13）：全部英雄的头像网格，搜索、按属性 / 职业 / 星级筛选，点开看详情（HeroDetailDialog）；可以联网更新数据。
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { HeroDetailDialog } from "@/components/heroes/HeroDetailDialog";
import { toast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "@/lib/api";
import { gameIcon } from "@/lib/gameIcons";
import {
  ELEMENT_COLORS, ELEMENTS, RARITIES, ROLES, filterHeroes,
  type Hero, type HeroFilter, type HeroList,
} from "@/lib/heroes";
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
        <div className="flex items-center gap-3">
          <label className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint" />
            <input className="field w-72 pl-8" placeholder="搜索名字" aria-label="搜索英雄" value={filter.query}
              onChange={(e) => set({ query: e.target.value })} />
          </label>
          <span className="text-sm text-muted">{data ? `${shown.length} / ${data.count} 名` : ""}</span>
        </div>
        {data && (
          <>
            <FilterRow label="属性" value={filter.element} options={ELEMENTS.map((e) => ({ value: e, label: data.labels.element[e] ?? e, color: ELEMENT_COLORS[e], icon: gameIcon(`element_${e}`) }))}
              onChange={(element) => set({ element })} />
            <FilterRow label="职业" value={filter.role} options={ROLES.map((r) => ({ value: r, label: data.labels.role[r] ?? r, icon: gameIcon(`role_${r}`) }))}
              onChange={(role) => set({ role })} />
            <FilterRow label="星级" value={filter.rarity} options={RARITIES.map((r) => ({ value: r, label: `${r} 星` }))}
              onChange={(rarity) => set({ rarity })} />
          </>
        )}
      </section>

      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading && <p className="text-muted">加载中…</p>}
        {data?.count === 0 && <p className="text-muted">没有英雄数据，点「检查更新」下载。</p>}
        {data && data.count > 0 && shown.length === 0 && <p className="text-muted">没有符合条件的英雄。</p>}
        <div className="grid grid-cols-[repeat(auto-fill,74px)] gap-x-1 gap-y-0.5">
          {data && shown.map((h) => (
            <button key={h.code} type="button" title={h.name} onClick={() => setOpen(h)}
              className="flex cursor-pointer flex-col items-center gap-1 rounded-lg px-0.5 py-1 transition-colors hover:bg-white/6">
              <HeroIcon hero={h} data={data} size={60} />
              <span className="line-clamp-2 text-center text-[11px] leading-tight">{h.name}</span>
            </button>
          ))}
        </div>
      </div>

      {data && <HeroDetailDialog hero={open} data={data} onClose={() => setOpen(null)} />}
    </div>
  );
}

function FilterRow<T extends string | number>({ label, value, options, onChange }: {
  label: string;
  value: T | null;
  options: { value: T; label: string; color?: string; icon?: string }[];
  onChange: (v: T | null) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={label}>
      <span className="w-10 text-sm text-muted">{label}</span>
      <button type="button" className={cn("tab", value === null && "active")} onClick={() => onChange(null)}>全部</button>
      {options.map((o) => (
        <button key={o.value} type="button" className={cn("tab inline-flex items-center gap-1.5", value === o.value && "active")}
          onClick={() => onChange(value === o.value ? null : o.value)}>
          {o.icon ? <img src={o.icon} alt="" className="size-4" draggable={false} />
            : o.color && <span className="size-2 rounded-full" style={{ background: o.color }} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** 头像：属性色的边框，右下角是属性图标（游戏里截的；没有时是写着属性的色块）。没有头像时显示名字的第一个字。 */
function HeroIcon({ hero, data, size }: { hero: Hero; data: HeroList; size: number }) {
  const color = ELEMENT_COLORS[hero.element] ?? "#888";
  const elementIcon = gameIcon(`element_${hero.element}`);
  return (
    <span className="relative flex-none rounded-[10px] border-2 bg-black/40" style={{ width: size, height: size, borderColor: color }}>
      {hero.icon ? (
        <img src={api().heroIconUrl(hero.code, data.updated)} alt="" loading="lazy" draggable={false}
          className="size-full rounded-[8px] object-cover" />
      ) : (
        <span className="grid size-full place-items-center text-xl font-bold text-muted">{hero.name.slice(0, 1)}</span>
      )}
      {elementIcon ? (
        <img src={elementIcon} alt={data.labels.element[hero.element]} draggable={false}
          className="absolute -right-2 -bottom-2 size-6 drop-shadow-[0_1px_2px_rgba(0,0,0,.8)]" />
      ) : (
        <span className="absolute -right-1.5 -bottom-1.5 grid size-5 place-items-center rounded-full border border-black/50 text-[11px] font-bold text-black"
          style={{ background: color }} aria-label={data.labels.element[hero.element]}>
          {data.labels.element[hero.element]}
        </span>
      )}
    </span>
  );
}
