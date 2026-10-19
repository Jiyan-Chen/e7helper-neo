// 流程编辑器左侧的步骤树：嵌套积木（「如果」「重复」里面再放步骤），可以拖动排序、拖进 / 拖出积木。
import {
  ArrowDown, ArrowUp, Copy, Crosshair, Flag, GitBranch, GripVertical, Hourglass, LogOut, MapPin, MousePointerClick,
  MoveHorizontal, Plus, Repeat, ScanSearch, Timer, Trash2, Undo2, type LucideIcon,
} from "lucide-react";
import { Popover } from "radix-ui";
import { createContext, Fragment, useContext, useState } from "react";
import {
  type ListAddr, ROOT, STEP_GROUPS, STEP_LABELS, type Step, type StepType, type TemplateLabel, containsList, describeStep,
  findStep,
} from "@/lib/flow";
import { cn } from "@/lib/utils";

export const STEP_ICONS: Record<StepType, LucideIcon> = {
  tap_template: MousePointerClick,
  tap_point: Crosshair,
  swipe: MoveHorizontal,
  back: Undo2,
  wait: Hourglass,
  wait_still: Timer,
  wait_template: ScanSearch,
  wait_scene: MapPin,
  end: Flag,
  break: LogOut,
  if: GitBranch,
  repeat: Repeat,
};

export interface TreeActions {
  select: (id: string | null) => void;
  move: (id: string, addr: ListAddr, index: number) => void;
  insert: (addr: ListAddr, index: number, type: StepType) => void;
  remove: (id: string) => void;
  duplicate: (id: string) => void;
  nudge: (id: string, delta: -1 | 1) => void;
}

interface Ctx extends TreeActions {
  steps: Step[];
  selected: string | null;
  numbers: Map<string, string>;
  problems: Map<string, string>;
  running: string | null;
  label: TemplateLabel;
  dragging: string | null;
  setDragging: (id: string | null) => void;
  readOnly: boolean;
}

const TreeCtx = createContext<Ctx | null>(null);
const useTree = () => useContext(TreeCtx)!;

export function StepTree(props: Omit<Ctx, "dragging" | "setDragging">) {
  const [dragging, setDragging] = useState<string | null>(null);
  return (
    <TreeCtx.Provider value={{ ...props, dragging, setDragging }}>
      <StepList steps={props.steps} addr={ROOT} />
    </TreeCtx.Provider>
  );
}

function StepList({ steps, addr }: { steps: Step[]; addr: ListAddr }) {
  return (
    <div className="flex flex-col">
      {steps.map((s, i) => (
        <Fragment key={s.id}>
          <DropZone addr={addr} index={i} />
          <StepItem step={s} index={i} count={steps.length} />
        </Fragment>
      ))}
      <DropZone addr={addr} index={steps.length} />
      <AddStep addr={addr} index={steps.length} empty={steps.length === 0} />
    </div>
  );
}

function DropZone({ addr, index }: { addr: ListAddr; index: number }) {
  const t = useTree();
  const [over, setOver] = useState(false);
  const moving = t.dragging ? findStep(t.steps, t.dragging)?.step : undefined;
  const ok = !!moving && !containsList(moving, addr);
  return (
    <div
      className={cn("transition-all", t.dragging ? "h-3.5" : "h-1", over && ok && "h-7 rounded-md border-2 border-dashed border-glow bg-glow/10")}
      onDragOver={(e) => {
        if (!ok) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (t.dragging && ok) t.move(t.dragging, addr, index);
        t.setDragging(null);
      }}
    />
  );
}

