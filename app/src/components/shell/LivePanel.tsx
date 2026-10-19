import { MonitorOff, PanelRightClose, PanelRightOpen, ScrollText } from "lucide-react";
import { useState } from "react";
import { isDev } from "@/lib/env";
import { useFrames } from "@/lib/frames";
import { sceneLabel } from "@/lib/labels";
import { useEngine } from "@/lib/store";
import { cn } from "@/lib/utils";
import { ActivityList } from "./ActivityList";

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem("e7.livePanel.collapsed") === "1";
  } catch {
    return false;
  }
}

/** 右侧栏：实时画面 + 动态。可以收起（记在本机）。 */
export function LivePanel() {
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [tab, setTab] = useState<"activity" | "all">("activity");
  const connected = useEngine((s) => s.status?.device.connected ?? false);
  const scene = useEngine((s) => s.scene);
  const frame = useFrames(connected && !collapsed);

  const toggle = () => {
    const v = !collapsed;
    setCollapsed(v);
    try {
      localStorage.setItem("e7.livePanel.collapsed", v ? "1" : "0");
    } catch {
      /* 存不了就算了 */
    }
  };

  if (collapsed) {
    return (
      <aside className="anim-fade flex w-11 flex-col items-center gap-3 border-l border-white/8 bg-[#0a1020]/50 pt-3">
        <button type="button" className="grid size-8 cursor-pointer place-items-center rounded-md text-muted hover:bg-white/8 hover:text-ink"
          onClick={toggle} aria-label="展开画面和动态" title="展开画面和动态">
          <PanelRightOpen className="size-5" />
        </button>
      </aside>
    );
  }

  return (
    <aside className="anim-slide-right flex w-[380px] min-h-0 flex-col gap-3 py-4 pr-4">
      <div className="relative overflow-hidden rounded-xl border-[1.5px] border-gold-line shadow-[0_0_0_3px_rgba(0,0,0,.35)]">
        {frame ? (
          <img src={frame} alt="当前游戏画面" className="block aspect-video w-full object-cover" />
        ) : (
          <div className="grid aspect-video w-full place-items-center bg-black/50 text-muted">
            <span className="flex items-center gap-2"><MonitorOff className="size-5" />{connected ? "画面加载中…" : "模拟器未连接"}</span>
          </div>
        )}
        {connected && (
          <span className="absolute right-2.5 bottom-2 rounded-full bg-black/60 px-2.5 text-xs text-gold">{sceneLabel(scene?.scene, scene?.popup)}</span>
        )}
        <button type="button" className="absolute top-2 right-2 grid size-7 cursor-pointer place-items-center rounded-md bg-black/50 text-muted hover:text-ink"
          onClick={toggle} aria-label="收起画面和动态" title="收起画面和动态">
          <PanelRightClose className="size-4" />
        </button>
      </div>
      <section className="panel flex min-h-0 flex-1 flex-col px-4 py-3">
        <div className="mb-2 flex items-center gap-2">
          <h3 className="panel-title mr-auto"><ScrollText className="size-4" />动态</h3>
          {isDev && (
            <>
              <button type="button" className={cn("tab", tab === "activity" && "active")} onClick={() => setTab("activity")}>动态</button>
              <button type="button" className={cn("tab", tab === "all" && "active")} onClick={() => setTab("all")}>全部</button>
            </>
          )}
        </div>
        <ActivityList mode={tab} className="-mx-1.5 flex-1" />
      </section>
    </aside>
  );
}
