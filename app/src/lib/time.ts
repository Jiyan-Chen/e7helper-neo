// 时间解析与显示。界面一律显示本地时间（国服玩家就是北京时间）。
import type { TimeValue } from "./types";

/** unix 秒、带时区的 ISO、不带时区的本地 ISO → Date；解析不了返回 null。 */
export function toDate(v: TimeValue): Date | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return Number.isFinite(v) ? new Date(v * 1000) : null;
  const d = new Date(v); // 不带时区的 "2026-10-15T01:17:43" 按本地时间解析（ES 规范）
  return Number.isNaN(d.getTime()) ? null : d;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 剩余秒数 → "4:20:15"；超过 100 小时照样显示小时（精灵之森会到 149 小时）。 */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}:${pad(m)}:${pad(s % 60)}`;
}

/** 到 target 还有多少秒（已过去为负）。 */
export function secondsUntil(target: TimeValue, now = Date.now()): number | null {
  const d = toDate(target);
  return d ? (d.getTime() - now) / 1000 : null;
}

/** 任务用时：23.0 秒 / 2 分 9 秒 / 1 小时 5 分。 */
export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} 分 ${Math.round(seconds % 60)} 秒`;
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
}

export function clock(v: TimeValue, withSeconds = true): string {
  const d = toDate(v);
  if (!d) return "—";
  return withSeconds ? `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** 「今天 14:05」「明天 03:00」「昨天 13:20」「10月15日 01:17」。 */
export function dayTime(v: TimeValue, now = new Date()): string {
  const d = toDate(v);
  if (!d) return "—";
  const hm = clock(d.getTime() / 1000, false);
  const day = new Date(now);
  if (sameDay(d, day)) return `今天 ${hm}`;
  day.setDate(day.getDate() + 1);
  if (sameDay(d, day)) return `明天 ${hm}`;
  day.setDate(day.getDate() - 2);
  if (sameDay(d, day)) return `昨天 ${hm}`;
  return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
}

/** 「刚刚」「5 分钟前」「3 小时前」，再早就用 dayTime。 */
export function ago(v: TimeValue, now = Date.now()): string {
  const d = toDate(v);
  if (!d) return "—";
  const s = (now - d.getTime()) / 1000;
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 6 * 3600) return `${Math.floor(s / 3600)} 小时前`;
  return dayTime(d.getTime() / 1000, new Date(now));
}
