// 模板采集（开发版）：冻结画面 → 在图上拖框 → 保存模板并回验；可以测试模块全部模板和 OCR。
// 和 CLI `capture` / `match` / `ocr` 等价（engine/e7helper/api/capture.py）。
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, ScanText, Search, Trash2, Upload } from "lucide-react";
import { type PointerEvent, useRef, useState } from "react";
import { Check } from "@/components/ui/Check";
import { confirmDialog } from "@/components/ui/Confirm";
import { Select } from "@/components/ui/Select";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useEngine } from "@/lib/store";
import type { CaptureFrame, CaptureHit, CaptureSaved, Rect4 } from "@/lib/types";
import { cn } from "@/lib/utils";

const W = 1600;
const H = 900;

type Tool = "box" | "region" | "tap" | "ocr";
const TOOLS: { id: Tool; label: string; color: string }[] = [
  { id: "box", label: "模板", color: "#43a6ff" },
  { id: "region", label: "检索区域", color: "#d8b679" },
  { id: "tap", label: "点击区域", color: "#8fdc6c" },
  { id: "ocr", label: "OCR 区域", color: "#ff8a70" },
];

function norm(a: [number, number], b: [number, number]): Rect4 {
  const x = Math.max(0, Math.min(a[0], b[0]));
  const y = Math.max(0, Math.min(a[1], b[1]));
  return [Math.round(x), Math.round(y), Math.round(Math.min(W, Math.max(a[0], b[0])) - x), Math.round(Math.min(H, Math.max(a[1], b[1])) - y)];
}

