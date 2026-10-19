// 自定义流程（B11）：数据形状（对照 engine/e7helper/core/flows/model.py）和步骤树的操作。
// 步骤按 id 定位；列表地址 = 父步骤 id + 分支（顶层是 parent=null）。

export type OnMissing = "stop" | "skip";
export type Branch = "then" | "else" | "body";

export interface Condition {
  kind: "template" | "scene";
  templates: string[];
  scene: string | null;
  appear: boolean;
  wait: number;
}

interface Base {
  id: string;
  note: string;
}

export type Step =
  | (Base & { type: "tap_template"; template: string; timeout: number; on_missing: OnMissing; settle: boolean })
  | (Base & { type: "tap_point"; x: number; y: number })
  | (Base & { type: "swipe"; x1: number; y1: number; x2: number; y2: number; duration: number })
  | (Base & { type: "back" })
  | (Base & { type: "wait"; seconds: number })
  | (Base & { type: "wait_still"; timeout: number })
  | (Base & { type: "wait_template"; templates: string[]; appear: boolean; timeout: number; on_missing: OnMissing })
  | (Base & { type: "wait_scene"; scene: string; timeout: number; on_missing: OnMissing })
  | (Base & { type: "end"; success: boolean; message: string })
  | (Base & { type: "break" })
  | (Base & { type: "if"; condition: Condition; then: Step[]; else: Step[] })
  | (Base & {
      type: "repeat";
      mode: "times" | "until" | "while";
      count: number;
      condition: Condition | null;
      on_limit: "stop" | "continue";
      body: Step[];
    });

export type StepType = Step["type"];
export type StepOf<T extends StepType> = Extract<Step, { type: T }>;

export interface FlowLimits {
  max_minutes: number;
  max_taps: number;
}

export interface Flow {
  version: number;
  id: string;
  name: string;
  description: string;
  limits: FlowLimits;
  steps: Step[];
  created: number | null;
  updated: number | null;
  missing?: string[];
}

export interface FlowRun {
  time: string;
  flow: string;
  name: string;
  status: string;
  steps: number;
  taps: number;
  popups: number;
  seconds: number;
  error: string | null;
  message: string;
}

export interface FlowSummary {
  id: string;
  name: string;
  description?: string;
  steps?: number;
  limits?: FlowLimits;
  created?: number | null;
  updated?: number | null;
  missing?: string[];
  last_run?: FlowRun | null;
  error?: string;
}

export interface UserTemplate {
  ref: string;
  name: string;
  size?: [number, number];
  note?: string;
  moving?: boolean;
  dim_check?: boolean;
  has_tap?: boolean;
  used_by: { id: string; name: string }[];
  error?: string;
}

export const COMMON_PREFIX = "common:";
export const FLOW_MODULE = "custom_flow";

// 和引擎 SCENE_NAMES 一致
export const SCENES: Record<string, string> = {
  lobby: "大厅",
  sanctuary: "圣域",
  shop: "商店",
  secret_shop: "秘密商店",
  arena: "竞技场",
};

export const STEP_LABELS: Record<StepType, string> = {
  tap_template: "点击模板",
  tap_point: "点击坐标",
  swipe: "滑动",
  back: "返回键",
  wait: "等待",
  wait_still: "等画面静止",
  wait_template: "等模板",
  wait_scene: "等界面",
  end: "结束流程",
  break: "跳出循环",
  if: "如果",
  repeat: "重复",
};

/** 添加步骤菜单的分组（说明给玩家看）。 */
export const STEP_GROUPS: { title: string; items: { type: StepType; hint: string }[] }[] = [
  {
    title: "操作",
    items: [
      { type: "tap_template", hint: "等画面上出现某个模板，然后点它" },
      { type: "tap_point", hint: "点画面上固定的位置" },
      { type: "swipe", hint: "从一点滑到另一点（翻页、滚动列表）" },
      { type: "back", hint: "按安卓返回键" },
    ],
  },
  {
    title: "等待",
    items: [
      { type: "wait", hint: "等固定的秒数" },
      { type: "wait_template", hint: "等某个模板出现或消失" },
      { type: "wait_scene", hint: "等回到大厅、圣域等界面" },
      { type: "wait_still", hint: "等画面不再动（动画放完）" },
    ],
  },
  {
    title: "条件和循环",
    items: [
      { type: "if", hint: "如果出现某个模板，就做…否则做…" },
      { type: "repeat", hint: "重复几次，或重复到某个模板出现" },
      { type: "break", hint: "跳出所在的循环" },
      { type: "end", hint: "到这里就结束整个流程" },
    ],
  },
];

