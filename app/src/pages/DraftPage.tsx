// RTA 助手（B14e1）：五步手动模式（准备 / 预禁 / 选秀 / 后禁 / 结果），布局参考 e7rtabot.com/draft（用户意见）：
// 准备是一张居中的卡片；预禁和选秀左边是这一步的内容、右边是英雄网格（按本赛季出场次数排）；选秀 / 后禁 / 结果
// 左边上面是信息条，下面双方阵容并排，再下面是推荐 / 后禁矩阵 / 结果。推荐来自引擎 /api/rta/*，胜率一律是我方的；
// 先动概率引擎给了才显示（还没有速度表时整块不出现）。
import { useQuery } from "@tanstack/react-query";
import { RotateCcw, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { HeroFilters, HeroGrid, type HeroCellDecor } from "@/components/heroes/HeroGrid";
import { HeroesCtx, RankBadge, useHeroes } from "@/components/rta/bits";
import { BanPanel, InfoBar, MinePanel, PrebanPanel, ResultPanel, SetupPanel, TheirsPanel } from "@/components/rta/Panels";
import { TeamColumn, type SlotSuggest } from "@/components/rta/TeamColumn";
import { ApiError, api, errorMessage } from "@/lib/api";
import {
  STEPS, addPicks, addPreban, apiState, prebanTarget, removePreban, ruleFor, setBan, setPrebans, stepOf, taken,
  teamPicks, turn, type Draft, type Step, type Team,
} from "@/lib/draft";
import { useDraft } from "@/lib/draftStore";
import { filterHeroes, type Hero, type HeroFilter } from "@/lib/heroes";
import { qk } from "@/lib/query";
import {
  inModel, pct0, pct1, useLatest, type Advice, type AdviseBody, type PrebanAdvice, type PrebanBody, type RtaModelInfo, type RtaPriors,
} from "@/lib/rta";
import { cn } from "@/lib/utils";

// 结果按局面缓存在页面外（切到别的页面再回来、撤销回去都不用再算）
const adviceCache = new Map<string, Advice>();
const prebanCache = new Map<string, PrebanAdvice>();
const fetchAdvice = (key: string) => api().rtaAdvise(JSON.parse(key) as AdviseBody);
const fetchPreban = (key: string) => api().rtaPreban(JSON.parse(key) as PrebanBody);

const EMPTY_FILTER: HeroFilter = { query: "", element: null, role: null, rarity: null };
/** 右边英雄网格那一栏的宽度（一行 5 个头像） */
const PICKER_COLS = "grid-cols-[minmax(0,1fr)_360px]";

export function DraftPage() {
  const heroes = useQuery({ queryKey: qk.heroes, queryFn: () => api().heroes(), staleTime: Infinity });
  const model = useQuery({ queryKey: qk.rtaModel, queryFn: () => api().rtaModel(), staleTime: Infinity, retry: false });
  const priors = useQuery({ queryKey: qk.rtaPriors, queryFn: () => api().rtaPriors(), staleTime: Infinity, retry: false });
  const byCode = useMemo(() => new Map((heroes.data?.heroes ?? []).map((h) => [h.code, h])), [heroes.data]);
  const ctx = useMemo(() => (heroes.data ? { data: heroes.data, byCode } : null), [heroes.data, byCode]);

  const failed = model.error ?? priors.error ?? heroes.error;
  if (failed) {
    const noModel = failed instanceof ApiError && failed.code === "no_model";
    return <Message text={noModel ? "没有选秀模型，用不了选秀推荐。" : errorMessage(failed)} />;
  }
  if (!ctx || !model.data || !priors.data) return <Message text="加载中…" />;
  return (
    <HeroesCtx.Provider value={ctx}>
      <Draft_ model={model.data} priors={priors.data} />
    </HeroesCtx.Provider>
  );
}

function Message({ text }: { text: string }) {
  return <p className="px-[22px] py-4 text-muted">{text}</p>;
}

function Draft_({ model, priors }: { model: RtaModelInfo; priors: RtaPriors }) {
  const { draft, history, apply, undo, restart } = useDraft();
  const step = stepOf(draft);
  const opts = model.options;
  const rule = ruleFor(draft.setup);

  // 推荐请求：预禁一步用 preban，之后用 advise（局面变了只算最新的）
  const prebanKey = step === "preban"
    ? JSON.stringify({
      side: draft.setup.side, grades: draft.setup.grades, rule,
      fixed: draft.prebans.mine.length === 1 ? draft.prebans.mine[0] : null,
    } satisfies PrebanBody)
    : null;
  const adviceKey = step === "pick" || step === "ban" || step === "result"
    ? JSON.stringify({ side: draft.setup.side, state: apiState(draft, rule) } satisfies AdviseBody)
    : null;
  const preban = useLatest(prebanKey, fetchPreban, prebanCache);
  const advice = useLatest(adviceKey, fetchAdvice, adviceCache);

  // Ctrl+Z 撤销（输入框里的不管）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !(e.target instanceof HTMLInputElement)) {
        e.preventDefault();
        undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo]);

  const pick = (heroes: string[], team?: Team) => apply((d) => addPicks(d, heroes, team));
  const ban = (team: Team, code: string) => apply((d) => setBan(d, team, code));
  // 网格上的推荐名次只用当前局面的结果（旧局面的会标错人）
  const pickAdvice = advice.fresh && advice.data?.phase === "pick" ? advice.data : undefined;
  const suggest = useMemo(() => slotSuggest(pickAdvice), [pickAdvice]);
  const picker = (
    <HeroPicker draft={draft} codes={model.codes} priors={priors} preban={preban.fresh ? preban.data : undefined} advice={pickAdvice}
      onPick={(code) => apply((d) => (step === "preban" ? addPrebanNext(d, code) : addPicks(d, [code])))} />
  );

  return (
    <div className="flex h-full flex-col gap-3 px-[18px] py-3">
      <header className="flex flex-none items-center gap-3">
        <Steps step={step} />
        <span className="flex-1" />
        <button type="button" className="btn btn-sm btn-ghost" disabled={!history.length} onClick={undo} title="撤销（Ctrl+Z）">
          <Undo2 className="size-4" />撤销
        </button>
        <button type="button" className="btn btn-sm btn-bronze" disabled={step === "setup" && !history.length} onClick={restart}>
          <RotateCcw className="size-4" />重新开始
        </button>
      </header>

      {step === "setup" && (
        <div className="min-h-0 flex-1 overflow-auto">
          <SetupPanel setup={draft.setup} options={opts} onChange={(s) => apply((d) => ({ ...d, setup: s }))}
            onStart={() => apply((d) => ({ ...d, phase: "preban" }))} />
        </div>
      )}

      {step === "preban" && (
        <div className={cn("grid min-h-0 flex-1 gap-3", PICKER_COLS)}>
          <PrebanPanel draft={draft} q={preban} onMine={(h) => apply((d) => setPrebans(d, "mine", h))}
            onTheirs={(h) => apply((d) => setPrebans(d, "theirs", h))}
            onRemove={(team, c) => apply((d) => removePreban(d, team, c))}
            onBack={() => apply((d) => ({ ...d, phase: "setup" }))}
            onStart={() => apply((d) => ({ ...d, phase: "draft" }))} />
          {picker}
        </div>
      )}

      {(step === "pick" || step === "ban" || step === "result") && (
        <div className={cn("grid min-h-0 flex-1 gap-3", step === "pick" ? PICKER_COLS : "grid-cols-1")}>
          <div className="flex min-h-0 min-w-0 flex-col gap-3">
            <InfoBar draft={draft} options={opts} advice={advice} />
            <div className="grid flex-none grid-cols-2 gap-3">
              <TeamColumn team="mine" draft={draft} onBan={(c) => ban("theirs", c)} row={step !== "pick"}
                suggest={pickAdvice?.turn === "mine" ? suggest : undefined} onSuggest={(c) => pick([c], "mine")} />
              <TeamColumn team="theirs" draft={draft} onBan={(c) => ban("mine", c)} row={step !== "pick"}
                suggest={pickAdvice?.turn === "theirs" ? suggest : undefined} onSuggest={(c) => pick([c], "theirs")} />
            </div>
            {step === "pick" && turn(draft)?.team === "mine" && <MinePanel draft={draft} q={advice} onPick={(h) => pick(h, "mine")} />}
            {step === "pick" && turn(draft)?.team === "theirs" && <TheirsPanel draft={draft} q={advice} onPick={(h) => pick(h, "theirs")} />}
            {step === "ban" && (
              <BanPanel draft={draft} q={advice} onBan={ban}
                onBoth={(m, t) => apply((d) => setBan(setBan(d, "mine", m, false), "theirs", t, false))} />
            )}
            {step === "result" && <ResultPanel q={advice} onUndo={undo} onNext={restart} />}
          </div>
          {step === "pick" && picker}
        </div>
      )}
    </div>
  );
}

