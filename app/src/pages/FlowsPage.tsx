// 我的流程（B11）：玩家自己编排的流程列表，运行 / 编辑 / 复制 / 加入计划 / 删除。
import { useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Copy, Images, Pencil, Play, Plus, Sparkles, Square, Trash2, Workflow } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { STATUS_COLOR } from "@/components/module/RecentRuns";
import { confirmDialog } from "@/components/ui/Confirm";
import { toast } from "@/components/ui/Toast";
import { ApiError, api, errorMessage } from "@/lib/api";
import { FLOW_MODULE, type Flow, type FlowSummary, type Step, newFlow, newStep } from "@/lib/flow";
import { useFlows, useTemplates } from "@/lib/flowHooks";
import { statusLabel } from "@/lib/labels";
import { qk } from "@/lib/query";
import { useEngine } from "@/lib/store";
import { ago } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ScheduleEditor } from "./SchedulesPage";

/** 示例流程：只用内置模板，不消耗任何资源。 */
function sampleFlow(): Flow {
  const s = (type: Step["type"], extra: Record<string, unknown> = {}) => ({ ...newStep(type), ...extra }) as Step;
  return {
    ...newFlow("示例：去圣域再回来"),
    description: "从大厅进圣域，再回到大厅。",
    limits: { max_minutes: 3, max_taps: 20 },
    steps: [
      s("wait_scene", { scene: "lobby", timeout: 15, note: "先确认在大厅" }),
      s("tap_template", { template: "common:lobby/sanctuary" }),
      s("wait_scene", { scene: "sanctuary", timeout: 15 }),
      s("wait", { seconds: 2 }),
      s("back"),
      s("wait_scene", { scene: "lobby", timeout: 15 }),
    ],
  };
}

