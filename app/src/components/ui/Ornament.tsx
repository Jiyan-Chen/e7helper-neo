import { cn } from "@/lib/utils";

/** 米金色装饰线：两端小菱形，中间三颗（游戏里分隔区块用的那种）。 */
export function Ornament({ className }: { className?: string }) {
  return (
    <div className={cn("relative h-[9px]", className)} aria-hidden>
      <div className="absolute inset-x-1 top-1 border-t border-gold-line" />
      <Diamond className="left-0" />
      <Diamond className="right-0" />
      <Diamond className="left-[calc(50%-15px)]" />
      <Diamond className="left-[calc(50%-4px)] bg-gold-line" />
      <Diamond className="left-[calc(50%+7px)]" />
    </div>
  );
}

function Diamond({ className }: { className?: string }) {
  return <i className={cn("absolute top-px size-[7px] rotate-45 border border-gold-line bg-[#141a28]", className)} />;
}