/**
 * 正在选的格子里直接给的前 3 名：我方按推荐（两手回合按英雄，带它所在那组的预期胜率）；
 * 对方按可能的选择（两手回合把每名英雄所在各组的可能性加起来）。
 */
function slotSuggest(a: Advice | undefined): SlotSuggest[] {
  if (!a) return [];
  if (a.turn === "mine") {
    const items = a.heroes?.length ? a.heroes.map((h) => ({ code: h.code, win: h.win }))
      : (a.recommend ?? []).map((r) => ({ code: r.heroes[0], win: r.win }));
    return items.slice(0, 3).map((x) => ({ code: x.code, label: pct1(x.win) }));
  }
  const prob = new Map<string, number>();
  for (const c of a.opponent?.likely ?? []) for (const h of c.heroes) prob.set(h, (prob.get(h) ?? 0) + c.prob);
  return [...prob].sort((x, y) => y[1] - x[1]).slice(0, 3).map(([code, p]) => ({ code, label: pct0(p) }));
}

/** 预禁这一步点英雄：填进还没填满的那一队（先我方后对方）。 */
function addPrebanNext(d: Draft, code: string): Draft {
  const t = prebanTarget(d);
  return t ? addPreban(d, t, code) : d;
}

function Steps({ step }: { step: Step }) {
  const at = STEPS.findIndex((s) => s.key === step);
  return (
    <ol className="flex items-center gap-1.5" aria-label="步骤">
      {STEPS.map((s, i) => (
        <li key={s.key} className="flex items-center gap-1.5">
          {i > 0 && <span className={cn("h-px w-5", i <= at ? "bg-gold/70" : "bg-white/15")} />}
          <span aria-current={i === at ? "step" : undefined}
            className={cn("tab inline-flex items-center gap-1.5 px-3 py-1 text-[13px]", i === at && "active", i < at && "border-gold/40 text-gold")}>
            <span className="num">{i + 1}</span>{s.label}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** 右边的英雄网格：只有模型里有的英雄，按本赛季出场次数排（预禁时按预禁次数），不能选的变灰，推荐的标名次。 */
function HeroPicker({ draft, codes, priors, preban, advice, onPick }: {
  draft: Draft;
  codes: string[];
  priors: RtaPriors;
  preban?: PrebanAdvice;
  advice?: Advice;
  onPick: (code: string) => void;
}) {
  const { data } = useHeroes();
  const [filter, setFilter] = useState<HeroFilter>(EMPTY_FILTER);
  const step = stepOf(draft);
  const isPreban = step === "preban";
  const score = useCallback((h: Hero) => {
    const p = priors.heroes[h.code];
    return p ? (isPreban ? p.preban * 1e9 : 0) + p.picks : 0;
  }, [priors, isPreban]);
  const usable = useMemo(() => inModel(data.heroes, codes), [data, codes]);
  const shown = useMemo(() => filterHeroes(usable, filter, score), [usable, filter, score]);

  // 推荐名次：预禁 → 我方预禁推荐里的英雄；轮到我方 → 推荐（两手回合按英雄）；轮到对方 → 对方可能选的
  const ranks = useMemo(() => {
    const m = new Map<string, number>();
    const add = (codes: string[]) => codes.forEach((c) => m.has(c) || m.set(c, m.size + 1));
    if (isPreban && preban) add(preban.heroes.map((h) => h.code));
    else if (advice?.turn === "mine") {
      if (advice.heroes?.length) add(advice.heroes.map((h) => h.code));
      else (advice.recommend ?? []).forEach((r) => add(r.heroes));
    } else if (advice?.turn === "theirs") (advice.opponent?.likely ?? []).forEach((c) => add(c.heroes));
    return m;
  }, [isPreban, preban, advice]);

  const used = taken(draft);
  const target = isPreban ? prebanTarget(draft) : turn(draft)?.team ?? null;
  const blocked = (code: string) => {
    if (target === null) return true;
    if (isPreban) return draft.prebans[target].includes(code);
    return used.has(code);
  };
  const decor = (h: Hero): HeroCellDecor | undefined => {
    if (blocked(h.code)) return { disabled: true };
    const r = ranks.get(h.code);
    return r && r <= 10 ? { badge: <RankBadge n={r} tone={target === "theirs" ? "blue" : "gold"} /> } : undefined;
  };
  const pickOne = (code: string) => {
    if (blocked(code)) return;
    onPick(code);
    setFilter((f) => ({ ...f, query: "" }));
  };
  const n = teamPicks(draft, target ?? "mine").length + 1;
  const hint = target === null ? ""
    : isPreban ? `点英雄填${target === "mine" ? "我方" : "对方"}预禁`
      : `点英雄填${target === "mine" ? "我方" : "对方"}第 ${n} 名`;

  return (
    <section className="panel flex min-h-0 flex-col gap-2 px-4 py-3">
      <HeroFilters data={data} filter={filter} onChange={(p) => setFilter((f) => ({ ...f, ...p }))} rarity={false} inputWidth="w-full" compact
        onEnter={() => {
          const h = shown.find((x) => !blocked(x.code));
          if (h) pickOne(h.code);
        }}>
        <span className="text-xs text-muted">{hint}</span>
      </HeroFilters>
      <div className="min-h-0 flex-1 overflow-auto">
        <HeroGrid heroes={shown} data={data} size={50} decor={decor} onPick={(h) => pickOne(h.code)} />
      </div>
    </section>
  );
}