export function newId(): string {
  return Math.random().toString(16).slice(2, 10).padEnd(8, "0");
}

export function newCondition(): Condition {
  return { kind: "template", templates: [], scene: "lobby", appear: true, wait: 0 };
}

export function newStep(type: StepType): Step {
  const base = { id: newId(), note: "" };
  switch (type) {
    case "tap_template":
      return { ...base, type, template: "", timeout: 5, on_missing: "stop", settle: true };
    case "tap_point":
      return { ...base, type, x: 800, y: 450 };
    case "swipe":
      return { ...base, type, x1: 1200, y1: 450, x2: 400, y2: 450, duration: 0.4 };
    case "back":
      return { ...base, type };
    case "wait":
      return { ...base, type, seconds: 1 };
    case "wait_still":
      return { ...base, type, timeout: 5 };
    case "wait_template":
      return { ...base, type, templates: [], appear: true, timeout: 10, on_missing: "stop" };
    case "wait_scene":
      return { ...base, type, scene: "lobby", timeout: 15, on_missing: "stop" };
    case "end":
      return { ...base, type, success: true, message: "" };
    case "break":
      return { ...base, type };
    case "if":
      return { ...base, type, condition: newCondition(), then: [], else: [] };
    case "repeat":
      return { ...base, type, mode: "times", count: 3, condition: null, on_limit: "stop", body: [] };
  }
}

export function newFlow(name = "新流程"): Flow {
  return { version: 1, id: "", name, description: "", limits: { max_minutes: 10, max_taps: 200 }, steps: [], created: null, updated: null };
}

// ---------------------------------------------------------------- 树操作

export interface ListAddr {
  parent: string | null;
  branch: Branch | null;
}

export const ROOT: ListAddr = { parent: null, branch: null };

export function childLists(step: Step): [Branch, Step[]][] {
  if (step.type === "if") return [["then", step.then], ["else", step.else]];
  if (step.type === "repeat") return [["body", step.body]];
  return [];
}

function withList(step: Step, branch: Branch, list: Step[]): Step {
  if (step.type === "if" && (branch === "then" || branch === "else")) return { ...step, [branch]: list };
  if (step.type === "repeat" && branch === "body") return { ...step, body: list };
  return step;
}

/** 对每个列表（含顶层）做变换，返回新树。fn 拿到列表地址和列表。 */
function mapLists(steps: Step[], fn: (addr: ListAddr, list: Step[]) => Step[], addr: ListAddr = ROOT): Step[] {
  const mapped = steps.map((s) => {
    let out = s;
    for (const [branch, list] of childLists(s)) out = withList(out, branch, mapLists(list, fn, { parent: s.id, branch }));
    return out;
  });
  return fn(addr, mapped);
}

export function findStep(steps: Step[], id: string, addr: ListAddr = ROOT): { step: Step; addr: ListAddr; index: number } | null {
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (s.id === id) return { step: s, addr, index: i };
    for (const [branch, list] of childLists(s)) {
      const hit = findStep(list, id, { parent: s.id, branch });
      if (hit) return hit;
    }
  }
  return null;
}

export function getList(steps: Step[], addr: ListAddr): Step[] | null {
  if (addr.parent === null) return steps;
  const hit = findStep(steps, addr.parent);
  if (!hit) return null;
  const found = childLists(hit.step).find(([b]) => b === addr.branch);
  return found ? found[1] : null;
}

const same = (a: ListAddr, b: ListAddr) => a.parent === b.parent && a.branch === b.branch;

export function updateStep(steps: Step[], id: string, fn: (s: Step) => Step): Step[] {
  return mapLists(steps, (_, list) => (list.some((s) => s.id === id) ? list.map((s) => (s.id === id ? fn(s) : s)) : list));
}

export function removeStep(steps: Step[], id: string): Step[] {
  return mapLists(steps, (_, list) => list.filter((s) => s.id !== id));
}

