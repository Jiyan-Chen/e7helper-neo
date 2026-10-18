import { useEffect, useState } from "react";
import { api } from "./api";

/**
 * /ws/frames 帧频道（二进制 JPEG）。返回最新一帧的 object URL；设备没连上时为 null。
 * 有任务时转发任务的截图，空闲时引擎自己截图（只读）。
 */
export function useFrames(enabled: boolean, fps = 2, scale = 0.5): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) {
      setUrl(null);
      return;
    }
    let ws: WebSocket | null = null;
    let current: string | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const open = () => {
      ws = new WebSocket(api().wsUrl("/ws/frames", { fps, scale, quality: 70 }));
      ws.binaryType = "blob";
      ws.onmessage = (ev) => {
        if (typeof ev.data === "string") {
          if (ev.data.includes('"connected": false') || ev.data.includes('"connected":false')) {
            if (current) URL.revokeObjectURL(current);
            current = null;
            setUrl(null);
          }
          return;
        }
        const next = URL.createObjectURL(ev.data as Blob);
        if (current) URL.revokeObjectURL(current);
        current = next;
        setUrl(next);
      };
      ws.onclose = () => {
        if (!stopped) retry = setTimeout(open, 2000);
      };
    };
    open();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      ws?.close();
      if (current) URL.revokeObjectURL(current);
    };
  }, [enabled, fps, scale]);
  return url;
}
