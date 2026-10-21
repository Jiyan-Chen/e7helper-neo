// 英雄详情（B13 审核后改版，参照 e7.wiki 的角色详情，860px 宽）：角色信息 / 技能详情 / 配装方案 三个页签（立绘不做，用户意见）。
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { gameIcon } from "@/lib/gameIcons";
import {
  BUILD_STATS, ELEMENT_COLORS, STAT_ROWS, formatDevotion, formatStat, pct,
  type Devotion, type Hero, type HeroBuilds, type HeroList, type HeroSkill, type RichText,
} from "@/lib/heroes";
import { qk } from "@/lib/query";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "info", label: "角色信息" },
  { id: "skills", label: "技能详情" },
  { id: "builds", label: "配装方案" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function HeroDetailDialog({ hero, data, onClose }: { hero: Hero | null; data: HeroList; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("info");
  return (
    <Dialog open={hero !== null} onOpenChange={(v) => { if (!v) { onClose(); setTab("info"); } }}
      title={hero?.name ?? ""} className="w-[860px]">
      {hero && (
        <div className="flex flex-col gap-4">
          <div className="flex gap-1.5" role="tablist">
            {TABS.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
                className={cn("tab px-4 py-1 text-[13px]", tab === t.id && "active")} onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
          {tab === "info" && <InfoTab hero={hero} data={data} />}
          {tab === "skills" && <SkillsTab hero={hero} />}
          {tab === "builds" && <BuildsTab hero={hero} data={data} />}
        </div>
      )}
    </Dialog>
  );
}

function useDetail(code: string) {
  return useQuery({ queryKey: qk.heroDetail(code), queryFn: () => api().heroDetail(code), staleTime: Infinity, retry: false });
}

/** 游戏里高亮（橙色加粗）的词 */
export function Rich({ text, className }: { text: RichText; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-1 text-sm leading-relaxed select-text", className)}>
      {text.map((para, i) => (
        <p key={i}>
          {para.map((seg, j) => (seg.hl ? <b key={j} className="text-[#f0a33c]">{seg.text}</b> : <span key={j}>{seg.text}</span>))}
        </p>
      ))}
    </div>
  );
}

function Section({ title, children, extra }: { title: string; children: ReactNode; extra?: ReactNode }) {
  return (
    <section className="rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
      <h4 className="panel-title mb-2.5 text-sm">{title}{extra}</h4>
      {children}
    </section>
  );
}

/** 属性 / 职业图标：有游戏图标用图标，没有用文字 */
export function GameBadge({ kind, value, label }: { kind: "element" | "role"; value: string; label: string }) {
  const src = gameIcon(`${kind}_${value}`);
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/12 bg-black/30 px-2.5 py-0.5 text-[13px]">
      {src ? <img src={src} alt="" className="size-4" draggable={false} />
        : kind === "element" && <span className="size-2 rounded-full" style={{ background: ELEMENT_COLORS[value] }} />}
      {label}
    </span>
  );
}

function InfoTab({ hero, data }: { hero: Hero; data: HeroList }) {
  const { data: det } = useDetail(hero.code);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4">
        <img src={api().heroIconUrl(hero.code, data.updated)} alt="" draggable={false}
          className="size-[88px] flex-none rounded-xl border-2 object-cover" style={{ borderColor: ELEMENT_COLORS[hero.element] }} />
        <div className="min-w-0 text-sm">
          <div className="text-muted select-text">{hero.name_en}</div>
          <div className="mt-0.5 text-gold">{"★".repeat(hero.rarity)}</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <GameBadge kind="element" value={hero.element} label={data.labels.element[hero.element] ?? hero.element} />
            <GameBadge kind="role" value={hero.role} label={data.labels.role[hero.role] ?? hero.role} />
            {hero.zodiac && <span className="rounded-full border border-white/12 bg-black/30 px-2.5 py-0.5 text-[13px]">{data.labels.zodiac[hero.zodiac] ?? hero.zodiac}</span>}
          </div>
          {hero.released && <div className="mt-0.5 text-xs text-faint">发布于 {hero.released}</div>}
        </div>
      </div>
      {det?.subtitle && <p className="rounded-lg bg-black/25 px-3 py-2 text-sm text-muted italic">{det.subtitle}</p>}

      {(det?.self_devotion || det?.devotion) && (
        <Section title="角色奉献">
          <div className="grid grid-cols-2 gap-2.5">
            <DevotionCard kind="self" dev={det.self_devotion} slot="" data={data} />
            <DevotionCard kind="team" dev={det.devotion} slot={det.devotion_slot} data={data} />
          </div>
        </Section>
      )}

      {det?.exclusive && (
        <Section title="专属装备">
          <div className="flex items-center gap-3">
            {det.exclusive.icon && <img src={api().heroAssetUrl(det.exclusive.icon)} alt="" className="size-12 flex-none rounded" />}
            <div className="min-w-0">
              <div className="font-bold">{det.exclusive.name}</div>
              {det.exclusive.main_stat.type && (
                <div className="flex items-center gap-1 text-xs text-muted">
                  主属性：<StatIcon type={det.exclusive.main_stat.type} className="size-3.5" />
                  {data.labels.stat[det.exclusive.main_stat.type] ?? det.exclusive.main_stat.type}{" "}
                  {formatDevotion(det.exclusive.main_stat.type, det.exclusive.main_stat.min, data.labels.percent_stats)}
                  ～{formatDevotion(det.exclusive.main_stat.type, det.exclusive.main_stat.max, data.labels.percent_stats)}
                </div>
              )}
            </div>
          </div>
          {det.exclusive.effects.length > 0 && (
            <div className="mt-2.5 flex flex-col gap-1.5">
              {det.exclusive.effects.map((e) => {
                const color = EXCLUSIVE_COLORS[(e.index - 1) % EXCLUSIVE_COLORS.length];
                const skill = det.skills.find((s) => s.slot === e.slot);
                return (
                  <div key={e.index} className="rounded-lg border-l-[3px] bg-black/25 px-3 py-1.5" style={{ borderColor: color }}>
                    <div className="text-xs font-bold" style={{ color }}>
                      效果 {e.index}<span className="ml-2 font-normal text-muted">技能 {e.slot}{skill ? `「${skill.name}」` : ""}</span>
                    </div>
                    <Rich text={e.description} />
                  </div>
                );
              })}
            </div>
          )}
        </Section>
      )}

      <Section title="满级属性" extra={<span className="text-xs font-normal text-faint">60 级 6 星满觉醒，不含装备</span>}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          {STAT_ROWS.map((s) => (
            <div key={s.key} className="flex justify-between border-b border-white/6 py-1">
              <dt className="flex items-center gap-1.5 text-muted"><StatIcon type={s.key} />{s.label}</dt>
              <dd className="num text-gold">{formatStat(hero.stats[s.key], s.percent)}</dd>
            </div>
          ))}
        </dl>
      </Section>
    </div>
  );
}

// 专属装备三选一的效果，按选项分三种颜色
const EXCLUSIVE_COLORS = ["#79d860", "#5cc4ff", "#c58cff"];

const TIER_LABELS: Record<string, string> = { fast: "快速", mid: "中速", slow: "慢速", top10: "前 10%", top25: "前 25%", all: "中位" };

const GRADES = ["d", "c", "b", "a", "s", "ss", "sss"] as const;

function DevotionCard({ kind, dev, slot, data }: { kind: "self" | "team"; dev: Devotion | null; slot: string; data: HeroList }) {
  const title = kind === "self" ? "自阵属性" : "群阵属性";
  // 游戏里的刻印图示：自身刻印；群阵是四个菱形，受影响的位置亮（1 右、2 下、3 上、4 左）
  const icon = gameIcon(kind === "self" ? "devotion_self" : `devotion_team_${slot || "1234"}`);
  if (!dev) return <div className="rounded-lg border border-white/8 bg-black/20 px-3 py-2.5 text-sm text-faint">{title}：无</div>;
  const ps = data.labels.percent_stats;
  const grades = GRADES.filter((g) => dev.grades[g] !== undefined);
  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/8 bg-black/20 px-3 py-2.5">
      {icon && <img src={icon} alt="" className="size-12 flex-none" draggable={false} />}
      <div className="min-w-0 flex-1">
        <div className="text-xs text-gold">{title}</div>
        <div className="mt-0.5 flex items-center gap-1.5">
          <StatIcon type={dev.type} />
          <span className="text-sm text-muted">{data.labels.stat[dev.type] ?? dev.type}</span>
          <span className="num ml-auto text-xl font-bold">{formatDevotion(dev.type, dev.grades.sss, ps)}</span>
        </div>
        {/* 等级：图标在上、数值在下，等宽排成一行（三星英雄有 D～SSS 七级） */}
        <div className="mt-2 grid gap-1 text-xs text-faint" style={{ gridTemplateColumns: `repeat(${grades.length}, minmax(0, 1fr))` }}>
          {grades.map((g) => {
            const gi = gameIcon(`grade_${g}`);
            return (
              <span key={g} className="flex flex-col items-center gap-0.5">
                {gi ? <img src={gi} alt={g.toUpperCase()} className="h-[18px] max-w-full object-contain" draggable={false} /> : <b className="h-[18px] leading-[18px]">{g.toUpperCase()}</b>}
                <span className="num">{formatDevotion(dev.type, dev.grades[g], ps)}</span>
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** 属性的游戏图标（攻击力、生命值…）；dev 类型和满级属性的键都认 */
function StatIcon({ type, className }: { type: string; className?: string }) {
  const src = gameIcon(`stat_${STAT_ICON[type] ?? type}`);
  return src ? <img src={src} alt="" className={cn("size-4 flex-none", className)} draggable={false} /> : null;
}

const STAT_ICON: Record<string, string> = {
  att: "atk", att_rate: "atk", def_rate: "def", max_hp: "hp", max_hp_rate: "hp", speed: "spd",
  cri: "chc", cri_dmg: "chd", acc: "eff", res: "efr", coop: "dac",
};

function SkillsTab({ hero }: { hero: Hero }) {
  const { data: det, isLoading, error } = useDetail(hero.code);
  if (isLoading) return <p className="text-muted">加载中…</p>;
  if (error || !det) return <p className="text-muted">这名英雄还没有技能资料。</p>;
  return (
    <div className="flex flex-col gap-3">
      {det.skills.map((s) => <SkillCard key={s.slot} skill={s} />)}
    </div>
  );
}

function SkillCard({ skill }: { skill: HeroSkill }) {
  const cooldown = skill.cooldown.flat().map((x) => x.text).join("");
  return (
    <section className="rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
      <div className="mb-2.5 flex items-center gap-3">
        {skill.icon && <img src={api().heroAssetUrl(skill.icon)} alt="" className="size-12 flex-none rounded-lg" draggable={false} />}
        <div className="min-w-0">
          <div className="text-[15px] font-bold">{skill.name}</div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
            <span className="rounded bg-white/8 px-1.5 py-0.5 text-muted">技能 {skill.slot}</span>
            {skill.soul_gain > 0 && <span className="rounded bg-[#3a5a8f]/50 px-1.5 py-0.5 text-[#9fd0ff]">灵魂 +{skill.soul_gain}</span>}
            {cooldown && <span className="rounded bg-white/8 px-1.5 py-0.5 text-muted">{cooldown}</span>}
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-2.5">
        <Rich text={skill.description} />
        {skill.soul_burn && (
          <div className="rounded-lg border border-[#c86bff]/30 bg-[#c86bff]/8 px-3 py-2">
            <div className="text-xs font-bold text-[#d9a4ff]">灵魂燃烧（消耗 {skill.soul_burn.cost}）</div>
            <Rich text={skill.soul_burn.description} />
          </div>
        )}
        {skill.exclusive.length > 0 && (
          <div className="rounded-lg border border-gold-line/40 bg-gold/5 px-3 py-2">
            <div className="text-xs font-bold text-gold">专属装备效果（多选一）</div>
            {skill.exclusive.map((t, i) => <Rich key={i} text={t} />)}
          </div>
        )}
        {skill.effects.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-bold text-glow">技能特效</div>
            <div className="flex flex-col gap-1.5">
              {skill.effects.map((e, i) => (
                <div key={i} className="flex gap-2.5 rounded-lg bg-black/25 px-2.5 py-1.5">
                  {e.icon ? <img src={api().heroAssetUrl(e.icon)} alt="" className="mt-0.5 size-6 flex-none" />
                    : <span className="mt-0.5 size-6 flex-none" />}
                  <div className="min-w-0">
                    <div className={cn("text-[13px] font-bold", e.type === "debuff" ? "text-bad" : "text-[#9fd0ff]")}>{e.name}</div>
                    <Rich text={e.description} className="text-[13px] text-muted" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {skill.enhancements.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-bold text-glow">技能强化</div>
            <ol className="flex flex-col gap-0.5 text-[13px] text-muted">
              {skill.enhancements.map((t, i) => (
                <li key={i} className="flex gap-2"><span className="text-gold">+{i + 1}</span><Rich text={t} className="text-[13px]" /></li>
              ))}
            </ol>
          </div>
        )}
        {skill.multipliers.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {skill.multipliers.map((m, i) => (
              <div key={i} className="rounded-lg bg-black/25 px-2.5 py-1.5 text-xs">
                <div className="mb-0.5 font-bold text-ok">{m.label}</div>
                {m.items.map((it, j) => (
                  <div key={j} className="flex justify-between gap-4 text-muted"><span>{it.label}</span><span className="num text-gold">{it.value}</span></div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function SetIcon({ set, label }: { set: string; label: string }) {
  const src = gameIcon(set);
  return src ? <img src={src} alt={label} title={label} className="size-6" draggable={false} /> : null;
}

function BuildsTab({ hero, data }: { hero: Hero; data: HeroList }) {
  const qc = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const { data: b, isFetching: loading, error } = useQuery({
    queryKey: qk.heroBuilds(hero.code), queryFn: () => api().heroBuilds(hero.code), staleTime: Infinity, retry: false,
  });
  const isFetching = loading || refreshing;
  const refresh = async () => {
    setRefreshing(true);
    try {
      qc.setQueryData(qk.heroBuilds(hero.code), await api().heroBuilds(hero.code, true));
    } catch (e) {
      toast(`配装数据取不到：${errorMessage(e)}`, "error");
    } finally {
      setRefreshing(false);
    }
  };
  if (!b && isFetching) return <p className="text-muted">正在从 Fribbels 取配装数据…</p>;
  if (!b) return <p className="text-bad">配装数据取不到：{errorMessage(error)}</p>;
  if (b.total === 0) return <p className="text-muted">还没有玩家上传这名英雄的配装。</p>;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 text-sm text-muted">
        <span>Fribbels 玩家配装统计 · 共 {b.total} 份{b.latest && ` · 最新 ${b.latest}`}{b.stale && "（没连上，显示的是上次的）"}</span>
        <button type="button" className="btn btn-sm btn-ghost ml-auto" disabled={isFetching} onClick={() => void refresh()}>
          <RefreshCw className={cn("size-3.5", isFetching && "animate-spin")} />刷新
        </button>
      </div>
      <Section title="全部配装"><TierTable rows={[{ key: "all", label: "中位数", count: b.total, stats: b.stats }]} /></Section>
      <Section title="套装组合" extra={<span className="text-xs font-normal text-faint">属性为中位数；带速度套的看速度最快的前 10% / 前 25% 和全部，没带的按速度分快 / 中 / 慢三档</span>}>
        <div className="flex flex-col gap-2">
          {b.combos.map((c, i) => (
            <div key={i} className="rounded-lg bg-black/25 px-3 py-2">
              <div className="flex items-center gap-2">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  {c.sets.length === 0 && <span className="text-muted">没有成套</span>}
                  {c.sets.map((s) => (
                    <span key={s.set} className="inline-flex items-center gap-1 text-sm font-bold">
                      <SetIcon set={s.set} label={data.labels.set[s.set] ?? s.set} />
                      {data.labels.set[s.set] ?? s.set}<span className="text-xs font-normal text-muted">×{s.pieces}</span>
                    </span>
                  ))}
                </div>
                <span className="num ml-auto text-sm text-gold">{pct(c.share)}</span>
                <span className="w-14 text-right text-xs text-faint">{c.count} 份</span>
              </div>
              <div className="mt-1.5 h-1 rounded bg-white/8"><div className="h-full rounded bg-glow/70" style={{ width: pct(c.share) }} /></div>
              <TierTable rows={c.tiers.length > 0
                ? c.tiers.map((t) => ({ key: t.tier, label: TIER_LABELS[t.tier] ?? t.tier, count: t.count, stats: t.stats }))
                : [{ key: "all", label: "中位数", stats: c.stats }]} />
              <ArtifactRow items={c.artifacts} />
            </div>
          ))}
        </div>
      </Section>
      <Section title="常用神器"><ArtifactRow items={b.artifacts} big /></Section>
    </div>
  );
}

/** 组合的属性中位数表：带速度套的分前 10% / 前 25% / 中位三行，不带的分快 / 中 / 慢三行（份数太少时一行）；列对齐方便比较（速度放第一列） */
function TierTable({ rows }: { rows: { key: string; label: string; count?: number; stats: Record<string, number> }[] }) {
  const cols = [BUILD_STATS.find((x) => x.key === "spd")!, ...BUILD_STATS.filter((x) => x.key !== "spd")];
  return (
    <table className="mt-1.5 w-full table-fixed text-xs">
      <thead>
        <tr className="text-faint">
          <th className="w-[104px] text-left font-normal" />
          {cols.map((x) => (
            <th key={x.key} className="font-normal">
              <span className="inline-flex items-center gap-0.5"><StatIcon type={x.key} className="size-3" />{SHORT_LABELS[x.key] ?? x.label}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.key} className="border-t border-white/6">
            <td className="whitespace-nowrap py-0.5 text-muted">{t.label}{t.count !== undefined && <span className="ml-1 text-faint">{t.count} 份</span>}</td>
            {cols.map((x) => (
              <td key={x.key} className={cn("num py-0.5 text-center", x.key === "spd" ? "text-gold" : "text-ink")}>
                {t.stats[x.key] ?? "—"}{x.percent && t.stats[x.key] !== undefined ? "%" : ""}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const SHORT_LABELS: Record<string, string> = { chd: "暴伤", eff: "命中", efr: "抗性", gear: "均分" };

function ArtifactRow({ items, big }: { items: HeroBuilds["artifacts"]; big?: boolean }) {
  if (!items.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", !big && "mt-1.5")}>
      {items.map((a) => (
        <span key={a.code} className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/30 py-0.5 pr-2.5 pl-0.5 text-xs">
          <img src={api().artifactIconUrl(a.code)} alt="" className={cn("rounded-full", big ? "size-7" : "size-5")}
            onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
          {a.name || a.code}<span className="num text-gold">{pct(a.share)}</span>
        </span>
      ))}
    </div>
  );
}
