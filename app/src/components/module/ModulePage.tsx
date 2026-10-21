import { useMemo } from "react";
import { ConfigForm } from "@/components/module/ConfigForm";
import { DryRunBanner } from "@/components/module/DryRunBanner";
import { RecentRuns } from "@/components/module/RecentRuns";
import { RunBar } from "@/components/module/RunBar";
import { Timers } from "@/components/module/Timers";
import { Ornament } from "@/components/ui/Ornament";
import { errorMessage } from "@/lib/api";
import { isDev } from "@/lib/env";
import { useConfigEditor, useModuleDetail } from "@/lib/hooks";
import { fieldsOf } from "@/lib/schema";
import { useEngine } from "@/lib/store";
import { moduleUI } from "@/modules/registry";

const SAVE_TEXT = { idle: "", saving: "保存中…", saved: "已保存", error: "没有保存" } as const;

/** 通用模块页：说明、计时、（开发版）演练开关、设置、最近运行、底部行动条。 */
export function ModulePage({ moduleId }: { moduleId: string }) {
  const ui = moduleUI(moduleId);
  const { data: module, error, isLoading } = useModuleDetail(moduleId);
  const { config, update, errors, state } = useConfigEditor(module, ui.onConfigSaved);
  const fields = useMemo(() => (module ? fieldsOf(module.config_schema) : []), [module]);
  const running = useEngine((s) => s.status?.task?.module === moduleId);

  if (isLoading) return <div className="p-6 text-muted">加载中…</div>;
  if (error || !module || !config) return <div className="p-6 text-bad">打不开这个功能：{errorMessage(error)}</div>;
  const dryField = fields.find((f) => f.key === "dry_run");
  const Header = ui.Header;
  const RunsPanel = ui.RunsPanel;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-auto px-[22px] pt-4 pb-5">
        <div>
          <p className="mb-2.5 text-muted">{module.description}</p>
          <Ornament />
        </div>
        <Timers moduleId={moduleId} />
        {isDev && dryField && (
          <DryRunBanner dryRun={config.dry_run === true} description={dryField.description} disabled={running}
            onChange={(v) => update("dry_run", v)} />
        )}
        {Header && <Header module={module} config={config} />}
        <div className="flex flex-col gap-3.5">
          <section className="panel px-4 py-3.5">
            <div className="mb-2.5 flex items-center justify-between">
              <h3 className="panel-title">设置</h3>
              <span className={state === "error" ? "text-xs text-bad" : "text-xs text-muted"}>{SAVE_TEXT[state]}</span>
            </div>
            <ConfigForm fields={fields} config={config} update={update} errors={errors} ui={ui} />
          </section>
          {RunsPanel ? <RunsPanel module={module} config={config} /> : (
            <section className="panel px-4 py-3.5">
              <h3 className="panel-title mb-2">最近运行</h3>
              <RecentRuns moduleId={moduleId} />
            </section>
          )}
        </div>
      </div>
      <RunBar module={module} config={config} ui={ui} />
    </div>
  );
}
