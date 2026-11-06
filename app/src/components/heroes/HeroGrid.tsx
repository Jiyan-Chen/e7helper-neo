// 英雄头像、筛选条和头像网格：英雄图鉴（B13）和 RTA 助手（B14e1）共用。
import { Check, Search } from "lucide-react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { gameIcon } from "@/lib/gameIcons";
import { ELEMENT_COLORS, ELEMENTS, RARITIES, ROLES, type Hero, type HeroFilter, type HeroList } from "@/lib/heroes";
import { cn } from "@/lib/utils";

/**
 * 头像：属性色的边框，右下角是属性图标（游戏里截的；没有时是写着属性的色块）。没有头像时显示名字的第一个字。
 * plain = 不画右下角的属性图标（推荐卡等小头像）。
 */
export function HeroIcon({ hero, data, size, plain, className }: {
  hero: Hero;
  data: HeroList;
  size: number;
  plain?: boolean;
  className?: string;
}) {
  const color = ELEMENT_COLORS[hero.element] ?? "#888";
  const elementIcon = gameIcon(`element_${hero.element}`);
  const radius = Math.max(4, Math.round(size / 6));
  return (
    <span className={cn("relative flex-none bg-black/40", size >= 40 ? "border-2" : "border", className)}
      style={{ width: size, height: size, borderColor: color, borderRadius: radius }}>
      {hero.icon ? (
        <img src={api().heroIconUrl(hero.code, data.updated)} alt="" loading="lazy" draggable={false}
          className="size-full object-cover" style={{ borderRadius: radius - 2 }} />
      ) : (
        <span className="grid size-full place-items-center font-bold text-muted" style={{ fontSize: size * 0.33 }}>
          {hero.name.slice(0, 1)}
        </span>
      )}
      {plain ? null : elementIcon ? (
        <img src={elementIcon} alt={data.labels.element[hero.element]} draggable={false}
          className="absolute -right-2 -bottom-2 size-6 drop-shadow-[0_1px_2px_rgba(0,0,0,.8)]" />
      ) : (
        <span className="absolute -right-1.5 -bottom-1.5 grid size-5 place-items-center rounded-full border border-black/50 text-[11px] font-bold text-black"
          style={{ background: color }} aria-label={data.labels.element[hero.element]}>
          {data.labels.element[hero.element]}
        </span>
      )}
    </span>
  );
}

/**
 * 一行筛选按钮。iconOnly：只画图标（名字放在鼠标提示里），没有「全部」，再点一次取消。
 * shrink：窗口不到 1200 宽时有图标的按钮只画图标（B14e2 英雄池模式，右边有一栏，放不下一行）。
 */
