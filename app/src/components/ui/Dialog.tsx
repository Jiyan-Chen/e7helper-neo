import { X } from "lucide-react";
import { Dialog as D } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Ornament } from "./Ornament";

/** 游戏风对话框：压暗遮罩 + 深色圆角框，标题下有装饰线。 */
export function Dialog({
  open, onOpenChange, title, children, footer, className,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]" />
        <D.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[86vh] w-[560px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-2xl border border-white/12 bg-[#151b2b]/97 shadow-[0_20px_60px_rgba(0,0,0,.6)]",
            className,
          )}
        >
          <div className="flex items-center justify-between px-6 pt-5">
            <D.Title className="text-lg font-bold">{title}</D.Title>
            <D.Close className="grid size-8 cursor-pointer place-items-center rounded-full text-muted hover:bg-white/8 hover:text-ink" aria-label="关闭">
              <X className="size-5" />
            </D.Close>
          </div>
          <Ornament className="mx-6 mt-3" />
          <D.Description className="sr-only">{typeof title === "string" ? title : "对话框"}</D.Description>
          <div className="min-h-0 flex-1 overflow-auto px-6 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-3 px-6 pb-5">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