export function insertStep(steps: Step[], addr: ListAddr, index: number, step: Step): Step[] {
  return mapLists(steps, (a, list) => {
    if (!same(a, addr)) return list;
    const out = list.slice();
    out.splice(Math.max(0, Math.min(index, out.length)), 0, step);
    return out;
  });
}

/** 步骤 id 自己或它的子孙是不是 addr 的父步骤（不能把步骤拖进自己里面）。 */
export function containsList(step: Step, addr: ListAddr): boolean {
  if (addr.parent === null) return false;
  if (step.id === addr.parent) return true;
  return childLists(step).some(([, list]) => list.some((s) => containsList(s, addr)));
}

/** 把步骤移到 addr 列表的 index 位置（index 按移动前的列表算）。不合法时原样返回。 */
export function moveStep(steps: Step[], id: string, addr: ListAddr, index: number): Step[] {
  const hit = findStep(steps, id);
  if (!hit || containsList(hit.step, addr) || !getList(steps, addr)) return steps;
  let to = index;
  if (same(hit.addr, addr)) {
    if (index === hit.index || index === hit.index + 1) return steps;
    if (index > hit.index) to -= 1;
  }
  return insertStep(removeStep(steps, id), addr, to, hit.step);
}

/** 深拷贝一步（含子步骤），全部换新 id。 */
export function cloneStep(step: Step): Step {
  const copy = { ...step, id: newId() } as Step;
  if (copy.type === "if") return { ...copy, then: copy.then.map(cloneStep), else: copy.else.map(cloneStep) };
  if (copy.type === "repeat") return { ...copy, body: copy.body.map(cloneStep) };
  return copy;
}

export function duplicateStep(steps: Step[], id: string): Step[] {
  const hit = findStep(steps, id);
  return hit ? insertStep(steps, hit.addr, hit.index + 1, cloneStep(hit.step)) : steps;
}

/** 步骤编号（和引擎日志一致）：顶层 1、2；「如果」先编「那么」再接着编「否则」；循环体 3.1、3.2。 */
export function numbering(steps: Step[], prefix = "", start = 1, out = new Map<string, string>()): Map<string, string> {
  steps.forEach((s, i) => {
    const path = `${prefix}${start + i}`;
    out.set(s.id, path);
    if (s.type === "if") {
      numbering(s.then, `${path}.`, 1, out);
      numbering(s.else, `${path}.`, s.then.length + 1, out);
    } else if (s.type === "repeat") {
      numbering(s.body, `${path}.`, 1, out);
    }
  });
  return out;
}

export function forEachStep(steps: Step[], fn: (s: Step) => void): void {
  for (const s of steps) {
    fn(s);
    for (const [, list] of childLists(s)) forEachStep(list, fn);
  }
}

/** 起作用的条件：「如果」的条件，「重复直到 / 当…时重复」的条件（「重复 N 次」没有条件）。 */
export function activeCondition(s: Step): Condition | null {
  if (s.type === "if") return s.condition;
  if (s.type === "repeat" && s.mode !== "times") return s.condition;
  return null;
}

/** 一步用到的模板。 */
export function stepRefs(s: Step): string[] {
  if (s.type === "tap_template") return s.template ? [s.template] : [];
  if (s.type === "wait_template") return s.templates;
  const cond = activeCondition(s);
  return cond?.kind === "template" ? cond.templates : [];
}

/** pydantic 的英文校验信息 → 中文（常见的几种）。 */
export function zhMessage(msg: string): string {
  return msg
    .replace(/^Value error, /, "")
    .replace(/Input should be less than or equal to ([\d.]+)/, "不能大于 $1")
    .replace(/Input should be greater than or equal to ([\d.]+)/, "不能小于 $1")
    .replace(/Input should be greater than ([\d.]+)/, "要大于 $1")
    .replace(/String should have at least \d+ characters?/, "不能为空")
    .replace(/String should have at most (\d+) characters/, "最多 $1 个字")
    .replace(/List should have at least \d+ items?/, "至少要选一个")
    .replace(/List should have at most (\d+) items/, "最多 $1 个");
}

export function countSteps(steps: Step[]): number {
  return steps.reduce((n, s) => n + 1 + childLists(s).reduce((m, [, l]) => m + countSteps(l), 0), 0);
}

