import { describe, expect, it } from "vitest";
import { filterHeroes, formatDevotion, formatStat, nameKey, type Hero, type HeroFilter } from "./heroes";

const hero = (code: string, name: string, name_en: string, extra: Partial<Hero> = {}): Hero => ({
  code, name, name_en, aliases: [], element: "fire", role: "warrior", rarity: 5, zodiac: "", stats: {}, slug: "", released: "", icon: true, ...extra,
});

const HEROES = [
  hero("c1001", "拉斯", "Ras", { rarity: 3, role: "knight", released: "2018-11-07" }),
  hero("c1007", "维德瑞", "Vildred", { element: "wind", role: "assassin", released: "2018-11-07" }),
  hero("c2007", "执行官维德瑞", "Arbiter Vildred", { element: "dark", role: "assassin", released: "2019-03-21" }),
  hero("c2111", "雪国的苏莉塔妮亚", "Solitaria of the Snow", { element: "light", role: "mage", aliases: ["雪苏"], released: "2021-04-15" }),
  hero("c4001", "苏琳", "Surin", { rarity: 4, role: "assassin" }), // 没有发布日期
];
const ALL: HeroFilter = { query: "", element: null, role: null, rarity: null };
const codes = (f: Partial<HeroFilter>) => filterHeroes(HEROES, { ...ALL, ...f }).map((h) => h.code);

describe("nameKey", () => {
  it("忽略空白、全半角、大小写和间隔号", () => {
    expect(nameKey("Ａｒｂｉｔｅｒ　Vildred")).toBe(nameKey("arbiter vildred"));
    expect(nameKey("爱德华·爱力克")).toBe("爱德华爱力克");
    expect(nameKey("爱德华・爱力克")).toBe("爱德华爱力克");
  });
});

describe("filterHeroes", () => {
  it("没有条件时按发布日期新的在前，同一天编号大的在前，没有日期的最后", () => {
    expect(codes({})).toEqual(["c2111", "c2007", "c1007", "c1001", "c4001"]);
  });

  it("搜索：完全一致 → 开头一致 → 包含；英文名、别名、编号也能搜", () => {
    expect(codes({ query: "维德瑞" })).toEqual(["c1007", "c2007"]);
    expect(codes({ query: "VILDRED" })).toEqual(["c1007", "c2007"]);
    expect(codes({ query: "雪苏" })).toEqual(["c2111"]);
    expect(codes({ query: "c21" })).toEqual(["c2111"]);
    expect(codes({ query: "苏" })).toEqual(["c4001", "c2111"]); // 开头一致的排在包含的前面，不管发布日期
    expect(codes({ query: "没有" })).toEqual([]);
  });

  it("属性 / 职业 / 星级筛选可以叠加", () => {
    expect(codes({ role: "assassin" })).toEqual(["c2007", "c1007", "c4001"]);
    expect(codes({ role: "assassin", rarity: 5 })).toEqual(["c2007", "c1007"]);
    expect(codes({ role: "assassin", element: "dark", query: "维德" })).toEqual(["c2007"]);
  });

  it("给了 score 按它排（RTA 助手按出场次数），搜索时仍先按命中程度", () => {
    const picks: Record<string, number> = { c1001: 50, c4001: 900, c1007: 10 };
    const byPicks = (f: Partial<HeroFilter>) => filterHeroes(HEROES, { ...ALL, ...f }, (h) => picks[h.code] ?? 0).map((h) => h.code);
    expect(byPicks({})).toEqual(["c4001", "c1001", "c1007", "c2111", "c2007"]); // 同分的按编号大的在前
    expect(byPicks({ query: "维德瑞" })).toEqual(["c1007", "c2007"]);
  });
});

describe("formatStat", () => {
  it("百分比和整数", () => {
    expect(formatStat(0.15, true)).toBe("15%");
    expect(formatStat(1.5, true)).toBe("150%");
    expect(formatStat(22755)).toBe("22,755");
    expect(formatStat(undefined)).toBe("—");
  });
});

describe("formatDevotion", () => {
  it("百分比类型和固定值", () => {
    const ps = ["acc", "max_hp_rate"];
    expect(formatDevotion("acc", 0.27, ps)).toBe("27%");
    expect(formatDevotion("max_hp_rate", 0.125, ps)).toBe("12.5%");
    expect(formatDevotion("att", 57, ps)).toBe("57");
    expect(formatDevotion("acc", undefined, ps)).toBe("—");
  });
});
