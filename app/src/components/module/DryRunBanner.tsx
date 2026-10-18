import { FlaskConical, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Check } from "@/components/ui/Check";
import { Dialog } from "@/components/ui/Dialog";
import { cn } from "@/lib/utils";

/**
 * 只在开发版出现的演练开关（正式版没有这个概念，一律实跑）。
 * 勾上 = 演练：只导航和识别；取消勾选切到实跑前要确认。
 */
export function DryRunBanner({
  dryRun, description, onChange, disabled,
}: {
  dryRun: boolean;
  description: string;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const [confirm, setConfirm] = useState(false);
  return (
    <>
      <div
        className={cn(
          "flex items-center gap-3 rounded-[10px] border px-4 py-2.5",
          dryRun ? "border-[#8fd36d]/40 bg-[#4f9e35]/16" : "border-bad bg-[#d9563a]/20",
        )}
      >
        {dryRun ? <FlaskConical className="size-5 flex-none text-[#9fe27c]" /> : <TriangleAlert className="size-5 flex-none text-bad" />}
        <div className={cn("flex-1", dryRun ? "text-[#d8f1cb]" : "font-semibold text-[#ffd2c8]")}>
          <b className="mr-2">{dryRun ? "演练" : "实跑"}</b>
          {dryRun ? `${description}。取消勾选才会真的操作。` : "会真的操作游戏（领取、购买、消耗资源）。"}
          <span className="ml-2 rounded border border-gold-line px-1.5 text-[11px] font-normal text-gold">开发版</span>
        </div>
        <Check checked={dryRun} label="演练" disabled={disabled} onChange={(v) => (v ? onChange(true) : setConfirm(true))} />
      </div>
      <Dialog
        open={confirm}
        onOpenChange={setConfirm}
        title="切换到实跑？"
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setConfirm(false)}>取消</button>
            <button type="button" className="btn btn-real" onClick={() => { onChange(false); setConfirm(false); }}>切换到实跑</button>
          </>
        }
      >
        <p>实跑会真的点击游戏里的领取、购买等按钮，可能消耗资源。确定要切换吗？</p>
      </Dialog>
    </>
  );
}