export function CapturePage() {
  const qc = useQueryClient();
  const connected = useEngine((s) => s.status?.device.connected ?? false);
  const [frame, setFrame] = useState<CaptureFrame | null>(null);
  const [tool, setTool] = useState<Tool>("box");
  const [rects, setRects] = useState<Partial<Record<Tool, Rect4>>>({});
  const drag = useRef<[number, number] | null>(null);
  const [module, setModule] = useState("common");
  const [name, setName] = useState("");
  const [threshold, setThreshold] = useState("0.85");
  const [maxDiff, setMaxDiff] = useState("");
  const [full, setFull] = useState(false);
  const [gray, setGray] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState<CaptureSaved | null>(null);
  const [hits, setHits] = useState<CaptureHit[]>([]);
  const [ocr, setOcr] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const img = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);

  const { data: stores } = useQuery({ queryKey: ["capture", "stores"], queryFn: () => api().captureStores() });
  const { data: templates } = useQuery({ queryKey: ["capture", "templates", module], queryFn: () => api().captureTemplates(module) });

  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    try {
      return await fn();
    } catch (e) {
      toast(errorMessage(e), "error");
      return undefined;
    }
  };

  const newFrame = (f: CaptureFrame | undefined) => {
    if (!f) return;
    setFrame(f);
    setHits([]);
    setSaved(null);
    setOcr(null);
  };

  const toBase = (e: PointerEvent): [number, number] => {
    const r = img.current!.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H];
  };

  const save = async () => {
    if (!frame || !rects.box || !name.trim()) return;
    const res = await run(() =>
      api().captureSave(module, {
        frame: frame.id, name: name.trim(), box: rects.box!, region: full ? null : rects.region ?? null, full,
        tap: rects.tap ?? null, threshold: Number(threshold) || 0.85, grayscale: gray,
        max_diff: maxDiff.trim() ? Number(maxDiff) : null, note, overwrite,
      }),
    );
    if (res) {
      setSaved(res);
      setVersion((v) => v + 1);
      toast(`已保存 ${res.name}`);
      void qc.invalidateQueries({ queryKey: ["capture"] });
    }
  };

  const testAll = async () => {
    if (!frame) return;
    const res = await run(() => api().captureMatch(frame.id, module));
    if (res) setHits(res);
  };

  const testOcr = async (mode: "read" | "line" | "number") => {
    if (!frame) return;
    setOcr("识别中…（第一次要加载模型）");
    const res = await run(() => api().captureOcr(frame.id, rects.ocr ?? null, mode));
    if (!res) return setOcr(null);
    setOcr(res.number !== undefined ? `数字：${res.number ?? "认不出"}（${res.ms} ms）`
      : `${(res.results ?? []).map((r) => `${r.text}（${r.score}）`).join("，") || "没有文字"}（${res.ms} ms）`);
  };

  const box = (r: Rect4 | undefined, color: string, label?: string, dashed = false) =>
    r && (
      <div className="pointer-events-none absolute border-2" style={{
        left: `${(r[0] / W) * 100}%`, top: `${(r[1] / H) * 100}%`, width: `${(r[2] / W) * 100}%`, height: `${(r[3] / H) * 100}%`,
        borderColor: color, borderStyle: dashed ? "dashed" : "solid",
      }}>
        {label && <span className="absolute -top-5 left-0 whitespace-nowrap rounded px-1 text-[11px] text-black" style={{ background: color }}>{label}</span>}
      </div>
    );

  return (
    <div className="flex h-full min-h-0 gap-4 overflow-auto px-[22px] py-4">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn btn-blue btn-sm" disabled={!connected} title={connected ? undefined : "模拟器未连接"}
            onClick={async () => newFrame(await run(() => api().captureFreeze()))}>
            <Camera className="size-4" />截取当前画面
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => file.current?.click()}>
            <Upload className="size-4" />打开图片
          </button>
          <input ref={file} type="file" accept="image/*" hidden onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) newFrame(await run(() => api().captureUpload(f)));
          }} />
          <span className="mx-1 h-4 w-px bg-white/15" />
          {TOOLS.map((t) => (
            <button key={t.id} type="button" className={cn("tab", tool === t.id && "active")} onClick={() => setTool(t.id)}>
              <span className="mr-1 inline-block size-2 rounded-full" style={{ background: t.color }} />框{t.label}
            </button>
          ))}
        </div>

        <div className="relative w-full overflow-hidden rounded-lg border border-gold-line/60 bg-black/50" style={{ aspectRatio: "16 / 9" }}>
          {frame ? (
            <div
              ref={img}
              className="absolute inset-0 cursor-crosshair"
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                const p = toBase(e);
                drag.current = p;
                setRects((r) => ({ ...r, [tool]: norm(p, p) }));
              }}
              onPointerMove={(e) => {
                const start = drag.current;
                if (start) setRects((r) => ({ ...r, [tool]: norm(start, toBase(e)) }));
              }}
              onPointerUp={(e) => {
                const start = drag.current;
                if (start) setRects((r) => ({ ...r, [tool]: norm(start, toBase(e)) }));
                drag.current = null;
              }}
            >
              <img src={api().captureFrameUrl(frame.id)} alt="冻结的画面" className="pointer-events-none size-full select-none" draggable={false} />
              {box(rects.region, "#d8b679", "检索", true)}
              {box(rects.tap, "#8fdc6c", "点击", true)}
              {box(rects.ocr, "#ff8a70", "OCR")}
              {box(rects.box, "#43a6ff", "模板")}
              {/* 只画命中的；没命中的分数在右边列表里 */}
              {hits.filter((h) => h.rect && h.hit).map((h) => <div key={h.name}>{box(h.rect, "#5fd35a", `${h.name} ${h.score?.toFixed(2)}`)}</div>)}
            </div>
          ) : (
            <div className="grid size-full place-items-center text-muted">先截取当前画面，或打开一张截图（例如 engine/tests/fixtures 里的）</div>
          )}
        </div>

        <div className="grid grid-cols-4 gap-2 text-xs">
          {TOOLS.map((t) => (
            <RectEditor key={t.id} label={t.label} color={t.color} value={rects[t.id]}
              onChange={(v) => setRects((r) => ({ ...r, [t.id]: v }))} />
          ))}
        </div>

        <div className="panel flex items-center gap-2 px-3 py-2 text-sm">
          <ScanText className="size-4 text-gold" />OCR
          <button type="button" className="btn btn-ghost btn-sm" disabled={!frame} onClick={() => testOcr("read")}>检测并识别</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={!frame || !rects.ocr} onClick={() => testOcr("line")}>单行</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={!frame || !rects.ocr} onClick={() => testOcr("number")}>数字</button>
          <span className="min-w-0 flex-1 truncate text-muted select-text" title={ocr ?? undefined}>{ocr}</span>
        </div>
      </div>

      <div className="flex w-[330px] flex-none flex-col gap-3">
        <section className="panel flex flex-col gap-2.5 px-4 py-3.5">
          <h3 className="panel-title">保存模板</h3>
          <Labeled label="模块">
            <Select value={module} label="模块" className="w-full"
              options={(stores ?? [{ module: "common", count: 0 }]).map((s) => ({ value: s.module, label: `${s.module}（${s.count}）` }))}
              onChange={(v) => { setModule(v); setHits([]); }} />
          </Labeled>
          <Labeled label="名字">
            <input className="field w-full" placeholder="例如 lobby/shop" value={name} onChange={(e) => setName(e.target.value)} />
          </Labeled>
          <div className="grid grid-cols-2 gap-2">
            <Labeled label="阈值"><input className="field num w-full" value={threshold} onChange={(e) => setThreshold(e.target.value)} /></Labeled>
            <Labeled label="max_diff"><input className="field num w-full" placeholder="不校验" value={maxDiff} onChange={(e) => setMaxDiff(e.target.value)} /></Labeled>
          </div>
          <Labeled label="备注"><input className="field w-full" value={note} onChange={(e) => setNote(e.target.value)} /></Labeled>
          <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
            <label className="flex items-center gap-2"><Check checked={full} onChange={setFull} label="全屏检索" />全屏检索</label>
            <label className="flex items-center gap-2"><Check checked={gray} onChange={setGray} label="灰度" />灰度</label>
            <label className="flex items-center gap-2"><Check checked={overwrite} onChange={setOverwrite} label="覆盖" />覆盖已有</label>
          </div>
          <p className="text-xs text-muted">没框检索区域时，按模板区域外扩 40 像素。</p>
          <button type="button" className="btn btn-go" disabled={!frame || !rects.box || !name.trim()} onClick={save}>保存并回验</button>
          {saved && (
            <div className="rounded-lg bg-black/30 px-3 py-2 text-xs">
              <div>原位置：<Score hit={saved.verify.own} /></div>
              <div>其他位置最高：<Score hit={saved.verify.other} warnIfHit /></div>
              <div className="mt-1 break-all text-faint select-text">{saved.path}</div>
            </div>
          )}
        </section>

        <section className="panel flex min-h-0 flex-1 flex-col px-4 py-3.5">
          <div className="mb-2 flex items-center">
            <h3 className="panel-title mr-auto">{module} 的模板</h3>
            <button type="button" className="btn btn-ghost btn-sm" disabled={!frame} onClick={testAll}><Search className="size-4" />全部测试</button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {(templates ?? []).map((t) => {
              const h = hits.find((x) => x.name === t.name);
              return (
                <div key={t.name} className="flex items-center gap-2 border-t border-white/6 py-1.5 text-xs first:border-t-0">
                  <img src={api().captureTemplateUrl(module, t.name, version)} alt="" className="h-7 max-w-16 object-contain" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold" title={t.meta?.note || t.name}>{t.name}</div>
                    {h && (h.error ? <span className="text-bad">{h.error}</span> : <Score hit={h} />)}
                  </div>
                  <button type="button" className="grid size-7 cursor-pointer place-items-center rounded text-muted hover:text-bad" aria-label={`删除 ${t.name}`}
                    onClick={async () => {
                      if (!(await confirmDialog("删除模板", `删除 ${module}/${t.name}？会删掉 png 和 json 文件。`, "删除", true))) return;
                      await run(() => api().captureDelete(module, t.name));
                      void qc.invalidateQueries({ queryKey: ["capture"] });
                    }}>
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              );
            })}
            {templates?.length === 0 && <p className="text-sm text-muted">这个模块还没有模板。</p>}
          </div>
        </section>
      </div>
    </div>
  );
}

