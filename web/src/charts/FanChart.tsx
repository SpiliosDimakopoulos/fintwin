import { scaleLinear } from "d3-scale";
import { area, line } from "d3-shape";
import { useState } from "react";
import { useSize } from "../hooks";

export type FanLayer = {
  label: string;
  color: string;      // CSS var, e.g. "var(--s1)"
  bands: number[][];  // [p5, p25, p50, p75, p95][t]
};

type Props = {
  histLabels?: string[];
  history?: (number | null)[];
  futureLabels: string[];
  layers: FanLayer[];
  realized?: (number | null)[];   // aligned with futureLabels
  realizedLabel?: string;
  format: (x: number) => string;
  tick: (x: number) => string;
  height?: number;
  refLine?: { y: number; label: string };
  yMin?: number;
  yMax?: number;
  samplePaths?: number[][];
  legend?: boolean;
  ariaLabel?: string;
};

const M = { top: 12, right: 12, bottom: 24, left: 46 };

export function FanChart(p: Props) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = p.height ?? 240;
  const hist = p.history ?? [];
  const nh = hist.length;
  const nf = p.futureLabels.length;
  const labels = [...(p.histLabels ?? []), ...p.futureLabels];
  const n = labels.length;

  const vals: number[] = [];
  hist.forEach((v) => v != null && vals.push(v));
  p.layers.forEach((l) => { vals.push(...l.bands[0], ...l.bands[4]); });
  p.realized?.forEach((v) => v != null && vals.push(v));
  if (p.refLine) vals.push(p.refLine.y);
  let lo = p.yMin ?? Math.min(...vals), hi = p.yMax ?? Math.max(...vals);
  if (lo === hi) { lo -= 1; hi += 1; }
  if (p.yMin == null && lo > 0 && lo < hi * 0.35) lo = 0;

  const w = Math.max(width, 200);
  const x = scaleLinear().domain([0, Math.max(n - 1, 1)]).range([M.left, w - M.right]);
  const y = scaleLinear().domain([lo, hi]).nice(5).range([H - M.bottom, M.top]);
  const yt = y.ticks(5);
  const fx = (t: number) => x(nh + t);

  const histLine = line<number | null>().defined((d) => d != null).x((_, i) => x(i)).y((d) => y(d as number));
  // connect the fan to the last observed point so the story reads continuously
  const anchor = nh > 0 ? hist[nh - 1] : null;

  const bandArea = (lo: number[], hi: number[]) => {
    const pts = lo.map((_, t) => ({ t, lo: lo[t], hi: hi[t] }));
    if (anchor != null) pts.unshift({ t: -1, lo: anchor, hi: anchor });
    return area<{ t: number; lo: number; hi: number }>().x((d) => fx(d.t)).y0((d) => y(d.lo)).y1((d) => y(d.hi))(pts) ?? "";
  };
  const medLine = (m: number[]) => {
    const pts = m.map((v, t) => ({ t, v }));
    if (anchor != null) pts.unshift({ t: -1, v: anchor });
    return line<{ t: number; v: number }>().x((d) => fx(d.t)).y((d) => y(d.v))(pts) ?? "";
  };
  const xTickEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(w / 70))));

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const i = Math.round(x.invert(e.clientX - r.left + M.left));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  let tip: React.ReactNode = null;
  if (hover != null && width > 0) {
    const rows: [string, string, string?][] = [];
    if (hover < nh) {
      const v = hist[hover];
      rows.push(["Reported", v == null ? "–" : p.format(v)]);
    } else {
      const t = hover - nh;
      for (const l of p.layers) {
        rows.push([`${l.label} median`, p.format(l.bands[2][t]), l.color]);
        rows.push(["  90% range", `${p.format(l.bands[0][t])} – ${p.format(l.bands[4][t])}`]);
      }
      const rv = p.realized?.[t];
      if (rv != null) rows.push([p.realizedLabel ?? "Realized", p.format(rv), "var(--ink)"]);
    }
    const left = x(hover);
    tip = (
      <div className="tooltip" style={{ left: left > w / 2 ? left - 12 : left + 12, top: 8, transform: left > w / 2 ? "translateX(-100%)" : undefined }}>
        <div className="tt-title">{labels[hover]}{hover >= nh ? " · simulated" : ""}</div>
        {rows.map(([k, v, c], i) => (
          <div className="tt-row" key={i}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--ink-2)" }}>
              {c && <span className="sw-line" style={{ background: c }} />}{k}
            </span>
            <span>{v}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={w} height={H} role="img" aria-label={p.ariaLabel ?? "Fan chart of simulated outcomes"}>
          {yt.map((t) => (
            <g key={t}>
              <line className="gridline" x1={M.left} x2={w - M.right} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{p.tick(t)}</text>
            </g>
          ))}
          {lo < 0 && hi > 0 && <line className="baseline" x1={M.left} x2={w - M.right} y1={y(0)} y2={y(0)} />}
          {labels.map((l, i) => ((i % xTickEvery === 0 && Math.abs(i - nh) >= xTickEvery / 2) || i === nh) && (
            <text key={i} className="tick" x={x(i)} y={H - 6} textAnchor="middle">{l}</text>
          ))}
          {nh > 0 && nf > 0 && (
            <g>
              <line x1={x(nh - 1)} x2={x(nh - 1)} y1={M.top} y2={H - M.bottom} stroke="var(--rule-2)" strokeWidth={1} />
              <text className="tick" x={x(nh - 1) + 6} y={M.top + 10}>forecast →</text>
            </g>
          )}
          {p.refLine && (
            <g>
              <line x1={M.left} x2={w - M.right} y1={y(p.refLine.y)} y2={y(p.refLine.y)} stroke="var(--critical)" strokeWidth={1} opacity={0.7} />
              <text className="tick" x={w - M.right} y={y(p.refLine.y) - 5} textAnchor="end" style={{ fill: "var(--critical)" }}>{p.refLine.label}</text>
            </g>
          )}
          {p.layers.map((l) => (
            <g key={l.label}>
              <path d={bandArea(l.bands[0], l.bands[4])} fill={l.color} opacity={0.1} />
              <path d={bandArea(l.bands[1], l.bands[3])} fill={l.color} opacity={0.18} />
            </g>
          ))}
          {p.samplePaths?.map((sp, i) => (
            <path key={i} d={medLine(sp)} fill="none" stroke={p.layers[p.layers.length - 1]?.color} strokeWidth={1} opacity={0.32}
              pathLength={1} className="draw-path" style={{ animationDelay: `${(i % 20) * 22}ms` }} />
          ))}
          {p.layers.map((l) => (
            <path key={l.label} d={medLine(l.bands[2])} fill="none" stroke={l.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {nh > 0 && <path d={histLine(hist) ?? ""} fill="none" stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
          {p.realized && (
            <g>
              <path d={line<number | null>().defined((d) => d != null).x((_, t) => fx(t)).y((d) => y(d as number))(p.realized) ?? ""}
                fill="none" stroke="var(--ink)" strokeWidth={2} />
              {p.realized.map((v, t) => v != null && (
                <circle key={t} cx={fx(t)} cy={y(v)} r={4} fill="var(--ink)" stroke="var(--page)" strokeWidth={2} />
              ))}
            </g>
          )}
          {hover != null && (
            <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={H - M.bottom} stroke="var(--ink-2)" strokeWidth={1} opacity={0.5} />
          )}
          <rect x={M.left} y={0} width={Math.max(w - M.left - M.right, 0)} height={H} fill="transparent"
            onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
      )}
      {tip}
      {p.legend !== false && <div className="legend" style={{ marginTop: 8 }}>
        {nh > 0 && <span><span className="sw-line" style={{ background: "var(--ink)" }} />Reported</span>}
        {p.layers.map((l) => (
          <span key={l.label}><span className="sw" style={{ background: l.color, opacity: 0.35 }} />{l.label}: median, 50% &amp; 90% bands</span>
        ))}
        {p.realized && <span><span className="dot" style={{ background: "var(--ink)" }} />{p.realizedLabel ?? "Realized"}</span>}
      </div>}
    </div>
  );
}

/** One legend for a row of fan charts that share the same encodings. */
export function FanLegend({ layers, reported = true, realized }: { layers: { label: string; color: string }[]; reported?: boolean; realized?: string }) {
  return (
    <div className="legend">
      {reported && <span><span className="sw-line" style={{ background: "var(--ink)" }} />Reported</span>}
      {layers.map((l) => (
        <span key={l.label}><span className="sw-line" style={{ background: l.color }} /><span className="sw" style={{ background: l.color, opacity: 0.22, marginLeft: -4 }} />{l.label} median with 50% and 90% bands</span>
      ))}
      {realized && <span><span className="dot" style={{ background: "var(--ink)" }} />{realized}</span>}
    </div>
  );
}
