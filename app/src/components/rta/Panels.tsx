// RTA 助手（B14e1）每一步的面板（布局参考 e7rtabot）：准备、信息条、预禁、我方推荐、对方可能的选择、后禁矩阵、结果。
// 胜率一律是我方的；先动概率（我方先动）引擎给了才显示。
import { Ban, Plus, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { errorMessage } from "@/lib/api";
import {
  GRADE_CHOICES, PICKS, PREBANS, needsRule, prebanTarget, ruleApplies, turn, type Draft, type Setup, type Side, type Team,
} from "@/lib/draft";
import {
  banHeadline, pct0, pct1, pickHeadline, rareTag, type Advice, type Choice, type Latest, type PrebanAdvice, type Recommend, type Reply, type RtaOptions,
} from "@/lib/rta";
import { cn } from "@/lib/utils";
import { Face, Faces, RankIcon, Segmented, Spinner, Tag, Win, gradeLabel, useName } from "./bits";

function Shell({ title, status, right, children, className }: {
  title: ReactNode;
  status?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("panel flex min-h-0 flex-col gap-2.5 px-4 py-3", className)}>
      <header className="flex min-h-[30px] flex-none items-center gap-3">
        <span className="panel-title">{title}</span>
        {status}
        <span className="flex-1" />
        {right}
      </header>
      {children}
    </section>
  );
}

/** 请求出错 / 还没有结果时的占位；有结果时画 children（结果是上一个局面的时变淡）。 */
function Body<T>({ q, ok, children }: { q: Latest<T>; ok: (d: T) => boolean; children: (d: T) => ReactNode }) {
  if (q.error) {
    return (
      <div className="flex items-center gap-3 text-sm text-bad">
        <span className="min-w-0 flex-1">{errorMessage(q.error)}</span>
        <button type="button" className="btn btn-sm btn-ghost" onClick={q.retry}><RefreshCw className="size-4" />重试</button>
      </div>
    );
  }
  if (!q.data || !ok(q.data)) return <div className="py-2"><Spinner /></div>;
  return <div className={cn("min-h-0 overflow-auto transition-opacity", !q.fresh && "opacity-50")}>{children(q.data)}</div>;
}

/** 面板里一组卡片上面的小标题 */
function Label({ children, tone }: { children: ReactNode; tone?: "bad" }) {
  return <div className={cn("text-xs", tone === "bad" ? "text-bad/90" : "text-muted")}>{children}</div>;
}

// 一组卡片一律放进列宽固定的网格（同一面板里几组用同一个模板，列对得齐；用户意见：不要前面对齐、后面不齐）
const CARD_GRID = "grid grid-cols-[repeat(auto-fill,minmax(310px,1fr))] gap-2";
const CHOICE_GRID = "grid grid-cols-[repeat(auto-fill,minmax(195px,1fr))] gap-2";
const PAIR_GRID = "grid max-w-[560px] grid-cols-5 gap-2";

/** 推荐卡上的标记（固定一行，放不下的截掉；完整意思在鼠标提示里）。rare = 「数据少 / 英雄池」那个标记（rareTag）。 */
function Marks({ close, second, win, rare, children }: {
  close?: boolean;
  second?: { win: number; spread: number } | null;
  win: number;
  rare?: { label: string; title: string } | null;
  children?: ReactNode;
}) {
  return (
    <span className="flex h-[18px] min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
      {children}
      {close && <Tag title="和第一名差不到 1 个百分点">差距小</Tag>}
      {second && <Tag tone="warn" title={`两个模型的预期差 ${Math.abs(Math.round((second.win - win) * 100))} 个百分点（另一个模型 ${pct1(second.win)}）`}>分歧大</Tag>}
      {rare && <Tag tone="warn" title={rare.title}>{rare.label}</Tag>}
    </span>
  );
}

