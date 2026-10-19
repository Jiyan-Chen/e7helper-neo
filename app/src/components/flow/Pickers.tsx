// 编辑器里用的选择框：选模板（我的 / 内置 / 现场采集）、在画面上点坐标 / 画滑动线。
import { Check as CheckIcon, Search } from "lucide-react";
import { useState } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { api } from "@/lib/api";
import type { UserTemplate } from "@/lib/flow";
import { templateLabel, useTemplates } from "@/lib/flowHooks";
import { cn } from "@/lib/utils";
import { FrameCanvas, type Overlay, type Pt } from "./FrameCanvas";
import { FrameButtons, TemplateCapture, useFrozenFrame } from "./TemplateCapture";

export function TemplateThumb({ tref, className }: { tref: string; className?: string }) {
  return (
    <img src={api().userTemplateUrl(tref)} alt="" className={cn("max-h-8 max-w-20 rounded-sm object-contain", className)}
      onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
  );
}

type Tab = "mine" | "common" | "capture";

/** 选模板。multiple=false 时点一下就选中并关闭。 */
export function TemplatePicker({
  open, onClose, value, onChange, multiple,
}: {
  open: boolean;
  onClose: () => void;
  value: string[];
  onChange: (refs: string[]) => void;
  multiple?: boolean;
}) {
  const { data } = useTemplates();
  const [tab, setTab] = useState<Tab>((data?.mine.length ?? 0) > 0 ? "mine" : "common");
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>(value);

  const toggle = (ref: string) => {
    if (!multiple) {
      onChange([ref]);
      onClose();
      return;
    }
    setPicked((p) => (p.includes(ref) ? p.filter((r) => r !== ref) : p.length >= 8 ? p : [...p, ref]));
  };
  const list = (tab === "mine" ? data?.mine : data?.common) ?? [];
  const shown = list.filter((t) => !q || templateLabel(t).includes(q) || t.name.includes(q));

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()} title={multiple ? "选模板（可以选几个，任一出现就算）" : "选模板"}
      className="w-[860px]"
      footer={multiple && tab !== "capture" ? (
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>取消</button>
          <button type="button" className="btn btn-go" disabled={picked.length === 0} onClick={() => { onChange(picked); onClose(); }}>
            选好了（{picked.length}）
          </button>
        </>
      ) : undefined}
    >
      <div className="mb-3 flex items-center gap-1.5">
        <button type="button" className={cn("tab", tab === "mine" && "active")} onClick={() => setTab("mine")}>我的模板（{data?.mine.length ?? 0}）</button>
        <button type="button" className={cn("tab", tab === "common" && "active")} onClick={() => setTab("common")}>内置（只读）</button>
        <button type="button" className={cn("tab", tab === "capture" && "active")} onClick={() => setTab("capture")}>＋ 采集新模板</button>
        {tab !== "capture" && (
          <span className="ml-auto flex items-center gap-1.5">
            <Search className="size-4 text-muted" />
            <input className="field h-7 w-40 text-xs" placeholder="搜索" value={q} onChange={(e) => setQ(e.target.value)} aria-label="搜索模板" />
          </span>
        )}
      </div>
      {tab === "capture" ? (
        <TemplateCapture compact onSaved={(t) => {
          if (!multiple) {
            onChange([t.ref]);
            onClose();
          } else {
            setPicked((p) => (p.includes(t.ref) ? p : [...p, t.ref]));
            setTab("mine");
          }
        }} />
      ) : (
        <>
          {tab === "common" && <p className="mb-2 text-xs text-muted">游戏里通用的按钮和界面标题。</p>}
          {shown.length === 0 && (
            <p className="py-6 text-center text-muted">{tab === "mine" ? "还没有自己的模板，点「采集新模板」截一张图框一个。" : "没有匹配的模板。"}</p>
          )}
          <div className="grid grid-cols-4 gap-2">
            {shown.map((t) => (
              <TemplateCard key={t.ref} t={t} selected={(multiple ? picked : value).includes(t.ref)} onClick={() => toggle(t.ref)} />
            ))}
          </div>
        </>
      )}
    </Dialog>
  );
}

function TemplateCard({ t, selected, onClick }: { t: UserTemplate; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={!!t.error} title={t.note || t.name}
      className={cn("relative flex h-[92px] cursor-pointer flex-col items-center justify-between gap-1 rounded-lg border bg-black/30 p-2 text-xs",
        selected ? "border-glow shadow-[0_0_10px_rgba(67,166,255,.45)]" : "border-white/10 hover:border-gold-line")}>
      <span className="grid h-12 w-full place-items-center overflow-hidden rounded bg-black/40">
        <TemplateThumb tref={t.ref} className="max-h-11 max-w-full" />
      </span>
      <span className="w-full truncate text-center">{t.error ? `（读不了）${t.name}` : templateLabel(t)}</span>
      {selected && <CheckIcon className="absolute top-1 right-1 size-4 text-glow" strokeWidth={3} />}
    </button>
  );
}

/** 在画面上点一个点（mode=point），或者从起点拖到终点（mode=line）。 */
export function PointPicker({
  open, onClose, mode, point, line, onPick,
}: {
  open: boolean;
  onClose: () => void;
  mode: "point" | "line";
  point?: Pt;
  line?: [Pt, Pt];
  onPick: (v: { point?: Pt; line?: [Pt, Pt] }) => void;
}) {
  const { src, freeze, upload, busy } = useFrozenFrame();
  const [p, setP] = useState<Pt | undefined>(point);
  const [l, setL] = useState<[Pt, Pt] | undefined>(line);
  const overlays: Overlay[] = [];
  if (mode === "point" && p) overlays.push({ point: p, color: "#43a6ff", label: `${p[0]}, ${p[1]}` });
  if (mode === "line" && l) overlays.push({ line: l, color: "#8fdc6c" }, { point: l[0], color: "#8fdc6c", label: "起点" });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()} title={mode === "point" ? "在画面上点要点的位置" : "在画面上从起点拖到终点"}
      className="w-[900px]"
      footer={
        <>
          <span className="mr-auto self-center text-sm text-muted num">
            {mode === "point" ? (p ? `(${p[0]}, ${p[1]})` : "") : l ? `(${l[0][0]}, ${l[0][1]}) → (${l[1][0]}, ${l[1][1]})` : ""}
          </span>
          <button type="button" className="btn btn-ghost" onClick={onClose}>取消</button>
          <button type="button" className="btn btn-go" disabled={mode === "point" ? !p : !l}
            onClick={() => { onPick(mode === "point" ? { point: p } : { line: l }); onClose(); }}>确定</button>
        </>
      }
    >
      <div className="mb-2 flex items-center gap-2">
        <FrameButtons freeze={() => void freeze()} upload={(f) => void upload(f)} busy={busy} />
      </div>
      <FrameCanvas src={src} mode={mode === "point" ? "point" : "line"} overlays={overlays}
        onPoint={setP}
        onLine={(a, b) => setL([a, b])}
        empty="先截取游戏画面，再在图上点。" />
    </Dialog>
  );
}
