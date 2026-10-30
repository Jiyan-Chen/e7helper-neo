// RTA 助手（B14e1）的局面：五步（准备 / 预禁 / 选秀 / 后禁 / 结果）、选人顺序和保护位、转成引擎接口的格式。
// 规则同引擎 core/rta/rules.py：先手 F、后手 S，选人顺序 1-2-2-2-2-1，每边按顺序的第 3 手是保护位（不能被后禁），
// 预禁每边 2 名（可以和对方重复，被预禁的双方都不能选），选完后双方各禁对方 1 名。
// 页面里按「我方 / 对方」记，发给引擎时再换成先手 / 后手。

export type Side = "F" | "S";
export type Team = "mine" | "theirs";
export type Step = "setup" | "preban" | "pick" | "ban" | "result";

export const PICK_ORDER: readonly Side[] = ["F", "S", "S", "F", "F", "S", "S", "F", "F", "S"];
export const PICKS = PICK_ORDER.length;
export const PREBANS = 2;
/** 每边按顺序的第 3 手（下标 2）是保护位 */
export const PROTECTED = 2;
export const UNKNOWN_RULE = "unknown";

export const STEPS: { key: Step; label: string }[] = [
  { key: "setup", label: "准备" },
  { key: "preban", label: "预禁" },
  { key: "pick", label: "选秀" },
  { key: "ban", label: "后禁" },
  { key: "result", label: "结果" },
];

/**
 * 准备里能选的段位（同 e7rtabot，用户意见）：挑战者及以下合成一项（发给引擎按挑战者算），优胜者以上各一项。从低到高；
 * icon 是游戏里的段位图标（`assets/game/rank_<code>.png`，从游戏截图裁）。
 */
export const GRADE_CHOICES: readonly { code: string; label: string }[] = [
  { code: "challenger", label: "挑战者及以下" },
  { code: "champion", label: "优胜者" },
  { code: "warlord", label: "战神" },
  { code: "emperor", label: "王者" },
  { code: "legend", label: "传说" },
];
/** 有开战规则的最低段位 */
export const RULE_MIN_GRADE = "champion";
const LOW_GRADES = ["bronze", "silver", "gold", "master", "challenger"];

/** 任意段位（包括旧版本存下的、不知道的）→ 准备里的一项；不认识的按传说。 */
export function gradeChoice(grade: string | null | undefined): string {
  if (grade && LOW_GRADES.includes(grade)) return "challenger";
  return GRADE_CHOICES.some((g) => g.code === grade) ? (grade as string) : "legend";
}

export interface Setup {
  /** 我方是先手 F 还是后手 S */
  side: Side;
  /** [我方, 对方] 的段位（GRADE_CHOICES 里的一项） */
  grades: [string, string];
  /** 开战规则（opening_rule_desc_tid）；双方都在优胜者以上才有，那时玩家一定知道（用户意见），"unknown" = 还没选 */
  rule: string;
}

export interface Draft {
  setup: Setup;
  /** 准备 → 预禁 → 选秀（选秀、后禁、结果按已填的内容判断） */
  phase: "setup" | "preban" | "draft";
  prebans: Record<Team, string[]>;
  /** 整局按顺序的选人（最多 10 手），第 i 手是 PICK_ORDER[i] 那一方的 */
  picks: string[];
  /** mine = 我方禁掉的对方英雄；theirs = 对方禁掉的我方英雄 */
  bans: Record<Team, string | null>;
}

export const DEFAULT_SETUP: Setup = { side: "F", grades: ["legend", "legend"], rule: UNKNOWN_RULE };

export function newDraft(setup: Setup = DEFAULT_SETUP): Draft {
  return { setup, phase: "setup", prebans: { mine: [], theirs: [] }, picks: [], bans: { mine: null, theirs: null } };
}

export const other = (t: Team): Team => (t === "mine" ? "theirs" : "mine");
export const sideOf = (team: Team, my: Side): Side => (team === "mine" ? my : my === "F" ? "S" : "F");
export const teamOf = (side: Side, my: Side): Team => (side === my ? "mine" : "theirs");

/** 这一队 5 个位置各是整局的第几手（从 1 数），例如先手方是 1、4、5、8、9。 */
export function pickNumbers(team: Team, my: Side): number[] {
  const side = sideOf(team, my);
  return PICK_ORDER.flatMap((s, i) => (s === side ? [i + 1] : []));
}

/** 这一队按顺序已选的英雄。 */
export function teamPicks(d: Draft, team: Team): string[] {
  const side = sideOf(team, d.setup.side);
  return d.picks.filter((_, i) => PICK_ORDER[i] === side);
}

/** 已经选了 n 手时，下一手是哪一队、这一轮还要连选几名；选完返回 null。 */
export function turnAt(n: number, my: Side): { team: Team; slots: number } | null {
  if (n >= PICKS) return null;
  const side = PICK_ORDER[n];
  let slots = 0;
  while (n + slots < PICKS && PICK_ORDER[n + slots] === side) slots++;
  return { team: teamOf(side, my), slots };
}

export const turn = (d: Draft) => turnAt(d.picks.length, d.setup.side);

