// RTA 助手（B14e1）选秀 / 后禁 / 结果时的阵容栏（参考 e7rtabot）：双方并排，每队按顺序 5 格；左边圆圈是这一队的第几名
// （保护位画盾牌），格子里写整局第几手；轮到的格子金色描边，被禁的打红叉。后禁这一步点对方的英雄 = 我方禁它。
// 后禁 / 结果时用 row：每队一行 5 个头像，给后禁矩阵腾出高度（桌面版窗口默认 1280×800）。
import { Shield, X } from "lucide-react";
import { PROTECTED, banOptions, other, pickNumbers, sideOf, stepOf, teamPicks, turn, type Draft, type Team } from "@/lib/draft";
import { cn } from "@/lib/utils";
import { Face, HeroBadges, Tag, useName } from "./bits";

/** 正在选的格子里直接给的前几个（同 e7rtabot）：我方是推荐（预期胜率），对方是可能的选择（可能性） */
export interface SlotSuggest {
  code: string;
  label: string;
}

export function TeamColumn({ team, draft, onBan, suggest, onSuggest, row }: {
  team: Team;
  draft: Draft;
  /** 后禁这一步点这一队的英雄：对方禁它（再点一次取消） */
  onBan: (code: string) => void;
  suggest?: SlotSuggest[];
  onSuggest?: (code: string) => void;
  row?: boolean;
}) {
  const name = useName();
  const step = stepOf(draft);
  const side = sideOf(team, draft.setup.side);
  const picks = teamPicks(draft, team);
  const t = turn(draft);
  const activeFrom = step === "pick" && t?.team === team ? picks.length : -1;
  const activeTo = activeFrom >= 0 && t ? activeFrom + t.slots : -1;
  const banned = draft.bans[other(team)];
  const bannable = step === "ban" || step === "result" ? banOptions(draft, other(team)) : [];

  return (
    <section className="panel flex min-w-0 flex-col gap-1 px-3 py-2" aria-label={team === "mine" ? "我方阵容" : "对方阵容"}>
      <header className="flex items-center gap-2 pb-0.5">
        <span className="panel-title">{team === "mine" ? "我方" : "对方"}</span>
        <span className={cn("rounded-full border px-2 text-xs leading-5", side === "F" ? "border-gold/60 text-gold" : "border-white/20 text-muted")}>
          {side === "F" ? "先手" : "后手"}
        </span>
      </header>
      {row ? (
        <div className="flex gap-2">
          {picks.map((code, i) => {
            const isBanned = code === banned;
            const canBan = bannable.includes(code);
            return (
              <button key={code} type="button" disabled={!canBan} onClick={() => onBan(code)}
                title={!canBan ? name(code) : isBanned ? "取消" : team === "mine" ? `对方禁了${name(code)}` : `我方禁${name(code)}`}
                className={cn("flex w-[68px] min-w-0 flex-col items-center gap-0.5 rounded-lg border px-0.5 py-1",
                  isBanned ? "border-bad/60 bg-bad/8" : "border-transparent", canBan && "cursor-pointer hover:border-bad/70")}>
                <span className="relative">
                  <Face code={code} size={40} shield={i === PROTECTED} className={cn(isBanned && "opacity-40 grayscale")} />
                  {isBanned && <X className="absolute inset-0 m-auto size-8 text-bad drop-shadow-[0_1px_2px_rgba(0,0,0,.9)]" />}
                </span>
                <span className={cn("w-full truncate text-center text-[11px]", isBanned && "text-bad")}>{name(code)}</span>
              </button>
            );
          })}
        </div>
      ) : pickNumbers(team, draft.setup.side).map((num, i) => {
        const code = picks[i];
        const active = i >= activeFrom && i < activeTo;
        const isBanned = !!code && code === banned;
        const canBan = !!code && bannable.includes(code);
        const cls = cn("flex h-[46px] min-w-0 flex-1 items-center gap-2.5 rounded-lg border px-2 text-left transition-colors",
          active ? "border-gold bg-gold/8 shadow-[0_0_12px_rgba(216,182,121,.35)]"
            : code ? "border-white/10 bg-black/25" : "border-dashed border-white/12 bg-black/15",
          isBanned && "border-bad/60 bg-bad/8",
          canBan && "cursor-pointer hover:border-bad/70");
        const body = code ? (
          <>
            <span className="relative flex-none">
              <Face code={code} size={38} className={cn(isBanned && "opacity-40 grayscale")} />
              {isBanned && <X className="absolute inset-0 m-auto size-8 text-bad drop-shadow-[0_1px_2px_rgba(0,0,0,.9)]" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px]">{name(code)}</span>
              <span className="flex items-center gap-1.5">
                <HeroBadges code={code} />
                {i === PROTECTED && <Tag tone="gold">保护</Tag>}
                {isBanned && <span className="text-[11px] text-bad">被禁</span>}
              </span>
            </span>
          </>
        ) : (
          <>
            <span className="min-w-0 flex-1">
              <span className={cn("block truncate text-[13px] whitespace-nowrap", active ? "text-gold" : "text-muted")}>{i === PROTECTED ? `保护位 · 第 ${num} 手` : `第 ${num} 手`}</span>
              <span className="block text-[11px] text-faint">{active ? "选择中" : i === PROTECTED ? "不能被禁" : "等待中"}</span>
            </span>
            {i === activeFrom && suggest?.map((x, k) => (
              <span key={x.code} role="button" tabIndex={0} title={name(x.code)} onClick={() => onSuggest?.(x.code)}
                onKeyDown={(e) => e.key === "Enter" && onSuggest?.(x.code)}
                className={cn("flex flex-none cursor-pointer flex-col items-center rounded-md px-0.5 hover:bg-white/8", k >= 2 && "max-[1199px]:hidden")}>
                <Face code={x.code} size={28} />
                <span className="num text-[10px] leading-3 text-muted">{x.label}</span>
              </span>
            ))}
          </>
        );
        return (
          <div key={num} className="flex items-center gap-2">
            <span className={cn("num grid size-7 flex-none place-items-center rounded-full border border-dashed text-[13px]",
              active ? "border-gold text-gold" : "border-white/20 text-faint")}>
              {i === PROTECTED ? <Shield className="size-4" /> : i + 1}
            </span>
            {canBan ? (
              <button type="button" className={cls} onClick={() => onBan(code)}
                title={isBanned ? "取消" : team === "mine" ? `对方禁了${name(code)}` : `我方禁${name(code)}`}>
                {body}
              </button>
            ) : (
              <div className={cls}>{body}</div>
            )}
          </div>
        );
      })}
    </section>
  );
}