export function FilterRow<T extends string | number>({ label, value, options, onChange, iconOnly, shrink }: {
  label: string;
  value: T | null;
  options: { value: T; label: string; color?: string; icon?: string }[];
  onChange: (v: T | null) => void;
  iconOnly?: boolean;
  shrink?: boolean;
}) {
  if (iconOnly) {
    return (
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label={label}>
        {options.map((o) => (
          <button key={o.value} type="button" title={o.label} aria-label={o.label} aria-pressed={value === o.value}
            className={cn("tab grid size-8 place-items-center p-0", value === o.value && "active")}
            onClick={() => onChange(value === o.value ? null : o.value)}>
            {o.icon ? <img src={o.icon} alt="" className="size-5" draggable={false} />
              : <span className="size-2.5 rounded-full" style={{ background: o.color }} />}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={label}>
      <span className="w-10 text-sm text-muted">{label}</span>
      <button type="button" className={cn("tab", value === null && "active")} onClick={() => onChange(null)}>全部</button>
      {options.map((o) => (
        <button key={o.value} type="button" className={cn("tab inline-flex items-center gap-1.5", value === o.value && "active")}
          title={shrink ? o.label : undefined} onClick={() => onChange(value === o.value ? null : o.value)}>
          {o.icon ? <img src={o.icon} alt="" className="size-4" draggable={false} />
            : o.color && <span className="size-2 rounded-full" style={{ background: o.color }} />}
          <span className={cn(shrink && (o.icon || o.color) && "max-[1199px]:sr-only")}>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

/**
 * 搜索框 + 属性 / 职业（/ 星级）筛选。onEnter：在搜索框里按 Enter；compact：窄栏用，属性和职业只画图标；
 * shrink：窗口不到 1200 宽时属性和职业只画图标。
 */
export function HeroFilters({ data, filter, onChange, rarity = true, onEnter, inputWidth = "w-72", compact, shrink, children }: {
  data: HeroList;
  filter: HeroFilter;
  onChange: (patch: Partial<HeroFilter>) => void;
  rarity?: boolean;
  onEnter?: () => void;
  inputWidth?: string;
  compact?: boolean;
  shrink?: boolean;
  /** 搜索框右边的内容（例如「x / y 名」） */
  children?: ReactNode;
}) {
  const rows = (
    <>
      <FilterRow label="属性" value={filter.element} iconOnly={compact} shrink={shrink}
        options={ELEMENTS.map((e) => ({ value: e, label: data.labels.element[e] ?? e, color: ELEMENT_COLORS[e], icon: gameIcon(`element_${e}`) }))}
        onChange={(element) => onChange({ element })} />
      <FilterRow label="职业" value={filter.role} iconOnly={compact} shrink={shrink}
        options={ROLES.map((r) => ({ value: r, label: data.labels.role[r] ?? r, icon: gameIcon(`role_${r}`) }))}
        onChange={(role) => onChange({ role })} />
    </>
  );
  return (
    <>
      <div className={cn("flex items-center gap-3", compact && "flex-wrap gap-y-1")}>
        <label className={cn("relative", compact && "w-full")}>
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint" />
          <input className={cn("field pl-8", inputWidth)} placeholder="搜索名字" aria-label="搜索英雄" value={filter.query}
            onChange={(e) => onChange({ query: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === "Enter" && onEnter) onEnter();
              if (e.key === "Escape") onChange({ query: "" });
            }} />
        </label>
        {children}
      </div>
      {rows}
      {rarity && (
        <FilterRow label="星级" value={filter.rarity} options={RARITIES.map((r) => ({ value: r, label: `${r} 星` }))}
          onChange={(rarity) => onChange({ rarity })} />
      )}
    </>
  );
}

/** 英雄池里的英雄（B14e2）：网格一格右上角的金色小勾。 */
export function PoolMark({ size = 18 }: { size?: number }) {
  return (
    <span className="pointer-events-none absolute top-0.5 right-1 grid place-items-center rounded-full bg-gold text-black shadow"
      style={{ width: size, height: size }} aria-label="英雄池">
      <Check style={{ width: size * 0.65, height: size * 0.65 }} strokeWidth={3.5} />
    </span>
  );
}

/** 网格里一格的附加状态（RTA 助手：不能选的变灰、推荐名次角标；英雄池：勾选）。 */
export interface HeroCellDecor {
  disabled?: boolean;
  /** 角标（推荐名次在左上、英雄池的勾在右上） */
  badge?: ReactNode;
  /** 金色描边 */
  highlight?: boolean;
  title?: string;
}

/** 头像网格（头像 + 名字），点一格调用 onPick。 */
export function HeroGrid({ heroes, data, onPick, size = 60, decor }: {
  heroes: Hero[];
  data: HeroList;
  onPick: (h: Hero) => void;
  size?: number;
  decor?: (h: Hero) => HeroCellDecor | undefined;
}) {
  return (
    <div className="grid gap-x-1 gap-y-0.5" style={{ gridTemplateColumns: `repeat(auto-fill, ${size + 14}px)` }}>
      {heroes.map((h) => {
        const d = decor?.(h);
        return (
          <button key={h.code} type="button" title={d?.title ?? h.name} disabled={d?.disabled} onClick={() => onPick(h)}
            className={cn("relative flex cursor-pointer flex-col items-center gap-1 rounded-lg px-0.5 py-1 transition-colors hover:bg-white/6",
              d?.disabled && "cursor-default opacity-30 grayscale hover:bg-transparent",
              d?.highlight && "bg-gold/12 ring-1 ring-gold/70")}>
            <HeroIcon hero={h} data={data} size={size} />
            <span className="line-clamp-2 h-[2.5em] text-center text-[11px] leading-tight">{h.name}</span>
            {d?.badge}
          </button>
        );
      })}
    </div>
  );
}
