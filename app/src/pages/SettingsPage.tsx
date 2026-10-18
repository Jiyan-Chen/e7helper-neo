import { useQuery } from "@tanstack/react-query";
import { MonitorSmartphone, Plug, Unplug } from "lucide-react";
import { useState } from "react";
import { toast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { isDev } from "@/lib/env";
import { qk } from "@/lib/query";
import { useEngine } from "@/lib/store";
import { cn } from "@/lib/utils";

export function SettingsPage() {
  const status = useEngine((s) => s.status);
  const connection = useEngine((s) => s.connection);
  const device = status?.device;
  const busy = !!status?.task;
  const [working, setWorking] = useState(false);
  const { data: inst, error: instError, refetch } = useQuery({ queryKey: qk.instances, queryFn: () => api().instances(), retry: 0 });

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setWorking(true);
    try {
      await fn();
      toast(ok);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setWorking(false);
      void refetch();
    }
  };

  return (
    <div className="h-full overflow-auto px-[22px] py-4">
      <section className="panel mb-3.5 px-4 py-3.5">
        <h3 className="panel-title mb-3"><MonitorSmartphone className="size-5" />MuMu 模拟器</h3>
        <div className="row-card mb-3">
          <span className={cn("size-3 rounded-full", device?.connected ? "bg-[#5fd35a] shadow-[0_0_8px_#5fd35a]" : "bg-bad")} />
          <div className="flex-1">
            <div className="font-bold">{device?.connected ? `已连接：${device.name}` : "没有连接"}</div>
            <div className="text-xs text-muted">
              {device?.connected
                ? `分辨率 ${device.resolution?.join("×")}${isDev && device.backend ? `，${device.backend}` : ""}`
                : device?.error ?? "先启动 MuMu 和游戏，再点「连接」。"}
            </div>
          </div>
          {device?.connected ? (
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy || working} title={busy ? "有任务在运行，不能断开" : undefined}
              onClick={() => run(() => api().disconnect(), "已断开")}>
              <Unplug className="size-4" />断开
            </button>
          ) : (
            <button type="button" className="btn btn-go btn-sm" disabled={working} onClick={() => run(() => api().connect(), "已连接")}>
              <Plug className="size-4" />连接
            </button>
          )}
        </div>
        {instError ? (
          <p className="text-sm text-muted">读不到 MuMu 的实例列表：{errorMessage(instError)}</p>
        ) : inst && (
          <>
            <div className="mb-1.5 text-xs text-muted">MuMu {inst.version ?? ""} 的实例（游戏要用 1600×900 平板模式）</div>
            <div className="flex flex-col gap-1.5">
              {inst.instances.map((i) => {
                const current = device?.connected && device.index === i.index;
                return (
                  <div key={i.index} className="flex items-center gap-3 rounded-[10px] bg-black/25 px-3 py-2 text-sm">
                    <span className="num w-6 text-muted">#{i.index}</span>
                    <span className="flex-1">{i.name}</span>
                    <span className={i.started ? "text-ok" : "text-muted"}>{i.started ? "运行中" : "未启动"}</span>
                    {current ? (
                      <span className="w-[72px] text-center text-gold">使用中</span>
                    ) : (
                      <button type="button" className="btn btn-ghost btn-sm w-[72px]" disabled={!i.started || busy || working}
                        onClick={() => run(() => api().connect(i.index), `已切换到 #${i.index}`)}>使用</button>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </section>

      <section className="panel px-4 py-3.5">
        <h3 className="panel-title mb-2">关于</h3>
        <div className="text-sm text-muted">
          <div>助手版本 {status?.version ?? "—"}</div>
          {isDev && connection && (
            <div className="select-text">
              引擎 {connection.url}（{connection.spawned ? "由本应用启动" : "外部启动"}）<a className="ml-2 text-glow" href={`${connection.url}/docs`} target="_blank" rel="noreferrer">接口文档</a>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
