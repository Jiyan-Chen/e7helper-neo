import { describe, expect, it } from "vitest";
import {
  addPicks, addPreban, apiState, banOptions, gradeChoice, needsRule, newDraft, pickNumbers, prebanTarget, removePreban, ruleFor,
  setBan, setPrebans, stepOf, taken, teamPicks, turn, turnAt, type Draft, type Setup,
} from "./draft";
const H = Array.from({ length: 16 }, (_, i) => `h${i}`);

/** 预禁完、进入选秀的局面（我方预禁 h12 h13，对方 h14 h15）。 */
function started(side: "F" | "S" = "F"): Draft {
  let d: Draft = { ...newDraft({ side, grades: ["legend", "emperor"], rule: "unknown" }), phase: "preban" };
  d = setPrebans(d, "mine", ["h12", "h13"]);
  d = setPrebans(d, "theirs", ["h14", "h15"]);
  return { ...d, phase: "draft" };
}

/** 按整局顺序一手一手填 h0…h(n-1)。 */
function picked(d: Draft, n: number): Draft {
  for (let i = 0; i < n; i++) d = addPicks(d, [H[i]]);
  return d;
}

describe("选人顺序", () => {
  it("1-2-2-2-2-1：轮到谁、这一轮还要选几名", () => {
    expect([0, 1, 2, 3, 9, 10].map((n) => turnAt(n, "F"))).toEqual([
      { team: "mine", slots: 1 }, { team: "theirs", slots: 2 }, { team: "theirs", slots: 1 },
      { team: "mine", slots: 2 }, { team: "theirs", slots: 1 }, null,
    ]);
    expect(turnAt(0, "S")).toEqual({ team: "theirs", slots: 1 });
  });

  it("每队 5 个位置是整局的第几手", () => {
    expect(pickNumbers("mine", "F")).toEqual([1, 4, 5, 8, 9]);
    expect(pickNumbers("mine", "S")).toEqual([2, 3, 6, 7, 10]);
    expect(pickNumbers("theirs", "S")).toEqual([1, 4, 5, 8, 9]);
  });

  it("按队拆开已选的", () => {
    const d = picked(started("S"), 5); // 先手是对方
    expect(teamPicks(d, "theirs")).toEqual(["h0", "h3", "h4"]);
    expect(teamPicks(d, "mine")).toEqual(["h1", "h2"]);
  });
});

describe("五步", () => {
  it("准备 → 预禁 → 选秀 → 后禁 → 结果", () => {
    const d0 = newDraft();
    expect(stepOf(d0)).toBe("setup");
    expect(stepOf({ ...d0, phase: "preban" })).toBe("preban");
    let d = started();
    expect(stepOf(d)).toBe("pick");
    d = picked(d, 10);
    expect(stepOf(d)).toBe("ban");
    d = setBan(d, "mine", "h1");
    expect(stepOf(d)).toBe("ban");
    d = setBan(d, "theirs", "h0");
    expect(stepOf(d)).toBe("result");
  });
});

describe("预禁", () => {
  it("先填我方 2 名再填对方，同一队不能重复，两队可以重复", () => {
    let d: Draft = { ...newDraft(), phase: "preban" };
    expect(prebanTarget(d)).toBe("mine");
    d = addPreban(d, "mine", "h0");
    expect(addPreban(d, "mine", "h0")).toBe(d);
    d = addPreban(d, "mine", "h1");
    expect(addPreban(d, "mine", "h2")).toBe(d); // 满了
    expect(prebanTarget(d)).toBe("theirs");
    d = addPreban(d, "theirs", "h0");
    expect(d.prebans.theirs).toEqual(["h0"]);
    d = removePreban(d, "mine", "h0");
    expect(d.prebans.mine).toEqual(["h1"]);
    expect(prebanTarget(d)).toBe("mine");
    expect(setPrebans(d, "mine", ["h3", "h3"])).toBe(d);
  });

  it("不在预禁这一步时不能改", () => {
    const d = started();
    expect(addPreban(d, "mine", "h0")).toBe(d);
  });
});

