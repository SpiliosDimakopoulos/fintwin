import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { HEALTH_WEIGHTS as W } from "../engine/types";
import { useSize } from "../hooks";

type Comp = { liq: number; cov: number; lev: number; solv: number };
const PARTS: [keyof Comp, string, string][] = [
  ["liq", "Liquidity runway", "Cash plus undrawn credit facility against fixed costs, interest and maturities that cannot be refinanced."],
  ["cov", "Interest coverage", "Synthetic rating from trailing EBIT ÷ interest, scored against the sector's leverage norm."],
  ["lev", "Leverage", "Net debt ÷ EBITDA, scored against the sector's norm."],
  ["solv", "Solvency (Altman Z″)", "Book-value Altman Z″: working capital, retained earnings, EBIT and equity relative to assets."],
];

/**
 * Explains a change in the (mean) health score as weighted component moves plus the cap applied to paths that
 * run out of cash. The pieces add up exactly to the difference between the two bars.
 */
export function Waterfall({ base, scen, baseMean, scenMean, baseLabel = "Baseline", scenLabel }: {
  base: Comp; scen: Comp; baseMean: number; scenMean: number; baseLabel?: string; scenLabel: string;
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const weighted = (c: Comp) => W.liq * c.liq + W.cov * c.cov + W.lev * c.lev + W.solv * c.solv;
  const capBase = weighted(base) - baseMean;
  const capScen = weighted(scen) - scenMean;
  const steps = [
    ...PARTS.map(([k, label, desc]) => ({ label, delta: W[k] * (scen[k] - base[k]), desc: `${desc} Weight ${W[k] * 100}%: ${base[k].toFixed(0)} → ${scen[k].toFixed(0)}.` })),
    { label: "Ran out of cash", delta: -(capScen - capBase), desc: "Paths that run out of cash are capped at 25, whatever their other scores." },
  ];
  const bars: { label: string; y0: number; y1: number; kind: "total" | "up" | "down"; desc: string; delta?: number }[] = [];
  let level = baseMean;
  bars.push({ label: baseLabel, y0: 0, y1: baseMean, kind: "total", desc: "Average health across all paths and quarters." });
  for (const s of steps) {
    bars.push({ label: s.label, y0: level, y1: level + s.delta, kind: s.delta >= 0 ? "up" : "down", desc: s.desc, delta: s.delta });
    level += s.delta;
  }
  bars.push({ label: scenLabel, y0: 0, y1: scenMean, kind: "total", desc: "Average health across all paths and quarters." });

  const H = 250, M = { t: 18, b: 46, l: 30, r: 8 };
  const y = scaleLinear().domain([0, Math.max(100, ...bars.map((b) => Math.max(b.y0, b.y1)))]).range([H - M.b, M.t]);
  const slot = (width - M.l - M.r) / bars.length;
  const bw = Math.min(42, slot * 0.62);
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={`Health score waterfall: average health ${baseMean.toFixed(0)} in the baseline and ${scenMean.toFixed(0)} under ${scenLabel}`}>
          {[0, 25, 50, 75, 100].map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.l - 6} y={y(t)} dy="0.32em" textAnchor="end">{t}</text>
            </g>
          ))}
          {bars.map((b, i) => {
            const cx = M.l + slot * i + slot / 2;
            const top = y(Math.max(b.y0, b.y1)), bot = y(Math.min(b.y0, b.y1));
            const fill = b.kind === "total" ? "var(--ink-2)" : b.kind === "up" ? "var(--good)" : "var(--s2)";
            const next = bars[i + 1];
            return (
              <g key={i} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                <rect x={M.l + slot * i} y={M.t} width={slot} height={H - M.t - M.b} fill={hover === i ? "var(--wash)" : "transparent"} />
                <rect x={cx - bw / 2} y={top} width={bw} height={Math.max(bot - top, 1)} rx={2} fill={fill} opacity={b.kind === "total" ? 0.9 : 0.85} />
                {next && next.kind !== "total" && (
                  <line x1={cx + bw / 2} x2={cx + slot - bw / 2} y1={y(b.y1)} y2={y(b.y1)} stroke="var(--rule-2)" strokeDasharray="2 2" />
                )}
                <text x={cx} y={top - 5} textAnchor="middle" fontSize={11} fontFamily="var(--font-mono)" fill="var(--ink)">
                  {b.kind === "total" ? b.y1.toFixed(0) : `${(b.delta ?? 0) >= 0 ? "+" : "−"}${Math.abs(b.delta ?? 0).toFixed(1)}`}
                </text>
                <foreignObject x={M.l + slot * i} y={H - M.b + 6} width={slot} height={M.b - 6}>
                  <div style={{ fontSize: 11, lineHeight: 1.25, textAlign: "center", color: "var(--ink-2)", padding: "0 2px" }}>{b.label}</div>
                </foreignObject>
              </g>
            );
          })}
        </svg>
      )}
      <div className="muted" style={{ minHeight: 34, marginTop: 4 }}>
        {hover != null ? bars[hover].desc : "Hover a bar to see what each component measures. Bars add up exactly from one total to the other."}
      </div>
    </div>
  );
}
