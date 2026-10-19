// 自己画的窗口按钮（B12 用户意见：系统标题栏太突兀，做进应用里）。窗口去掉了系统标题栏（decorations: false），
// 顶栏带 data-tauri-drag-region：按住拖动窗口，双击最大化 / 还原。浏览器里（pnpm dev）不显示。
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Copy, Minus, Square, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const inTauri = isTauri();

export function WindowControls({ className }: { className?: string }) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!inTauri) return;
    const win = getCurrentWindow();
    let unlisten: (() => void) | undefined;
    let alive = true;
    const sync = () => void win.isMaximized().then((m) => alive && setMaximized(m));
    sync();
    void win.onResized(sync).then((u) => (alive ? (unlisten = u) : u()));
    return () => {
      alive = false;
      unlisten?.();
    };
  }, []);

  if (!inTauri) return null;
  const win = getCurrentWindow();
  return (
    <div className={cn("flex self-stretch", className)}>
      <WinButton label="最小化" onClick={() => void win.minimize()}>
        <Minus className="size-4" />
      </WinButton>
      <WinButton label={maximized ? "还原" : "最大化"} onClick={() => void win.toggleMaximize()}>
        {maximized ? <Copy className="size-3.5 -scale-x-100" /> : <Square className="size-3.5" />}
      </WinButton>
      <WinButton label="关闭" danger onClick={() => void win.close()}>
        <X className="size-[18px]" />
      </WinButton>
    </div>
  );
}

function WinButton({ label, danger, onClick, children }: {
  label: string;
  danger?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick}
      className={cn(
        "grid w-[46px] cursor-pointer place-items-center text-muted transition-colors",
        danger ? "hover:bg-[#c4402b] hover:text-white" : "hover:bg-white/10 hover:text-[#ffe2a1]",
      )}>
      {children}
    </button>
  );
}

/** 启动 / 连接失败画面用：顶上一条能拖动的空白 + 窗口按钮（这时顶栏还没出来）。 */
export function WindowDragStrip() {
  if (!inTauri) return null;
  return (
    <div data-tauri-drag-region className="absolute inset-x-0 top-0 z-10 flex h-10 justify-end">
      <WindowControls />
    </div>
  );
}
