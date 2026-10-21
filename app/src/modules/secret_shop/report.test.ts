import { describe, expect, it } from "vitest";
import { buckets, inRange, pageLabel, pagesPerHit, rangeStart, type ShopDay, sumDays, wan } from "./report";

const day = (date: string, refreshes: number, bought: Record<string, number> = {}): ShopDay => ({
  date, runs: 1, refreshes, skystone_spent: refreshes * 3, gold_spent: 0, pages: refreshes + 1, bought, channel_switches: 0,
});

const today = new Date(2026, 9, 20, 15, 0); // 2026-10-20（周二）

describe("范围", () => {
  it("近 7 天含今天", () => {
    expect(rangeStart("7", today)).toBe("2026-10-14");
    expect(rangeStart("30", today)).toBe("2026-09-21");
    expect(rangeStart("all", today)).toBeNull();
    expect(inRange("2026-10-14T00:00:01", "2026-10-14")).toBe(true);
    expect(inRange("2026-10-13T23:59:59", "2026-10-14")).toBe(false);
    expect(inRange("2026-01-01T00:00:00", null)).toBe(true);
  });
});

describe("汇总", () => {
  it("按商品累加，平均几页出一次", () => {
    const t = sumDays([day("2026-10-15", 9, { 誓约书签: 1 }), day("2026-10-17", 29, { 誓约书签: 1, 神秘奖牌: 1 })]);
    expect([t.runs, t.refreshes, t.skystone, t.pages]).toEqual([2, 38, 114, 40]);
    expect(t.bought).toEqual({ 誓约书签: 2, 神秘奖牌: 1 });
    expect(pagesPerHit(t.pages, t.bought["誓约书签"])).toBe(20);
    expect(pagesPerHit(10, 0)).toBeNull();
  });
});

describe("图表的柱子", () => {
  it("近 7 天：每天一根，没跑的天是空柱", () => {
    const b = buckets([day("2026-10-01", 50), day("2026-10-15", 9, { 誓约书签: 1 }), day("2026-10-20", 3)], "7", today);
    expect(b.map((x) => x.label)).toEqual(["10/14", "10/15", "10/16", "10/17", "10/18", "10/19", "10/20"]);
    expect(b.map((x) => x.refreshes)).toEqual([0, 9, 0, 0, 0, 0, 3]);
    expect(b[1].bought).toEqual({ 誓约书签: 1 });
    expect(b[1].title).toBe("10月15日");
  });

  it("全部：从第一条记录开始；跨度长就按周（周一开始）", () => {
    expect(buckets([], "all", today)).toEqual([]);
    const short = buckets([day("2026-10-18", 3)], "all", today);
    expect(short.map((x) => x.key)).toEqual(["2026-10-18", "2026-10-19", "2026-10-20"]);
    const long = buckets([day("2026-08-01", 10, { 神秘奖牌: 1 }), day("2026-08-02", 5), day("2026-10-20", 3)], "all", today);
    expect(long[0].key).toBe("2026-07-27"); // 8/1 是周六，那一周从 7/27 周一开始
    expect(long[0].refreshes).toBe(15);
    expect(long[0].bought).toEqual({ 神秘奖牌: 1 });
    expect(long[0].title).toBe("7月27日–8月2日");
    expect(long[0].span).toBe(7);
    expect(short[0].span).toBe(1);
    expect(long.at(-1)!.key).toBe("2026-10-19");
    expect(long.at(-1)!.refreshes).toBe(3);
    expect(long.length).toBe(13);
  });
});

describe("格式化", () => {
  it("金币按万", () => {
    expect(wan(9000)).toBe("9,000");
    expect(wan(464000)).toBe("46.4万");
    expect(wan(1_840_000)).toBe("184万");
    expect(wan(200_000)).toBe("20万");
  });

  it("第几页", () => {
    expect(pageLabel(0)).toBe("进店时");
    expect(pageLabel(12)).toBe("第 12 次刷新");
  });
});
