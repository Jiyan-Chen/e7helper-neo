import { CircleAlert, CircleCheck } from "lucide-react";
import { create } from "zustand";
import { cn } from "@/lib/utils";

interface ToastItem {
  id: number;
  kind: "ok" | "error";
  text: string;
}

const useToasts = create<{ items: ToastItem[] }>(() => ({ items: [] }));
let seq = 0;

/** 底部居中的短提示，几秒后自动消失（仿游戏里的提示条）。 */
export function toast(text: string, kind: "ok" | "error" = "ok") {
  const id = ++seq;
  useToasts.setState((s) => ({ items: [...s.items.slice(-2), { id, kind, text }] }));
  setTimeout(() => useToasts.setState((s) => ({ items: s.items.filter((t) => t.id !== id) })), kind === "error" ? 6000 : 2500);
}

export function Toaster() {
  const items = useToasts((s) => s.items);
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex flex-col items-center gap-2" role="status" aria-live="polite">
      {items.map((t) => (
        <div
          key={t.id}
          className={cn(
            "flex items-center gap-2 rounded-full border px-5 py-2 text-sm shadow-lg backdrop-blur",
            t.kind === "ok" ? "border-ok/40 bg-[#14301a]/90 text-[#d8f1cb]" : "border-bad/50 bg-[#3a1610]/92 text-[#ffd2c8]",
          )}
        >
          {t.kind === "ok" ? <CircleCheck className="size-4" /> : <CircleAlert className="size-4" />}
          {t.text}
        </div>
      ))}
    </div>
  );
}
