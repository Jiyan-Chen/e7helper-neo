// RTA 选秀推荐接口（/api/rta/*，B14c / B14d1 / B14e1）的数据形状和请求调度。胜率一律是我方的。
import { useEffect, useRef, useState } from "react";
import type { ApiState, Side } from "./draft";

export interface RtaOptions {
  /** 开战规则（双方都在优胜者以上才有，每局随机一条） */
  rules: { tid: string; label: string; desc: string }[];
}

export interface RtaModelInfo {
  model: { kind: string; heroes: number; trained_on?: unknown } | null;
  second: { kind: string } | null;
  rare_picks: number;
  /** 速度表信息；还没有速度表（先动概率不可用）时是 null */
  speed: Record<string, unknown> | null;
  options: RtaOptions;
}

export interface RtaHeroPrior {
  /** 训练数据里被选的次数 */
  picks: number;
  rare: boolean;
  ban_rate: number | null;
  preban: number;
}

export interface RtaPriors {
  built: string | null;
  matches: number | null;
  rare_picks: number;
  heroes: Record<string, RtaHeroPrior>;
}

/** 对手的一种回应（和我方之后的胜率）；reply = 我方再怎么选 */
export interface Reply {
  heroes: string[];
  prob: number;
  win: number;
  reply?: string[];
  reply_win?: number;
}

export interface Recommend {
  heroes: string[];
  /** 放保护位的那名（两手回合里正好轮到保护位时） */
  protected: string | null;
  score: number;
  /** 预期胜率 */
  win: number;
  /** 最坏胜率 */
  worst: number;
  gap: number;
  /** 和第一名差不到 1 个百分点 */
  close: boolean;
  /** 数据少的英雄 */
  rare: string[];
  pool_only: string[];
  responses: Reply[];
  threat: Reply | null;
  second?: { win: number; spread: number };
  /** 两个模型差 ≥ 5 个百分点 */
  uncertain?: boolean;
  /** 我方先动的概率（有速度表时） */
  first?: number | null;
}

/** 两手回合里按英雄：每名英雄所在最好的那组 */
export interface HeroRec {
  code: string;
  score: number;
  win: number;
  partner: string;
  protected?: boolean;
}

export interface Choice {
  heroes: string[];
  prob: number;
  win: number;
}

export interface BanAdvice {
  /** 行 = 我方禁对方哪名 */
  rows: string[];
  /** 列 = 对方禁我方哪名 */
  cols: string[];
  matrix: number[][];
  row_stats: { code: string; worst: number; win: number; score: number; second?: { win: number; worst: number; spread: number } }[];
  recommend: string;
  their_likely: { code: string; prob: number }[];
  nash: { mine: number[]; theirs: number[]; value: number };
  /** 每格上场 4 打 4 我方先动的概率（有速度表时） */
  first?: (number | null)[][];
}

export interface Advice {
  phase: "pick" | "ban" | "done";
  turn: "mine" | "theirs" | null;
  side: Side;
  n: number;
  slots: number;
  win: number;
  second_win: number | null;
  /** 模型没见过的英雄 */
  unknown: string[];
  recommend?: Recommend[];
  heroes?: HeroRec[];
  opponent?: { likely: Choice[]; threats: Choice[] };
  ban?: BanAdvice;
  first: { mine: number; partial: boolean } | null;
  stats: { ms: number; truncated: boolean; depth: number };
}

export interface PrebanRec {
  heroes: string[];
  score: number;
  win: number;
  worst: number;
  /** 最怕对方预禁哪一组 */
  worst_vs: Partial<Record<Side, string[]>>;
  gap: number;
  close: boolean;
  share: Partial<Record<Side, number>>;
  second?: { win: number; spread: number };
  uncertain?: boolean;
}

export interface PrebanAdvice {
  phase: "preban";
  side: Side | null;
  recommend: PrebanRec[];
  heroes: { code: string; score: number; win: number; partner: string }[];
  /** 对方最常见的预禁组合，键是「我方」的先后手 */
  theirs: Partial<Record<Side, { heroes: string[]; share: number }[]>>;
  stats: { ms: number; truncated: boolean };
}

export interface AdviseBody {
  side: Side;
  state: ApiState;
}

export interface PrebanBody {
  side: Side;
  grades: [string | null, string | null];
  rule: string;
  fixed?: string | null;
}

/** useLatest 的返回 */
export interface Latest<T> {
  data: T | undefined;
  /** data 是不是当前局面的（不是就是上一个局面的，正在算新的） */
  fresh: boolean;
  loading: boolean;
  error: unknown;
  retry: () => void;
}

/** 胜率等比例：0.5612 → "56.1%" */
export const pct1 = (p: number) => `${(p * 100).toFixed(1)}%`;
export const pct0 = (p: number) => `${Math.round(p * 100)}%`;

/**
 * 后禁这一步信息条上的胜率（用户意见：显示推荐行，不显示后禁前的读数）：我方禁 code、对方按常见后禁的预期胜率；
 * 我方已经选了要禁谁时用选的那一行。first = 这一行按对方后禁可能性加权的先动概率（每格都有才算）。
 */
export function banHeadline(ban: BanAdvice, chosen: string | null): { code: string; win: number; first: number | null } {
  const code = chosen && ban.rows.includes(chosen) ? chosen : ban.recommend;
  const i = ban.rows.indexOf(code);
  const q = ban.their_likely.map((x) => x.prob);
  const cells = ban.first?.[i];
  const total = q.reduce((a, b) => a + b, 0);
  const first = cells && total > 0 && cells.every((v) => v != null)
    ? cells.reduce((a: number, v, j) => a + (v as number) * q[j], 0) / total
    : null;
  return { code, win: ban.row_stats[i].win, first };
}

/**
 * 只要最新的结果：同一时间只发一个请求，在途时局面又变了只记下最新的，等在途的回来再发
 * （引擎同一时间只跑一个搜索，一次 2–4 秒，排队的旧请求只会拖慢新的）。结果按 key 缓存（撤销回去不用再算）。
 * 返回最近一次拿到的结果（可能是旧局面的，fresh = 是不是当前局面的）。
 */
export function useLatest<T>(key: string | null, fetcher: (key: string) => Promise<T>, cache: Map<string, T>): Latest<T> {
  const [tick, rerender] = useState(0);
  const inflight = useRef(false);
  const shown = useRef<T | undefined>(undefined);
  const errors = useRef(new Map<string, unknown>());
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // 每次拿到结果后 tick 变一次，这里再看当前局面有没有结果、要不要接着发
  useEffect(() => {
    if (key === null || cache.has(key) || errors.current.has(key) || inflight.current) return;
    inflight.current = true;
    fetcher(key)
      .then((data) => {
        cache.set(key, data);
        if (cache.size > 200) cache.delete(cache.keys().next().value as string);
      })
      .catch((e) => errors.current.set(key, e))
      .finally(() => {
        inflight.current = false;
        if (alive.current) rerender((x) => x + 1);
      });
  }, [key, fetcher, cache, tick]);

  const data = key !== null ? cache.get(key) : undefined;
  if (data !== undefined) shown.current = data;
  const error = key !== null ? errors.current.get(key) : undefined;
  return {
    data: key === null ? undefined : (data ?? shown.current),
    fresh: data !== undefined,
    loading: key !== null && data === undefined && error === undefined,
    error,
    /** 出错后重试当前局面 */
    retry: () => {
      if (key !== null) errors.current.delete(key);
      rerender((x) => x + 1);
    },
  };
}
