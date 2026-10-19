// 流程编辑器右侧：选中步骤的属性。
import { Copy, Crosshair, ScanSearch, Trash2, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Check } from "@/components/ui/Check";
import { Select } from "@/components/ui/Select";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { type Condition, SCENES, STEP_LABELS, type Step, type StepOf, newCondition } from "@/lib/flow";
import { useTemplates } from "@/lib/flowHooks";
import { useEngine } from "@/lib/store";
import { cn } from "@/lib/utils";
import { PointPicker, TemplatePicker, TemplateThumb } from "./Pickers";
import { STEP_ICONS } from "./StepTree";

const SCENE_OPTIONS = Object.entries(SCENES).map(([value, label]) => ({ value, label }));
const MISSING_OPTIONS = [
  { value: "stop", label: "停止流程（记为失败）" },
  { value: "skip", label: "跳过这一步，接着往下" },
];

const HINTS: Partial<Record<Step["type"], string>> = {
  tap_template: "等模板出现，然后点它。模板设了「能点的地方」时点那里。",
  tap_point: "点画面上固定的位置。界面位置会变的按钮用「点击模板」更稳。",
  swipe: "从起点滑到终点，用来翻页、滚动列表。",
  back: "按安卓返回键，大多数界面会回到上一层。在大厅按会弹「结束游戏」确认框——会自动点取消。",
  wait: "什么都不做，等一段时间（例如等动画、等加载）。",
  wait_still: "等画面不再变化（静止 0.5 秒），一直在动就等到上限后继续。",
  wait_template: "等某个模板出现或消失。",
  wait_scene: "等回到助手认识的界面，并等画面静止。途中断线会自动重进游戏。",
  end: "流程到这里就结束。",
  break: "跳出所在的「重复」，接着做循环后面的步骤。",
  if: "看条件成不成立，分别做「那么」或「否则」里的步骤。",
  repeat: "反复做里面的步骤。每个循环都必须有次数上限。",
};

export function StepPanel({
  step, number, update, onRemove, onDuplicate, problem,
}: {
  step: Step;
  number: string;
  update: (fn: (s: Step) => Step) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  problem?: string;
}) {
  const Icon = STEP_ICONS[step.type];
  const set = <T extends Step>(patch: Partial<T>) => update((s) => ({ ...s, ...patch }) as Step);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2.5">
        <span className="medal size-10"><Icon className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-xs text-muted">第 <span className="num">{number}</span> 步</div>
          <div className="text-base font-bold">{STEP_LABELS[step.type]}</div>
        </div>
        <button type="button" className="grid size-8 cursor-pointer place-items-center rounded-lg text-muted hover:bg-white/8 hover:text-ink"
          title="复制这一步" aria-label="复制这一步" onClick={onDuplicate}><Copy className="size-4" /></button>
        <button type="button" className="grid size-8 cursor-pointer place-items-center rounded-lg text-muted hover:bg-white/8 hover:text-bad"
          title="删除这一步" aria-label="删除这一步" onClick={onRemove}><Trash2 className="size-4" /></button>
      </div>
      {HINTS[step.type] && <p className="text-xs leading-5 text-muted">{HINTS[step.type]}</p>}
      {problem && <p className="rounded-lg bg-bad/12 px-3 py-1.5 text-xs text-[#ffd2c8]">{problem}</p>}
      <Fields step={step} set={set} />
      <Row label="备注">
        <input className="field w-full" maxLength={200} value={step.note} placeholder="写给自己看的说明（可选）"
          onChange={(e) => set({ note: e.target.value })} />
      </Row>
    </div>
  );
}

