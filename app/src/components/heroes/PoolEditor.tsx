// 英雄图鉴的英雄池模式（B14e2）：勾选自己有的英雄（可以填速度），RTA 助手只推荐这些。
// 只列选秀模型里有的英雄（B14h 用户意见），按发布日期排（同平时的图鉴，用户选）；点头像 = 勾选 / 取消。
// 右边一列是已勾的英雄和速度；改了 400ms 后自动保存（PUT /api/rta/pool）。没设置过时是默认的热门英雄（第 2 轮审核），
// 「恢复默认」删掉存的（DELETE /api/rta/pool）。
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { HeroFilters, HeroGrid, HeroIcon, PoolMark } from "@/components/heroes/HeroGrid";
import { confirmDialog } from "@/components/ui/Confirm";
import { toast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "@/lib/api";
import { filterHeroes, type Hero, type HeroFilter, type HeroList } from "@/lib/heroes";
import { RESET, SPEED_MAX, SPEED_MIN, autoSave, parseSpeed, setPoolSpeed, togglePool, type PoolHero } from "@/lib/pool";
import { qk } from "@/lib/query";
import { inModel } from "@/lib/rta";
import { cn } from "@/lib/utils";

const EMPTY_FILTER: HeroFilter = { query: "", element: null, role: null, rarity: null };

export function PoolEditor({ data, exitLabel, onExit }: { data: HeroList; exitLabel: string; onExit: () => void }) {
  const model = useQuery({ queryKey: qk.rtaModel, queryFn: () => api().rtaModel(), staleTime: Infinity, retry: false });
  const saved = useQuery({ queryKey: qk.rtaPool, queryFn: () => api().rtaPool(), staleTime: Infinity, retry: false });
  const failed = model.error ?? saved.error;
  const noModel = failed instanceof ApiError && failed.code === "no_model";
  return (
    <div className="flex h-full flex-col gap-3 px-[22px] py-4">
      <div className="flex items-center gap-3">
        <p className="min-w-0 flex-1 truncate text-muted">勾选你有的英雄，RTA 助手只推荐这些。</p>
        <button type="button" className="btn btn-sm btn-ghost" onClick={onExit}>
          <ArrowLeft className="size-4" />{exitLabel}
        </button>
      </div>
      {failed ? <p className="text-muted">{noModel ? "没有选秀模型，用不了英雄池。" : errorMessage(failed)}</p>
        : !model.data || !saved.data ? <p className="text-muted">加载中…</p>
          : <PoolBody data={data} codes={model.data.codes} initial={saved.data.heroes} initialDefault={!!saved.data.default} />}
    </div>
  );
}

type SaveState = "idle" | "saving" | "saved" | "error";

function PoolBody({ data, codes, initial, initialDefault }: {
  data: HeroList;
  codes: string[];
  initial: PoolHero[];
  initialDefault: boolean;
}) {
  const qc = useQueryClient();
  const [pool, setPool] = useState(initial);
  const [isDefault, setIsDefault] = useState(initialDefault);
  const [status, setStatus] = useState<SaveState>("idle");
  const [filter, setFilter] = useState<HeroFilter>(EMPTY_FILTER);
  const [onlyPicked, setOnlyPicked] = useState(false);

  const saver = useMemo(() => autoSave((c) => (c === RESET ? api().rtaResetPool() : api().rtaSavePool(c)), {
    saving: () => setStatus("saving"),
    saved: (p) => {
      qc.setQueryData(qk.rtaPool, p);
      if (p.default) setPool(p.heroes); // 恢复默认：换成引擎给的默认英雄
      setStatus("saved");
    },
    failed: (e) => {
      setStatus("error");
      toast(`英雄池没保存上：${errorMessage(e)}`, "error");
    },
  }), [qc]);
  // 离开页面时还没存的立刻存
  useEffect(() => () => saver.flush(), [saver]);

  const change = (next: PoolHero[]) => {
    setPool(next);
    setIsDefault(false);
    saver.change(next);
  };

  const usable = useMemo(() => inModel(data.heroes, codes), [data, codes]);
  const picked = useMemo(() => new Set(pool.map((h) => h.code)), [pool]);
  const shown = useMemo(
    () => filterHeroes(onlyPicked ? usable.filter((h) => picked.has(h.code)) : usable, filter),
    [usable, filter, onlyPicked, picked],
  );
  const byCode = useMemo(() => new Map(data.heroes.map((h) => [h.code, h])), [data]);
  // 右边一列和网格同样按发布日期排，好找
  const rows = useMemo(() => {
    const heroes = pool.map((p) => byCode.get(p.code)).filter((h): h is Hero => !!h);
    return filterHeroes(heroes, EMPTY_FILTER);
  }, [pool, byCode]);
  const speedOf = useMemo(() => new Map(pool.map((p) => [p.code, p.speed ?? null])), [pool]);

  const clear = async () => {
    if (await confirmDialog("清空英雄池", `去掉全部 ${pool.length} 名英雄和填的速度？一名都不勾时推荐全部英雄。`, "清空", true)) change([]);
  };
  const reset = async () => {
    if (!await confirmDialog("恢复默认", "换成本赛季最常被选的英雄，去掉你勾的和填的速度？", "恢复默认", true)) return;
    setIsDefault(true);
    saver.change(RESET);
    saver.flush();
  };

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px] gap-3">
      <div className="flex min-h-0 min-w-0 flex-col gap-3">
        <section className="panel flex flex-col gap-2 px-4 py-3">
          <HeroFilters data={data} filter={filter} onChange={(p) => setFilter((f) => ({ ...f, ...p }))} shrink
            onEnter={() => {
              const h = shown[0];
              if (h && !picked.has(h.code)) change(togglePool(pool, h.code));
              setFilter((f) => ({ ...f, query: "" }));
            }}>
            <span className="text-sm whitespace-nowrap text-muted">{`${shown.length} / ${usable.length} 名`}</span>
            <button type="button" className={cn("tab whitespace-nowrap", onlyPicked && "active")} aria-pressed={onlyPicked}
              onClick={() => setOnlyPicked((v) => !v)}>只看已勾选</button>
          </HeroFilters>
        </section>
        <div className="min-h-0 flex-1 overflow-auto">
          {shown.length === 0 && <p className="text-muted">{onlyPicked && !pool.length ? "还没有勾选英雄。" : "没有符合条件的英雄。"}</p>}
          <HeroGrid heroes={shown} data={data} onPick={(h) => change(togglePool(pool, h.code))}
            decor={(h) => (picked.has(h.code)
              ? { highlight: true, badge: <PoolMark />, title: `${h.name}（已勾选，点一下取消）` }
              : { title: `${h.name}（点一下勾选）` })} />
        </div>
      </div>

      <section className="panel flex min-h-0 flex-col gap-2 px-3 py-3" aria-label="英雄池">
        <header className="flex min-h-[30px] flex-none items-center gap-2 px-1">
          <span className="panel-title whitespace-nowrap">英雄池</span>
          <span className="num text-sm whitespace-nowrap text-muted">{pool.length} 名</span>
          {isDefault && <span className="rounded border border-white/15 px-1.5 text-[11px] leading-[18px] text-muted">默认</span>}
          <span className="flex-1" />
          <SaveStatus status={status} />
        </header>
        <p className="flex-none px-1 text-xs leading-relaxed text-faint">
          {isDefault && <span className="block text-muted">还没设置过，先用本赛季最常被选的英雄。</span>}
          速度可以不填，按段位的常见速度算。
        </p>
        <div className="min-h-0 flex-1 overflow-auto">
          {rows.length === 0 && <p className="px-1 py-6 text-center text-sm text-faint">点左边的头像勾选英雄；一名都不勾时推荐全部英雄</p>}
          {rows.map((h) => (
            <div key={h.code} className="flex h-11 items-center gap-2 rounded-lg px-1 hover:bg-white/4">
              <HeroIcon hero={h} data={data} size={34} plain />
              <span className="min-w-0 flex-1 truncate text-[13px]" title={h.name}>{h.name}</span>
              <SpeedInput name={h.name} value={speedOf.get(h.code) ?? null}
                onChange={(v) => change(setPoolSpeed(pool, h.code, v))} />
              <button type="button" className="grid size-7 flex-none cursor-pointer place-items-center rounded-md text-faint hover:bg-white/8 hover:text-bad"
                title={`去掉${h.name}`} aria-label={`去掉${h.name}`} onClick={() => change(togglePool(pool, h.code))}>
                <X className="size-4" />
              </button>
            </div>
          ))}
        </div>
        <footer className="flex flex-none justify-end gap-2 border-t border-white/8 px-1 pt-2">
          <button type="button" className="btn btn-sm btn-ghost" disabled={isDefault} onClick={() => void reset()}>恢复默认</button>
          <button type="button" className="btn btn-sm btn-ghost" disabled={!pool.length} onClick={() => void clear()}>全部清空</button>
        </footer>
      </section>
    </div>
  );
}

