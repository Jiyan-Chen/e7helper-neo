// 计划：列表 + 新建 / 编辑。三种触发方式见 architecture.md「定时调度」。
import { useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Pause, Pencil, Play, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { ConfigForm } from "@/components/module/ConfigForm";
import { STATUS_COLOR } from "@/components/module/RecentRuns";
import { Check } from "@/components/ui/Check";
import { confirmDialog } from "@/components/ui/Confirm";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { isDev } from "@/lib/env";
import { useModuleDetail, useModules, useNow, useSchedules } from "@/lib/hooks";
import { moduleName, statusLabel, triggerLabel } from "@/lib/labels";
import { qk } from "@/lib/query";
import { isDryRun, runConfig } from "@/lib/run";
import { fieldsOf } from "@/lib/schema";
import { dayTime, formatDuration, secondsUntil } from "@/lib/time";
import type { Schedule, ScheduleSpec, Trigger } from "@/lib/types";
import { cn } from "@/lib/utils";
import { moduleUI, visibleModules } from "@/modules/registry";
import type { SchedulePreset } from "@/modules/types";

export function SchedulesPage() {
  const { data, isLoading } = useSchedules();
  const { data: modules } = useModules();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  const [preset, setPreset] = useState<{ module: string; preset: SchedulePreset } | null>(null);
  const now = useNow();

  const refresh = () => qc.invalidateQueries({ queryKey: qk.schedules });
  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast(ok);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      void refresh();
    }
  };

  const presets = (modules ?? []).flatMap((m) => (moduleUI(m.id).presets ?? []).map((p) => ({ module: m.id, preset: p })));
  const existing = new Set((data?.schedules ?? []).map((s) => `${s.module}:${s.name}`));

  return (
    <div className="h-full overflow-auto px-[22px] py-4">
      <div className="mb-4 flex items-center gap-3">
        <p className="flex-1 text-muted">到点自动运行。</p>
        <label className="flex items-center gap-2 text-sm">
          <Check checked={!(data?.paused ?? false)} label="计划总开关" onChange={(on) => act(() => api().setSchedulerPaused(!on), on ? "计划已恢复" : "计划已全部暂停")} />
          计划总开关
        </label>
        <button type="button" className="btn btn-blue" onClick={() => setEditing("new")}>
          <CalendarPlus className="size-4" />新建计划
        </button>
      </div>

      {data?.paused && (
        <div className="mb-3 flex items-center gap-2 rounded-[10px] border border-warn/50 bg-warn/12 px-4 py-2 text-[#ffe2b8]">
          <Pause className="size-4" />所有计划都已暂停，到点不会运行。
        </div>
      )}

      {isLoading && <p className="text-muted">加载中…</p>}
      {data && data.schedules.length === 0 && (
        <div className="panel px-5 py-6 text-center text-muted">还没有计划。可以从下面的推荐里添加，或者点「新建计划」。</div>
      )}

      <div className="flex flex-col gap-2">
        {data?.schedules.map((s) => {
          const left = secondsUntil(s.state.next_run, now);
          let next = "—";
          if (!s.enabled) next = "已关闭";
          else if (s.state.running_task) next = "运行中";
          else if (s.state.queued_since) next = "排队中";
          else if (left !== null) next = left <= 0 ? "马上" : `${formatDuration(left)} 后`;
          const Icon = moduleUI(s.module).icon;
          return (
            <div key={s.id} className={cn("row-card", !s.enabled && "opacity-60")}>
              <span className="medal"><Icon className="size-5" /></span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 font-bold">
                  {s.name || moduleName(s.module)}
                  <span className="text-xs font-normal text-gold">{moduleName(s.module)}</span>
                  {/* 开发版建的演练计划到了正式版也要看得出来（两边共用数据目录） */}
                  {isDryRun(s.config) && <span className="text-xs font-normal text-warn" title="这个计划只导航和识别，不会真的操作">演练</span>}
                </div>
                <div className="text-xs text-muted">
                  {triggerLabel(s.trigger)}
                  {s.state.last_status && (
                    <>
                      {"，上次"}
                      <span className={STATUS_COLOR[s.state.last_status]}>{statusLabel(s.state.last_status)}</span>
                      {s.state.last_ended && `（${dayTime(s.state.last_ended)}）`}
                    </>
                  )}
                  {s.state.failures > 0 && <span className="text-bad">，连续失败 {s.state.failures} 次</span>}
                  {s.state.last_skip && <span>，上次跳过：{s.state.last_skip}</span>}
                </div>
              </div>
              <div className="w-[120px] text-right">
                <div className="text-xs text-muted">下次</div>
                <div className="num text-base font-semibold" title={s.state.next_run ? dayTime(s.state.next_run) : undefined}>{next}</div>
              </div>
              <span className="w-px self-stretch bg-white/10" />
              <div className="flex items-center gap-1.5">
                <IconButton label="立即运行" onClick={() => act(() => api().runSchedule(s.id), "已开始")}><Play className="size-4" /></IconButton>
                <IconButton label="编辑" onClick={() => setEditing(s)}><Pencil className="size-4" /></IconButton>
                <IconButton label="删除" danger onClick={async () => {
                  if (await confirmDialog("删除计划", `删除「${s.name || moduleName(s.module)}」？`, "删除", true))
                    void act(() => api().deleteSchedule(s.id), "已删除");
                }}><Trash2 className="size-4" /></IconButton>
                <Check checked={s.enabled} label={s.enabled ? "关闭这个计划" : "开启这个计划"}
                  onChange={(v) => act(() => api().updateSchedule(s.id, { enabled: v }))} />
              </div>
            </div>
          );
        })}
      </div>

      {presets.length > 0 && (
        <>
          <h3 className="panel-title mt-6 mb-2">推荐计划</h3>
          <div className="flex flex-col gap-2">
            {presets.map(({ module, preset: p }) => {
              const added = existing.has(`${module}:${p.name}`);
              const Icon = moduleUI(module).icon;
              return (
                <div key={`${module}:${p.name}`} className="row-card">
                  <span className="medal"><Icon className="size-5" /></span>
                  <div className="flex-1">
                    <div className="font-bold">{p.name} <span className="text-xs font-normal text-gold">{moduleName(module)}</span></div>
                    <div className="text-xs text-muted">{p.description}</div>
                  </div>
                  <button type="button" className="btn btn-bronze btn-sm" disabled={added} onClick={() => setPreset({ module, preset: p })}>
                    {added ? "已添加" : "添加"}
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}

      {editing && (
        <ScheduleEditor
          key={editing === "new" ? "new" : editing.id}
          schedule={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={refresh}
          moduleOptions={visibleModules(modules ?? []).map((m) => ({ value: m.id, label: moduleUI(m.id).menuLabel ?? m.name }))}
        />
      )}
      {preset && (
        <ScheduleEditor
          key={`preset:${preset.preset.name}`}
          schedule={null}
          preset={preset}
          onClose={() => setPreset(null)}
          onSaved={refresh}
          moduleOptions={visibleModules(modules ?? []).map((m) => ({ value: m.id, label: moduleUI(m.id).menuLabel ?? m.name }))}
        />
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

// ---------------------------------------------------------------- 编辑

type TriggerType = Trigger["type"];

const TRIGGER_OPTIONS: { value: TriggerType; label: string }[] = [
  { value: "interval", label: "每隔一段时间" },
  { value: "daily", label: "每天固定时间" },
  { value: "module", label: "按游戏时间（由功能决定）" },
];

export function ScheduleEditor({
  schedule, preset, initial, onClose, onSaved, moduleOptions,
}: {
  schedule: Schedule | null;
  preset?: { module: string; preset: SchedulePreset };
  /** 新建时预先填好的功能、名字和设置（「我的流程」的「加入计划」） */
  initial?: { module: string; name: string; config: Record<string, unknown> };
  onClose: () => void;
  onSaved: () => void;
  moduleOptions: { value: string; label: string }[];
}) {
  const [moduleId, setModuleId] = useState(schedule?.module ?? preset?.module ?? initial?.module ?? moduleOptions[0]?.value ?? "");
  const [name, setName] = useState(schedule?.name ?? preset?.preset.name ?? initial?.name ?? "");
  const [trigger, setTrigger] = useState<Trigger>(schedule?.trigger ?? preset?.preset.trigger ?? { type: "interval", minutes: 30 });
  const [onBusy, setOnBusy] = useState<ScheduleSpec["on_busy"]>(schedule?.on_busy ?? "queue");
  const [config, setConfig] = useState<Record<string, unknown> | null>(schedule?.config ?? initial?.config ?? null);
  const [saving, setSaving] = useState(false);
  const { data: detail } = useModuleDetail(moduleId);
  const fields = useMemo(() => (detail ? fieldsOf(detail.config_schema) : []), [detail]);
  const ui = moduleUI(moduleId);

  // 新建时以模块当前设置为底（加上推荐计划的覆盖）
  const cfg = config ?? (detail ? { ...detail.config, ...(preset?.preset.config ?? {}) } : null);

  const setType = (t: TriggerType) =>
    setTrigger(t === "interval" ? { type: "interval", minutes: 30 } : t === "daily" ? { type: "daily", at: "03:05" } : { type: "module", min_interval_minutes: 10 });

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    try {
      const body = { module: moduleId, name, trigger, on_busy: onBusy, config: runConfig(cfg) };
      if (schedule) await api().updateSchedule(schedule.id, body);
      else await api().createSchedule(body);
      toast(schedule ? "计划已保存" : "计划已添加");
      onSaved();
      onClose();
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setSaving(false);
    }
  };

  const triggerOptions = TRIGGER_OPTIONS.filter((o) => o.value !== "module" || detail?.supports_next_due);

  return (
    <Dialog
      open
      onOpenChange={(v) => !v && onClose()}
      title={schedule ? "编辑计划" : "新建计划"}
      className="w-[680px]"
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>取消</button>
          <button type="button" className="btn btn-go" disabled={saving || !cfg || !moduleId} onClick={save}>{schedule ? "保存" : "添加"}</button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Row label="功能">
          <Select value={moduleId} label="功能" options={moduleOptions} disabled={!!schedule}
            onChange={(v) => { setModuleId(v); setConfig(null); }} />
        </Row>
        <Row label="名字">
          <input className="field w-60" value={name} placeholder={moduleName(moduleId)} onChange={(e) => setName(e.target.value)} aria-label="名字" />
        </Row>
        <Row label="什么时候运行">
          <Select value={trigger.type} label="触发方式" options={triggerOptions} onChange={(v) => setType(v as TriggerType)} />
        </Row>
        {trigger.type === "interval" && (
          <Row label="间隔" hint="从上次结束算起">
            <span className="flex items-center gap-2">
              每
              <input className="field num w-20 text-right" inputMode="numeric" value={trigger.minutes} aria-label="间隔分钟"
                onChange={(e) => setTrigger({ type: "interval", minutes: Number(e.target.value) || 0 })} />
              分钟
            </span>
          </Row>
        )}
        {trigger.type === "daily" && (
          <Row label="时间" hint="北京时间">
            <input type="time" className="field num w-32" value={trigger.at} aria-label="每天的时间"
              onChange={(e) => setTrigger({ type: "daily", at: e.target.value })} />
          </Row>
        )}
        {trigger.type === "module" && (
          <Row label="说明">
            <span className="text-sm text-muted">由功能自己决定什么时候运行。</span>
          </Row>
        )}
        <Row label="到点时有别的任务在运行">
          <Select value={onBusy} label="忙时" options={[{ value: "queue", label: "排队等它结束" }, { value: "skip", label: "这次跳过" }]}
            onChange={(v) => setOnBusy(v as ScheduleSpec["on_busy"])} />
        </Row>
        <h4 className="panel-title mt-2">运行时用的设置</h4>
        {cfg && detail ? (
          <ConfigForm fields={fields} config={cfg} ui={ui} errors={{}} update={(k, v) => setConfig({ ...cfg, [k]: v })} />
        ) : (
          <p className="text-muted">加载中…</p>
        )}
        {isDev && cfg && "dry_run" in cfg && (
          <label className="flex items-center gap-2 text-sm">
            <Check checked={cfg.dry_run === true} label="演练" onChange={(v) => setConfig({ ...cfg, dry_run: v })} />
            演练（开发版）
          </label>
        )}
      </div>
    </Dialog>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-4">
      <div className="w-44 flex-none">
        <div className="font-semibold">{label}</div>
        {hint && <div className="text-xs text-muted">{hint}</div>}
      </div>
      {children}
    </div>
  );
}
