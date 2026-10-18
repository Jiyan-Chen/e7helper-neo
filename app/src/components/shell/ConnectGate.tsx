import { LoaderCircle, PlugZap } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Ornament } from "@/components/ui/Ornament";
import { resolveConnection } from "@/lib/connection";
import { startEngine } from "@/lib/store";

/** 启动画面：等引擎连上（Tauri 可能要先拉起引擎，几秒到几十秒）。 */
export function ConnectGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  const connect = useCallback(async () => {
    setState("loading");
    try {
      await startEngine(await resolveConnection());
      setState("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  }, []);

  // StrictMode 下 effect 会执行两次；连接只发起一次（Tauri 可能要拉起引擎）
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void connect();
  }, [connect]);

  if (state === "ready") return <>{children}</>;
  return (
    <div className="grid h-full place-items-center">
      <div className="panel flex w-[440px] flex-col items-center gap-4 px-8 py-7 text-center">
        <div className="text-2xl font-bold tracking-wide">第七史诗助手</div>
        <Ornament className="w-full" />
        {state === "loading" ? (
          <>
            <LoaderCircle className="size-8 animate-spin text-gold" />
            <p className="text-muted">正在启动助手…</p>
          </>
        ) : (
          <>
            <PlugZap className="size-8 text-bad" />
            <p>助手没有启动成功</p>
            <p className="max-h-40 overflow-auto text-sm break-all text-muted select-text">{error}</p>
            <button type="button" className="btn btn-go" onClick={() => void connect()}>重试</button>
          </>
        )}
      </div>
    </div>
  );
}
