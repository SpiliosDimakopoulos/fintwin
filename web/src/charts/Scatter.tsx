import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { useSize } from "../hooks";

export type Pt = { id: string; x: number; y: number; label: string; detail: string; group?: number };

/** Two-variable scatter, one series color, selective direct labels for the extremes. */
export function Scatter({ points, xLabel, yLabel, xFmt, yFmt, labelIds = [], onClick }: {
  points: Pt[]; xLabel: string; yLabel: string; xFmt: (x: number) => string; yFmt: (y: number) => string;
  labelIds?: string[]; onClick?: (id: string) => void;
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const H = 340, M = { l: 52, r: 16, t: 14, b: 40 };
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const x = scaleLinear().domain([Math.min(0, ...xs), Math.max(...xs)]).nice().range([M.l, width - M.r]);
  const y = scaleLinear().domain([Math.min(...ys), Math.max(0, ...ys)]).nice().range([H - M.b, M.t]);
  const hp = points.find((p) => p.id === hover);
  // keyboard: arrows walk the dots left to right, Enter/Space opens the focused one
  const order = [...points].sort((a, b) => a.x - b.x || a.y - b.y).map((p) => p.id);
  const dotKey = (e: React.KeyboardEvent<SVGGElement>, id: string) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick?.(id); return; }
    const step = e.key === "ArrowRight" || e.key === "ArrowUp" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = order[(order.indexOf(id) + step + order.length) % order.length];
    (e.currentTarget.parentElement?.querySelector(`[data-dot="${CSS.escape(next)}"]`) as SVGGElement | null)?.focus();
  };

  // Greedy label placement: try four offsets around each labelled dot and keep the first that clears
  // every label already placed, so clustered names (the cruise lines) stay readable.
  const placed: Record<string, { lx: number; ly: number; anchor: "start" | "end" }> = {};
  const boxes: { x0: number; x1: number; y0: number; y1: number }[] = [];
  const labelled = points.filter((p) => labelIds.includes(p.id)).sort((a, b) => y(a.y) - y(b.y));
  for (const p of labelled) boxes.push({ x0: x(p.x) - 6, x1: x(p.x) + 6, y0: y(p.y) - 6, y1: y(p.y) + 6 });
  for (const p of labelled) {
    const px = x(p.x), py = y(p.y), w = p.label.length * 6.6 + 2;
    const tries: [number, number, "start" | "end"][] = [[px + 8, py - 7, "start"], [px + 8, py + 13, "start"], [px - 8, py - 7, "end"], [px - 8, py + 13, "end"], [px + 8, py - 19, "start"], [px - 8, py + 25, "end"]];
    let pick = tries[0];
    for (const t of tries) {
      const x0 = t[2] === "start" ? t[0] : t[0] - w, x1 = x0 + w, y0 = t[1] - 10, y1 = t[1] + 2;
      if (!boxes.some((bx) => x0 < bx.x1 && x1 > bx.x0 && y0 < bx.y1 && y1 > bx.y0) && x1 < width - 2 && x0 > M.l) { pick = t; break; }
    }
    const x0 = pick[2] === "start" ? pick[0] : pick[0] - w;
    boxes.push({ x0, x1: x0 + w, y0: pick[1] - 10, y1: pick[1] + 2 });
    placed[p.id] = { lx: pick[0], ly: pick[1], anchor: pick[2] };
  }
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="group" aria-label={`${yLabel} versus ${xLabel}: ${points.length} companies. Tab to a company; Enter opens it.`}>
          {y.ticks(5).map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.l - 8} y={y(t)} dy="0.32em" textAnchor="end">{yFmt(t)}</text>
            </g>
          ))}
          {x.ticks(5).map((t) => <text key={t} className="tick" x={x(t)} y={H - M.b + 16} textAnchor="middle">{xFmt(t)}</text>)}
          <line className="baseline" x1={M.l} x2={width - M.r} y1={y(0)} y2={y(0)} />
          <text className="tick" x={(M.l + width - M.r) / 2} y={H - 4} textAnchor="middle" style={{ fill: "var(--ink-2)" }}>{xLabel}</text>
          <text className="tick" transform={`translate(12 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle" style={{ fill: "var(--ink-2)" }}>{yLabel}</text>
          {points.map((p) => (
            <g key={p.id} style={{ cursor: onClick ? "pointer" : undefined }} className="dot-focus" data-dot={p.id}
              tabIndex={p.id === order[0] ? 0 : -1} role={onClick ? "button" : "img"}
              aria-label={`${p.label}: ${xLabel} ${xFmt(p.x)}, ${yLabel} ${yFmt(p.y)}`}
              onPointerEnter={() => setHover(p.id)} onPointerLeave={() => setHover(null)} onFocus={() => setHover(p.id)} onBlur={() => setHover(null)}
              onKeyDown={(e) => dotKey(e, p.id)} onClick={() => onClick?.(p.id)}>
              <circle cx={x(p.x)} cy={y(p.y)} r={12} fill="transparent" />
              <circle cx={x(p.x)} cy={y(p.y)} r={hover === p.id ? 6 : 5} fill={labelIds.includes(p.id) || hover === p.id ? "var(--s1)" : "color-mix(in srgb, var(--s1) 55%, var(--page))"} stroke="var(--page)" strokeWidth={1.5} />
              {placed[p.id] ? (
                <text x={placed[p.id].lx} y={placed[p.id].ly} textAnchor={placed[p.id].anchor} fontSize={11} fill="var(--ink-2)" fontFamily="var(--font-mono)">{p.label}</text>
              ) : hover === p.id && (
                <text x={x(p.x) + 8} y={y(p.y) - 7} fontSize={11} fill="var(--ink)" fontFamily="var(--font-mono)">{p.label}</text>
              )}
            </g>
          ))}
        </svg>
      )}
      {hp && (
        <div className="tooltip" style={{ left: Math.min(x(hp.x) + 14, width - 220), top: Math.max(y(hp.y) - 60, 0) }}>
          <div className="tt-title">{hp.label}</div>
          <div className="tt-row"><span>{xLabel}</span><span>{xFmt(hp.x)}</span></div>
          <div className="tt-row"><span>{yLabel}</span><span>{yFmt(hp.y)}</span></div>
          <div className="muted">{hp.detail}</div>
        </div>
      )}
    </div>
  );
}
