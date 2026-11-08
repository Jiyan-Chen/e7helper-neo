import { describe, expect, it } from "vitest";
import { adviceBody, adviceKey, banHeadline, inModel, pickHeadline, rareTag, splitTip, type Advice, type AdviseBody, type BanAdvice, type Recommend } from "./rta";

const ban = (first?: (number | null)[][]): BanAdvice => ({
  rows: ["a", "b"],
  cols: ["x", "y"],
  matrix: [[0.6, 0.5], [0.7, 0.4]],
  row_stats: [{ code: "a", worst: 0.5, win: 0.57, score: 0.535 }, { code: "b", worst: 0.4, win: 0.61, score: 0.505 }],
  recommend: "a",
  their_likely: [{ code: "x", prob: 0.3 }, { code: "y", prob: 0.1 }],
  nash: { mine: [1, 0], theirs: [0, 1], value: 0.5 },
  first,
});

describe("banHeadline", () => {
  it("没选时用推荐行，选了用选的那一行", () => {
    expect(banHeadline(ban(), null)).toEqual({ code: "a", win: 0.57, first: null });
    expect(banHeadline(ban(), "b")).toMatchObject({ code: "b", win: 0.61 });
    expect(banHeadline(ban(), "zz").code).toBe("a"); // 不在行里的当没选
  });

  it("先动概率按对方后禁的可能性加权，缺一格就不算", () => {
    expect(banHeadline(ban([[0.8, 0.4], [0.5, 0.5]]), null).first).toBeCloseTo((0.8 * 0.3 + 0.4 * 0.1) / 0.4);
    expect(banHeadline(ban([[0.8, null], [0.5, 0.5]]), null).first).toBeNull();
  });

  it("引擎给了这一行的先动概率和两种胜率（B14g2）就用引擎的", () => {
    const b = ban([[0.8, 0.4], [0.5, 0.5]]);
    b.row_stats[0] = { ...b.row_stats[0], first: 0.66, win_first: 0.7, win_second: 0.375 };
    expect(banHeadline(b, null)).toEqual({ code: "a", win: 0.57, first: 0.66, win_first: 0.7, win_second: 0.375 });
    b.row_stats[0].first = null; // 没有速度表
    expect(banHeadline(b, null).first).toBeNull();
  });
});

describe("splitTip", () => {
  it("我方先动时 / 后动时两种胜率", () => {
    expect(splitTip({ win_first: 0.612, win_second: 0.405 })).toBe("我方先动时 61.2%，后动时 40.5%");
    expect(splitTip({ win_first: 0.6 })).toBeUndefined();
    expect(splitTip(null)).toBeUndefined();
  });
});

describe("inModel", () => {
  it("只留模型里有的英雄，顺序不变", () => {
    const heroes = [{ code: "c2187" }, { code: "c1001" }, { code: "c1002" }];
    expect(inModel(heroes, ["c1002", "c1001"]).map((h) => h.code)).toEqual(["c1001", "c1002"]);
    expect(inModel(heroes, [])).toEqual([]);
  });
});

describe("adviceKey", () => {
  const body: AdviseBody = { side: "F", state: { prebans: { F: [], S: [] }, picks: { F: [], S: [] }, banned: {}, grades: ["legend", "legend"], rule: null } };

  it("英雄池改了键就不同；请求能从键里取回", () => {
    const k = adviceKey(body, "2026-11-04T10:00:00");
    expect(adviceKey(body, "2026-11-04T10:00:00")).toBe(k);
    expect(adviceKey(body, "2026-11-04T10:00:05")).not.toBe(k);
    expect(adviceKey(body, "")).not.toBe(k); // 默认英雄池
    expect(adviceBody(k)).toEqual(body);
  });
});

describe("rareTag", () => {
  const name = (c: string) => ({ a: "甲", b: "乙" })[c] ?? c;

  it("没有数据少的英雄不标", () => {
    expect(rareTag([], [], name)).toBeNull();
  });

  it("都是因为英雄池才推荐的标「英雄池」，否则标「数据少」", () => {
    expect(rareTag(["a"], ["a"], name)).toEqual({ label: "英雄池：甲", title: "你英雄池里的英雄，对局数据少，胜率估计不太准：甲" });
    expect(rareTag(["a"], [], name)).toEqual({ label: "数据少：甲", title: "对局数据少，胜率估计不太准：甲" });
    const mixed = rareTag(["a", "b"], ["b"], name)!;
    expect(mixed.label).toBe("数据少：甲、乙");
    expect(mixed.title).toContain("乙是因为在你的英雄池里才推荐的");
  });
});

describe("pickHeadline", () => {
  const rec = (heroes: string[], win: number, first?: number): Recommend => ({
    heroes, protected: null, score: win, win, worst: win - 0.05, gap: 0, close: false, rare: [], pool_only: [],
    responses: [], threat: null, first,
  });
  const advice = (extra: Partial<Advice>): Advice => ({
    phase: "pick", turn: "mine", side: "F", n: 0, slots: 1, win: 0.566, second_win: null, unknown: [], first: null,
    recommend: [rec(["a"], 0.5, 0.3), rec(["b"], 0.447)], pool: ["a", "b"], pool_short: false,
    stats: { ms: 1, truncated: false, depth: 3 }, ...extra,
  });

  it("轮到我方：推荐第 1 名的预期和先动（池不够这一轮时也是）", () => {
    expect(pickHeadline(advice({}))).toEqual({ turn: "mine", heroes: ["a"], win: 0.5, first: 0.3 });
    expect(pickHeadline(advice({ recommend: [rec(["a", "b"], 0.52)] }))).toMatchObject({ win: 0.52, first: null });
    expect(pickHeadline(advice({ pool_short: true }))).toMatchObject({ win: 0.5 });
    expect(pickHeadline(advice({ recommend: [] }))).toBeNull();
  });

  it("轮到对方：opponent.win（我方的读数），先动用目前双方在场的；没算出来照常显示读数", () => {
    const theirs = (win: number | null | undefined) => advice({
      turn: "theirs", recommend: undefined, first: { mine: 0.7, partial: true }, opponent: { likely: [], threats: [], win },
    });
    expect(pickHeadline(theirs(0.48))).toEqual({ turn: "theirs", heroes: [], win: 0.48, first: 0.7 });
    // B14g2：引擎给了 opponent.first（当前局面的先动概率）就用它
    const o = advice({ turn: "theirs", recommend: undefined, first: { mine: 0.7, partial: true },
      opponent: { likely: [], threats: [], win: 0.48, first: 0.55, win_first: 0.6, win_second: 0.333 } });
    expect(pickHeadline(o)).toEqual({ turn: "theirs", heroes: [], win: 0.48, first: 0.55, win_first: 0.6, win_second: 0.333 });
    expect(pickHeadline(theirs(null))).toBeNull();
    expect(pickHeadline(theirs(undefined))).toBeNull();
    expect(pickHeadline(advice({ phase: "ban", turn: null }))).toBeNull();
  });
});