export function templateRefs(steps: Step[]): Set<string> {
  const out = new Set<string>();
  forEachStep(steps, (s) => stepRefs(s).forEach((r) => out.add(r)));
  return out;
}

// ---------------------------------------------------------------- 文字

export type TemplateLabel = (ref: string) => string;
const plainLabel: TemplateLabel = (ref) => (ref.startsWith(COMMON_PREFIX) ? ref.slice(COMMON_PREFIX.length) : ref);

const quote = (refs: string[], label: TemplateLabel) => (refs.length ? refs.map((r) => `「${label(r)}」`).join("或") : "「未选模板」");

export function describeCondition(c: Condition | null, label: TemplateLabel = plainLabel): string {
  if (!c) return "";
  const what = c.kind === "scene"
    ? `${c.appear ? "在" : "不在"}「${SCENES[c.scene ?? ""] ?? c.scene}」`
    : `${quote(c.templates, label)}${c.appear ? "出现" : "不出现"}`;
  return c.wait > 0 ? `${what}（最多等 ${c.wait} 秒）` : what;
}

/** 一步的中文摘要（编辑器卡片上显示）。 */
export function describeStep(s: Step, label: TemplateLabel = plainLabel): string {
  switch (s.type) {
    case "tap_template":
      return `点击${quote(s.template ? [s.template] : [], label)}`;
    case "tap_point":
      return `点击坐标 (${s.x}, ${s.y})`;
    case "swipe":
      return `从 (${s.x1}, ${s.y1}) 滑到 (${s.x2}, ${s.y2})`;
    case "back":
      return "按返回键";
    case "wait":
      return `等待 ${s.seconds} 秒`;
    case "wait_still":
      return `等画面静止（最多 ${s.timeout} 秒）`;
    case "wait_template":
      return `等${quote(s.templates, label)}${s.appear ? "出现" : "消失"}（最多 ${s.timeout} 秒）`;
    case "wait_scene":
      return `等回到「${SCENES[s.scene] ?? s.scene}」（最多 ${s.timeout} 秒）`;
    case "end":
      return s.success ? "结束流程（成功）" : "结束流程（失败）";
    case "break":
      return "跳出循环";
    case "if":
      return `如果 ${describeCondition(s.condition, label)}`;
    case "repeat":
      if (s.mode === "times") return `重复 ${s.count} 次`;
      return `${s.mode === "until" ? "重复直到" : "一直重复，当"} ${describeCondition(s.condition, label)}（最多 ${s.count} 轮）`;
  }
}

/** 本地检查（保存前提示，引擎还会再校验一遍）：步骤 id → 问题。 */
export function localProblems(steps: Step[], inLoop = false, out = new Map<string, string>()): Map<string, string> {
  for (const s of steps) {
    if (s.type === "break" && !inLoop) out.set(s.id, "「跳出循环」只能放在循环里");
    if (s.type === "tap_template" && !s.template) out.set(s.id, "还没选模板");
    if (s.type === "wait_template" && s.templates.length === 0) out.set(s.id, "还没选模板");
    const cond = activeCondition(s);
    if (cond && cond.kind === "template" && cond.templates.length === 0) {
      out.set(s.id, "条件里还没选模板");
    }
    if (s.type === "if") {
      localProblems(s.then, inLoop, out);
      localProblems(s.else, inLoop, out);
    } else if (s.type === "repeat") {
      localProblems(s.body, true, out);
    }
  }
  return out;
}

/** 引擎返回的校验错误位置（pydantic loc）→ 出错的步骤 id。 */
export function locateError(steps: Step[], loc: (string | number)[]): string | null {
  let list = null as Step[] | null;
  let cur = null as Step | null;
  let found = null as string | null;
  for (const tok of loc) {
    if (tok === "steps" && list === null && cur === null) {
      list = steps;
    } else if (typeof tok === "number" && list) {
      cur = list[tok] ?? null;
      if (!cur) break;
      found = cur.id;
      list = null;
    } else if (cur && tok === cur.type) {
      continue;
    } else if (cur && (tok === "then" || tok === "else" || tok === "else_" || tok === "body")) {
      const branch = tok === "else_" ? "else" : tok;
      list = childLists(cur).find(([b]) => b === branch)?.[1] ?? null;
      if (!list) break;
    } else {
      break;
    }
  }
  return found;
}
