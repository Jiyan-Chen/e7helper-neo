import { useState } from "react";
import { Ornament } from "@/components/ui/Ornament";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { isDev } from "@/lib/env";
import { useModules, useNow } from "@/lib/hooks";
import { runConfig } from "@/lib/run";
import { useEngine } from "@/lib/store";
import { formatElapsed } from "@/lib/time";
import type { ModuleDetail } from "@/lib/types";
import type { ModuleUI } from "@/modules/types";

/** 底部行动条（仿准备战斗界面）：左边放模块的附加控件，右边是开始 / 停止。 */
export function RunBar({ module, config, ui }: { module: ModuleDetail; config: Record<string, unknown>; ui: ModuleUI }) {
  const status = useEngine((s) => s.status);
  const { data: modules } = useModules();
  const [busy, setBusy] = useState(false);
  const now = useNow();
  const task = status?.task ?? null;
  const connected = status?.device.connected ?? false;
  const mine = task?.module === module.id;
  const real = runConfig(config);
  const dry = isDev && real.dry_run === true;
  const Extra = ui.RunExtra;

  const start = async () => {
    setBusy(true);
    try {
      await api().startTask(module.id, real);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };
  const stop = async () => {
    try {
      await api().stopTask();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  let button;
  if (mine) {
    const elapsed = (now / 1000) - task!.started;
    button = (
      <button type="button" className="btn btn-lg btn-real min-w-[230px]" onClick={stop}>
        <span className="chip num">{formatElapsed(elapsed)}</span>停止
      </button>
    );
  } else {
    const other = task ? modules?.find((m) => m.id === task.module)?.name ?? task.module : null;
    const reason = !connected ? "模拟器未连接" : other ? `${other}进行中` : null;
    button = (
      <button type="button" className={`btn btn-lg min-w-[230px] ${isDev && "dry_run" in config && !dry ? "btn-real" : "btn-go"}`}
        disabled={!!reason || busy} title={reason ?? undefined} onClick={start}>
        {isDev && "dry_run" in config && <span className="chip">{dry ? "演练" : "实跑"}</span>}
        {reason ?? ui.runLabel ?? "开始"}
      </button>
    );
  }

  return (
    <div className="relative flex items-center gap-4 bg-[#080c18]/62 px-[22px] py-4 backdrop-blur-sm">
      <Ornament className="absolute inset-x-[22px] top-0.5" />
      {Extra && <Extra module={module} config={config} />}
      <span className="flex-1" />
      {button}
    </div>
  );
}