function Score({ hit, warnIfHit }: { hit: CaptureHit | null; warnIfHit?: boolean }) {
  if (!hit) return <span className="text-muted">—</span>;
  const bad = warnIfHit ? hit.hit : !hit.hit;
  return (
    <span className={bad ? "text-bad" : "text-ok"}>
      {hit.score?.toFixed(3)}，diff {hit.diff}
      {hit.rect && <span className="text-muted">（{hit.rect.join(",")}）</span>}
    </span>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      {children}
    </label>
  );
}

/** 矩形的数值微调（基准坐标）。 */
function RectEditor({ label, color, value, onChange }: { label: string; color: string; value?: Rect4; onChange: (v: Rect4 | undefined) => void }) {
  const set = (i: number, n: string) => {
    const v = [...(value ?? [0, 0, 0, 0])] as Rect4;
    v[i] = Math.max(0, Math.round(Number(n) || 0));
    onChange(v);
  };
  return (
    <div className="rounded-lg bg-black/30 px-2 py-1.5">
      <div className="mb-1 flex items-center gap-1.5">
        <span className="size-2 rounded-full" style={{ background: color }} />
        {label}
        {value && <button type="button" className="ml-auto cursor-pointer text-faint hover:text-ink" onClick={() => onChange(undefined)}>清除</button>}
      </div>
      <div className="grid grid-cols-4 gap-1">
        {["x", "y", "w", "h"].map((k, i) => (
          <input key={k} className="field num h-6 w-full px-1 text-center text-xs" aria-label={`${label} ${k}`}
            value={value ? value[i] : ""} placeholder={k} onChange={(e) => set(i, e.target.value)} />
        ))}
      </div>
    </div>
  );
}
