// 冻结的画面 + 在上面框选 / 点选 / 画滑动线。坐标一律是 1600×900 基准。
import { type PointerEvent, type ReactNode, useRef } from "react";
import type { Rect4 } from "@/lib/types";
import { cn } from "@/lib/utils";

export const W = 1600;
export const H = 900;
export type Pt = [number, number];

export function normRect(a: Pt, b: Pt): Rect4 {
  const x = Math.max(0, Math.min(a[0], b[0]));
  const y = Math.max(0, Math.min(a[1], b[1]));
  return [Math.round(x), Math.round(y), Math.round(Math.min(W, Math.max(a[0], b[0])) - x), Math.round(Math.min(H, Math.max(a[1], b[1])) - y)];
}

const clampPt = (p: Pt): Pt => [Math.round(Math.max(0, Math.min(W, p[0]))), Math.round(Math.max(0, Math.min(H, p[1])))];

export interface Overlay {
  rect?: Rect4;
  point?: Pt;
  line?: [Pt, Pt];
  color: string;
  label?: string;
  dashed?: boolean;
}

/**
 * mode：box = 拖一个框（onRect），point = 点一下（onPoint），line = 从起点拖到终点（onLine）。
 * 拖动过程中也会回调，松手时 done=true。
 */
export function FrameCanvas({
  src, mode, overlays, onRect, onPoint, onLine, empty, className,
}: {
  src: string | null;
  mode: "box" | "point" | "line";
  overlays: Overlay[];
  onRect?: (r: Rect4, done: boolean) => void;
  onPoint?: (p: Pt) => void;
  onLine?: (a: Pt, b: Pt, done: boolean) => void;
  empty?: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const start = useRef<Pt | null>(null);

  const toBase = (e: PointerEvent): Pt => {
    const r = ref.current!.getBoundingClientRect();
    return clampPt([((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H]);
  };
  const emit = (e: PointerEvent, done: boolean) => {
    const s = start.current;
    if (!s) return;
    const p = toBase(e);
    if (mode === "box") onRect?.(normRect(s, p), done);
    else if (mode === "line") onLine?.(s, p, done);
  };

  return (
    <div className={cn("relative w-full overflow-hidden rounded-lg border border-gold-line/60 bg-black/50", className)} style={{ aspectRatio: "16 / 9" }}>
      {src ? (
        <div
          ref={ref}
          className="absolute inset-0 cursor-crosshair touch-none"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            const p = toBase(e);
            if (mode === "point") {
              onPoint?.(p);
              return;
            }
            start.current = p;
            emit(e, false);
          }}
          onPointerMove={(e) => emit(e, false)}
          onPointerUp={(e) => {
            emit(e, true);
            start.current = null;
          }}
        >
          <img src={src} alt="截取的画面" className="pointer-events-none size-full select-none" draggable={false} />
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="pointer-events-none absolute inset-0 size-full">
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M0 0 L10 5 L0 10 z" fill="#8fdc6c" />
              </marker>
            </defs>
            {overlays.map((o, i) => (
              <g key={i}>
                {o.rect && (
                  <rect x={o.rect[0]} y={o.rect[1]} width={o.rect[2]} height={o.rect[3]} fill="none" stroke={o.color}
                    strokeWidth={4} strokeDasharray={o.dashed ? "12 8" : undefined} />
                )}
                {o.point && (
                  <g stroke={o.color} strokeWidth={4}>
                    <circle cx={o.point[0]} cy={o.point[1]} r={18} fill="none" />
                    <line x1={o.point[0] - 30} y1={o.point[1]} x2={o.point[0] + 30} y2={o.point[1]} />
                    <line x1={o.point[0]} y1={o.point[1] - 30} x2={o.point[0]} y2={o.point[1] + 30} />
                  </g>
                )}
                {o.line && (
                  <line x1={o.line[0][0]} y1={o.line[0][1]} x2={o.line[1][0]} y2={o.line[1][1]} stroke={o.color} strokeWidth={6}
                    markerEnd="url(#arrow)" />
                )}
              </g>
            ))}
          </svg>
          {overlays.filter((o) => o.label && (o.rect || o.point)).map((o, i) => {
            const [x, y] = o.rect ? [o.rect[0], o.rect[1]] : [o.point![0] + 22, o.point![1] - 22];
            return (
              <span key={i} className="pointer-events-none absolute -translate-y-full whitespace-nowrap rounded px-1 text-[11px] text-black"
                style={{ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%`, background: o.color }}>{o.label}</span>
            );
          })}
        </div>
      ) : (
        <div className="grid size-full place-items-center p-6 text-center text-muted">{empty}</div>
      )}
    </div>
  );
}
