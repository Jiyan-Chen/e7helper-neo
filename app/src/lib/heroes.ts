// 英雄图鉴（B13）：数据形状和筛选 / 排序。数据来自引擎 GET /api/heroes。

export interface Hero {
  code: string;
  /** 国服中文名 */
  name: string;
  name_en: string;
  aliases: string[];
  element: string;
  role: string;
  rarity: number;
  zodiac: string;
  /** 60 级 6 星满觉醒的基础属性（不含装备） */
  stats: Record<string, number>;
  slug: string;
  /** 发布日期 YYYY-MM-DD，没有的为空 */
  released: string;
  icon: boolean;
}

/** 富文本：段落 → 片段，hl 是游戏里高亮的词 */
export type RichText = { text: string; hl?: boolean }[][];

export interface HeroEffect {
  name: string;
  type: string;
  icon: string;
  description: RichText;
}

export interface HeroSkill {
  slot: number;
  name: string;
  icon: string;
  soul_gain: number;
  cooldown: RichText;
  description: RichText;
  soul_burn: { cost: number; description: RichText } | null;
  effects: HeroEffect[];
  enhancements: RichText[];
  multipliers: { label: string; items: { label: string; value: string }[] }[];
  exclusive: RichText[];
}

export interface Devotion {
  type: string;
  grades: Record<string, number>;
}

export interface HeroDetail {
  code: string;
  subtitle: string;
  release_date: string;
  self_devotion: Devotion | null;
  devotion: Devotion | null;
  /** 群阵影响的位置，例如 "14"（1 右、2 下、3 上、4 左） */
  devotion_slot: string;
  skills: HeroSkill[];
  exclusive: {
    name: string;
    icon: string;
    main_stat: { type?: string; min?: number; max?: number };
    /** 三选一的效果：index 第几个选项，slot 作用于第几个技能 */
    effects: { index: number; slot: number; description: RichText }[];
  } | null;
}

export interface BuildArtifact {
  code: string;
  name: string;
  count: number;
  share: number;
}

export interface HeroBuilds {
  total: number;
  latest: string;
  fetched: number;
  stale?: boolean;
  stats: Record<string, number>;
  artifacts: BuildArtifact[];
  combos: {
    sets: { set: string; pieces: number }[];
    count: number;
    share: number;
    speed_set: boolean;
    /** 带速度套：top10 / top25 / all（速度最快的前 10%、前 25% 和全部）；不带：fast / mid / slow（按速度三等分）；份数太少时为空 */
    tiers: { tier: string; count: number; stats: Record<string, number> }[];
    /** 属性中位数 */
    stats: Record<string, number>;
    artifacts: BuildArtifact[];
  }[];
}

export interface HeroList {
  source: string;
  origin: "bundled" | "user" | "";
  updated: string;
  count: number;
  labels: {
    element: Record<string, string>;
    role: Record<string, string>;
    zodiac: Record<string, string>;
    set: Record<string, string>;
    stat: Record<string, string>;
    percent_stats: string[];
  };
  heroes: Hero[];
}

export interface HeroUpdateResult {
  changed: boolean;
  total: number;
  added: string[];
  removed: string[];
  modified: string[];
  icons: number;
  icon_failed: string[];
  missing_names: string[];
  details: number;
  detail_icons: number;
  detail_failed: string[];
  wiki_error: string;
  updated: string;
  count: number;
}

export const ELEMENTS = ["fire", "ice", "wind", "light", "dark"] as const;
export const ROLES = ["warrior", "knight", "assassin", "ranger", "mage", "manauser"] as const;
export const RARITIES = [5, 4, 3] as const;

/** 属性的颜色（头像框、筛选按钮） */
export const ELEMENT_COLORS: Record<string, string> = {
  fire: "#ff7a52",
  ice: "#5cc4ff",
  wind: "#79d860",
  light: "#ffd768",
  dark: "#b88cff",
};

/** 详情里显示的属性（叫法同游戏简中） */
export const STAT_ROWS: { key: string; label: string; percent?: boolean }[] = [
  { key: "cp", label: "战斗力" },
  { key: "atk", label: "攻击力" },
  { key: "def", label: "防御力" },
  { key: "hp", label: "生命值" },
  { key: "spd", label: "速度" },
  { key: "chc", label: "暴击率", percent: true },
  { key: "chd", label: "暴击伤害", percent: true },
  { key: "eff", label: "效果命中", percent: true },
  { key: "efr", label: "效果抗性", percent: true },
  { key: "dac", label: "夹攻率", percent: true },
];

/** 配装统计里的属性（暴击率等已经是百分数；装备均分 = 6 件装备的平均分） */
export const BUILD_STATS: { key: string; label: string; percent?: boolean }[] = [
  { key: "atk", label: "攻击力" },
  { key: "def", label: "防御力" },
  { key: "hp", label: "生命值" },
  { key: "spd", label: "速度" },
  { key: "chc", label: "暴击率", percent: true },
  { key: "chd", label: "暴击伤害", percent: true },
  { key: "eff", label: "效果命中", percent: true },
  { key: "efr", label: "效果抗性", percent: true },
  { key: "gear", label: "装备均分" },
];

/** 角色奉献 / 专属装备的数值：百分比类型显示成 12%，其他显示整数 */
export function formatDevotion(type: string, value: number | undefined, percentStats: string[]): string {
  if (value === undefined) return "—";
  if (percentStats.includes(type)) return `${+(value * 100).toFixed(1)}%`;
  return String(Math.round(value));
}

export const pct = (share: number) => `${+(share * 100).toFixed(1)}%`;

export function formatStat(value: number | undefined, percent = false): string {
  if (value === undefined) return "—";
  if (percent) return `${Math.round(value * 100)}%`;
  return Math.round(value).toLocaleString("en-US");
}

/** 名字比对用的键：去空白、全角转半角、忽略大小写和间隔号（同引擎 name_key）。 */
export function nameKey(text: string): string {
  return text
    .replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/[\s·・•.\-'’]/g, "")
    .toLowerCase();
}

export interface HeroFilter {
  query: string;
  element: string | null;
  role: string | null;
  rarity: number | null;
}

/** 搜索命中的程度：0 完全一致、1 开头一致、2 包含；不命中返回 null。 */
function matchRank(h: Hero, key: string): number | null {
  let best: number | null = null;
  for (const k of [h.name, h.name_en, h.code, ...h.aliases].map(nameKey)) {
    if (k === key) return 0;
    if (k.startsWith(key)) best = 1;
    else if (best === null && k.includes(key)) best = 2;
  }
  return best;
}

/** 按条件筛选。按发布日期新的在前（没有日期的排最后，同一天按编号大的在前）；有搜索词时先按命中程度。 */
const cmpDesc = (a: string, b: string) => (a < b ? 1 : a > b ? -1 : 0);

export function filterHeroes(heroes: Hero[], f: HeroFilter): Hero[] {
  const key = nameKey(f.query);
  const ranked: { h: Hero; rank: number }[] = [];
  for (const h of heroes) {
    if (f.element && h.element !== f.element) continue;
    if (f.role && h.role !== f.role) continue;
    if (f.rarity && h.rarity !== f.rarity) continue;
    const rank = key ? matchRank(h, key) : 0;
    if (rank !== null) ranked.push({ h, rank });
  }
  ranked.sort((a, b) => a.rank - b.rank || cmpDesc(a.h.released, b.h.released) || cmpDesc(a.h.code, b.h.code));
  return ranked.map((r) => r.h);
}
