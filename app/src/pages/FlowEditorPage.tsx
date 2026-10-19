// 流程编辑器（B11）：左边步骤树（嵌套积木，可拖动），右边选中步骤的属性，底部保存 / 运行。
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useBlocker, useNavigate, useParams } from "react-router";
import { Num, StepPanel } from "@/components/flow/StepPanel";
import { StepTree } from "@/components/flow/StepTree";
import { confirmDialog } from "@/components/ui/Confirm";
import { Ornament } from "@/components/ui/Ornament";
import { toast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "@/lib/api";
import {
  FLOW_MODULE, type Flow, type ListAddr, type Step, duplicateStep, findStep, forEachStep, insertStep, localProblems,
  locateError, moveStep, newFlow, newStep, numbering, removeStep, stepRefs, updateStep, zhMessage, countSteps,
} from "@/lib/flow";
import { useTemplates } from "@/lib/flowHooks";
import { useNow } from "@/lib/hooks";
import { qk } from "@/lib/query";
import { useEngine } from "@/lib/store";
import { formatElapsed } from "@/lib/time";

export function FlowEditorPage() {
  const { id = "new" } = useParams();
  const isNew = id === "new";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({ queryKey: qk.flow(id), queryFn: () => api().flow(id), enabled: !isNew });
  const { byRef, label } = useTemplates();
  const [draft, setDraft] = useState<Flow | null>(isNew ? newFlow() : null);
  const [dirty, setDirty] = useState(isNew);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const [selected, setSelected] = useState<string | null>(null);
  const [serverProblems, setServerProblems] = useState<Map<string, string>>(new Map());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data && !dirtyRef.current) setDraft(data);
  }, [data]);

  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirtyRef.current && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    void confirmDialog("有没保存的修改", "离开这个页面会丢掉刚才的修改。", "不保存，离开", true).then((ok) =>
      ok ? blocker.proceed() : blocker.reset());
  }, [blocker]);

  const status = useEngine((s) => s.status);
  const flowStep = useEngine((s) => s.flowStep);
  const task = status?.task;
  const runningHere = task?.module === FLOW_MODULE && !!draft?.id && task.config.flow === draft.id;
  const connected = status?.device.connected ?? false;
  const now = useNow();

  const numbers = useMemo(() => numbering(draft?.steps ?? []), [draft?.steps]);
  const problems = useMemo(() => {
    const out = localProblems(draft?.steps ?? []);
    if (byRef.size) {
      forEachStep(draft?.steps ?? [], (s) => {
        const gone = stepRefs(s).filter((r) => !byRef.has(r));
        if (gone.length && !out.has(s.id)) out.set(s.id, `模板不存在：${gone.map(label).join("、")}`);
      });
    }
    for (const [k, v] of serverProblems) if (!out.has(k)) out.set(k, v);
    return out;
  }, [draft?.steps, byRef, label, serverProblems]);

  if (!isNew && isLoading) return <div className="p-6 text-muted">加载中…</div>;
  if (!draft) return <div className="p-6 text-bad">打不开这个流程：{errorMessage(error)}</div>;

  const edit = (fn: (f: Flow) => Flow) => {
    setDraft((d) => (d ? fn(d) : d));
    setDirty(true);
  };
  const editSteps = (fn: (s: Step[]) => Step[]) => edit((f) => ({ ...f, steps: fn(f.steps) }));

  const actions = {
    select: setSelected,
    insert: (addr: ListAddr, index: number, type: Step["type"]) => {
      const st = newStep(type);
      editSteps((s) => insertStep(s, addr, index, st));
      setSelected(st.id);
    },
    move: (sid: string, addr: ListAddr, index: number) => editSteps((s) => moveStep(s, sid, addr, index)),
    remove: (sid: string) => {
      editSteps((s) => removeStep(s, sid));
      if (selected && (selected === sid || !findStep(removeStep(draft.steps, sid), selected))) setSelected(null);
    },
    duplicate: (sid: string) => editSteps((s) => duplicateStep(s, sid)),
    nudge: (sid: string, delta: -1 | 1) =>
      editSteps((s) => {
        const hit = findStep(s, sid);
        return hit ? moveStep(s, sid, hit.addr, delta < 0 ? hit.index - 1 : hit.index + 2) : s;
      }),
  };

  const save = async (): Promise<string | null> => {
    if (!draft.name.trim()) {
      toast("先给流程起个名字", "error");
      return null;
    }
    setSaving(true);
    try {
      const saved = draft.id ? await api().saveFlow(draft.id, draft) : await api().createFlow(draft);
      dirtyRef.current = false;
      setDirty(false);
      setDraft(saved);
      setServerProblems(new Map());
      qc.setQueryData(qk.flow(saved.id), saved);
      void qc.invalidateQueries({ queryKey: qk.flows, exact: true });
      void qc.invalidateQueries({ queryKey: qk.module(FLOW_MODULE) });
      if (isNew) navigate(`/flows/${saved.id}`, { replace: true });
      toast("流程已保存");
      return saved.id;
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.detail)) {
        const map = new Map<string, string>();
        const general: string[] = [];
        for (const d of e.detail as { loc: (string | number)[]; msg: string }[]) {
          const sid = locateError(draft.steps, d.loc);
          if (sid) map.set(sid, zhMessage(d.msg));
          else general.push(zhMessage(d.msg));
        }
        setServerProblems(map);
        toast(`没有保存：${general[0] ?? `有 ${map.size} 步需要修改（标红的）`}`, "error");
      } else {
        toast(`没有保存：${errorMessage(e)}`, "error");
      }
      return null;
    } finally {
      setSaving(false);
    }
  };

  const run = async () => {
    const fid = dirty || !draft.id ? await save() : draft.id;
    if (!fid) return;
    try {
      await api().startTask(FLOW_MODULE, { flow: fid });
      toast("流程开始运行");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  const sel = selected ? findStep(draft.steps, selected) : null;
  const runningStep = runningHere && flowStep?.flow === draft.id ? flowStep.id : null;
  const otherTask = task && !runningHere;
  const reason = !connected ? "模拟器未连接" : otherTask ? "有别的任务在运行" : draft.steps.length === 0 ? "还没有步骤" : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-end gap-3 px-[22px] pt-4 pb-3">
        <button type="button" className="btn btn-ghost btn-sm mb-0.5" onClick={() => navigate("/flows")}><ChevronLeft className="size-4" />我的流程</button>
        <label className="flex flex-col gap-1 text-xs text-muted">
          流程名
          <input className="field h-10 w-64 text-base font-bold" maxLength={40} value={draft.name}
            onChange={(e) => edit((f) => ({ ...f, name: e.target.value }))} aria-label="流程名" />
        </label>
        <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-xs text-muted">
          说明
          <input className="field h-10 w-full" maxLength={500} value={draft.description} placeholder="这个流程做什么（可选）"
            onChange={(e) => edit((f) => ({ ...f, description: e.target.value }))} aria-label="说明" />
        </label>
        <div className="flex items-center gap-3 rounded-[10px] border border-white/8 bg-black/25 px-3 py-1.5 text-sm" title="流程最多运行多久、点多少次">
          <ShieldCheck className="size-4 text-gold" />
          最多
          <Num value={draft.limits.max_minutes} min={0.5} max={120} suffix="分钟" onChange={(v) => edit((f) => ({ ...f, limits: { ...f.limits, max_minutes: v } }))} />
          <Num int value={draft.limits.max_taps} min={1} max={5000} suffix="次点击" onChange={(v) => edit((f) => ({ ...f, limits: { ...f.limits, max_taps: v } }))} />
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] gap-3.5 px-[22px] pb-4">
        {/* 只在点面板空白处时取消选择（弹出菜单的点击会经 React 冒泡上来） */}
        <section className="panel min-h-0 overflow-auto px-3 py-3" onClick={(e) => e.target === e.currentTarget && setSelected(null)}>
          <StepTree steps={draft.steps} selected={selected} numbers={numbers} problems={problems} running={runningStep}
            label={label} readOnly={false} {...actions} />
        </section>
        <section className="panel min-h-0 overflow-auto px-4 py-3.5">
          {sel ? (
            <StepPanel key={sel.step.id} step={sel.step} number={numbers.get(sel.step.id) ?? ""} problem={problems.get(sel.step.id)}
              update={(fn) => editSteps((s) => updateStep(s, sel.step.id, fn))}
              onRemove={() => actions.remove(sel.step.id)} onDuplicate={() => actions.duplicate(sel.step.id)} />
          ) : (
            <Overview steps={draft.steps} />
          )}
        </section>
      </div>

      <div className="relative flex items-center gap-4 bg-[#080c18]/62 px-[22px] py-4 backdrop-blur-sm">
        <Ornament className="absolute inset-x-[22px] top-0.5" />
        <span className="text-sm">
          {dirty ? <span className="text-warn">有没保存的修改</span> : <span className="text-muted">已保存</span>}
          {problems.size > 0 && <span className="ml-3 text-bad">{problems.size} 步需要修改</span>}
        </span>
        <span className="flex-1" />
        <button type="button" className="btn btn-bronze btn-lg min-w-[140px]" disabled={saving || !dirty} onClick={() => void save()}>保存</button>
        {runningHere ? (
          <button type="button" className="btn btn-lg btn-real min-w-[200px]" onClick={() => void api().stopTask().catch((e) => toast(errorMessage(e), "error"))}>
            <span className="chip num">{formatElapsed(now / 1000 - task!.started)}</span>停止
          </button>
        ) : (
          <button type="button" className="btn btn-lg btn-go min-w-[200px]" disabled={!!reason || saving} title={reason ?? undefined} onClick={() => void run()}>
            {reason ?? (dirty ? "保存并运行" : "运行")}
          </button>
        )}
      </div>
    </div>
  );
}

function Overview({ steps }: { steps: Step[] }) {
  return (
    <div className="flex flex-col gap-3 text-sm leading-6">
      <h3 className="panel-title">怎么编辑</h3>
      <ul className="list-disc pl-5 text-muted">
        <li>点左边的「添加步骤」加一步，点一步在这里改它。</li>
        <li>拖动步骤左边的 <span className="text-ink">⋮⋮</span> 调整顺序，也可以拖进「如果」「重复」里面。</li>
        <li>现在一共 <span className="num text-ink">{countSteps(steps)}</span> 步。</li>
      </ul>
    </div>
  );
}
