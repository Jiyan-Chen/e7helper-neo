// 拿到引擎地址和 token：
// - 在 Tauri 里：调用 Rust 命令 engine_connection（先连已在运行的服务，连不上再拉起，见 src-tauri/src/engine.rs）；
// - 在普通浏览器里（只跑 `pnpm dev` 调界面时）：地址栏 ?url=...&token=...，或环境变量 VITE_E7_URL / VITE_E7_TOKEN。
import { invoke, isTauri } from "@tauri-apps/api/core";

export interface EngineConnection {
  url: string;
  token: string | null;
  spawned: boolean;
}

export async function resolveConnection(): Promise<EngineConnection> {
  if (isTauri()) {
    const c = await invoke<{ url: string; token: string | null; spawned: boolean }>("engine_connection");
    return { url: c.url.replace(/\/$/, ""), token: c.token, spawned: c.spawned };
  }
  const q = new URLSearchParams(window.location.search);
  const url = q.get("url") ?? import.meta.env.VITE_E7_URL ?? "http://127.0.0.1:47800";
  const token = q.get("token") ?? import.meta.env.VITE_E7_TOKEN ?? null;
  return { url: url.replace(/\/$/, ""), token, spawned: false };
}