function Fields({ step, set }: { step: Step; set: <T extends Step>(patch: Partial<T>) => void }) {
  switch (step.type) {
    case "tap_template":
      return (
        <>
          <Row label="要点的模板"><TemplateField value={step.template ? [step.template] : []} onChange={(r) => set({ template: r[0] ?? "" })} /></Row>
          <Row label="最多等" inline><Num value={step.timeout} min={0} max={300} suffix="秒" onChange={(v) => set({ timeout: v })} /></Row>
          <Row label="找不到时" inline><Opt value={step.on_missing} options={MISSING_OPTIONS} onChange={(v) => set({ on_missing: v as "stop" })} /></Row>
          <Toggle checked={step.settle} onChange={(v) => set({ settle: v })} label="点之前等画面静止" hint="界面切换动画期间点击会被游戏忽略，一般保持勾选" />
        </>
      );
    case "tap_point":
      return <PointFields step={step} set={set} />;
    case "swipe":
      return <SwipeFields step={step} set={set} />;
    case "wait":
      return <Row label="等待" inline><Num value={step.seconds} min={0.1} max={300} suffix="秒" onChange={(v) => set({ seconds: v })} /></Row>;
    case "wait_still":
      return <Row label="最多等" inline><Num value={step.timeout} min={0} max={300} suffix="秒" onChange={(v) => set({ timeout: v })} /></Row>;
    case "wait_template":
      return (
        <>
          <Row label="模板（任一）"><TemplateField multiple value={step.templates} onChange={(r) => set({ templates: r })} /></Row>
          <Row label="等它" inline>
            <Opt value={step.appear ? "1" : "0"} options={[{ value: "1", label: "出现" }, { value: "0", label: "消失" }]}
              onChange={(v) => set({ appear: v === "1" })} />
          </Row>
          <Row label="最多等" inline><Num value={step.timeout} min={0} max={300} suffix="秒" onChange={(v) => set({ timeout: v })} /></Row>
          <Row label="等不到时" inline><Opt value={step.on_missing} options={MISSING_OPTIONS} onChange={(v) => set({ on_missing: v as "stop" })} /></Row>
        </>
      );
    case "wait_scene":
      return (
        <>
          <Row label="界面" inline><Opt value={step.scene} options={SCENE_OPTIONS} onChange={(v) => set({ scene: v })} /></Row>
          <Row label="最多等" inline><Num value={step.timeout} min={0} max={300} suffix="秒" onChange={(v) => set({ timeout: v })} /></Row>
          <Row label="等不到时" inline><Opt value={step.on_missing} options={MISSING_OPTIONS} onChange={(v) => set({ on_missing: v as "stop" })} /></Row>
        </>
      );
    case "end":
      return (
        <>
          <Row label="结果" inline>
            <Opt value={step.success ? "1" : "0"} options={[{ value: "1", label: "成功" }, { value: "0", label: "失败" }]}
              onChange={(v) => set({ success: v === "1" })} />
          </Row>
          <Row label="说明">
            <input className="field w-full" maxLength={200} value={step.message} placeholder="例如：今天已经领过了"
              onChange={(e) => set({ message: e.target.value })} />
          </Row>
        </>
      );
    case "if":
      return <ConditionEditor value={step.condition} onChange={(c) => set({ condition: c })} />;
    case "repeat":
      return <RepeatFields step={step} set={set} />;
    default:
      return null;
  }
}

function RepeatFields({ step, set }: { step: StepOf<"repeat">; set: <T extends Step>(patch: Partial<T>) => void }) {
  return (
    <>
      <Row label="怎么重复">
        <Opt value={step.mode} className="w-full"
          options={[
            { value: "times", label: "重复固定次数" },
            { value: "until", label: "重复，直到条件成立" },
            { value: "while", label: "条件成立时一直重复" },
          ]}
          onChange={(v) => set({ mode: v as "times", condition: v === "times" ? step.condition : step.condition ?? newCondition() })} />
      </Row>
      <Row label={step.mode === "times" ? "次数" : "最多几轮"} inline>
        <Num int value={step.count} min={1} max={999} suffix={step.mode === "times" ? "次" : "轮"} onChange={(v) => set({ count: v })} />
      </Row>
      {step.mode !== "times" && step.condition && (
        <>
          <p className="text-xs text-muted">{step.mode === "until" ? "每一轮开始前看条件，成立就不再重复。" : "每一轮开始前看条件，不成立就不再重复。"}</p>
          <ConditionEditor value={step.condition} onChange={(c) => set({ condition: c })} />
          <Row label={`跑满 ${step.count} 轮后`} inline>
            <Opt value={step.on_limit} options={[{ value: "stop", label: "停止流程（失败）" }, { value: "continue", label: "接着往下" }]}
              onChange={(v) => set({ on_limit: v as "stop" })} />
          </Row>
        </>
      )}
    </>
  );
}

