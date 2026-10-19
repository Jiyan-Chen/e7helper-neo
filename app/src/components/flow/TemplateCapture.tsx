// 玩家版模板采集（B11）：截一张图 → 框出要认的东西（可选：框能点的地方）→ 起名保存 → 马上自测。
// 模板存在数据目录，只给「我的流程」用；内置功能的模板不会被改动。
import { useQueryClient } from "@tanstack/react-query";
import { Camera, CircleAlert, CircleCheck, CircleX, ImageUp } from "lucide-react";
import { useRef, useState } from "react";
import { Check } from "@/components/ui/Check";
import { Select } from "@/components/ui/Select";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage, type UserTemplateSaved } from "@/lib/api";
import { qk } from "@/lib/query";
import { useEngine } from "@/lib/store";
import type { CaptureFrame, Rect4 } from "@/lib/types";
import { cn } from "@/lib/utils";
import { FrameCanvas, type Overlay } from "./FrameCanvas";

const STRICTNESS = [
  { value: "0.8", label: "宽松（画面有点变化也认）" },
  { value: "0.85", label: "标准" },
  { value: "0.92", label: "严格（几乎一模一样才认）" },
];

/** 冻结画面（截当前画面或打开图片）。 */
export function useFrozenFrame() {
  const [frame, setFrame] = useState<CaptureFrame | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<CaptureFrame>) => {
    setBusy(true);
    try {
      const f = await fn();
      setFrame(f);
      return f;
    } catch (e) {
      toast(errorMessage(e), "error");
      return null;
    } finally {
      setBusy(false);
    }
  };
  return {
    frame,
    busy,
    src: frame ? api().captureFrameUrl(frame.id) : null,
    freeze: () => run(() => api().captureFreeze()),
    upload: (file: Blob) => run(() => api().captureUpload(file)),
  };
}

export function FrameButtons({ freeze, upload, busy }: { freeze: () => void; upload: (f: Blob) => void; busy: boolean }) {
  const connected = useEngine((s) => s.status?.device.connected ?? false);
  const file = useRef<HTMLInputElement>(null);
  return (
    <>
      <button type="button" className="btn btn-blue btn-sm" disabled={!connected || busy} title={connected ? undefined : "模拟器未连接"} onClick={freeze}>
        <Camera className="size-4" />截取游戏画面
      </button>
      <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => file.current?.click()} title="用一张 1600×900 的游戏截图">
        <ImageUp className="size-4" />打开截图
      </button>
      <input ref={file} type="file" accept="image/*" hidden onChange={(e) => {
        const f = e.target.files?.[0];
        e.target.value = "";
        if (f) upload(f);
      }} />
    </>
  );
}

