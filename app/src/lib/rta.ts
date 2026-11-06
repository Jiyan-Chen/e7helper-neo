// RTA 选秀推荐接口（/api/rta/*，B14c / B14d1 / B14e1 / B14e2）的数据形状和请求调度。胜率一律是我方的。
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
  /** 主模型里有的英雄（B14h）：RTA 助手只放这些，模型没训练进的只在图鉴里看 */
  codes: string[];
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
  /** 只因为在英雄池里才推荐的冷门英雄（数据少） */
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
  /** 之后我方的胜率：我方再从英雄池里选最好的回应的预期（B14e2 第 2 轮审核；时间不够没算到的是模型读数） */
  win: number;
  /** 模型读数（不知道英雄池） */
  now?: number;
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
  /** win = 按对方选法的先验加权的「我方的读数」（B14e2 第 2 轮审核）；一个都没算到时是 null */
  opponent?: { likely: Choice[]; threats: Choice[]; win?: number | null };
  ban?: BanAdvice;
  first: { mine: number; partial: boolean } | null;
  /** 这次推荐用的英雄池（null = 不限制） */
  pool?: string[] | null;
  /** 英雄池里能选的不够这一轮，这一轮推荐的是全部英雄（B14e2） */
  pool_short?: boolean;
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

/**
 * advise 的请求兼缓存键（B14e2）：引擎始终按保存的英雄池推荐，键里带上英雄池的保存时间，英雄池改了（选人范围、
 * 填的速度都会变结果）就重算。adviceBody 从键里取回请求。
 */
export const adviceKey = (body: AdviseBody, poolUpdated: string) => JSON.stringify({ body, pool: poolUpdated });
export const adviceBody = (key: string) => (JSON.parse(key) as { body: AdviseBody }).body;

export interface PrebanBody {
  side: Side;
  grades: [string | null, string | null];
  /** null = 没有开战规则 */
  rule: string | null;
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

/** 只留模型里有的英雄（B14h 用户意见：模型没训练进的英雄不放进 RTA 助手）。 */
export function inModel<T extends { code: string }>(heroes: readonly T[], codes: readonly string[]): T[] {
  const set = new Set(codes);
  return heroes.filter((h) => set.has(h.code));
}

/**
 * 推荐卡上「数据少」的标记（B14e2）：数据少的英雄都是只因为在英雄池里才推荐的，标「英雄池」；
 * 有不是因为英雄池的，标「数据少」（两种合成一个标记，完整意思在鼠标提示里）。没有数据少的英雄返回 null。
 */
export function rareTag(rare: readonly string[], poolOnly: readonly string[], name: (code: string) => string) {
  if (!rare.length) return null;
  const names = rare.map(name).join("、");
  const pooled = rare.filter((c) => poolOnly.includes(c));
  const tip = `对局数据少，胜率估计不太准：${names}`;
  if (pooled.length === rare.length) return { label: `英雄池：${names}`, title: `你英雄池里的英雄，${tip}` };
  return {
    label: `数据少：${names}`,
    title: pooled.length ? `${tip}（${pooled.map(name).join("、")}是因为在你的英雄池里才推荐的）` : tip,
  };
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
 * 选秀这一步信息条上的胜率：始终用「我方的读数」（B14e2 审核，用户意见），不用模型对当前局面的读数（它不知道
 * 英雄池，相当于假设我方像一般玩家那样选，池里没有强势英雄时比每个推荐都高）。
 * - 轮到我方：推荐第 1 名（只在英雄池里选；池里不够这一轮时是全部英雄里选）的预期和先动；
 * - 轮到对方：对方按先验的几种选法、我方再从英雄池里选最好的回应的预期（opponent.win），先动是目前双方在场的。
 * 不是选秀、还没算出来时返回 null（照常显示模型读数）。
 */
export function pickHeadline(a: Advice): { turn: "mine" | "theirs"; heroes: string[]; win: number; first: number | null } | null {
  if (a.phase !== "pick") return null;
  if (a.turn === "mine") {
    const r = a.recommend?.[0];
    return r ? { turn: "mine", heroes: r.heroes, win: r.win, first: r.first ?? null } : null;
  }
  const w = a.opponent?.win;
  return w != null ? { turn: "theirs", heroes: [], win: w, first: a.first?.mine ?? null } : null;
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
