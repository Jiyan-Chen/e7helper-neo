// 书签刷取：要买的商品。固定三种，点一下选中（高亮）/ 取消，不能增删改（B12 用户意见）。
import { cn } from "@/lib/utils";
import type { FieldRendererProps } from "../types";
import covenant from "./icons/covenant.png";
import friendship from "./icons/friendship.png";
import mystic from "./icons/mystic.png";

const ITEMS = [
  { id: "covenant", name: "誓约书签", icon: covenant },
  { id: "mystic", name: "神秘奖牌", icon: mystic },
  { id: "friendship", name: "友情点数", icon: friendship },
] as const;

export function ItemPicker({ field, value, onChange }: FieldRendererProps) {
  const picked = new Set(Array.isArray(value) ? (value as string[]) : []);
  const toggle = (id: string) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(ITEMS.map((it) => it.id).filter((i) => next.has(i)));
  };
  return (
    <div className="row-card flex-col items-stretch gap-3">
      <div className="font-bold">{field.label}</div>
      <div className="grid grid-cols-3 gap-3">
        {ITEMS.map((it) => {
          const on = picked.has(it.id);
          return (
            <button key={it.id} type="button" role="switch" aria-checked={on} aria-label={it.name}
              onClick={() => toggle(it.id)}
              className={cn(
                "flex cursor-pointer flex-col items-center gap-1.5 rounded-[10px] border-[1.5px] px-2 pt-2 pb-2.5 transition",
                on
                  ? "border-gold bg-gold/12 shadow-[0_0_14px_rgba(216,182,121,0.35)]"
                  : "border-white/10 bg-black/25 opacity-45 grayscale-[60%] hover:opacity-75",
              )}>
              <img src={it.icon} alt="" className="size-20 object-contain drop-shadow-[0_4px_6px_rgba(0,0,0,0.5)]" draggable={false} />
              <span className={cn("text-sm font-bold", on ? "text-[#ffe2a1]" : "text-muted")}>{it.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