function SaveStatus({ status }: { status: SaveState }) {
  if (status === "idle") return null;
  return (
    <span className={cn("text-xs whitespace-nowrap", status === "error" ? "text-bad" : "text-faint")}>
      {status === "saving" ? "保存中…" : status === "saved" ? "已保存" : "没保存上"}
    </span>
  );
}

/** 速度输入：不合法时标红、不保存，离开输入框时退回原来的值。 */
function SpeedInput({ name, value, onChange }: { name: string; value: number | null; onChange: (v: number | null) => void }) {
  const [text, setText] = useState(value === null ? "" : String(value));
  const [bad, setBad] = useState(false);
  useEffect(() => {
    setText(value === null ? "" : String(value));
    setBad(false);
  }, [value]);
  return (
    <input className="field num h-[30px] w-[68px] flex-none px-2 text-center" inputMode="numeric" maxLength={3}
      placeholder="速度" aria-label={`${name}的速度`} aria-invalid={bad} value={text}
      title={`${SPEED_MIN}–${SPEED_MAX}；不填 = 按段位的常见速度`}
      onChange={(e) => {
        setText(e.target.value);
        const v = parseSpeed(e.target.value);
        setBad(v === undefined);
        if (v !== undefined && v !== value) onChange(v);
      }}
      onBlur={() => {
        if (!bad) return;
        setText(value === null ? "" : String(value));
        setBad(false);
      }} />
  );
}
