// 实时状态：连接、设备、当前任务、调度器概况、场景、日志。数据来自 /ws 的 hello 和事件。
import { create } from "zustand";
import { Api, setApi } from "./api";
import type { EngineConnection } from "./connection";
import { qk, queryClient } from "./query";
import type { LogRecord, SceneInfo, Status, WsEvent } from "./types";
import { EngineSocket, type SocketState } from "./ws";

const LOG_LIMIT = 1000;

interface EngineStore {
  connection: EngineConnection | null;
  socket: SocketState;
  status: Status | null;
  scene: SceneInfo | null;
  logs: LogRecord[];
  /** 本次连接以来最新的事件时间（unix 秒），给需要「刚刚发生」的组件用 */
  lastEventAt: number;
  /** 自定义流程正在执行的那一步（B11，custom_flow.step 事件） */
  flowStep: { flow: string; path: string; id: string } | null;
}

export const useEngine = create<EngineStore>(() => ({
  connection: null,
  socket: "connecting",
  status: null,
  scene: null,
  logs: [],
  lastEventAt: 0,
  flowStep: null,
}));

/** 引擎带不带 RTA 助手（正式版打包时不带）；还没拿到状态时是 null。 */
export const useHasRta = (): boolean | null =>
  useEngine((s) => (s.status ? s.status.features?.rta === true : null));

let socket: EngineSocket | null = null;
let statusTimer: ReturnType<typeof setTimeout> | null = null;

function pushLogs(items: LogRecord[]) {
  useEngine.setState((s) => {
    const logs = s.logs.concat(items);
    return { logs: logs.length > LOG_LIMIT ? logs.slice(logs.length - LOG_LIMIT) : logs };
  });
}

/** 设备、任务、计划有变化时重新取一次概况（合并 200ms 内的多次请求）。 */
function refreshStatus() {
  if (statusTimer) return;
  statusTimer = setTimeout(async () => {
    statusTimer = null;
    try {
      const status = await socket?.request<Status>("status");
      if (status) useEngine.setState({ status });
    } catch {
      /* 断线时由重连后的 hello 补上 */
    }
  }, 200);
}

function onEvent(e: WsEvent) {
  useEngine.setState({ lastEventAt: e.time });
  switch (e.topic) {
    case "log":
      pushLogs([e.data as LogRecord]);
      break;
    case "scene":
      useEngine.setState({ scene: e.data as SceneInfo });
      break;
    case "device":
      useEngine.setState((s) => (s.status ? { status: { ...s.status, device: e.data as Status["device"] } } : {}));
      refreshStatus();
      break;
    case "task": {
      const d = e.data as { module: string; status: string };
      refreshStatus();
      if (d.status !== "running") {
        if (d.module === "custom_flow") {
          useEngine.setState({ flowStep: null });
          void queryClient.invalidateQueries({ queryKey: qk.flows });
        }
        void queryClient.invalidateQueries({ queryKey: ["history"] });
        void queryClient.invalidateQueries({ queryKey: qk.timers(d.module) });
        void queryClient.invalidateQueries({ queryKey: qk.schedules });
      }
      break;
    }
    case "stats": {
      const d = e.data as { module: string };
      void queryClient.invalidateQueries({ queryKey: qk.stats(d.module) });
      void queryClient.invalidateQueries({ queryKey: qk.timers(d.module) });
      void queryClient.invalidateQueries({ queryKey: ["history"] });
      break;
    }
    case "schedule":
      void queryClient.invalidateQueries({ queryKey: qk.schedules });
      refreshStatus();
      break;
    case "assistant":
      refreshStatus();
      break;
    case "custom_flow.step":
      useEngine.setState({ flowStep: e.data as EngineStore["flowStep"] });
      break;
  }
}

/** 连接建立后调用一次：设置 REST 客户端、取最近日志、打开 WS。 */
export async function startEngine(conn: EngineConnection) {
  const client = new Api(conn.url, conn.token);
  setApi(client);
  useEngine.setState({ connection: conn });
  try {
    useEngine.setState({ logs: await client.logs(300) });
  } catch {
    /* 日志拿不到不影响使用 */
  }
  socket?.close();
  socket = new EngineSocket(client.wsUrl("/ws"), {
    onHello: (status) => {
      useEngine.setState({ status });
      // 重连后补一次：断线期间可能有任务结束
      void queryClient.invalidateQueries();
    },
    onEvent,
    onState: (state) => useEngine.setState({ socket: state }),
  });
  socket.open();
}

export function engineSocket(): EngineSocket | null {
  return socket;
}
