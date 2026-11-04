import { describe, expect, it } from "vitest";
import { banHeadline, inModel, type BanAdvice } from "./rta";

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
});

describe("inModel", () => {
  it("只留模型里有的英雄，顺序不变", () => {
    const heroes = [{ code: "c2187" }, { code: "c1001" }, { code: "c1002" }];
    expect(inModel(heroes, ["c1002", "c1001"]).map((h) => h.code)).toEqual(["c1001", "c1002"]);
    expect(inModel(heroes, [])).toEqual([]);
  });
});