function StepItem({ step, index, count }: { step: Step; index: number; count: number }) {
  const t = useTree();
  const Icon = STEP_ICONS[step.type];
  const selected = t.selected === step.id;
  const running = t.running === step.id;
  const problem = t.problems.get(step.id);
  const block = step.type === "if" || step.type === "repeat";

  return (
    <div className={cn(t.dragging === step.id && "opacity-40")}>
      <div
        role="button"
        tabIndex={0}
        draggable={!t.readOnly}
        onDragStart={(e) => {
          e.dataTransfer.setData("text/plain", step.id);
          e.dataTransfer.effectAllowed = "move";
          t.setDragging(step.id);
        }}
        onDragEnd={() => t.setDragging(null)}
        onClick={(e) => {
          e.stopPropagation();
          t.select(step.id);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") t.select(step.id);
        }}
        className={cn(
          "group flex cursor-pointer items-center gap-2.5 rounded-[10px] border px-2.5 py-2 transition-colors",
          block ? "bg-[#2a2f3e]/85" : "bg-[var(--panel-hi)]",
          selected ? "border-glow shadow-[0_0_0_1px_var(--color-glow),0_0_12px_rgba(67,166,255,.35)]" : "border-white/6 hover:border-white/18",
          running && "border-ok shadow-[0_0_14px_rgba(143,220,108,.55)]",
          problem && !selected && "border-bad/70",
        )}
      >
        {!t.readOnly && <GripVertical className="size-4 flex-none cursor-grab text-faint" aria-hidden />}
        <span className={cn("num min-w-[34px] rounded-md px-1.5 text-center text-xs font-semibold leading-5",
          running ? "bg-ok text-black" : "bg-black/40 text-gold")}>{t.numbers.get(step.id)}</span>
        <Icon className={cn("size-[18px] flex-none", block ? "text-gold" : "text-[#cfd6e4]")} />
        <div className="min-w-0 flex-1">
          <div className={cn("truncate", block && "font-bold")}>{describeStep(step, t.label)}</div>
          {(step.note || problem || running) && (
            <div className="truncate text-xs">
              {running && <span className="mr-2 text-ok">正在执行</span>}
              {problem && <span className="mr-2 text-bad">{problem}</span>}
              {step.note && <span className="text-muted">{step.note}</span>}
            </div>
          )}
        </div>
        {!t.readOnly && (
          <span className="flex flex-none items-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <Mini label="上移" disabled={index === 0} onClick={() => t.nudge(step.id, -1)}><ArrowUp className="size-3.5" /></Mini>
            <Mini label="下移" disabled={index === count - 1} onClick={() => t.nudge(step.id, 1)}><ArrowDown className="size-3.5" /></Mini>
            <Mini label="复制这一步" onClick={() => t.duplicate(step.id)}><Copy className="size-3.5" /></Mini>
            <Mini label="删除这一步" danger onClick={() => t.remove(step.id)}><Trash2 className="size-3.5" /></Mini>
          </span>
        )}
      </div>
      {step.type === "if" && (
        <div className="mt-1 ml-5 flex flex-col gap-1 border-l-2 border-gold-line/70 pl-3">
          <BranchLabel text="那么" hint="条件成立时" />
          <StepList steps={step.then} addr={{ parent: step.id, branch: "then" }} />
          <BranchLabel text="否则" hint="条件不成立时（可以空着）" />
          <StepList steps={step.else} addr={{ parent: step.id, branch: "else" }} />
        </div>
      )}
      {step.type === "repeat" && (
        <div className="mt-1 ml-5 border-l-2 border-glow/60 pl-3">
          <BranchLabel text="每一轮做" />
          <StepList steps={step.body} addr={{ parent: step.id, branch: "body" }} />
        </div>
      )}
    </div>
  );
}

function BranchLabel({ text, hint }: { text: string; hint?: string }) {
  return (
    <div className="flex items-baseline gap-2 pt-1 text-xs">
      <span className="font-bold text-gold">{text}</span>
      {hint && <span className="text-faint">{hint}</span>}
    </div>
  );
}

function Mini({ label, onClick, disabled, danger, children }: {
  label: string; onClick: () => void; disabled?: boolean; danger?: boolean; children: React.ReactNode;
}) {
  return (
    <button type="button" aria-label={label} title={label} disabled={disabled}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      className={cn("grid size-7 cursor-pointer place-items-center rounded-md text-muted hover:bg-white/10 disabled:cursor-default disabled:opacity-30",
        danger ? "hover:text-bad" : "hover:text-ink")}>
      {children}
    </button>
  );
}

function AddStep({ addr, index, empty }: { addr: ListAddr; index: number; empty: boolean }) {
  const t = useTree();
  const [open, setOpen] = useState(false);
  if (t.readOnly) return empty ? <p className="px-2 py-1 text-xs text-faint">（空）</p> : null;
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button"
          className={cn("flex w-fit cursor-pointer items-center gap-1.5 rounded-lg border border-dashed px-2.5 text-xs text-muted hover:border-gold hover:text-gold",
            empty ? "h-8 border-white/20" : "h-7 border-transparent")}>
          <Plus className="size-3.5" />添加步骤
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="right" align="start" sideOffset={6} collisionPadding={12}
          className="z-50 w-[520px] rounded-xl border border-gold-line/60 bg-[#151b2b] p-3 shadow-xl">
          <div className="grid grid-cols-3 gap-3">
            {STEP_GROUPS.map((g) => (
              <div key={g.title} className="flex flex-col gap-1">
                <div className="mb-0.5 text-xs font-bold text-gold">{g.title}</div>
                {g.items.map((it) => {
                  const Icon = STEP_ICONS[it.type];
                  return (
                    <button key={it.type} type="button" title={it.hint}
                      className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-blue/30"
                      onClick={() => { t.insert(addr, index, it.type); setOpen(false); }}>
                      <Icon className="mt-0.5 size-4 flex-none text-[#cfd6e4]" />
                      <span>
                        <span className="block text-sm">{STEP_LABELS[it.type]}</span>
                        <span className="block text-[11px] leading-4 text-faint">{it.hint}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
