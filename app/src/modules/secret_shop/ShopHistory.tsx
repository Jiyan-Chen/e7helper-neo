// 书签刷取页的「刷取历史」（B12c）：代替通用的「最近运行」。只算实跑（引擎已去掉 dry-run 的记录）。
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { qk } from "@/lib/query";
import { dayTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { ModuleExtraProps } from "../types";
import {
  type Bucket, buckets, inRange, pageLabel, pagesPerHit, RANGES, type Range, rangeStart, type ShopReport, type ShopRun,
  sumDays, wan,
} from "./report";
import { ITEMS, type ShopItemInfo } from "./items";

const RANGE_KEY = "e7helper.secret_shop.history_range";
const RUNS_FOLDED = 6;
const byName = new Map(ITEMS.map((it) => [it.name, it]));
const order = (name: string) => {
  const i = ITEMS.findIndex((it) => it.name === name);
  return i < 0 ? ITEMS.length : i;
};
/** 买到的商品按固定顺序（誓约书签、神秘奖牌、友情点数、其他） */
const ordered = (bought: Record<string, number>) => Object.entries(bought).sort((a, b) => order(a[0]) - order(b[0]));

function loadRange(): Range {
  try {
    const v = localStorage.getItem(RANGE_KEY);
    if (v === "7" || v === "30" || v === "all") return v;
  } catch {
    // 存储不可用时用默认
  }
  return "30";
}

export function ShopHistory({ config }: ModuleExtraProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: [...qk.stats("secret_shop"), "report"],
    queryFn: () => api().moduleGet<ShopReport>("secret_shop", "report"),
  });
  const [range, setRangeState] = useState<Range>(loadRange);
  const setRange = (r: Range) => {
    setRangeState(r);
    try {
      localStorage.setItem(RANGE_KEY, r);
    } catch {
      // 只是记住选择，失败无所谓
    }
  };

  const today = new Date();
  const todayKey = today.toDateString();
  const view = useMemo(() => {
    if (!data) return null;
    const start = rangeStart(range, today);
    const days = data.days.filter((d) => inRange(d.date, start));
    return {
      totals: sumDays(days),
      everBought: sumDays(data.days).bought,
      bars: buckets(data.days, range, today),
      runs: data.runs.filter((r) => inRange(r.started, start)),
    };
  }, [data, range, todayKey]); // eslint-disable-line react-hooks/exhaustive-deps -- today 只按日期变化

  const picked = Array.isArray(config.items) ? (config.items as string[]) : [];
  const items = ITEMS.filter((it) => picked.includes(it.id) || (view?.everBought[it.name] ?? 0) > 0);

  return (
    <section className="panel px-4 py-3.5">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="panel-title">刷取历史</h3>
        {data && data.run_count > 0 && (
          <div className="ml-auto flex gap-1.5" role="tablist" aria-label="时间范围">
            {RANGES.map((r) => (
              <button key={r.id} type="button" role="tab" aria-selected={range === r.id}
                className={cn("tab", range === r.id && "active")} onClick={() => setRange(r.id)}>
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {error ? (
        <p className="text-sm text-bad">读不到刷取记录：{errorMessage(error)}</p>
      ) : !data || !view ? (
        <p className="text-sm text-muted">{isLoading ? "加载中…" : ""}</p>
      ) : data.run_count === 0 ? (
        <p className="py-1 text-sm text-muted">还没有刷取记录。</p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2.5">
            {items.map((it) => (
              <ItemCard key={it.id} item={it} hits={view.totals.bought[it.name] ?? 0} pages={view.totals.pages} />
            ))}
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2.5">
            <Tile label="刷新次数" value={view.totals.refreshes.toLocaleString("zh-CN")} />
            <Tile label="花费天空石" value={view.totals.skystone.toLocaleString("zh-CN")} />
            <Tile label="花费金币" value={wan(view.totals.gold)} />
            <Tile label="运行次数" value={String(view.totals.runs)}
              note={view.totals.channelSwitches > 0 ? `换频道 ${view.totals.channelSwitches} 次` : undefined} />
          </div>
          <Chart bars={view.bars} weekly={view.bars[0]?.span === 7} />
          <RunList runs={view.runs} />
        </div>
      )}
    </section>
  );
}

function ItemCard({ item, hits, pages }: { item: ShopItemInfo; hits: number; pages: number }) {
  const every = pagesPerHit(pages, hits);
  return (
    <div className="flex items-center gap-3 rounded-[10px] border border-gold-line/50 bg-black/25 px-3 py-2">
      <img src={item.icon} alt="" className="size-12 flex-none object-contain drop-shadow-[0_3px_5px_rgba(0,0,0,0.5)]" draggable={false} />
      <div className="min-w-0">
        <div className="text-xs text-muted">{item.name}</div>
        <div className="flex items-baseline gap-2">
          <span className="num text-[24px] leading-tight font-semibold text-[#ffe2a1]">{hits}</span>
          <span className="text-sm">次</span>
          {item.units && hits > 0 && <span className="text-xs whitespace-nowrap text-muted">共 {hits * item.units} 个</span>}
        </div>
        <div className="truncate text-xs text-muted">{every === null ? "还没出过" : `平均刷 ${every} 次出一次`}</div>
      </div>
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-[10px] bg-black/25 px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className="num text-[22px] font-semibold">{value}</span>
        {note && <span className="text-xs text-muted">{note}</span>}
      </div>
    </div>
  );
}

const CHART_H = 120;
const MARK_H = 36; // 柱子上方放商品图标的高度（最多两个）
const MARK_ITEMS = ITEMS.filter((it) => it.units); // 图上只标书签和奖牌

/** 每天（或每周）刷新次数的柱状图，柱子上方标出那天买到的书签 / 奖牌；悬停看明细。 */
function Chart({ bars, weekly }: { bars: Bucket[]; weekly: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...bars.map((b) => b.refreshes));
  const every = Math.ceil(bars.length / 8);
  const h = hover === null ? null : bars[hover];
  return (
    <div className="rounded-[10px] bg-black/25 px-3 pt-2 pb-1.5">
      <div className="mb-1 flex text-xs text-muted">
        <span>{weekly ? "每周刷新次数" : "每天刷新次数"}</span>
        <span className="num ml-auto">最多 {max}</span>
      </div>
      <div className="relative" onMouseLeave={() => setHover(null)}>
        <div className="pointer-events-none absolute inset-x-0 border-t border-dashed border-white/10" style={{ top: MARK_H }} />
        <div className="flex items-end" style={{ height: CHART_H + MARK_H }}>
          {bars.map((b, i) => {
            const marks = MARK_ITEMS.filter((it) => (b.bought[it.name] ?? 0) > 0);
            const pct = b.refreshes / max;
            return (
              <button key={b.key} type="button"
                className="group flex h-full min-w-0 flex-1 cursor-default flex-col items-center justify-end px-px outline-none"
                aria-label={`${b.title}：刷新 ${b.refreshes} 次`}
                onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                <span className="flex flex-col items-center gap-px pb-0.5">
                  {marks.map((it) => (
                    <img key={it.id} src={it.icon} alt="" className="size-4 object-contain" draggable={false} />
                  ))}
                </span>
                <span
                  className={cn(
                    "block w-full max-w-[26px] rounded-t-[4px] transition-colors",
                    hover === i ? "bg-gold" : "bg-gradient-to-b from-glow to-[#1d4f99]",
                  )}
                  style={{ height: b.refreshes > 0 ? Math.max(2, pct * CHART_H) : 0 }}
                />
              </button>
            );
          })}
        </div>
        <div className="border-t border-white/15" />
        {h && hover !== null && <Tip bucket={h} left={(hover + 0.5) / bars.length} />}
      </div>
      <div className="flex text-[11px] text-faint">
        {bars.map((b, i) => (
          <span key={b.key} className="num min-w-0 flex-1 overflow-visible text-center whitespace-nowrap">
            {i % every === 0 ? b.label : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function Tip({ bucket: b, left }: { bucket: Bucket; left: number }) {
  const bought = ordered(b.bought);
  const align = left < 0.3 ? "translate-x-0" : left > 0.7 ? "-translate-x-full" : "-translate-x-1/2";
  return (
    <div role="tooltip" className={cn("pointer-events-none absolute top-0 z-10 rounded-lg border border-gold-line bg-[#141a2a]/95 px-3 py-2 text-xs whitespace-nowrap shadow-lg", align)}
      style={{ left: `${left * 100}%` }}>
      <div className="mb-1 font-bold text-gold">{b.title}</div>
      {b.runs === 0 ? <div className="text-muted">没有刷取</div> : (
        <>
          <div>刷新 <b className="num">{b.refreshes}</b> 次 · 天空石 <b className="num">{b.skystone}</b> · 金币 <b className="num">{wan(b.gold)}</b></div>
          <div className="text-muted">{bought.length ? bought.map(([n, c]) => `${n} ${c} 次`).join("、") : "没买到"}</div>
        </>
      )}
    </div>
  );
}

function RunList({ runs }: { runs: ShopRun[] }) {
  const [open, setOpen] = useState(false);
  if (runs.length === 0) return <p className="text-sm text-muted">这段时间没有刷取。</p>;
  const shown = open ? runs : runs.slice(0, RUNS_FOLDED);
  return (
    <div>
      <div className="mb-1 text-xs text-muted">每次运行</div>
      <div className="flex flex-col text-[13px]">
        {shown.map((r) => <RunRow key={r.started} run={r} />)}
      </div>
      {runs.length > RUNS_FOLDED && (
        <button type="button" className="btn btn-ghost btn-sm mt-1.5" onClick={() => setOpen(!open)}>
          {open ? "收起" : `显示全部 ${runs.length} 次`}
        </button>
      )}
    </div>
  );
}

function RunRow({ run: r }: { run: ShopRun }) {
  return (
    <div className="flex items-center gap-3 border-t border-white/6 py-1.5 first:border-t-0">
      <span className="w-[92px] flex-none text-muted">{dayTime(r.started)}</span>
      <div className="min-w-0 flex-1">
        <div>
          刷新 <b className="num">{r.refreshes}</b> 次
          <span className="text-muted"> · 天空石 </span><b className="num">{r.skystone_spent}</b>
          {r.gold_spent > 0 && <><span className="text-muted"> · 金币 </span><b className="num">{wan(r.gold_spent)}</b></>}
          {r.channel_switches > 0 && <span className="text-muted"> · 换频道 {r.channel_switches} 次</span>}
        </div>
        {r.stop_reason && <div className="truncate text-xs text-faint" title={r.stop_reason}>{r.stop_reason}</div>}
      </div>
      <div className="flex flex-none items-center gap-2.5">
        {ordered(r.bought).map(([name, n]) => {
          const it = byName.get(name);
          const tip = `${name}：${r.purchases.filter((p) => p.name === name).map((p) => pageLabel(p.page)).join("、")}`;
          return (
            <span key={name} className="flex items-center gap-0.5" title={tip}>
              {it ? <img src={it.icon} alt={name} className="size-7 object-contain" draggable={false} /> : <span className="text-xs">{name}</span>}
              {n > 1 && <span className="num text-sm font-semibold text-[#ffe2a1]">×{n}</span>}
            </span>
          );
        })}
      </div>
    </div>
  );
}
