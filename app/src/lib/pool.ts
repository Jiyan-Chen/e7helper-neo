// RTA 英雄池（B14e2）：在英雄图鉴里勾选自己有的英雄（可以填速度），RTA 助手始终只推荐这些（第 2 轮审核去掉了开关）。
// 存在引擎 GET / PUT / DELETE /api/rta/pool（<数据目录>/modules/rta_draft/pool.json），只收选秀模型里有的英雄；
// 没设置过时是默认的热门英雄（default: true，主模型里被选最多的 60 名），DELETE 回到默认。

export interface PoolHero {
  code: string;
  /** 面板速度；不填 = 按段位的常见速度 */
  speed?: number | null;
}

export interface RtaPool {
  format?: number;
  /** 保存时间（空 = 还没存过）；RTA 助手的推荐缓存按它区分 */
  updated: string;
  heroes: PoolHero[];
  /** 玩家没设置过，用的是默认的热门英雄 */
  default?: boolean;
}

export const SPEED_MIN = 50;
export const SPEED_MAX = 400;

/** 勾选 / 取消一名英雄（新勾的放最后）。 */
export function togglePool(heroes: readonly PoolHero[], code: string): PoolHero[] {
  return heroes.some((h) => h.code === code) ? heroes.filter((h) => h.code !== code) : [...heroes, { code }];
}

/** 改一名英雄的速度（null = 不填）；不在英雄池里的不管。 */
export function setPoolSpeed(heroes: readonly PoolHero[], code: string, speed: number | null): PoolHero[] {
  return heroes.map((h) => (h.code === code ? (speed === null ? { code } : { code, speed }) : h));
}

/** 速度输入：空 = null（不填）；50–400 的整数 = 速度；其余 = undefined（不合法，不保存）。 */
export function parseSpeed(text: string): number | null | undefined {
  const t = text.trim().replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
  if (!t) return null;
  if (!/^\d+$/.test(t)) return undefined;
  const v = Number(t);
  return v >= SPEED_MIN && v <= SPEED_MAX ? v : undefined;
}

/** 要存的：一份英雄池，或者 RESET（恢复默认 = 删掉存的） */
export const RESET = "reset" as const;
export type PoolChange = PoolHero[] | typeof RESET;

/**
 * 改了自动保存：最后一次修改后 delay 毫秒保存一次；同一时间只有一个请求（在途时又改了，等它回来再存最新的，
 * 免得两个请求先后颠倒、旧的盖掉新的）。flush() 立刻保存还没存的（离开页面时）；恢复默认也走这里排队（change(RESET) 再 flush）。
 */
export function autoSave(save: (change: PoolChange) => Promise<RtaPool>, on: {
  saving?: () => void;
  saved?: (pool: RtaPool) => void;
  failed?: (e: unknown) => void;
}, delay = 400) {
  let pending: PoolChange | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inflight = false;

  const flush = () => {
    clearTimeout(timer);
    timer = undefined;
    if (inflight || pending === null) return;
    const body = pending;
    pending = null;
    inflight = true;
    on.saving?.();
    save(body)
      .then((pool) => {
        if (pending === null) on.saved?.(pool);
      })
      .catch((e) => on.failed?.(e))
      .finally(() => {
        inflight = false;
        if (pending !== null) flush();
      });
  };

  return {
    change(c: PoolChange) {
      pending = c;
      clearTimeout(timer);
      timer = setTimeout(flush, delay);
    },
    flush,
    /** 有没有还没存上的修改 */
    dirty: () => pending !== null || inflight,
  };
}
