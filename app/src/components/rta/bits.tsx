// RTA 助手（B14e1）的小部件：按编号画英雄头像、段位图标、分段按钮、胜率数字、标记。
import { Loader2, Shield } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";
import { HeroIcon } from "@/components/heroes/HeroGrid";
import { GRADE_CHOICES } from "@/lib/draft";
import { gameIcon } from "@/lib/gameIcons";
import type { Hero, HeroList } from "@/lib/heroes";
import { pct1 } from "@/lib/rta";
import { cn } from "@/lib/utils";

export const HeroesCtx = createContext<{ data: HeroList; byCode: Map<string, Hero> } | null>(null);

export function useHeroes() {
  const c = useContext(HeroesCtx);
  if (!c) throw new Error("HeroesCtx 没有提供");
  return c;
}

/** 编号 → 中文名（图鉴里没有的显示编号）。 */
export function useName() {
  const { byCode } = useHeroes();
  return (code: string) => byCode.get(code)?.name ?? code;
}

/** 按编号画头像；shield = 右上角的保护位标记。 */
export function Face({ code, size, shield, className }: { code: string; size: number; shield?: boolean; className?: string }) {
  const { data, byCode } = useHeroes();
  const h = byCode.get(code);
  return (
    <span className={cn("relative inline-flex flex-none", className)} title={h?.name ?? code}>
      {h ? (
        <HeroIcon hero={h} data={data} size={size} plain />
      ) : (
        <span className="grid place-items-center rounded-md border border-white/20 bg-black/40 text-[10px] text-muted" style={{ width: size, height: size }}>
          ?
        </span>
      )}
      {shield && <ShieldMark className="absolute -top-1.5 -right-1.5" />}
    </span>
  );
}

export function ShieldMark({ className }: { className?: string }) {
  return <Shield className={cn("size-4 fill-[#1b2234] text-gold drop-shadow-[0_1px_2px_rgba(0,0,0,.8)]", className)} aria-label="保护位" />;
}

/** 一组头像（两手回合的一对）。 */
export function Faces({ codes, size, shield }: { codes: string[]; size: number; shield?: string | null }) {
  return (
    <span className="inline-flex flex-none gap-1">
      {codes.map((c) => <Face key={c} code={c} size={size} shield={c === shield} />)}
    </span>
  );
}

/** 我方胜率：高的绿、低的红。 */
export function Win({ p, className }: { p: number; className?: string }) {
  return <span className={cn("num", p >= 0.55 ? "text-ok" : p <= 0.45 ? "text-bad" : "text-ink", className)}>{pct1(p)}</span>;
}

export function Tag({ children, tone = "muted", title }: { children: ReactNode; tone?: "muted" | "warn" | "gold"; title?: string }) {
  return (
    <span title={title} className={cn("rounded border px-1.5 text-[11px] leading-[18px] whitespace-nowrap",
      tone === "warn" ? "border-warn/40 text-warn" : tone === "gold" ? "border-gold/60 text-gold" : "border-white/15 text-muted")}>
      {children}
    </span>
  );
}

export function Spinner({ label = "计算中…" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <Loader2 className="size-3.5 animate-spin" />
      {label}
    </span>
  );
}

/** 推荐名次的小圆角标（英雄网格左上角）。 */
export function RankBadge({ n, tone = "gold" }: { n: number; tone?: "gold" | "blue" }) {
  return (
    <span className={cn("absolute top-0.5 left-1 grid size-[18px] place-items-center rounded-full text-[11px] font-bold shadow",
      tone === "gold" ? "bg-gold text-black" : "bg-blue text-white")}>
      {n}
    </span>
  );
}

/** 英雄的属性和职业图标（阵容格子里名字下面）。 */
export function HeroBadges({ code }: { code: string }) {
  const { data, byCode } = useHeroes();
  const h = byCode.get(code);
  if (!h) return null;
  const icons = [
    { src: gameIcon(`element_${h.element}`), label: data.labels.element[h.element] },
    { src: gameIcon(`role_${h.role}`), label: data.labels.role[h.role] },
  ];
  return (
    <span className="inline-flex items-center gap-0.5">
      {icons.map((i) => i.src && <img key={i.src} src={i.src} alt={i.label} title={i.label} className="size-4" draggable={false} />)}
    </span>
  );
}

export const gradeLabel = (code: string) => GRADE_CHOICES.find((g) => g.code === code)?.label ?? code;

/** 段位图标（游戏里截的 rank_<段位>.png；还没有时写段位名）。 */
export function RankIcon({ code, size }: { code: string; size: number }) {
  const icon = gameIcon(`rank_${code}`);
  const label = gradeLabel(code);
  if (icon) return <img src={icon} alt={label} title={label} className="flex-none object-contain" style={{ width: size, height: size }} draggable={false} />;
  return (
    <span title={label} className="grid flex-none place-items-center rounded-md border border-white/15 bg-black/30 text-center leading-tight text-muted"
      style={{ width: size, height: size, fontSize: Math.max(10, Math.round(size / 4.2)) }}>
      {label.replace("及以下", "")}
    </span>
  );
}

/** 分段按钮（准备里的开战规则、先后手）。 */
export function Segmented<T extends string>({ label, value, options, onChange, disabled }: {
  label: string;
  value: T;
  options: { value: T; label: string; title?: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} aria-disabled={disabled}
      className={cn("inline-flex flex-wrap gap-1 self-start rounded-xl border border-white/10 bg-black/30 p-1", disabled && "pointer-events-none opacity-35")}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value} title={o.title} disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn("cursor-pointer rounded-lg border px-4 py-1.5 text-sm transition-colors",
            o.value === value ? "border-glow bg-gradient-to-b from-blue/80 to-blue/45 font-bold text-white" : "border-transparent text-muted hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
