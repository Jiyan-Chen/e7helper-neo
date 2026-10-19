// 「持续收菜」= 一条 module 触发的计划（B08）：每日重置后跑一次，精灵之森到时间再跑。
import { useState } from "react";
import { Check } from "@/components/ui/Check";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useNow, useSchedules } from "@/lib/hooks";
import { qk, queryClient } from "@/lib/query";
import { isDryRun, runConfig } from "@/lib/run";
import { formatDuration, secondsUntil } from "@/lib/time";
import type { Schedule, SchedulesSnapshot } from "@/lib/types";
import type { ModuleExtraProps } from "../types";

export const CONTINUOUS_NAME = "持续收菜";

export function findContinuous(snap: SchedulesSnapshot | undefined): Schedule | undefined {
  return snap?.schedules.find((s) => s.module === "daily" && s.trigger.type === "module");
}

/** 设置改了以后，把新设置同步到持续收菜的计划里（计划里存的是配置快照）。 */
export async function syncContinuous(config: Record<string, unknown>) {
  const snap = queryClient.getQueryData<SchedulesSnapshot>(qk.schedules) ?? (await api().schedules());
  const s = findContinuous(snap);
  if (!s) return;
  try {
    await api().updateSchedule(s.id, { config: runConfig(config) });
    void queryClient.invalidateQueries({ queryKey: qk.schedules });
  } catch (e) {
    toast(`持续收菜没有跟着更新：${errorMessage(e)}`, "error");
  }
}

export function Continuous({ config }: ModuleExtraProps) {
  const { data } = useSchedules();
  const [busy, setBusy] = useState(false);
  const now = useNow();
  const s = findContinuous(data);
  const on = !!s?.enabled;
  const paused = data?.paused ?? false;

  const toggle = async (v: boolean) => {
    setBusy(true);
    try {
      if (s) await api().updateSchedule(s.id, v ? { enabled: true, config: runConfig(config) } : { enabled: false });
      else if (v)
        await api().createSchedule({
          module: "daily",
          name: CONTINUOUS_NAME,
          trigger: { type: "module", min_interval_minutes: 10 },
          config: runConfig(config),
        });
      await queryClient.invalidateQueries({ queryKey: qk.schedules });
      toast(v ? "已开启持续收菜" : "已关闭持续收菜");
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const left = on ? secondsUntil(s?.state.next_run, now) : null;
  let next = "关闭中";
  let countdown = false;
  if (on && paused) next = "计划已暂停";
  else if (on && s?.state.running_task) next = "正在收菜";
  else if (on && s?.state.queued_since) next = "排队中";
  else if (on && left !== null) {
    next = left <= 0 ? "马上" : formatDuration(left);
    countdown = left > 0;
  }

  return (
    <div className="flex items-center gap-3 whitespace-nowrap rounded-[10px] border border-white/8 bg-black/35 px-3.5 py-2">
      <Check checked={on} onChange={toggle} label={CONTINUOUS_NAME} disabled={busy} />
      <div>
        <b className="text-[15px]">{CONTINUOUS_NAME}</b>
        {on && isDryRun(s?.config) && <span className="ml-2 text-xs text-warn" title="只导航和识别，不会真的领取">演练</span>}
        <div className="text-xs text-muted">每天自动收菜</div>
      </div>
      <div className="ml-2 text-right">
        <div className="text-xs text-muted">下次</div>
        <div className={countdown ? "num text-lg font-semibold" : "text-sm font-semibold text-muted"}>{next}</div>
      </div>
    </div>
  );
}
