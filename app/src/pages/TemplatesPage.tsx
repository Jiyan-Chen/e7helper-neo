// 我的模板（B11，玩家版模板采集）：采集 + 管理玩家自己的模板，只给「我的流程」用。
import { useQueryClient } from "@tanstack/react-query";
import { ScanSearch, Trash2 } from "lucide-react";
import { useState } from "react";
import { TemplateThumb } from "@/components/flow/Pickers";
import { TemplateCapture } from "@/components/flow/TemplateCapture";
import { confirmDialog } from "@/components/ui/Confirm";
import { toast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "@/lib/api";
import type { UserTemplate } from "@/lib/flow";
import { useTemplates } from "@/lib/flowHooks";
import { qk } from "@/lib/query";
import { useEngine } from "@/lib/store";

export function TemplatesPage() {
  const { data } = useTemplates();
  const qc = useQueryClient();
  const connected = useEngine((s) => s.status?.device.connected ?? false);
  const [found, setFound] = useState<Record<string, string>>({});
  const [version, setVersion] = useState(0);
  const mine = data?.mine ?? [];

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: qk.userTemplates });
    void qc.invalidateQueries({ queryKey: qk.flows });
    setVersion((v) => v + 1);
  };

  const remove = async (t: UserTemplate) => {
    const used = t.used_by.map((f) => `「${f.name}」`).join("、");
    const body = used ? `流程 ${used} 用到了它，删了这些流程就跑不了（要重新选模板）。确定删除？` : `删除模板「${t.name}」？`;
    if (!(await confirmDialog("删除模板", body, "删除", true))) return;
    try {
      await api().deleteUserTemplate(t.name, true);
      toast("已删除");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
    refresh();
  };

  const test = async (t: UserTemplate) => {
    try {
      const res = await api().testTemplates([t.ref]);
      const r = res.results[0];
      setFound((f) => ({ ...f, [t.ref]: r.hit ? `找到了（${r.score?.toFixed(2)}）` : `没找到（最像 ${r.score?.toFixed(2) ?? "—"}）` }));
    } catch (e) {
      toast(e instanceof ApiError ? e.message : errorMessage(e), "error");
    }
  };

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto px-[22px] py-4">
      <p className="text-muted">模板就是一小块截图，流程靠它认出画面上的按钮和界面。这里采集的模板只给「我的流程」用，不会影响助手的内置功能。</p>
      <TemplateCapture onSaved={() => refresh()} />
      <section className="panel px-4 py-3.5">
        <h3 className="panel-title mb-3">我的模板（{mine.length}）</h3>
        {mine.length === 0 && <p className="text-sm text-muted">还没有。在上面截图、框选、起名保存。</p>}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2.5">
          {mine.map((t) => (
            <div key={t.ref} className="flex gap-3 rounded-[10px] border border-white/8 bg-[var(--panel-hi)] p-2.5">
              <span className="grid h-14 w-20 flex-none place-items-center overflow-hidden rounded bg-black/40">
                <TemplateThumb key={version} tref={t.ref} className="max-h-13 max-w-full" />
              </span>
              <div className="min-w-0 flex-1 text-xs">
                <div className="truncate text-sm font-bold" title={t.name}>{t.name}</div>
                <div className="text-faint">{t.error ? <span className="text-bad">文件读不了</span> : (
                  <>{t.moving ? "会移动" : "位置固定"}{t.has_tap ? " · 有点击区域" : ""}{t.dim_check ? " · 变暗不算" : ""}</>
                )}</div>
                <div className="truncate text-muted" title={t.used_by.map((f) => f.name).join("、")}>
                  {t.used_by.length ? `用在：${t.used_by.map((f) => f.name).join("、")}` : "还没有流程用它"}
                </div>
                {found[t.ref] && <div className={found[t.ref].startsWith("找到") ? "text-ok" : "text-warn"}>{found[t.ref]}</div>}
              </div>
              <div className="flex flex-col gap-1">
                <button type="button" className="grid size-7 cursor-pointer place-items-center rounded text-muted hover:bg-white/8 hover:text-ink disabled:opacity-40"
                  disabled={!connected} title={connected ? "在当前画面上找（只截图）" : "模拟器未连接"} aria-label="在当前画面上找" onClick={() => void test(t)}>
                  <ScanSearch className="size-4" />
                </button>
                <button type="button" className="grid size-7 cursor-pointer place-items-center rounded text-muted hover:bg-white/8 hover:text-bad"
                  title="删除" aria-label={`删除 ${t.name}`} onClick={() => void remove(t)}>
                  <Trash2 className="size-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
