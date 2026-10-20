// 日常收取 · 商店：要买的商品。固定清单（B12b 用户圈定），按所在页签分组，点一下选中（高亮）/ 取消。
import { cn } from "@/lib/utils";
import type { FieldRendererProps } from "../types";
import accessoryHigh from "./icons/accessory_high.png";
import accessoryLow from "./icons/accessory_low.png";
import affinityBox from "./icons/affinity_box.png";
import arenaEnergy from "./icons/arena_energy.png";
import artifactHigh from "./icons/artifact_high.png";
import artifactLow from "./icons/artifact_low.png";
import catalystBox from "./icons/catalyst_box.png";
import core from "./icons/core.png";
import energy from "./icons/energy.png";
import flower from "./icons/flower.png";
import free from "./icons/free.png";
import molagora from "./icons/molagora.png";
import potential from "./icons/potential.png";

interface Item {
  id: string;
  name: string;
  icon: string;
  weekly?: boolean;
}

const GROUPS: { label: string; items: Item[] }[] = [
  { label: "交易所 · 竞技场", items: [{ id: "arena_energy", name: "40点行动力", icon: arenaEnergy }] },
  {
    label: "商店 · 一般",
    items: [
      { id: "free", name: "普琳每日免费商品", icon: free },
      { id: "energy", name: "40点行动力", icon: energy },
      { id: "core", name: "光谱核心", icon: core },
      { id: "affinity_box", name: "亲密度献礼选择箱", icon: affinityBox, weekly: true },
      { id: "artifact_low_general", name: "下级神器强化石", icon: artifactLow, weekly: true },
    ],
  },
  {
    label: "商店 · 传承石",
    items: [
      { id: "molagora", name: "魔罗戈拉", icon: molagora, weekly: true },
      { id: "flower", name: "上级精灵之花", icon: flower, weekly: true },
      { id: "potential", name: "潜能开发碎片", icon: potential, weekly: true },
      { id: "catalyst_box", name: "装备炼制石选择箱", icon: catalystBox, weekly: true },
      { id: "artifact_high", name: "上级神器强化石", icon: artifactHigh, weekly: true },
      { id: "accessory_high", name: "2个上级饰品强化石", icon: accessoryHigh, weekly: true },
      { id: "artifact_low", name: "下级神器强化石", icon: artifactLow, weekly: true },
      { id: "accessory_low", name: "2个下级饰品强化石", icon: accessoryLow, weekly: true },
    ],
  },
];

const ORDER = GROUPS.flatMap((g) => g.items.map((it) => it.id));

export function ShopItemPicker({ field, value, onChange, disabled }: FieldRendererProps) {
  const picked = new Set(Array.isArray(value) ? (value as string[]) : []);
  const toggle = (id: string) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(ORDER.filter((i) => next.has(i)));
  };
  return (
    <div className={cn("row-card flex-col items-stretch gap-3", disabled && "pointer-events-none opacity-45")}>
      <div className="font-bold">{field.label}</div>
      {GROUPS.map((g) => (
        <div key={g.label} className="flex flex-col gap-2">
          <div className="text-xs text-muted">{g.label}</div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(104px,1fr))] gap-2">
            {g.items.map((it) => {
              const on = picked.has(it.id);
              return (
                <button key={it.id} type="button" role="switch" aria-checked={on} aria-label={`${g.label} ${it.name}`}
                  disabled={disabled} onClick={() => toggle(it.id)}
                  className={cn(
                    "relative flex cursor-pointer flex-col items-center gap-1 rounded-[10px] border-[1.5px] px-1.5 pt-1.5 pb-2 transition",
                    on
                      ? "border-gold bg-gold/12 shadow-[0_0_12px_rgba(216,182,121,0.3)]"
                      : "border-white/10 bg-black/25 opacity-45 grayscale-[60%] hover:opacity-75",
                  )}>
                  <span className={cn(
                    "absolute top-1 right-1 rounded px-1 text-[10px] leading-4",
                    on ? "bg-black/40 text-[#ffe2a1]" : "bg-black/40 text-muted",
                  )}>
                    {it.weekly ? "每周" : "每日"}
                  </span>
                  <img src={it.icon} alt="" className="size-14 object-contain drop-shadow-[0_3px_5px_rgba(0,0,0,0.5)]" draggable={false} />
                  <span className={cn("text-center text-xs leading-tight font-bold", on ? "text-[#ffe2a1]" : "text-muted")}>
                    {it.name}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
