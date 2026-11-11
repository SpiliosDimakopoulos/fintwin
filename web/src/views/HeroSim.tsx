import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { useEffect, useRef, useState } from "react";
import { loadCompany, type Company, type Meta } from "../data";
import type { Summary } from "../engine/summary";
import { futureQuarters, healthStatus } from "../format";
import { runSimulation, useSize } from "../hooks";
import { IconArrow, useTween } from "../ui";

const SCENARIOS = [["base", "Business as usual"], ["recession", "Recession"], ["pandemic", "Demand freeze"], ["credit_crunch", "Credit crunch"]] as const;
const N_PATHS = 2000;

/** Landing-page centrepiece: a real Monte Carlo of Carnival's twin, redrawn live per scenario. */
export function HeroSim({ meta, onOpen }: { meta: Meta; onOpen: (preset: string) => void }) {
  const [c, setC] = useState<Company | null>(null);
  const [key, setKey] = useState<string>("base");
  const [auto, setAuto] = useState(true);
  const [failed, setFailed] = useState(false);
  const [reducedMotion] = useState(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [res, setRes] = useState<{ s: Summary; ms: number; run: number } | null>(null);
  const runId = useRef(0);
  const [ref, width] = useSize<HTMLDivElement>();

  // start once the browser is idle, so the first paint and the headline are never delayed by the simulation
  useEffect(() => {
    let live = true;
    const start = () => loadCompany("CCL").then((x) => { if (live) setC(x); }).catch((e) => { console.error(e); if (live) setFailed(true); });
    // Safari has no requestIdleCallback
    if ("requestIdleCallback" in window) {
      const h = requestIdleCallback(start, { timeout: 1200 });
      return () => { live = false; cancelIdleCallback(h); };
    }
    const h = setTimeout(start, 300);
    return () => { live = false; clearTimeout(h); };
  }, []);
  useEffect(() => {
    if (!c) return;
    const id = ++runId.current;
    runSimulation(c.params, meta.presets[key].knobs, meta.levers, N_PATHS, 11).then((r) => {
      if (id === runId.current) setRes({ s: r.summary, ms: r.ms, run: id });
    });
  }, [c, key, meta]);
  // ambient cycling until the visitor takes control
  useEffect(() => {
    if (!auto || reducedMotion) return;
    const t = setInterval(() => setKey((k) => SCENARIOS[(SCENARIOS.findIndex(([x]) => x === k) + 1) % SCENARIOS.length][0]), 4200);
    return () => clearInterval(t);
  }, [auto, reducedMotion]);

  const health = useTween(res?.s.healthScore ?? NaN, 500);
  const breach = useTween((res?.s.pBreach ?? NaN) * 100, 500);
  const H = 250, M = { l: 30, r: 10, t: 10, b: 22 };
  const T = c?.params.horizon ?? 12;
  const x = scaleLinear().domain([0, T]).range([M.l, Math.max(width - M.r, M.l + 50)]);
  const y = scaleLinear().domain([0, 100]).range([H - M.b, M.t]);
  const start = c?.presets.base.health_score ?? 50;
  const path = (vals: number[]) => line<number>().x((_, i) => x(i)).y((v) => y(v))([start, ...vals]) ?? "";
  const fut = c ? futureQuarters(c.params.last_quarter, T) : [];
  const scenLabel = SCENARIOS.find(([k]) => k === key)?.[1] ?? "";
  const readout = res ? `${scenLabel}: median health ${res.s.healthScore.toFixed(0)} of 100, ${(res.s.pBreach * 100).toFixed(0)}% of paths run out of cash` : "";

  return (
    <div className="terminal" role="group" aria-label="Live Monte Carlo simulation of Carnival">
      <div className="term-head">
        <span><span className="live-dot" /> LIVE · CCL Carnival</span>
        <span>{N_PATHS.toLocaleString()} paths · {failed ? "unavailable" : res ? `${res.ms.toFixed(0)} ms` : "…"}</span>
      </div>
      <div className="term-chips" role="group" aria-label="Scenario">
        {SCENARIOS.map(([k, label]) => (
          <button key={k} aria-pressed={key === k} onClick={() => { setAuto(false); setKey(k); }}>{label}</button>
        ))}
        {!reducedMotion && (
          <button className="term-pause" aria-pressed={!auto} onClick={() => setAuto(!auto)}>{auto ? "Pause" : "Cycle scenarios"}</button>
        )}
      </div>
      {/* announce only scenarios the visitor picked, not the ambient cycle */}
      <p className="sr-only" aria-live="polite">{auto ? "" : readout}</p>
      <div className="term-readout">
        <div><div className="t-label">Median health</div><div className="t-value">{Number.isFinite(health) ? health.toFixed(0) : "–"}<small>/100</small></div></div>
        <div><div className="t-label">Runs out of cash</div><div className="t-value">{Number.isFinite(breach) ? breach.toFixed(0) : "–"}<small>%</small></div></div>
        <div><div className="t-label">Horizon</div><div className="t-value">{T}<small> qtrs</small></div></div>
      </div>
      <div ref={ref} style={{ position: "relative" }}>
        {failed && <p style={{ color: "var(--t-muted)", padding: "40px 0" }}>The simulation could not load. Reload the page to try again.</p>}
        {width > 0 && !failed && (
          <svg width={width} height={H} role="img" aria-label={readout ? `Simulated health score paths. ${readout}.` : "Simulated health score paths"}>
            {[30, 50, 70].map((t) => (
              <g key={t}>
                <line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} stroke="var(--t-rule)" strokeDasharray="2 4" />
                <text x={M.l - 6} y={y(t)} dy="0.32em" textAnchor="end" className="t-tick">{t}</text>
              </g>
            ))}
            <text x={M.l} y={H - 6} className="t-tick">now</text>
            <text x={width - M.r} y={H - 6} textAnchor="end" className="t-tick">{fut[T - 1] ?? ""}</text>
            {res && (
              <g key={res.run}>
                {res.s.samplePaths.health.map((p, i) => {
                  const end = p[p.length - 1];
                  return <path key={i} d={path(p)} pathLength={1} className="t-path" fill="none" strokeWidth={1.2}
                    stroke={`var(--${healthStatus(end).key})`} style={{ animationDelay: `${(i % 20) * 18}ms` }} />;
                })}
                <path d={path(res.s.bands.health[2])} pathLength={1} className="t-path t-median" fill="none" strokeWidth={2.5} stroke="var(--t-ink)" />
              </g>
            )}
          </svg>
        )}
      </div>
      <div className="term-foot">
        <span>Each line is one simulated future of the health score, coloured by where it ends.</span>
        <button className="term-link" onClick={() => onOpen(key)}>Open in stress lab <IconArrow /></button>
      </div>
    </div>
  );
}
