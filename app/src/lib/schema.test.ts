import { describe, expect, it } from "vitest";
import { checkNumber, emptyItem, fieldsOf } from "./schema";
import type { JsonSchema } from "./types";

// 取自 repeat_battle / secret_shop 的 config_schema（B08 实际输出的形状）
const schema: JsonSchema = {
  type: "object",
  $defs: {
    Hunt: { enum: ["双足飞龙", "魔像", "报丧妖"], title: "Hunt", type: "string" },
    Target: {
      type: "object",
      properties: {
        name: { title: "Name", type: "string", description: "商品名（以游戏里 OCR 为准）" },
        price: { anyOf: [{ minimum: 1, type: "integer" }, { type: "null" }], default: null, title: "Price" },
      },
    },
  },
  properties: {
    hunt: { $ref: "#/$defs/Hunt", default: "双足飞龙", description: "讨伐目标" },
    dry_run: { type: "boolean", default: true, title: "Dry Run", description: "只导航和识别，不点「战斗开始」" },
    manual_runs: { type: "integer", default: 0, minimum: 0, title: "手动场数", description: "手动最多打几场" },
    targets: { type: "array", items: { $ref: "#/$defs/Target" }, title: "要买的商品" },
  },
};

describe("fieldsOf", () => {
  const fields = Object.fromEntries(fieldsOf(schema).map((f) => [f.key, f]));

  it("枚举走 $ref，保留字段自己的默认值", () => {
    expect(fields.hunt.kind).toBe("enum");
    expect(fields.hunt.enumValues).toEqual(["双足飞龙", "魔像", "报丧妖"]);
    expect(fields.hunt.default).toBe("双足飞龙");
  });

  it("自动生成的英文 title 换成说明的第一句", () => {
    expect(fields.dry_run.label).toBe("只导航和识别");
    expect(fields.manual_runs.label).toBe("手动场数");
  });

  it("对象数组展开子字段，可空整数标成 nullable", () => {
    expect(fields.targets.kind).toBe("array");
    const price = fields.targets.children!.find((c) => c.key === "price")!;
    expect(price.kind).toBe("integer");
    expect(price.nullable).toBe(true);
    expect(price.minimum).toBe(1);
    expect(emptyItem(fields.targets.children!)).toEqual({ name: "", price: null });
  });

  it("数字校验", () => {
    expect(checkNumber(fields.manual_runs, -1)).toBe("不能小于 0");
    expect(checkNumber(fields.manual_runs, 1.5)).toBe("请输入整数");
    expect(checkNumber(fields.manual_runs, 3)).toBeNull();
    expect(checkNumber(fields.manual_runs, "")).toBe("必须填写");
  });
});