export function FlowsPage() {
  const { data: flows, isLoading } = useFlows();
  const { label } = useTemplates();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const status = useEngine((s) => s.status);
  const flowStep = useEngine((s) => s.flowStep);
  const [scheduleFor, setScheduleFor] = useState<FlowSummary | null>(null);
  const connected = status?.device.connected ?? false;
  const task = status?.task;

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: qk.flows });
    void qc.invalidateQueries({ queryKey: qk.module(FLOW_MODULE) });
  };
  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast(ok);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      refresh();
    }
  };

  const remove = async (f: FlowSummary) => {
    if (!(await confirmDialog("删除流程", `删除「${f.name}」？删了不能恢复（用到的模板会保留）。`, "删除", true))) return;
    try {
      await api().deleteFlow(f.id);
      toast("已删除");
    } catch (e) {
      if (e instanceof ApiError && e.code === "in_use") {
        const names = (e.detail as { name: string }[]).map((x) => `「${x.name}」`).join("、");
        if (await confirmDialog("有计划在用这个流程", `计划 ${names} 用的是这个流程，要一起删除吗？`, "一起删除", true)) {
          await act(() => api().deleteFlow(f.id, true), "流程和计划都已删除");
          void qc.invalidateQueries({ queryKey: qk.schedules });
        }
      } else {
        toast(errorMessage(e), "error");
      }
    }
    refresh();
  };

  const addSample = () => act(async () => {
    const f = await api().createFlow(sampleFlow());
    navigate(`/flows/${f.id}`);
  }, "已添加示例流程");

  return (
    <div className="h-full overflow-auto px-[22px] py-4">
      <div className="mb-4 flex items-center gap-3">
        <p className="flex-1 text-muted">把常用的点击顺序存成流程，一键运行，或者加进计划定时运行。</p>
        <Link to="/templates" className="btn btn-ghost"><Images className="size-4" />我的模板</Link>
        <button type="button" className="btn btn-blue" onClick={() => navigate("/flows/new")}><Plus className="size-4" />新建流程</button>
      </div>

      {isLoading && <p className="text-muted">加载中…</p>}
      {flows && flows.length === 0 && (
        <div className="panel flex flex-col items-center gap-3 px-5 py-8 text-center">
          <Workflow className="size-10 text-gold" />
          <p className="text-muted">还没有流程。可以先加一个示例看看，或者自己新建一个。</p>
          <div className="flex gap-2">
            <button type="button" className="btn btn-bronze" onClick={() => void addSample()}><Sparkles className="size-4" />添加示例：去圣域再回来</button>
            <button type="button" className="btn btn-blue" onClick={() => navigate("/flows/new")}><Plus className="size-4" />新建流程</button>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {flows?.map((f) => {
          const running = task?.module === FLOW_MODULE && task.config.flow === f.id;
          const missing = f.missing ?? [];
          const reason = f.error ? "流程文件读不了" : !connected ? "模拟器未连接" : task && !running ? "有别的任务在运行"
            : missing.length ? "缺少模板" : !f.steps ? "还没有步骤" : null;
          const last = f.last_run;
          return (
            <div key={f.id} className={cn("row-card", running && "border-ok/60")}>
              <span className="medal"><Workflow className="size-5" /></span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 font-bold">
                  <Link to={`/flows/${f.id}`} className="truncate hover:text-gold">{f.name}</Link>
                  {running && <span className="text-xs font-normal text-ok">运行中{flowStep?.flow === f.id ? `：第 ${flowStep.path} 步` : ""}</span>}
                </div>
                {f.description && <div className="truncate text-xs text-muted">{f.description}</div>}
                <div className="text-xs text-faint">
                  {f.error ? <span className="text-bad">{f.error}</span> : (
                    <>
                      {f.steps} 步 · 最多 {f.limits?.max_minutes} 分钟 / {f.limits?.max_taps} 次点击
                      {last && (
                        <>
                          {" · 上次 "}
                          <span className={STATUS_COLOR[last.status]}>{statusLabel(last.status)}</span>
                          {`（${ago(last.time)}）`}
                        </>
                      )}
                    </>
                  )}
                </div>
                {missing.length > 0 && <div className="text-xs text-bad">缺少模板：{missing.map(label).join("、")}（去编辑里重新选，或者重新采集）</div>}
                {last?.status === "failed" && last.error && <div className="truncate text-xs text-bad" title={last.error}>{last.error}</div>}
              </div>
              <span className="w-px self-stretch bg-white/10" />
              <div className="flex items-center gap-1.5">
                <IconButton label="编辑" onClick={() => navigate(`/flows/${f.id}`)}><Pencil className="size-4" /></IconButton>
                <IconButton label="复制一份" onClick={() => act(() => api().copyFlow(f.id), "已复制")}><Copy className="size-4" /></IconButton>
                <IconButton label="加入计划" onClick={() => setScheduleFor(f)}><CalendarPlus className="size-4" /></IconButton>
                <IconButton label="删除" danger onClick={() => void remove(f)}><Trash2 className="size-4" /></IconButton>
                {running ? (
                  <button type="button" className="btn btn-real btn-sm ml-1 w-[84px]" onClick={() => act(() => api().stopTask())}>
                    <Square className="size-3.5" />停止
                  </button>
                ) : (
                  <button type="button" className="btn btn-go btn-sm ml-1 w-[84px]" disabled={!!reason} title={reason ?? "运行这个流程"}
                    onClick={() => act(() => api().startTask(FLOW_MODULE, { flow: f.id }), `「${f.name}」开始运行`)}>
                    <Play className="size-3.5" />运行
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {flows && flows.length > 0 && !flows.some((f) => f.name.startsWith("示例")) && (
        <button type="button" className="mt-3 text-xs text-faint hover:text-gold" onClick={() => void addSample()}>＋ 添加示例流程：去圣域再回来</button>
      )}

      {scheduleFor && (
        <ScheduleEditor schedule={null} onClose={() => setScheduleFor(null)}
          onSaved={() => void qc.invalidateQueries({ queryKey: qk.schedules })}
          initial={{ module: FLOW_MODULE, name: scheduleFor.name, config: { flow: scheduleFor.id } }}
          moduleOptions={[{ value: FLOW_MODULE, label: "自定义流程" }]} />
      )}
    </div>
  );
}

function IconButton({ label, onClick, danger, children }: { label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick}
      className={cn("grid size-8 cursor-pointer place-items-center rounded-lg text-muted hover:bg-white/8", danger ? "hover:text-bad" : "hover:text-ink")}>
      {children}
    </button>
  );
}