function ConditionEditor({ value, onChange }: { value: Condition; onChange: (c: Condition) => void }) {
  const c = value;
  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-gold-line/40 bg-black/20 p-3">
      <div className="text-xs font-bold text-gold">条件</div>
      <Row label="看什么" inline>
        <Opt value={c.kind} options={[{ value: "template", label: "模板" }, { value: "scene", label: "在哪个界面" }]}
          onChange={(v) => onChange({ ...c, kind: v as "template", scene: c.scene ?? "lobby" })} />
      </Row>
      {c.kind === "template" ? (
        <>
          <Row label="模板（任一）"><TemplateField multiple value={c.templates} onChange={(r) => onChange({ ...c, templates: r })} /></Row>
          <Row label="成立条件" inline>
            <Opt value={c.appear ? "1" : "0"} options={[{ value: "1", label: "出现" }, { value: "0", label: "不出现" }]}
              onChange={(v) => onChange({ ...c, appear: v === "1" })} />
          </Row>
        </>
      ) : (
        <>
          <Row label="界面" inline><Opt value={c.scene ?? "lobby"} options={SCENE_OPTIONS} onChange={(v) => onChange({ ...c, scene: v })} /></Row>
          <Row label="成立条件" inline>
            <Opt value={c.appear ? "1" : "0"} options={[{ value: "1", label: "在这个界面" }, { value: "0", label: "不在这个界面" }]}
              onChange={(v) => onChange({ ...c, appear: v === "1" })} />
          </Row>
        </>
      )}
      <Row label="最多等" inline hint="0 = 只看当前画面">
        <Num value={c.wait} min={0} max={300} suffix="秒" onChange={(v) => onChange({ ...c, wait: v })} />
      </Row>
    </div>
  );
}

function PointFields({ step, set }: { step: StepOf<"tap_point">; set: <T extends Step>(patch: Partial<T>) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Row label="位置" inline>
        <span className="flex items-center gap-1.5">
          <Num int value={step.x} min={0} max={1600} onChange={(v) => set({ x: v })} label="x" />
          <Num int value={step.y} min={0} max={900} onChange={(v) => set({ y: v })} label="y" />
        </span>
      </Row>
      <button type="button" className="btn btn-bronze btn-sm w-fit" onClick={() => setOpen(true)}><Crosshair className="size-4" />在画面上点选</button>
      {open && (
        <PointPicker open mode="point" point={[step.x, step.y]} onClose={() => setOpen(false)}
          onPick={({ point }) => point && set({ x: point[0], y: point[1] })} />
      )}
    </>
  );
}

function SwipeFields({ step, set }: { step: StepOf<"swipe">; set: <T extends Step>(patch: Partial<T>) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Row label="起点" inline>
        <span className="flex items-center gap-1.5">
          <Num int value={step.x1} min={0} max={1600} onChange={(v) => set({ x1: v })} label="x" />
          <Num int value={step.y1} min={0} max={900} onChange={(v) => set({ y1: v })} label="y" />
        </span>
      </Row>
      <Row label="终点" inline>
        <span className="flex items-center gap-1.5">
          <Num int value={step.x2} min={0} max={1600} onChange={(v) => set({ x2: v })} label="x" />
          <Num int value={step.y2} min={0} max={900} onChange={(v) => set({ y2: v })} label="y" />
        </span>
      </Row>
      <Row label="用时" inline><Num value={step.duration} min={0.1} max={3} suffix="秒" onChange={(v) => set({ duration: v })} /></Row>
      <button type="button" className="btn btn-bronze btn-sm w-fit" onClick={() => setOpen(true)}><Crosshair className="size-4" />在画面上画</button>
      {open && (
        <PointPicker open mode="line" line={[[step.x1, step.y1], [step.x2, step.y2]]} onClose={() => setOpen(false)}
          onPick={({ line }) => line && set({ x1: line[0][0], y1: line[0][1], x2: line[1][0], y2: line[1][1] })} />
      )}
    </>
  );
}

