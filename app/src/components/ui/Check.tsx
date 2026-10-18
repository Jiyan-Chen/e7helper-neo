import { Check as CheckIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** 游戏里那种米金描边的勾选框，语义上是开关。 */
export function Check({
  checked, onChange, label, disabled, className, tone = "gold",
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  className?: string;
  tone?: "gold" | "red";
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "grid size-[30px] flex-none place-items-center rounded-md border-[1.5px] bg-black/35 transition-colors",
        checked ? (tone === "red" ? "border-bad text-bad" : "border-gold text-[#ffe2a1]") : "border-gold-line text-transparent",
        disabled ? "cursor-default opacity-50" : "cursor-pointer hover:border-gold",
        className,
      )}
    >
      <CheckIcon className="size-5" strokeWidth={3} />
    </button>
  );
}
