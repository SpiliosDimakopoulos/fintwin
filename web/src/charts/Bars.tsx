import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { useSize } from "../hooks";

/** Horizontal diverging bars from a zero baseline (tornado). Values labeled at the tip. */
export function Tornado({ rows, format }: { rows: { label: string; value: number; detail?: string }[]; format: (x: number) => string }) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const rowH = 34, labelW = Math.min(150, Math.max(width * 0.36, 100)), H = rows.length * rowH + 8;
  const ext = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  const x = scaleLinear().domain([-ext, Math.max(ext * 0.15, 0)]).range([labelW + 44, Math.max(width - 12, labelW + 120)]);
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={`Change in health score versus baseline for each single stress. ${rows.map((r) => `${r.label}: ${format(r.value)}`).join("; ")}`}>
          <line className="baseline" x1={x(0)} x2={x(0)} y1={0} y2={H} />
          {rows.map((r, i) => {
            const y0 = i * rowH + 8, bh = 14, x0 = x(Math.min(r.value, 0)), x1 = x(Math.max(r.value, 0));
            const neg = r.value < 0, wBar = Math.max(x1 - x0, 1), rad = Math.min(4, wBar);
            const d = neg
              ? `M${x1},${y0}H${x0 + rad}Q${x0},${y0} ${x0},${y0 + rad}V${y0 + bh - rad}Q${x0},${y0 + bh} ${x0 + rad},${y0 + bh}H${x1}Z`
              : `M${x0},${y0}H${x1 - rad}Q${x1},${y0} ${x1},${y0 + rad}V${y0 + bh - rad}Q${x1},${y0 + bh} ${x1 - rad},${y0 + bh}H${x0}Z`;
            return (
              <g key={r.label} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                <rect x={0} y={y0 - 8} width={width} height={rowH} fill={hover === i ? "var(--wash)" : "transparent"} />
                <text x={0} y={y0 + bh / 2} dy="0.32em" fontSize={12} fill="var(--ink-2)">{r.label}</text>
                <path d={d} fill={neg ? "var(--s2)" : "var(--s1)"} />
                <text x={neg ? x0 - 6 : x1 + 6} y={y0 + bh / 2} dy="0.32em" textAnchor={neg ? "end" : "start"} fontSize={12} fill="var(--ink)" className="num">
                  {format(r.value)}
                </text>
                {hover === i && r.detail && (
                  <text x={x(0) + 6} y={y0 + bh + 11} fontSize={11} fill="var(--muted)">{r.detail}</text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

/** Vertical column chart for a categorical distribution (e.g. rating at horizon). */
export function Columns({ labels, values, highlight, format, ariaLabel = "Column chart" }: { labels: string[]; values: number[]; highlight?: (i: number) => string; format: (x: number) => string; ariaLabel?: string }) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 170, M = { t: 18, b: 22 };
  const max = Math.max(...values, 0.01);
  const slot = width / labels.length, bw = Math.min(24, slot - 4);
  const y = scaleLinear().domain([0, max]).range([H - M.b, M.t]);
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={`${ariaLabel}. ${labels.map((l, i) => `${l}: ${format(values[i])}`).join("; ")}`}>
          <line className="baseline" x1={0} x2={width} y1={H - M.b} y2={H - M.b} />
          {values.map((v, i) => {
            const cx = slot * i + slot / 2, top = y(v), h = H - M.b - top, r = Math.min(4, h);
            const d = h <= 0 ? "" : `M${cx - bw / 2},${H - M.b}V${top + r}Q${cx - bw / 2},${top} ${cx - bw / 2 + r},${top}H${cx + bw / 2 - r}Q${cx + bw / 2},${top} ${cx + bw / 2},${top + r}V${H - M.b}Z`;
            return (
              <g key={i} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                <rect x={slot * i} y={0} width={slot} height={H} fill={hover === i ? "var(--wash)" : "transparent"} />
                <path d={d} fill={highlight ? highlight(i) : "var(--s1)"} />
                <text className="tick" x={cx} y={H - 6} textAnchor="middle">{labels[i]}</text>
                {(hover === i || v === max) && v > 0 && (
                  <text x={cx} y={top - 5} textAnchor="middle" fontSize={11} fill="var(--ink)" className="num">{format(v)}</text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

/** Thin area/step line for a probability over time (e.g. cumulative breach probability). */
export function ProbLine({ labels, values, secondary, color = "var(--critical)" }: { labels: string[]; values: number[]; secondary?: number[]; color?: string }) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 150, M = { l: 40, r: 10, t: 10, b: 22 };
  const x = scaleLinear().domain([0, Math.max(values.length - 1, 1)]).range([M.l, width - M.r]);
  const top = Math.max(0.1, Math.min(1, Math.ceil(Math.max(...values, ...(secondary ?? [])) * 10 + 0.5) / 10));
  const y = scaleLinear().domain([0, top]).range([H - M.b, M.t]);
  const pts = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={`Cumulative probability of running out of cash by quarter. ${labels.map((l, i) => `${l}: ${(values[i] * 100).toFixed(0)}%`).join("; ")}`}>
          {y.ticks(4).map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.l - 6} y={y(t)} dy="0.32em" textAnchor="end">{Math.round(t * 100)}%</text>
            </g>
          ))}
          <polygon points={`${x(0)},${y(0)} ${pts} ${x(values.length - 1)},${y(0)}`} fill={color} opacity={0.1} />
          <polyline points={pts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
          {secondary && <polyline points={secondary.map((v, i) => `${x(i)},${y(v)}`).join(" ")} fill="none" stroke="var(--ink-2)" strokeWidth={1.5} strokeDasharray="4 3" />}
          {labels.map((l, i) => i % Math.ceil(labels.length / 6) === 0 && <text key={i} className="tick" x={x(i)} y={H - 6} textAnchor="middle">{l}</text>)}
          {hover != null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={H - M.b} stroke="var(--ink-2)" opacity={0.5} />
              <circle cx={x(hover)} cy={y(values[hover])} r={4} fill={color} stroke="var(--page)" strokeWidth={2} />
              <text x={Math.min(x(hover) + 8, width - 150)} y={M.t + 12} fontSize={12} fill="var(--ink)" className="num">
                {labels[hover]}: breach {(values[hover] * 100).toFixed(1)}%{secondary ? ` · recession ${(secondary[hover] * 100).toFixed(0)}%` : ""}
              </text>
            </g>
          )}
          <rect x={M.l} y={0} width={Math.max(width - M.l - M.r, 0)} height={H} fill="transparent"
            onPointerMove={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              setHover(Math.max(0, Math.min(values.length - 1, Math.round(x.invert(e.clientX - r.left + M.l)))));
            }}
            onPointerLeave={() => setHover(null)} />
        </svg>
      )}
    </div>
  );
}
