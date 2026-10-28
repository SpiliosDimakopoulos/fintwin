import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { useSize } from "../hooks";

export type SobolRow = { knob: string; label: string; range: number[]; S1: number; ST: number; S1_ci: number[]; ST_ci: number[] };

/** Total-order index (light bar) with first-order index inside it (solid) and a 90% bootstrap whisker on ST. */
export function SobolChart({ rows }: { rows: SobolRow[] }) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const rowH = 34, labelW = Math.min(150, Math.max(width * 0.34, 100)), H = rows.length * rowH + 22;
  const x = scaleLinear().domain([0, 1]).range([labelW, Math.max(width - 44, labelW + 80)]);
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={`Share of health-score variance explained by each shock, first-order and total. ${rows.map((r) => `${r.label}: ${Math.round(r.S1 * 100)}% and ${Math.round(r.ST * 100)}%`).join("; ")}`}>
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line className="gridline" x1={x(t)} x2={x(t)} y1={0} y2={H - 18} />
              <text className="tick" x={x(t)} y={H - 4} textAnchor="middle">{Math.round(t * 100)}%</text>
            </g>
          ))}
          {rows.map((r, i) => {
            const y0 = i * rowH + 8, bh = 14;
            const wt = Math.max(x(Math.min(r.ST, 1)) - x(0), 1), w1 = Math.max(x(Math.min(r.S1, 1)) - x(0), 0);
            return (
              <g key={r.knob} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                <rect x={0} y={y0 - 8} width={width} height={rowH} fill={hover === i ? "var(--wash)" : "transparent"} />
                <text x={0} y={y0 + bh / 2} dy="0.32em" fontSize={12} fill="var(--ink-2)">{r.label}</text>
                <rect x={x(0)} y={y0} width={wt} height={bh} rx={Math.min(4, wt / 2)} fill="var(--s1)" opacity={0.3} />
                {w1 > 0 && <rect x={x(0)} y={y0} width={w1} height={bh} rx={Math.min(4, w1 / 2)} fill="var(--s1)" />}
                <line x1={x(Math.min(r.ST_ci[0], 1))} x2={x(Math.min(r.ST_ci[1], 1))} y1={y0 + bh / 2} y2={y0 + bh / 2} stroke="var(--ink-2)" strokeWidth={1.5} />
                <text x={x(Math.min(Math.max(r.ST, r.ST_ci[1]), 1)) + 8} y={y0 + bh / 2} dy="0.32em" fontSize={12} className="num" fill="var(--ink)">{r.ST >= 0.995 ? "≈100" : Math.round(r.ST * 100)}%</text>
                {hover === i && (
                  <text x={labelW} y={y0 + bh + 11} fontSize={11} fill="var(--muted)">
                    alone {Math.round(r.S1 * 100)}% · with interactions {Math.round(Math.min(r.ST, 1) * 100)}% (90% CI {Math.round(r.ST_ci[0] * 100)}–{Math.round(r.ST_ci[1] * 100)}%)
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      <div className="legend">
        <span><span className="sw" style={{ background: "var(--s1)" }} />First-order (factor alone)</span>
        <span><span className="sw" style={{ background: "var(--s1)", opacity: 0.3 }} />Total (incl. interactions)</span>
        <span><span className="sw-line" style={{ background: "var(--ink-2)" }} />90% bootstrap CI</span>
      </div>
    </div>
  );
}
