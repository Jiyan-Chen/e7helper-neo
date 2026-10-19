import { describe, expect, it } from "vitest";
import {
  type Step, ROOT, cloneStep, countSteps, describeStep, duplicateStep, findStep, insertStep, localProblems,
  locateError, moveStep, newStep, numbering, removeStep, templateRefs, updateStep,
} from "./flow";

function s<T extends Step["type"]>(type: T, id: string, extra: Partial<Extract<Step, { type: T }>> = {}): Step {
  return { ...newStep(type), id, ...extra } as Step;
}

function tree(): Step[] {
  return [
    s("tap_template", "a", { template: "common:lobby/sanctuary" }),
    s("if", "b", {
      condition: { kind: "template", templates: ["圣域标题"], scene: null, appear: true, wait: 5 },
      then: [s("wait", "b1"), s("back", "b2")],
      else: [s("end", "b3", { success: false })],
    }),
    s("repeat", "c", { mode: "until", count: 5, condition: { kind: "scene", templates: [], scene: "lobby", appear: true, wait: 0 }, body: [s("back", "c1"), s("break", "c2")] }),
  ];
}

describe("步骤树", () => {
  it("编号和引擎一致：否则接着那么编", () => {
    const n = numbering(tree());
    expect([...n.entries()]).toEqual([
      ["a", "1"], ["b", "2"], ["b1", "2.1"], ["b2", "2.2"], ["b3", "2.3"], ["c", "3"], ["c1", "3.1"], ["c2", "3.2"],
    ]);
    expect(countSteps(tree())).toBe(8);
  });

  it("查找、修改、删除、插入", () => {
    const t = tree();
    expect(findStep(t, "c1")).toMatchObject({ addr: { parent: "c", branch: "body" }, index: 0 });
    const u = updateStep(t, "b1", (x) => ({ ...x, note: "改了" }));
    expect(findStep(u, "b1")!.step.note).toBe("改了");
    expect(findStep(t, "b1")!.step.note).toBe(""); // 不改原树
    expect(findStep(removeStep(t, "b"), "b1")).toBeNull();
    const ins = insertStep(t, { parent: "b", branch: "else" }, 0, s("back", "x"));
    expect(numbering(ins).get("x")).toBe("2.3");
    expect(numbering(ins).get("b3")).toBe("2.4");
  });

  it("移动：同列表、跨列表、不能移进自己", () => {
    const t = tree();
    const down = moveStep(t, "a", ROOT, 2); // 移到 b 后面
    expect(down.map((x) => x.id)).toEqual(["b", "a", "c"]);
    expect(moveStep(t, "a", ROOT, 0)).toBe(t); // 原地不动
    expect(moveStep(t, "a", ROOT, 1)).toBe(t);
    const into = moveStep(t, "a", { parent: "c", branch: "body" }, 1);
    expect(into.map((x) => x.id)).toEqual(["b", "c"]);
    expect(findStep(into, "a")!.addr).toEqual({ parent: "c", branch: "body" });
    expect(moveStep(t, "b", { parent: "b", branch: "then" }, 0)).toBe(t);
    const outer = [s("repeat", "r", { body: [s("if", "i", { then: [] })] })];
    expect(moveStep(outer, "r", { parent: "i", branch: "then" }, 0)).toBe(outer);
  });

  it("复制会换新 id（含子步骤）", () => {
    const t = tree();
    const d = duplicateStep(t, "b");
    expect(d.length).toBe(4);
    const copy = d[2];
    expect(copy.id).not.toBe("b");
    expect(copy.type === "if" && copy.then.map((x) => x.id)).not.toContain("b1");
    expect(cloneStep(t[2]).id).not.toBe("c");
  });

  it("模板引用", () => {
    expect([...templateRefs(tree())].sort()).toEqual(["common:lobby/sanctuary", "圣域标题"]);
  });
});

describe("文字", () => {
  it("描述", () => {
    const t = tree();
    const label = (r: string) => (r === "common:lobby/sanctuary" ? "大厅「圣域」" : r);
    expect(describeStep(t[0], label)).toBe("点击「大厅「圣域」」");
    expect(describeStep(t[1])).toBe("如果 「圣域标题」出现（最多等 5 秒）");
    expect(describeStep(t[2])).toBe("重复直到 在「大厅」（最多 5 轮）");
    expect(describeStep(s("tap_template", "z"))).toBe("点击「未选模板」");
  });

  it("本地检查", () => {
    const p = localProblems([s("break", "x"), s("tap_template", "y"), s("repeat", "r", { body: [s("break", "z")] })]);
    expect(p.get("x")).toContain("只能放在循环里");
    expect(p.get("y")).toBe("还没选模板");
    expect(p.has("z")).toBe(false);
    expect(localProblems(tree()).size).toBe(0);
  });

  it("校验错误定位到步骤", () => {
    const t = tree();
    expect(locateError(t, ["steps", 1, "if", "else", 0, "end", "message"])).toBe("b3");
    expect(locateError(t, ["steps", 2, "repeat", "body", 1, "break"])).toBe("c2");
    expect(locateError(t, ["steps", 0, "tap_template", "template"])).toBe("a");
    expect(locateError(t, ["name"])).toBeNull();
  });
});
