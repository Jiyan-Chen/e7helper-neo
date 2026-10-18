// /ws 控制 + 事件频道（协议见 engine/e7helper/api/ws.py）。断线后自动重连（1 秒起，最多 5 秒一次）。
import type { Status, WsEvent } from "./types";

type Reply = { type: "reply"; id: number | null; ok: boolean; data?: unknown; error?: { code: string; message: string } };
type Pending = { resolve: (v: unknown) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> };

export type SocketState = "connecting" | "open" | "closed";

export class EngineSocket {
  private ws: WebSocket | null = null;
  private seq = 0;
  private pending = new Map<number, Pending>();
  private retry = 0;
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly url: string,
    private readonly handlers: {
      onHello: (status: Status) => void;
      onEvent: (event: WsEvent) => void;
      onState: (state: SocketState) => void;
    },
  ) {}

  open() {
    this.closedByUser = false;
    this.handlers.onState("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.handlers.onState("open");
      // 除帧以外的全部主题；日志只要 INFO 及以上
      void this.request("subscribe", { topics: ["*"], log_level: "INFO" }).catch(() => {});
    };
    ws.onmessage = (ev) => this.onMessage(ev.data);
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      for (const p of this.pending.values()) {
        clearTimeout(p.timer);
        p.reject(new Error("连接已断开"));
      }
      this.pending.clear();
      this.handlers.onState("closed");
      if (!this.closedByUser) {
        const delay = Math.min(5000, 1000 * 2 ** this.retry++);
        this.reconnectTimer = setTimeout(() => this.open(), delay);
      }
    };
  }

  close() {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  request<T = unknown>(op: string, payload: Record<string, unknown> = {}, timeoutMs = 15000): Promise<T> {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) return Promise.reject(new Error("和引擎的连接已断开"));
    const id = ++this.seq;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`引擎没有回应（${op}）`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer });
      ws.send(JSON.stringify({ id, op, ...payload }));
    });
  }

  private onMessage(raw: unknown) {
    if (typeof raw !== "string") return;
    let msg: { type?: string };
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    if (msg.type === "hello") {
      this.handlers.onHello((msg as { data: Status }).data);
    } else if (msg.type === "event") {
      this.handlers.onEvent(msg as WsEvent);
    } else if (msg.type === "reply") {
      const r = msg as Reply;
      const p = r.id === null ? undefined : this.pending.get(r.id);
      if (!p) return;
      this.pending.delete(r.id as number);
      clearTimeout(p.timer);
      if (r.ok) p.resolve(r.data);
      else p.reject(new Error(r.error?.message ?? "操作失败"));
    }
  }
}
