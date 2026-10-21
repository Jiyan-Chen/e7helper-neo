// 刷取历史的数据形状和汇总（引擎 GET /api/modules/secret_shop/report，只有实跑记录）。

export interface ShopDay {
  /** 本地日期 YYYY-MM-DD */
  date: string;
  runs: number;
  refreshes: number;
  skystone_spent: number;
  gold_spent: number;
  pages: number;
  bought: Record<string, number>;
  channel_switches: number;
}

export interface ShopRun {
  started: string;
  ended: string | null;
  refreshes: number;
  skystone_spent: number;
  gold_spent: number;
  pages: number;
  bought: Record<string, number>;
  /** page：0 是进店时的列表，之后每刷新一次 +1 */
  purchases: { name: string; page: number }[];
  channel_switches: number;
  max_misses: number;
  failures: number;
  stop_reason: string;
}

export interface ShopReport {
  days: ShopDay[];
  runs: ShopRun[];
  run_count: number;
}

export type Range = "7" | "30" | "all";
export const RANGES: { id: Range; label: string }[] = [
  { id: "7", label: "近 7 天" },
  { id: "30", label: "近 30 天" },
  { id: "all", label: "全部" },
];

const pad = (n: number) => String(n).padStart(2, "0");

export function dateKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseDate(key: string): Date {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

/** 范围的第一天（含）；全部返回 null。 */
export function rangeStart(range: Range, today: Date): string | null {
  if (range === "all") return null;
  return dateKey(addDays(today, -(Number(range) - 1)));
}

export function inRange(dateOrTime: string, start: string | null): boolean {
  return start === null || dateOrTime.slice(0, 10) >= start;
}

export interface Totals {
  runs: number;
  refreshes: number;
  skystone: number;
  gold: number;
  pages: number;
  channelSwitches: number;
  bought: Record<string, number>;
}

export function sumDays(days: ShopDay[]): Totals {
  const t: Totals = { runs: 0, refreshes: 0, skystone: 0, gold: 0, pages: 0, channelSwitches: 0, bought: {} };
  for (const d of days) {
    t.runs += d.runs;
    t.refreshes += d.refreshes;
    t.skystone += d.skystone_spent;
    t.gold += d.gold_spent;
    t.pages += d.pages;
    t.channelSwitches += d.channel_switches;
    for (const [name, n] of Object.entries(d.bought)) t.bought[name] = (t.bought[name] ?? 0) + n;
  }
  return t;
}

/** 平均看多少页列表出一次（每页 = 进店时的列表或一次刷新）；没出过返回 null。 */
export function pagesPerHit(pages: number, hits: number): number | null {
  return hits > 0 ? Math.round(pages / hits) : null;
}

export interface Bucket {
  key: string;
  /** 横轴上的短名字：10/15 */
  label: string;
  /** 提示里的完整名字：10月15日 / 10月13日–10月19日 */
  title: string;
  /** 一根柱子是几天（1 或 7） */
  span: number;
  refreshes: number;
  skystone: number;
  gold: number;
  runs: number;
  bought: Record<string, number>;
}

const short = (d: Date) => `${d.getMonth() + 1}/${d.getDate()}`;
const long = (d: Date) => `${d.getMonth() + 1}月${d.getDate()}日`;

/** 超过这么多天就按周画 */
export const WEEKLY_AFTER = 45;

/**
 * 图表的柱子：按天（没跑的天也有一根空柱）；「全部」跨度超过 WEEKLY_AFTER 天时按周（周一开始）。
 */
export function buckets(days: ShopDay[], range: Range, today: Date): Bucket[] {
  const start = rangeStart(range, today) ?? days[0]?.date;
  if (!start) return [];
  const first = parseDate(start);
  const span = Math.round((parseDate(dateKey(today)).getTime() - first.getTime()) / 86_400_000) + 1;
  const weekly = range === "all" && span > WEEKLY_AFTER;
  const byDate = new Map(days.map((d) => [d.date, d]));
  const out: Bucket[] = [];
  let cur = weekly ? addDays(first, -((first.getDay() + 6) % 7)) : first;
  const end = dateKey(today);
  while (dateKey(cur) <= end) {
    const len = weekly ? 7 : 1;
    const last = addDays(cur, len - 1);
    const b: Bucket = {
      key: dateKey(cur),
      label: short(cur),
      title: weekly ? `${long(cur)}–${long(last)}` : long(cur),
      span: len,
      refreshes: 0, skystone: 0, gold: 0, runs: 0, bought: {},
    };
    for (let i = 0; i < len; i++) {
      const d = byDate.get(dateKey(addDays(cur, i)));
      if (!d) continue;
      b.refreshes += d.refreshes;
      b.skystone += d.skystone_spent;
      b.gold += d.gold_spent;
      b.runs += d.runs;
      for (const [name, n] of Object.entries(d.bought)) b.bought[name] = (b.bought[name] ?? 0) + n;
    }
    out.push(b);
    cur = addDays(cur, len);
  }
  return out;
}

/** 464000 → 46.4万；不到一万原样加千分位。 */
export function wan(n: number): string {
  if (Math.abs(n) < 10_000) return n.toLocaleString("zh-CN");
  const v = n / 10_000;
  return `${Number(v.toFixed(v >= 100 ? 0 : 1))}万`;
}

/** 第几页 → 「进店时」/「第 3 次刷新」 */
export function pageLabel(page: number): string {
  return page === 0 ? "进店时" : `第 ${page} 次刷新`;
}
