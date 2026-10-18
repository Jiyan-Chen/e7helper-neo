import { useQuery } from "@tanstack/react-query";
import { Timer } from "lucide-react";
import { api } from "@/lib/api";
import { useNow } from "@/lib/hooks";
import { qk } from "@/lib/query";
import { formatDuration, secondsUntil } from "@/lib/time";
import { cn } from "@/lib/utils";

/** 模块计时（仿精灵之森的胶囊）：倒计时；到时间的发蓝光、带红点。没有计时的模块不显示。 */
export function Timers({ moduleId }: { moduleId: string }) {
  const { data } = useQuery({ queryKey: qk.timers(moduleId), queryFn: () => api().timers(moduleId), refetchInterval: 60_000 });
  const now = useNow();
  if (!data || data.length === 0) return null;
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(data.length, 4)}, minmax(0, 1fr))` }}>
      {data.map((t) => {
        const left = secondsUntil(t.at, now);
        const ready = left !== null && left <= 0;
        return (
          <div key={t.key} className={cn("pill", ready && "pill-ready")} title={t.note || undefined}>
            <div className="text-[13px] text-[#dfe3ea]">{t.label}</div>
            {left === null ? (
              <div className="py-1 text-base text-muted">{t.note || "—"}</div>
            ) : ready ? (
              <div className="text-[22px] font-bold leading-snug">已到时间</div>
            ) : (
              <div className="num flex items-center justify-center gap-2 text-[26px] font-semibold leading-tight">
                <Timer className="size-5" />
                {formatDuration(left)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
