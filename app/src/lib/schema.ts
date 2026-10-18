// pydantic 生成的 JSON Schema → 表单字段描述。只处理模块配置实际用到的子集：
// 布尔、整数 / 小数（含上下限）、字符串、枚举（$ref 到 $defs）、可空（anyOf [X, null]）、对象数组。
import type { JsonSchema } from "./types";

export type FieldKind = "boolean" | "integer" | "number" | "string" | "enum" | "array" | "object" | "unknown";

export interface Field {
  key: string;
  label: string;
  description: string;
  kind: FieldKind;
  nullable: boolean;
  default: unknown;
  enumValues?: string[];
  minimum?: number;
  maximum?: number;
  /** 数组元素 / 对象的子字段 */
  children?: Field[];
  schema: JsonSchema;
}

export function resolveRef(s: JsonSchema, root: JsonSchema): JsonSchema {
  let cur = s;
  for (let i = 0; i < 8 && cur.$ref; i++) {
    const name = cur.$ref.replace(/^#\/\$defs\//, "");
    const target = root.$defs?.[name];
    if (!target) break;
    // $ref 旁边的 default / description 优先
    const { $ref: _ignored, ...rest } = cur;
    cur = { ...target, ...rest };
  }
  return cur;
}

function unwrapNullable(s: JsonSchema, root: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  const variants = s.anyOf ?? s.oneOf;
  if (variants) {
    const nonNull = variants.filter((v) => v.type !== "null");
    if (nonNull.length === 1 && nonNull.length < variants.length) {
      const { anyOf: _a, oneOf: _o, ...rest } = s;
      return { schema: { ...resolveRef(nonNull[0], root), ...rest }, nullable: true };
    }
  }
  return { schema: resolveRef(s, root), nullable: false };
}

function kindOf(s: JsonSchema): FieldKind {
  if (s.enum) return "enum";
  const t = Array.isArray(s.type) ? s.type.find((x) => x !== "null") : s.type;
  switch (t) {
    case "boolean":
    case "integer":
    case "number":
    case "string":
    case "array":
    case "object":
      return t;
    default:
      return "unknown";
  }
}

/** pydantic 没写 title 时会把字段名转成 "Dry Run" 这样的英文；这种情况下退回到 description 的第一句。 */
function labelOf(key: string, s: JsonSchema): string {
  const auto = key.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  if (s.title && s.title !== auto) return s.title;
  const first = s.description?.split(/[，。；（(:：]/)[0]?.trim();
  return first || key;
}

export function fieldsOf(schema: JsonSchema, root: JsonSchema = schema): Field[] {
  const props = schema.properties ?? {};
  return Object.entries(props).map(([key, raw]) => {
    const { schema: s, nullable } = unwrapNullable(raw, root);
    const kind = kindOf(s);
    const field: Field = {
      key,
      label: labelOf(key, raw.title ? raw : s),
      description: raw.description ?? s.description ?? "",
      kind,
      nullable,
      default: raw.default !== undefined ? raw.default : s.default,
      minimum: s.minimum ?? (s.exclusiveMinimum !== undefined ? s.exclusiveMinimum + (kind === "integer" ? 1 : 0) : undefined),
      maximum: s.maximum ?? (s.exclusiveMaximum !== undefined ? s.exclusiveMaximum - (kind === "integer" ? 1 : 0) : undefined),
      schema: s,
    };
    if (kind === "enum") field.enumValues = (s.enum ?? []).map(String);
    if (kind === "array" && s.items) {
      const item = resolveRef(s.items, root);
      if (item.properties) field.children = fieldsOf(item, root);
    }
    if (kind === "object" && s.properties) field.children = fieldsOf(s, root);
    return field;
  });
}

/** 新数组元素的默认值。 */
export function emptyItem(children: Field[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const c of children) out[c.key] = c.default ?? (c.nullable ? null : c.kind === "boolean" ? false : c.kind === "string" ? "" : null);
  return out;
}

/** 数字输入的校验：返回错误文字或 null。 */
export function checkNumber(f: Field, v: unknown): string | null {
  if (v === null || v === undefined || v === "") return f.nullable ? null : "必须填写";
  const n = Number(v);
  if (!Number.isFinite(n)) return "请输入数字";
  if (f.kind === "integer" && !Number.isInteger(n)) return "请输入整数";
  if (f.minimum !== undefined && n < f.minimum) return `不能小于 ${f.minimum}`;
  if (f.maximum !== undefined && n > f.maximum) return `不能大于 ${f.maximum}`;
  return null;
}