export function TemplateCapture({ onSaved, compact }: { onSaved?: (t: UserTemplateSaved) => void; compact?: boolean }) {
  const qc = useQueryClient();
  const { frame, src, freeze, upload, busy } = useFrozenFrame();
  const [tool, setTool] = useState<"box" | "tap">("box");
  const [box, setBox] = useState<Rect4 | null>(null);
  const [tap, setTap] = useState<Rect4 | null>(null);
  const [name, setName] = useState("");
  const [moving, setMoving] = useState(false);
  const [dimCheck, setDimCheck] = useState(false);
  const [strict, setStrict] = useState("0.85");
  const [overwrite, setOverwrite] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<UserTemplateSaved | null>(null);

  const newFrame = async (p: Promise<unknown>) => {
    if (await p) {
      setBox(null);
      setTap(null);
      setResult(null);
    }
  };

  const save = async () => {
    if (!frame || !box || !name.trim()) return;
    setSaving(true);
    try {
      const res = await api().saveUserTemplate({
        frame: frame.id, name: name.trim(), box, tap, moving, dim_check: dimCheck, threshold: Number(strict), overwrite,
      });
      setResult(res);
      if (res.quality === "good") toast(`已保存模板「${res.name}」，认得很清楚`);
      else toast(`已保存「${res.name}」，但${res.quality === "weak" ? "原位置都认不出来" : "画面上还有很像的地方，可能认错"}`, "error");
      void qc.invalidateQueries({ queryKey: qk.userTemplates });
      onSaved?.(res);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setSaving(false);
    }
  };

  const overlays: Overlay[] = [];
  if (tap) overlays.push({ rect: tap, color: "#8fdc6c", label: "点这里", dashed: true });
  if (box) overlays.push({ rect: box, color: "#43a6ff", label: "要认的东西" });

  const form = (
    <div className="flex flex-col gap-2.5">
      <label className="flex flex-col gap-1 text-xs text-muted">
        名字
        <input className="field w-full text-sm" placeholder="例如：圣域入口、领取按钮" maxLength={30} value={name}
          onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        位置
        <Select value={moving ? "moving" : "fixed"} label="位置" className="w-full text-sm"
          options={[{ value: "fixed", label: "固定在这里（更快、更准）" }, { value: "moving", label: "会移动（在整个画面里找）" }]}
          onChange={(v) => setMoving(v === "moving")} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        识别严格度
        <Select value={strict} label="识别严格度" className="w-full text-sm" options={STRICTNESS} onChange={setStrict} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <Check checked={dimCheck} onChange={setDimCheck} label="变暗时不算" />
        <span>按钮变暗（不能点 / 被弹窗盖住）时不算</span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <Check checked={overwrite} onChange={setOverwrite} label="覆盖同名模板" />覆盖同名模板
      </label>
      <button type="button" className="btn btn-go" disabled={!frame || !box || !name.trim() || saving} onClick={save}>保存并测试</button>
      {result && <Quality result={result} />}
    </div>
  );

  return (
    <div className={cn("flex min-h-0 gap-4", compact ? "flex-col" : "")}>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <FrameButtons freeze={() => void newFrame(freeze())} upload={(f) => void newFrame(upload(f))} busy={busy} />
          <span className="mx-1 h-4 w-px bg-white/15" />
          <button type="button" className={cn("tab", tool === "box" && "active")} onClick={() => setTool("box")}>
            <span className="mr-1 inline-block size-2 rounded-full bg-glow" />框出要认的东西
          </button>
          <button type="button" className={cn("tab", tool === "tap" && "active")} onClick={() => setTool("tap")}
            title="要点的位置和认的东西不一样时才需要">
            <span className="mr-1 inline-block size-2 rounded-full bg-ok" />框能点的地方（可选）
          </button>
          {tap && <button type="button" className="text-xs text-faint hover:text-ink" onClick={() => setTap(null)}>清除点击区域</button>}
        </div>
        <FrameCanvas src={src} mode="box" overlays={overlays}
          onRect={(r) => (tool === "box" ? setBox(r) : setTap(r))}
          empty={<>先点「截取游戏画面」，把游戏停在你要认的界面上。<br />然后在图上拖一个框。</>} />
        <ul className="list-disc pl-5 text-xs leading-6 text-muted">
          <li>框要<b className="text-ink">小而有特点</b>：按钮上的字、图标。</li>
        </ul>
      </div>
      <div className={cn("flex flex-none flex-col", compact ? "" : "w-[300px]")}>
        <section className="panel px-4 py-3.5">
          <h3 className="panel-title mb-2.5">保存模板</h3>
          {form}
        </section>
      </div>
    </div>
  );
}

function Quality({ result }: { result: UserTemplateSaved }) {
  const own = result.verify.own?.score;
  const other = result.verify.other?.score;
  if (result.quality === "good") {
    return (
      <p className="flex gap-2 rounded-lg bg-ok/10 px-3 py-2 text-xs text-[#d8f1cb]">
        <CircleCheck className="size-4 flex-none text-ok" />认得很清楚（匹配度 {own?.toFixed(2)}，画面上别处最多 {other?.toFixed(2) ?? "—"}）。
      </p>
    );
  }
  if (result.quality === "ambiguous") {
    return (
      <p className="flex gap-2 rounded-lg bg-warn/10 px-3 py-2 text-xs text-[#ffe2b8]">
        <CircleAlert className="size-4 flex-none text-warn" />画面上还有很像的地方（{other?.toFixed(2)}），可能认错。框大一点，或者换个更有特点的地方。
      </p>
    );
  }
  return (
    <p className="flex gap-2 rounded-lg bg-bad/10 px-3 py-2 text-xs text-[#ffd2c8]">
      <CircleX className="size-4 flex-none text-bad" />在原位置都认不出来（{own?.toFixed(2) ?? "—"}）。框里的颜色太单一，换个有文字或图案的地方。
    </p>
  );
}
