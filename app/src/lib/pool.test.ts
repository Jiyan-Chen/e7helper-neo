import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RESET, autoSave, parseSpeed, setPoolSpeed, togglePool, type PoolChange, type PoolHero, type RtaPool } from "./pool";

describe("togglePool / setPoolSpeed", () => {
  it("勾上放最后，再点一次去掉（连同填的速度）", () => {
    let h: PoolHero[] = [];
    h = togglePool(h, "c1");
    h = togglePool(h, "c2");
    expect(h).toEqual([{ code: "c1" }, { code: "c2" }]);
    h = setPoolSpeed(h, "c1", 300);
    expect(h[0]).toEqual({ code: "c1", speed: 300 });
    h = togglePool(h, "c1");
    expect(h).toEqual([{ code: "c2" }]);
    expect(togglePool(h, "c1")).toEqual([{ code: "c2" }, { code: "c1" }]); // 重新勾上不带以前的速度
  });

  it("清掉速度、不在英雄池里的不管", () => {
    const h = [{ code: "c1", speed: 300 }, { code: "c2" }];
    expect(setPoolSpeed(h, "c1", null)).toEqual([{ code: "c1" }, { code: "c2" }]);
    expect(setPoolSpeed(h, "c9", 250)).toEqual(h);
  });
});

describe("parseSpeed", () => {
  it("空 = 不填，50–400 的整数，别的不合法", () => {
    expect(parseSpeed("")).toBeNull();
    expect(parseSpeed("  ")).toBeNull();
    expect(parseSpeed("300")).toBe(300);
    expect(parseSpeed(" 50 ")).toBe(50);
    expect(parseSpeed("400")).toBe(400);
    expect(parseSpeed("３１５")).toBe(315); // 全角数字
    for (const bad of ["49", "401", "3", "30.5", "abc", "-200", "2e2"]) expect(parseSpeed(bad)).toBeUndefined();
  });
});

describe("autoSave", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const pool = (heroes: PoolHero[], updated = "t"): RtaPool => ({ updated, heroes });

  it("最后一次修改后 400ms 存一次，存的是最新的", async () => {
    const save = vi.fn(async (h: PoolChange) => pool(h === RESET ? [] : h));
    const saved = vi.fn();
    const s = autoSave(save, { saved });
    s.change([{ code: "c1" }]);
    await vi.advanceTimersByTimeAsync(300);
    s.change([{ code: "c1" }, { code: "c2" }]);
    await vi.advanceTimersByTimeAsync(300);
    expect(save).not.toHaveBeenCalled();
    expect(s.dirty()).toBe(true);
    await vi.advanceTimersByTimeAsync(100);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenLastCalledWith([{ code: "c1" }, { code: "c2" }]);
    expect(saved).toHaveBeenCalledWith(pool([{ code: "c1" }, { code: "c2" }]));
    expect(s.dirty()).toBe(false);
  });

  it("同一时间只有一个保存请求：在途时又改了，回来后再存最新的", async () => {
    const resolvers: (() => void)[] = [];
    const save = vi.fn((h: PoolChange) => new Promise<RtaPool>((ok) => resolvers.push(() => ok(pool(h === RESET ? [] : h)))));
    const saved = vi.fn();
    const s = autoSave(save, { saved });
    s.change([{ code: "c1" }]);
    await vi.advanceTimersByTimeAsync(400);
    expect(save).toHaveBeenCalledTimes(1);
    s.change([{ code: "c2" }]);
    s.change([{ code: "c3" }]);
    await vi.advanceTimersByTimeAsync(400);
    expect(save).toHaveBeenCalledTimes(1); // 第一个还没回来
    resolvers[0]();
    await vi.advanceTimersByTimeAsync(0);
    expect(saved).not.toHaveBeenCalled(); // 已经过时了，不报
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith([{ code: "c3" }]);
    resolvers[1]();
    await vi.advanceTimersByTimeAsync(0);
    expect(saved).toHaveBeenCalledTimes(1);
    expect(saved).toHaveBeenCalledWith(pool([{ code: "c3" }]));
  });

  it("恢复默认也排队：在途的保存回来后才发，之后的修改再接着存", async () => {
    const calls: PoolChange[] = [];
    const resolvers: (() => void)[] = [];
    const save = vi.fn((c: PoolChange) => {
      calls.push(c);
      return new Promise<RtaPool>((ok) => resolvers.push(() => ok(c === RESET ? { updated: "", heroes: [{ code: "d" }], default: true } : pool(c))));
    });
    const saved = vi.fn();
    const s = autoSave(save, { saved });
    s.change([{ code: "c1" }]);
    s.flush();
    s.change(RESET);
    s.flush(); // 第一个还在途：先不发
    expect(calls).toEqual([[{ code: "c1" }]]);
    resolvers[0]();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toEqual([[{ code: "c1" }], RESET]);
    resolvers[1]();
    await vi.advanceTimersByTimeAsync(0);
    expect(saved).toHaveBeenLastCalledWith({ updated: "", heroes: [{ code: "d" }], default: true });
  });

  it("flush 立刻存（离开页面时）；没有修改不发请求；失败报出来", async () => {
    const save = vi.fn(async () => {
      throw new Error("not_in_model");
    });
    const failed = vi.fn();
    const s = autoSave(save, { failed });
    s.flush();
    expect(save).not.toHaveBeenCalled();
    s.change([{ code: "c1" }]);
    s.flush();
    expect(save).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(0);
    expect(failed).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(save).toHaveBeenCalledTimes(1); // 定时器已经清掉了
  });
});