describe("选秀", () => {
  it("被预禁 / 已选的不能再选", () => {
    let d = started();
    expect(taken(d)).toEqual(new Set(["h12", "h13", "h14", "h15"]));
    expect(addPicks(d, ["h14"])).toBe(d);
    d = addPicks(d, ["h0"]);
    expect(addPicks(d, ["h0"])).toBe(d);
  });

  it("一次填一轮里的两名；超过这一轮、轮错队、重复的都不收", () => {
    let d = addPicks(started(), ["h0"]);
    expect(addPicks(d, ["h1", "h2", "h3"])).toBe(d);
    expect(addPicks(d, ["h1", "h2"], "mine")).toBe(d); // 这一轮是对方
    expect(addPicks(d, ["h1", "h1"])).toBe(d);
    d = addPicks(d, ["h1", "h2"], "theirs");
    expect(turn(d)).toEqual({ team: "mine", slots: 2 });
    d = addPicks(d, ["h3"]);
    expect(turn(d)).toEqual({ team: "mine", slots: 1 });
    expect(addPicks(d, ["h4", "h5"])).toBe(d);
  });
});

describe("后禁", () => {
  it("只能禁对方不在保护位的英雄，再点一次取消", () => {
    let d = picked(started(), 10);
    // 我方先手：h0 h3 h4 h7 h8（保护位 h4）；对方：h1 h2 h5 h6 h9（保护位 h5）
    expect(banOptions(d, "mine")).toEqual(["h1", "h2", "h6", "h9"]);
    expect(banOptions(d, "theirs")).toEqual(["h0", "h3", "h7", "h8"]);
    expect(setBan(d, "mine", "h5")).toBe(d);
    expect(setBan(d, "mine", "h0")).toBe(d);
    d = setBan(d, "mine", "h1");
    expect(d.bans.mine).toBe("h1");
    expect(setBan(d, "mine", "h1").bans.mine).toBeNull();
    expect(setBan(d, "mine", "h1", false)).toBe(d); // 点矩阵格子：已经是它就不变
    expect(setBan(d, "mine", "h2", false).bans.mine).toBe("h2");
  });

  it("没选完不能禁", () => {
    const d = picked(started(), 9);
    expect(setBan(d, "mine", "h1")).toBe(d);
  });
});

describe("转成引擎的局面", () => {
  it("我方后手：按先手 / 后手分，段位换成 [先手, 后手]", () => {
    const d = picked(started("S"), 3);
    expect(apiState(d, "unknown")).toEqual({
      prebans: { F: ["h14", "h15"], S: ["h12", "h13"] },
      picks: { F: ["h0"], S: ["h1", "h2"] },
      banned: {},
      grades: ["emperor", "legend"],
      rule: "unknown",
    });
  });

  it("后禁双方都填了才带上：banned[F] 是先手方被禁的", () => {
    let d = picked(started("F"), 10);
    d = setBan(d, "mine", "h1");
    expect(apiState(d, "unknown").banned).toEqual({});
    d = setBan(d, "theirs", "h0");
    expect(apiState(d, "unknown").banned).toEqual({ F: "h0", S: "h1" });
  });

  it("开战规则：双方都在优胜者以上才用选的；有规则时没选不能开始", () => {
    const s = (grades: Setup["grades"], rule = "rta_cs_dodge_down_desc"): Setup => ({ side: "F", grades, rule });
    expect(ruleFor(s(["legend", "champion"]))).toBe("rta_cs_dodge_down_desc");
    expect(ruleFor(s(["legend", "challenger"]))).toBeNull(); // 没有规则（海外数据的记法）
    expect(needsRule(s(["legend", "champion"], "unknown"))).toBe(true);
    expect(needsRule(s(["legend", "champion"]))).toBe(false);
    expect(needsRule(s(["legend", "challenger"], "unknown"))).toBe(false); // 没有规则
  });

  it("段位：挑战者及以下合成一项，旧的 / 不认识的按传说", () => {
    expect(["bronze", "gold", "master", "challenger"].map(gradeChoice)).toEqual(Array(4).fill("challenger"));
    expect(gradeChoice("warlord")).toBe("warlord");
    expect(gradeChoice(null)).toBe("legend");
    expect(gradeChoice("xx")).toBe("legend");
  });
});