export function stepOf(d: Draft): Step {
  if (d.phase !== "draft") return d.phase;
  if (d.picks.length < PICKS) return "pick";
  return d.bans.mine && d.bans.theirs ? "result" : "ban";
}

/** 不能再选的英雄：双方预禁的 + 已经选走的。 */
export function taken(d: Draft): Set<string> {
  return new Set([...d.prebans.mine, ...d.prebans.theirs, ...d.picks]);
}

/** 预禁这一步点英雄时填给哪一队：先填满我方 2 名，再填对方；都满了返回 null。 */
export function prebanTarget(d: Draft): Team | null {
  if (d.prebans.mine.length < PREBANS) return "mine";
  if (d.prebans.theirs.length < PREBANS) return "theirs";
  return null;
}

export function addPreban(d: Draft, team: Team, code: string): Draft {
  const cur = d.prebans[team];
  if (d.phase !== "preban" || cur.length >= PREBANS || cur.includes(code)) return d;
  return { ...d, prebans: { ...d.prebans, [team]: [...cur, code] } };
}

export function removePreban(d: Draft, team: Team, code: string): Draft {
  if (d.phase !== "preban" || !d.prebans[team].includes(code)) return d;
  return { ...d, prebans: { ...d.prebans, [team]: d.prebans[team].filter((c) => c !== code) } };
}

/** 整组换掉一队的预禁（点了预禁推荐 / 对手常见的组合）。 */
export function setPrebans(d: Draft, team: Team, codes: string[]): Draft {
  if (d.phase !== "preban" || codes.length > PREBANS || new Set(codes).size !== codes.length) return d;
  return { ...d, prebans: { ...d.prebans, [team]: [...codes] } };
}

/**
 * 按顺序填入下一手（或这一轮的两手）。英雄都要能选、都属于当前这一轮、不超过这一轮剩下的位置；
 * team 给了时还要正好轮到这一队。不合法时原样返回。
 */
export function addPicks(d: Draft, codes: string[], team?: Team): Draft {
  const t = turn(d);
  if (stepOf(d) !== "pick" || !t || !codes.length || codes.length > t.slots) return d;
  if (team && team !== t.team) return d;
  const used = taken(d);
  if (new Set(codes).size !== codes.length || codes.some((c) => used.has(c))) return d;
  return { ...d, picks: [...d.picks, ...codes] };
}

/** team 这一队能禁的英雄：对方已选的、不在保护位的。 */
export function banOptions(d: Draft, team: Team): string[] {
  return teamPicks(d, other(team)).filter((_, i) => i !== PROTECTED);
}

/** team 这一队禁掉对方的 code；toggle 时再点同一名取消（点后禁矩阵的格子是直接设定，不取消）。 */
export function setBan(d: Draft, team: Team, code: string | null, toggle = true): Draft {
  if (d.phase !== "draft" || d.picks.length < PICKS) return d;
  if (code !== null && !banOptions(d, team).includes(code)) return d;
  const next = toggle && d.bans[team] === code ? null : code;
  return next === d.bans[team] ? d : { ...d, bans: { ...d.bans, [team]: next } };
}

/** 有没有开战规则：双方都不低于优胜者。 */
export function ruleApplies(grades: Setup["grades"]): boolean {
  const at = (g: string) => GRADE_CHOICES.findIndex((c) => c.code === g);
  const min = at(RULE_MIN_GRADE);
  return grades.every((g) => at(g) >= min);
}

/** 有开战规则、但还没选：准备这一步不能开始。 */
export function needsRule(setup: Setup): boolean {
  return ruleApplies(setup.grades) && setup.rule === UNKNOWN_RULE;
}

/** 发给引擎的开战规则：有规则时用准备里选的，否则按「不知道」（国服的训练数据都是这么记的）。 */
export function ruleFor(setup: Setup): string {
  return ruleApplies(setup.grades) ? setup.rule : UNKNOWN_RULE;
}

/** 引擎的局面格式（`DraftState.to_dict()`，按先手 F / 后手 S 分）。 */
export interface ApiState {
  prebans: Record<Side, string[]>;
  picks: Record<Side, string[]>;
  banned: Partial<Record<Side, string>>;
  grades: [string, string];
  rule: string;
}

/** 转成引擎接口的局面。后禁只在双方都填了才带上（只填了一边时还是按后禁前的局面算）。 */
export function apiState(d: Draft, rule: string): ApiState {
  const f: Team = d.setup.side === "F" ? "mine" : "theirs";
  const s = other(f);
  const banned: Partial<Record<Side, string>> = {};
  if (d.bans.mine && d.bans.theirs) {
    banned[sideOf("mine", d.setup.side)] = d.bans.theirs; // 我方被禁的那名 = 对方禁的
    banned[sideOf("theirs", d.setup.side)] = d.bans.mine;
  }
  const grade = (team: Team) => d.setup.grades[team === "mine" ? 0 : 1];
  return {
    prebans: { F: [...d.prebans[f]], S: [...d.prebans[s]] },
    picks: { F: teamPicks(d, f), S: teamPicks(d, s) },
    banned,
    grades: [grade(f), grade(s)],
    rule,
  };
}