/** 两名英雄的名字（推荐卡里头像旁边）；shield = 放保护位的那名，名字后面标「保护」 */
function Names({ codes, shield, className }: { codes: string[]; shield?: string | null; className?: string }) {
  const name = useName();
  return (
    <span className={cn("min-w-0 flex-1 text-[13px] leading-tight", className)}>
      {codes.map((c) => (
        <span key={c} className="block truncate">
          {name(c)}
          {c === shield && <span className="ml-1 text-[11px] text-gold">保护</span>}
        </span>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------- 准备（参考 e7rtabot：段位图标、分段按钮）

function RankPicker({ label, value, tone, onChange }: { label: string; value: string; tone: "mine" | "theirs"; onChange: (g: string) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-bold">{label}</span>
        <span className={cn("text-sm", tone === "mine" ? "text-gold" : "text-bad")}>{gradeLabel(value)}</span>
      </div>
      <div className="flex gap-2" role="radiogroup" aria-label={label}>
        {GRADE_CHOICES.map((g) => {
          const on = g.code === value;
          return (
            <button key={g.code} type="button" role="radio" aria-checked={on} aria-label={g.label} title={g.label}
              onClick={() => onChange(g.code)}
              className={cn("grid size-[58px] cursor-pointer place-items-center rounded-xl border-2 bg-black/30 transition",
                on ? (tone === "mine" ? "border-gold shadow-[0_0_12px_rgba(216,182,121,.45)]" : "border-bad shadow-[0_0_12px_rgba(255,138,112,.4)]")
                  : "border-white/10 opacity-55 hover:opacity-100")}>
              <RankIcon code={g.code} size={46} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function SetupPanel({ setup, options, onChange, onStart }: {
  setup: Setup;
  options: RtaOptions;
  onChange: (s: Setup) => void;
  onStart: () => void;
}) {
  const hasRule = ruleApplies(setup.grades);
  const rule = options.rules.find((r) => r.tid === setup.rule);
  const grade = (i: 0 | 1, g: string) => {
    const grades: Setup["grades"] = [...setup.grades];
    grades[i] = g;
    onChange({ ...setup, grades });
  };
  return (
    <section className="panel mx-auto flex w-full max-w-[760px] flex-col gap-5 px-7 py-6">
      <h2 className="border-l-[3px] border-gold pl-3 text-lg font-bold text-gold">准备</h2>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(310px,1fr))] gap-x-8 gap-y-4">
        <RankPicker label="我方段位" value={setup.grades[0]} tone="mine" onChange={(g) => grade(0, g)} />
        <RankPicker label="对方段位" value={setup.grades[1]} tone="theirs" onChange={(g) => grade(1, g)} />
      </div>
      <div className="h-px bg-white/8" />
      <div className="flex flex-col gap-2">
        <div className="flex items-baseline gap-2">
          <span className={cn("font-bold", !hasRule && "text-faint")}>开战规则</span>
          <span className="text-xs text-faint">优胜者以上</span>
        </div>
        <Segmented label="开战规则" value={hasRule ? setup.rule : ""} disabled={!hasRule}
          options={options.rules.map((r) => ({ value: r.tid, label: r.label, title: r.desc }))}
          onChange={(v) => onChange({ ...setup, rule: v })} />
        {hasRule && rule && <span className="text-xs text-muted">{rule.desc}</span>}
      </div>
      <div className="flex flex-col gap-2">
        <span className="font-bold">先后手</span>
        <Segmented label="先后手" value={setup.side} onChange={(v) => onChange({ ...setup, side: v })}
          options={[{ value: "F" as Side, label: "我方先手" }, { value: "S" as Side, label: "我方后手" }]} />
      </div>
      <div className="flex items-center justify-end gap-3">
        {needsRule(setup) && <span className="text-sm text-warn">选开战规则</span>}
        <button type="button" className="btn btn-go" disabled={needsRule(setup)} onClick={onStart}>开始预禁</button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- 选秀 / 后禁 / 结果上面的信息条

export function InfoBar({ draft, options, advice }: { draft: Draft; options: RtaOptions; advice: Latest<Advice> }) {
  const hasRule = ruleApplies(draft.setup.grades);
  const rule = options.rules.find((r) => r.tid === draft.setup.rule);
  const name = useName();
  const d = advice.data;
  const sep = <span className="h-4 w-px bg-white/12" />;
  // 始终用「我方的读数」（B14e2 审核，用户意见）：选秀时我方回合是推荐第 1 名的预期、对方回合是对方按常见选法、
  // 我方再从英雄池里回应的预期；后禁这一步是推荐行（我方已选禁谁时用选的那一行）的预期；结果是最后的胜率
  const head = d?.phase === "ban" && d.ban ? banHeadline(d.ban, draft.bans.mine) : null;
  const pick = !head && d ? pickHeadline(d) : null;
  const win = head ? head.win : pick ? pick.win : d?.win;
  const first = head ? head.first : pick ? pick.first : d?.first?.mine ?? null;
  const label = head ? `禁${name(head.code)}后` : pick ? "预期" : d?.phase === "done" ? "胜率" : "当前胜率";
  const model = d ? `（不知道英雄池的模型读数 ${pct1(d.win)}）` : "";
  const tip = head ? `我方禁${name(head.code)}、对方按常见后禁`
    : pick?.turn === "mine" ? `推荐第 1 名（${pick.heroes.map(name).join("、")}）的预期${d?.pool_short ? "（英雄池里能选的不够，这一轮是全部英雄里选）" : "，只在英雄池里选"}${model}`
      : pick ? `对方按常见的选法、我方再从英雄池里选最好的回应的预期${model}` : undefined;
  // 加上先动概率后 1280 宽放不下一行（B14h）：1440 以下去掉三个文字标签，1200 以下再去掉手数
  return (
    <div className="panel flex flex-none flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm max-[1199px]:gap-x-2 max-[1199px]:px-3">
      <span className="text-xs text-muted max-[1439px]:hidden">段位</span>
      <RankIcon code={draft.setup.grades[0]} size={28} />
      <span className="text-xs text-faint">vs</span>
      <RankIcon code={draft.setup.grades[1]} size={28} />
      {sep}
      <span className="text-xs text-muted max-[1439px]:hidden">开战规则</span>
      <span title={hasRule ? `开战规则：${rule?.desc ?? ""}` : "开战规则：无"}>{hasRule ? rule?.label ?? "—" : "无"}</span>
      {sep}
      <span className="text-xs text-muted max-[1439px]:hidden">预禁</span>
      <Faces codes={draft.prebans.mine} size={26} />
      <Faces codes={draft.prebans.theirs} size={26} />
      {sep}
      <span className="num text-muted max-[1199px]:hidden">{draft.picks.length} / {PICKS}</span>
      <span className="flex-1" />
      {d && d.unknown.length > 0 && (
        <Tag tone="warn" title={d.unknown.map(name).join("、")}>{`模型没见过：${d.unknown.length} 名`}</Tag>
      )}
      {win !== undefined && (
        <span className={cn("flex items-baseline gap-2 transition-opacity", !advice.fresh && "opacity-50")} title={tip}>
          <span className="text-xs text-muted">{label}</span>
          <Win p={win} className="text-xl font-bold" />
          {first !== null && <span className="text-xs text-muted">先动 <span className="num text-sm text-ink">{pct0(first)}</span></span>}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- 预禁

function PrebanSlots({ draft, team, onRemove }: { draft: Draft; team: Team; onRemove: (code: string) => void }) {
  const name = useName();
  const codes = draft.prebans[team];
  const next = prebanTarget(draft) === team ? codes.length : -1;
  return (
    <div className="flex flex-col items-center gap-2">
      <span className={cn("text-xs font-bold", team === "mine" ? "text-gold" : "text-bad")}>
        {team === "mine" ? "我方预禁" : "对方预禁"} <span className="num ml-1">{codes.length} / {PREBANS}</span>
      </span>
      <div className="flex gap-2.5">
        {Array.from({ length: PREBANS }, (_, i) => {
          const code = codes[i];
          return (
            <button key={i} type="button" disabled={!code} onClick={() => code && onRemove(code)}
              title={code ? `${name(code)}（点一下去掉）` : undefined}
              className={cn("relative grid size-[58px] place-items-center rounded-xl border-2 border-dashed border-white/15 bg-black/30",
                code && "cursor-pointer border-solid border-bad/60 hover:border-bad",
                i === next && "border-solid border-glow shadow-[0_0_10px_rgba(67,166,255,.5)]")}>
              {code ? (
                <>
                  <Face code={code} size={52} className="opacity-80" />
                  <Ban className="absolute -top-1.5 -right-1.5 size-5 rounded-full bg-[#1b2234] text-bad" />
                </>
              ) : (
                <Plus className="size-5 text-faint" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function PrebanPanel({ draft, q, onMine, onTheirs, onRemove, onBack, onStart }: {
  draft: Draft;
  q: Latest<PrebanAdvice>;
  onMine: (heroes: string[]) => void;
  onTheirs: (heroes: string[]) => void;
  onRemove: (team: Team, code: string) => void;
  onBack: () => void;
  onStart: () => void;
}) {
  const my = draft.setup.side;
  const target = prebanTarget(draft);
  const mine = [...draft.prebans.mine].sort().join();
  return (
    <Shell title="预禁" className="h-full"
      status={<>
        <span className="text-sm text-muted">{target === "mine" ? "选我方预禁的 2 名" : target === "theirs" ? "选对方预禁的 2 名，可以和我方重复" : ""}</span>
        {q.loading && <Spinner />}
      </>}
      right={<>
        <button type="button" className="btn btn-sm btn-ghost" onClick={onBack}>返回</button>
        <button type="button" className={cn("btn btn-sm", target === null ? "btn-go" : "btn-ghost")} onClick={onStart}>开始选秀</button>
      </>}>
      <div className="flex flex-none justify-center gap-10 border-b border-white/8 pb-3">
        <PrebanSlots draft={draft} team="mine" onRemove={(c) => onRemove("mine", c)} />
        <span className="w-px self-stretch bg-white/8" />
        <PrebanSlots draft={draft} team="theirs" onRemove={(c) => onRemove("theirs", c)} />
      </div>
      <Body q={q} ok={(d) => d.phase === "preban"}>
        {(d) => (
          <div className="flex flex-col gap-1.5">
            {(d.theirs[my]?.length ?? 0) > 0 && (
              <>
                <Label>对方常见预禁</Label>
                <div className={cn(PAIR_GRID, "mb-1.5")}>
                  {d.theirs[my]!.map((p) => (
                    <button key={p.heroes.join()} type="button" onClick={() => onTheirs(p.heroes)}
                      className="flex cursor-pointer flex-col items-center gap-0.5 rounded-lg border border-white/10 bg-black/25 px-1 py-1 hover:border-gold/60">
                      <Faces codes={p.heroes} size={28} />
                      <span className="num text-[11px] leading-3 text-muted">{pct0(p.share)}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
            <Label>我方预禁推荐</Label>
            <div className={CARD_GRID}>
              {d.recommend.map((r, i) => {
                const worst = r.worst_vs[my];
                return (
                  <button key={r.heroes.join()} type="button" onClick={() => onMine(r.heroes)}
                    className={cn("flex cursor-pointer flex-col gap-1.5 rounded-xl border bg-[var(--panel-hi)] px-3 py-2 text-left transition-colors hover:border-gold/60",
                      [...r.heroes].sort().join() === mine ? "border-gold ring-1 ring-gold/60" : "border-white/8")}>
                    <span className="flex items-center gap-2">
                      <span className="num w-4 flex-none text-gold">{i + 1}</span>
                      <Faces codes={r.heroes} size={36} />
                      <Names codes={r.heroes} />
                      <span className="flex-none text-right text-xs text-muted">
                        <span className="block">预期 <Win p={r.win} className="text-base" /></span>
                        <span className="block">最坏 <Win p={r.worst} /></span>
                      </span>
                    </span>
                    <span className="flex items-center gap-2 pl-6">
                      <Marks close={r.close} second={r.uncertain ? r.second : null} win={r.win}>
                        {r.share[my] !== undefined && <Tag title="这一方玩家用这组预禁的比例">{`常用 ${pct1(r.share[my] ?? 0)}`}</Tag>}
                      </Marks>
                      {worst && (
                        <span className="inline-flex flex-none items-center gap-1 text-[11px] text-muted" title="对方预禁这一组时我方最难受">
                          最怕 <Faces codes={worst} size={20} />
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </Body>
    </Shell>
  );
}

// ---------------------------------------------------------------- 选秀：轮到我方

function ReplyChip({ r, danger }: { r: Reply; danger?: boolean }) {
  const name = useName();
  const names = (cs: string[]) => cs.map(name).join("、");
  const title = `对方选 ${names(r.heroes)}（${pct0(r.prob)}）后我方 ${pct1(r.win)}`
    + (r.reply && r.reply_win !== undefined ? `；我方再选 ${names(r.reply)} → ${pct1(r.reply_win)}` : "");
  return (
    <span title={title} className={cn("flex min-w-0 flex-col items-center gap-0.5 rounded-md border px-0.5 py-1",
      danger ? "border-bad/40 bg-bad/8" : "border-white/8 bg-black/25")}>
      <Faces codes={r.heroes} size={20} />
      <span className="text-[10px] leading-3 whitespace-nowrap">
        {!danger && <span className="num mr-1 text-muted">{pct0(r.prob)}</span>}
        <Win p={r.win} />
      </span>
    </span>
  );
}

function RecCard({ r, rank, onPick }: { r: Recommend; rank: number; onPick: () => void }) {
  const name = useName();
  return (
    <button type="button" onClick={onPick}
      className="flex cursor-pointer flex-col gap-1.5 rounded-xl border border-white/8 bg-[var(--panel-hi)] px-3 py-2 text-left transition-colors hover:border-gold/60">
      <span className="flex items-center gap-2">
        <span className="num w-4 flex-none text-gold">{rank}</span>
        <Faces codes={r.heroes} size={40} shield={r.protected} />
        <Names codes={r.heroes} shield={r.protected} />
        <span className="flex-none text-right text-xs text-muted">
          <span className="block">预期 <Win p={r.win} className="text-base" /></span>
          <span className="block">最坏 <Win p={r.worst} /></span>
          {r.first != null && <span className="block">先动 <span className="num text-ink">{pct0(r.first)}</span></span>}
        </span>
      </span>
      <span className="flex pl-6">
        <Marks close={r.close} second={r.uncertain ? r.second : null} win={r.win} rare={rareTag(r.rare, r.pool_only, name)} />
      </span>
      {(r.responses.length > 0 || r.threat) && (
        <span className="grid grid-cols-4 gap-1 pl-6 text-[10px]">
          <span className="col-span-3 text-faint">对方可能</span>
          <span className="text-bad/80">最怕</span>
          {[0, 1, 2].map((i) => (r.responses[i] ? <ReplyChip key={i} r={r.responses[i]} /> : <span key={i} />))}
          {r.threat ? <ReplyChip r={r.threat} danger /> : <span />}
        </span>
      )}
    </button>
  );
}

export function MinePanel({ draft, q, onPick }: { draft: Draft; q: Latest<Advice>; onPick: (heroes: string[]) => void }) {
  const t = turn(draft);
  return (
    <Shell title={`轮到我方选 ${t?.slots ?? 0} 名`} status={q.loading && <Spinner />}>
      <Body q={q} ok={(d) => d.phase === "pick" && d.turn === "mine"}>
        {(d) => (
          <div className="flex flex-col gap-1.5">
            {d.pool_short && <div className="text-xs text-warn">英雄池里能选的不够，这一轮推荐全部英雄</div>}
            <div className={CARD_GRID}>
              {(d.recommend ?? []).map((r, i) => (
                <RecCard key={r.heroes.join()} r={r} rank={i + 1} onPick={() => onPick(r.heroes)} />
              ))}
            </div>
          </div>
        )}
      </Body>
    </Shell>
  );
}

// ---------------------------------------------------------------- 选秀：轮到对方

function ChoiceChip({ c, danger, onPick }: { c: Choice; danger?: boolean; onPick: () => void }) {
  return (
    <button type="button" onClick={onPick}
      className={cn("flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-lg border px-2 py-1 text-left transition-colors hover:border-gold/60",
        danger ? "border-bad/40 bg-bad/8" : "border-white/10 bg-black/25")}>
      <Faces codes={c.heroes} size={34} />
      <span className="min-w-0 flex-1 text-xs leading-tight">
        <Names codes={c.heroes} className="block text-xs" />
        <span className="mt-0.5 block truncate text-muted">
          <span className="num">{pct0(c.prob)}</span> · 之后 <Win p={c.win} />
        </span>
      </span>
    </button>
  );
}

export function TheirsPanel({ draft, q, onPick }: { draft: Draft; q: Latest<Advice>; onPick: (heroes: string[]) => void }) {
  const t = turn(draft);
  return (
    <Shell title={`轮到对方选 ${t?.slots ?? 0} 名`}
      status={<><span className="text-sm text-muted">点一下记为对方的选择</span>{q.loading && <Spinner />}</>}>
      <Body q={q} ok={(d) => d.phase === "pick" && d.turn === "theirs"}>
        {(d) => (
          <div className="flex flex-col gap-1.5">
            <Label>对方可能的选择</Label>
            <div className={CHOICE_GRID}>
              {(d.opponent?.likely ?? []).map((c) => <ChoiceChip key={c.heroes.join()} c={c} onPick={() => onPick(c.heroes)} />)}
            </div>
            {(d.opponent?.threats.length ?? 0) > 0 && (
              <>
                <div className="mt-1"><Label tone="bad">对我方最不利</Label></div>
                <div className={CHOICE_GRID}>
                  {d.opponent!.threats.map((c) => <ChoiceChip key={c.heroes.join()} c={c} danger onPick={() => onPick(c.heroes)} />)}
                </div>
              </>
            )}
          </div>
        )}
      </Body>
    </Shell>
  );
}

// ---------------------------------------------------------------- 后禁

export function BanPanel({ draft, q, onBan, onBoth }: {
  draft: Draft;
  q: Latest<Advice>;
  /** team 这一队禁 code */
  onBan: (team: Team, code: string) => void;
  /** 一次填好双方的后禁（点矩阵里的格子） */
  onBoth: (mine: string, theirs: string) => void;
}) {
  const name = useName();
  return (
    <Shell title="后禁" status={<><span className="text-sm text-muted">点格子记下双方实际禁的</span>{q.loading && <Spinner />}</>}
      className="min-h-0 flex-1">
      <Body q={q} ok={(d) => d.phase === "ban" && !!d.ban}>
        {(d) => {
          const b = d.ban!;
          const nash = (codes: string[], p: number[]) => codes.map((c, i) => ({ c, p: p[i] })).filter((x) => x.p >= 0.01)
            .sort((a, z) => z.p - a.p).map((x) => `${name(x.c)} ${pct0(x.p)}`).join(" · ");
          return (
            <div className="flex flex-col gap-3">
              <table className="w-full max-w-[860px] table-fixed border-separate border-spacing-1">
                <colgroup>
                  <col className="w-[180px]" />
                  {b.cols.map((c) => <col key={c} />)}
                  <col className="w-[64px]" />
                  <col className="w-[64px]" />
                </colgroup>
                <thead>
                  <tr>
                    <th className="text-left align-bottom text-xs font-normal text-muted">我方禁 ↓ ／ 对方禁 →</th>
                    {b.cols.map((c, j) => (
                      <th key={c} className="font-normal">
                        <button type="button" onClick={() => onBan("theirs", c)}
                          className={cn("flex w-full cursor-pointer flex-col items-center gap-0.5 rounded-lg border px-1 py-1 hover:border-bad/60",
                            draft.bans.theirs === c ? "border-bad bg-bad/10" : "border-transparent")}>
                          <Face code={c} size={32} />
                          <span className="w-full truncate text-[11px]">{name(c)}</span>
                          <span className="text-[11px] text-muted">可能 <span className="num">{pct0(b.their_likely[j]?.prob ?? 0)}</span></span>
                        </button>
                      </th>
                    ))}
                    <th className="align-bottom text-xs font-normal text-muted">最坏</th>
                    <th className="align-bottom text-xs font-normal text-muted">预期</th>
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((r, i) => {
                    const st = b.row_stats[i];
                    const rec = r === b.recommend;
                    return (
                      <tr key={r}>
                        <th className="font-normal">
                          <button type="button" onClick={() => onBan("mine", r)}
                            className={cn("flex w-full cursor-pointer items-center gap-2 rounded-lg border px-1.5 py-1 text-left hover:border-bad/60",
                              draft.bans.mine === r ? "border-bad bg-bad/10" : rec ? "border-gold/70" : "border-transparent")}>
                            <Face code={r} size={32} />
                            <span className="min-w-0 flex-1 truncate text-[13px]">{name(r)}</span>
                            {rec && <Tag tone="gold">推荐</Tag>}
                          </button>
                        </th>
                        {b.matrix[i].map((v, j) => {
                          const f = b.first?.[i]?.[j];
                          const sel = draft.bans.mine === r && draft.bans.theirs === b.cols[j];
                          return (
                            <td key={b.cols[j]}>
                              <button type="button" onClick={() => onBoth(r, b.cols[j])}
                                className={cn("flex h-full w-full cursor-pointer flex-col items-center justify-center rounded-lg border px-2 py-1.5 hover:border-gold/60",
                                  sel ? "border-gold bg-gold/12" : "border-white/8 bg-black/25",
                                  v === st.worst && "outline outline-1 -outline-offset-2 outline-bad/40")}>
                                <Win p={v} className="text-base" />
                                {f != null && <span className="text-[11px] text-muted">先动 <span className="num">{pct0(f)}</span></span>}
                              </button>
                            </td>
                          );
                        })}
                        <td className="px-2 text-center"><Win p={st.worst} /></td>
                        <td className="px-2 text-center"><Win p={st.win} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="text-xs leading-relaxed text-muted">
                <div>混合策略：我方禁 {nash(b.rows, b.nash.mine)}；对方禁 {nash(b.cols, b.nash.theirs)}</div>
              </div>
            </div>
          );
        }}
      </Body>
    </Shell>
  );
}

// ---------------------------------------------------------------- 结果

export function ResultPanel({ q, onUndo, onNext }: {
  q: Latest<Advice>;
  onUndo: () => void;
  onNext: () => void;
}) {
  return (
    <Shell title="结果">
      <Body q={q} ok={(d) => d.phase === "done"}>
        {(d) => (
          <div className="flex flex-col items-center gap-2 py-4">
            <div className="text-sm text-muted">我方胜率</div>
            <Win p={d.win} className="text-5xl font-bold" />
            {d.first && <div className="text-sm text-muted">我方先动 <span className="num text-ink">{pct0(d.first.mine)}</span></div>}
          </div>
        )}
      </Body>
      <div className="flex justify-center gap-3">
        <button type="button" className="btn btn-ghost" onClick={onUndo}>撤销后禁</button>
        <button type="button" className="btn btn-go" onClick={onNext}>下一局</button>
      </div>
    </Shell>
  );
}