/** 选模板（单个或几个），带缩略图和「在当前画面上找」。 */
function TemplateField({ value, onChange, multiple }: { value: string[]; onChange: (refs: string[]) => void; multiple?: boolean }) {
  const { label, byRef } = useTemplates();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      {value.map((ref) => (
        <div key={ref} className="flex items-center gap-2 rounded-lg bg-black/30 px-2 py-1.5">
          <span className="grid h-9 w-16 flex-none place-items-center overflow-hidden rounded bg-black/40"><TemplateThumb tref={ref} /></span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm">{label(ref)}</span>
            {!byRef.has(ref) ? <span className="text-xs text-bad">模板不存在（被删了？）</span>
              : ref.startsWith("common:") && <span className="text-xs text-faint">内置</span>}
          </span>
          {multiple && (
            <button type="button" className="grid size-6 cursor-pointer place-items-center rounded text-muted hover:text-bad" aria-label={`去掉 ${label(ref)}`}
              onClick={() => onChange(value.filter((r) => r !== ref))}><X className="size-3.5" /></button>
          )}
        </div>
      ))}
      <div className="flex flex-wrap gap-1.5">
        <button type="button" className="btn btn-bronze btn-sm" onClick={() => setOpen(true)}>
          {value.length === 0 ? "选择模板" : multiple ? "增减模板" : "更换"}
        </button>
        {value.length > 0 && <TestButton refs={value} />}
      </div>
      {open && <TemplatePicker open multiple={multiple} value={value} onChange={onChange} onClose={() => setOpen(false)} />}
    </div>
  );
}

function TestButton({ refs }: { refs: string[] }) {
  const connected = useEngine((s) => s.status?.device.connected ?? false);
  const { label } = useTemplates();
  const [result, setResult] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  useEffect(() => setResult(null), [refs.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
  const test = async () => {
    try {
      const res = await api().testTemplates(refs);
      const hits = res.results.filter((r) => r.hit);
      setOk(hits.length > 0);
      if (hits.length) setResult(`找到了：${hits.map((h) => `「${label(h.ref)}」${h.score?.toFixed(2)}`).join("、")}`);
      else {
        const best = Math.max(...res.results.map((r) => r.score ?? 0));
        setResult(`当前画面上没找到（最像的 ${best.toFixed(2)}）`);
      }
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };
  return (
    <>
      <button type="button" className="btn btn-ghost btn-sm" disabled={!connected} title={connected ? "只截图，不点击" : "模拟器未连接"} onClick={test}>
        <ScanSearch className="size-4" />在当前画面上找
      </button>
      {result && <span className={cn("w-full text-xs", ok ? "text-ok" : "text-warn")}>{result}</span>}
    </>
  );
}

// ---------------------------------------------------------------- 小部件

function Row({ label, children, inline, hint }: { label: string; children: ReactNode; inline?: boolean; hint?: string }) {
  return (
    <div className={cn("flex gap-2", inline ? "items-center justify-between" : "flex-col")}>
      <span className="text-sm text-muted">
        {label}
        {hint && <span className="block text-[11px] text-faint">{hint}</span>}
      </span>
      {children}
    </div>
  );
}

function Opt({ value, options, onChange, className }: { value: string; options: { value: string; label: string }[]; onChange: (v: string) => void; className?: string }) {
  return <Select value={value} options={options} onChange={onChange} label="选择" className={cn("text-sm", className)} />;
}

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <Check checked={checked} onChange={onChange} label={label} />
      <span>
        {label}
        {hint && <span className="block text-[11px] text-faint">{hint}</span>}
      </span>
    </label>
  );
}

/** 数字输入：输入过程中保留原文，合法时才提交。 */
export function Num({ value, onChange, min, max, suffix, int, label }: {
  value: number; onChange: (v: number) => void; min: number; max: number; suffix?: string; int?: boolean; label?: string;
}) {
  const [text, setText] = useState(String(value));
  const [bad, setBad] = useState(false);
  useEffect(() => setText(String(value)), [value]);
  return (
    <span className="flex items-center gap-1.5">
      {label && <span className="text-xs text-faint">{label}</span>}
      <input className="field num h-8 w-20 text-right" inputMode="decimal" value={text} aria-invalid={bad} aria-label={label ?? suffix ?? "数值"}
        title={`${min}–${max}`}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value);
          const okNum = e.target.value.trim() !== "" && Number.isFinite(n) && n >= min && n <= max && (!int || Number.isInteger(n));
          setBad(!okNum);
          if (okNum) onChange(n);
        }} />
      {suffix && <span className="text-sm text-muted">{suffix}</span>}
    </span>
  );
}
