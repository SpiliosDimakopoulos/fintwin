import { scaleLinear } from "d3-scale";
import { area, line } from "d3-shape";
import { useEffect, useMemo, useState } from "react";
import { FanChart, FanLegend } from "../charts/FanChart";
import { loadTimeline, type Meta, type Timeline } from "../data";
import type { Knobs, Params } from "../engine/types";
import { futureQuarters, money, moneyTick, pct, prettyName, quarterLabel } from "../format";
import { useSimulation, useSize } from "../hooks";
import { Delta, Metric, MetricText, Section, Skeleton, Status } from "../ui";

const SCEN = [["base", "Baseline"], ["recession", "Recession"], ["pandemic", "Demand freeze"], ["credit_crunch", "Credit crunch"]] as const;
const yearOf = (v: { asof: string; last_quarter: string }) => (v.asof === "latest" ? "Now" : v.asof.slice(0, 4));

export function TimeMachineView({ ticker, name, meta }: { ticker: string; name: string; meta: Meta }) {
  const [tl, setTl] = useState<Timeline | null | undefined>(undefined);
  const [i, setI] = useState(0);
  const [scen, setScen] = useState<string>("base");
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    setTl(undefined);
    loadTimeline(ticker).then((t) => {
      setTl(t);
      if (t) {
        const k = t.vintages.findIndex((v) => v.asof.startsWith("2020"));
        setI(k >= 0 ? k : 0);
      }
    });
  }, [ticker]);
  useEffect(() => {
    if (!playing || !tl) return;
    const id = setInterval(() => setI((k) => {
      if (k + 1 >= tl.vintages.length) { setPlaying(false); return k; }
      return k + 1;
    }), 2200);
    return () => clearInterval(id);
  }, [playing, tl]);

  const v = tl?.vintages[i];
  const params = useMemo(() => (v ? ({ ...v.params, _sources: {} } as unknown as Params) : null), [v]);
  const knobs: Knobs = useMemo(() => ({ ...meta.presets[scen].knobs }), [scen, meta]);
  const sim = useSimulation(params, knobs, meta.levers, 3000);
  const baseSim = useSimulation(params, useMemo(() => ({}), []), meta.levers, 3000);

  if (tl === undefined) return <Skeleton h={560} />;
  if (tl === null || !v || !params) {
    return (
      <Section>
        <div className="eyebrow">{ticker} · time machine</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>Rewind the twin</h1>
        <p className="lede">No point-in-time history for this company yet. It is rebuilt every week by the data pipeline.</p>
      </Section>
    );
  }

  const T = params.horizon;
  const dates = tl.series.dates;
  const cut = dates.findIndex((d) => d > v.last_quarter);
  const histEnd = cut < 0 ? dates.length : cut;
  const histIdx = Array.from({ length: Math.min(16, histEnd) }, (_, k) => histEnd - Math.min(16, histEnd) + k);
  const fut = futureQuarters(v.last_quarter, T);
  const realized = (key: "revenue" | "cash") => Array.from({ length: T }, (_, k) => (cut >= 0 && cut + k < dates.length ? tl.series[key][cut + k] : null));
  const s = sim.summary, b = baseSim.summary;
  const isBase = scen === "base";
  const layers = (key: "revenue" | "cash") => !s || !b ? [] :
    isBase ? [{ label: "Twin's view then", color: "var(--s1)", bands: s.bands[key] }]
      : [{ label: "Baseline then", color: "var(--muted)", bands: b.bands[key] }, { label: meta.presets[scen].label, color: "var(--s2)", bands: s.bands[key] }];
  const legend = isBase ? [{ label: "Twin's view then", color: "var(--s1)" }] : [{ label: "Baseline then", color: "var(--muted)" }, { label: meta.presets[scen].label, color: "var(--s2)" }];
  const realRev = realized("revenue"), realCash = realized("cash");
  const yrAhead = realRev[3], twinYrAhead = b?.bands.revenue[2][3];
  const known = realRev.filter((x) => x != null).length;

  return (
    <div className="fade-in">
      <Section>
        <div className="eyebrow">{ticker} · time machine</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>Rewind {prettyName(name)}</h1>
        <p className="lede">Pick a date. The twin is rebuilt from only the filings that existed then, simulated live in your
          browser, and laid over what actually happened next. Ratings and spreads use today's rating table (Damodaran, Jan 2026),
          not the table of that date, so this is a replay of the filings, not a strict point-in-time test.</p>
      </Section>

      <div className="timeline-bar" role="group" aria-label="Point in time">
        <button className="play" onClick={() => { if (i >= tl.vintages.length - 1) setI(0); setPlaying(!playing); }} aria-label={playing ? "Pause" : "Play through the years"}>
          {playing ? "❚❚" : "▶"}
        </button>
        <div className="years">
          {tl.vintages.map((x, k) => (
            <button key={x.asof} aria-pressed={k === i} onClick={() => { setPlaying(false); setI(k); }}
              title={`Filings available on ${x.asof === "latest" ? "today" : x.asof}`}
              aria-label={`${yearOf(x)}: health ${x.health.toFixed(0)}, ${x.health >= 70 ? "low" : x.health >= 50 ? "moderate" : x.health >= 30 ? "elevated" : "high"} model stress`}>
              <span className="yr">{yearOf(x)}</span>
              <span className="mini" style={{ background: `var(--${x.health >= 70 ? "good" : x.health >= 50 ? "warning" : x.health >= 30 ? "serious" : "critical"})`, height: `${Math.max(3, x.health * 0.28)}px` }} />
            </button>
          ))}
        </div>
      </div>

      <div className="metrics" style={{ ["--n" as string]: 4, marginTop: 22 }}>
        <Metric label={<>Health then <Status health={v.health} /></>} value={v.health} format={(x) => x.toFixed(0)} unit="/100"
          foot={`as of ${v.asof === "latest" ? "today" : v.asof} · last filing ${v.last_quarter}`} />
        <Metric label="Runs out of cash (baseline)" value={v.p_breach * 100} format={(x) => x.toFixed(v.p_breach < 0.1 ? 1 : 0)} unit="%" foot="probability over the next 3 years" />
        <MetricText label="Revenue a year later" value={yrAhead != null ? money(yrAhead) : "not yet known"}
          foot={yrAhead != null && twinYrAhead ? <Delta value={(yrAhead / twinYrAhead - 1) * 100} fmt={(x) => `${x.toFixed(0)}%`} suffix="vs the twin's median" /> : "the future has not happened yet"} />
        <MetricText label="Quarters of hindsight" value={`${known}`} foot={`of ${T} simulated`} />
      </div>

      <Section eyebrow="Then versus what happened" title={`What the twin expected in ${yearOf(v) === "Now" ? "today's filings" : yearOf(v)}`}
        right={<div className="chips">{SCEN.map(([k, l]) => <button key={k} className="chip" aria-pressed={scen === k} onClick={() => setScen(k)}>{l}</button>)}</div>}>
        <FanLegend layers={legend} realized={known ? "What actually happened" : undefined} />
        {!s || !b ? <Skeleton h={260} /> : (
          <div className="cols-2" style={{ marginTop: 12 }}>
            <div>
              <div className="chart-title">Revenue</div>
              <div className="chart-sub">per quarter</div>
              <FanChart histLabels={histIdx.map((k) => quarterLabel(dates[k]))} history={histIdx.map((k) => tl.series.revenue[k])}
                futureLabels={fut} legend={false} layers={layers("revenue")} realized={known ? realRev : undefined}
                realizedLabel="What actually happened" format={(x) => money(x)} tick={moneyTick} height={260} />
            </div>
            <div>
              <div className="chart-title">Cash and short-term investments</div>
              <div className="chart-sub">end of quarter</div>
              <FanChart histLabels={histIdx.map((k) => quarterLabel(dates[k]))} history={histIdx.map((k) => tl.series.cash[k])}
                futureLabels={fut} legend={false} layers={layers("cash")} realized={known ? realCash : undefined}
                realizedLabel="What actually happened" format={(x) => money(x)} tick={moneyTick} height={260} />
            </div>
          </div>
        )}
        {!isBase && s && <p className="muted" style={{ marginTop: 10 }}>Under this scenario the {yearOf(v)} twin gave a {pct(s.pBreach)} chance of running out of cash.</p>}
      </Section>

      <Section eyebrow="Verdict over time" title="How the twin's view of the company evolved"
        note="Baseline health at each yearly vintage, with the unluckiest decile shaded. Click a point to travel there.">
        <VerdictChart tl={tl} selected={i} onPick={(k) => { setPlaying(false); setI(k); }} />
      </Section>
    </div>
  );
}

function VerdictChart({ tl, selected, onPick }: { tl: Timeline; selected: number; onPick: (k: number) => void }) {
  const [ref, width] = useSize<HTMLDivElement>();
  const H = 200, M = { l: 30, r: 14, t: 14, b: 24 };
  const n = tl.vintages.length;
  const x = scaleLinear().domain([0, Math.max(n - 1, 1)]).range([M.l, Math.max(width - M.r, M.l + 100)]);
  const y = scaleLinear().domain([0, 100]).range([H - M.b, M.t]);
  const vs = tl.vintages;
  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="group" aria-label={`Health score at each yearly vintage: ${vs.map((v) => `${v.asof === "latest" ? "now" : v.asof.slice(0, 4)} ${v.health.toFixed(0)}`).join(", ")}`}>
          {[30, 50, 70].map((t) => (
            <g key={t}><line className="gridline" x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} strokeDasharray="2 3" /><text className="tick" x={M.l - 6} y={y(t)} dy="0.32em" textAnchor="end">{t}</text></g>
          ))}
          <path d={area<number>().x((_, k) => x(k)).y0((_, k) => y(vs[k].health_p10)).y1((_, k) => y(vs[k].health))(vs.map((_, k) => k)) ?? ""} fill="var(--s1)" opacity={0.12} />
          <path d={line<number>().x((_, k) => x(k)).y((_, k) => y(vs[k].health))(vs.map((_, k) => k)) ?? ""} fill="none" stroke="var(--s1)" strokeWidth={2} />
          {vs.map((v, k) => (
            <g key={v.asof} style={{ cursor: "pointer" }} tabIndex={0} role="button" className="dot-focus" aria-label={`Go to ${v.asof === "latest" ? "now" : v.asof}: health ${v.health.toFixed(0)}`}
              aria-pressed={k === selected}
              onClick={() => onPick(k)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(k); } }}>
              <circle cx={x(k)} cy={y(v.health)} r={14} fill="transparent" />
              <circle cx={x(k)} cy={y(v.health)} r={k === selected ? 6 : 4} fill={k === selected ? "var(--s2)" : "var(--s1)"} stroke="var(--page)" strokeWidth={2} />
              <text className="tick" x={x(k)} y={H - 6} textAnchor="middle">{v.asof === "latest" ? "now" : `'${v.asof.slice(2, 4)}`}</text>
              {k === selected && <text x={x(k)} y={y(v.health) - 12} textAnchor="middle" fontSize={11} fontFamily="var(--font-mono)" fill="var(--ink)">{v.health.toFixed(0)}</text>}
            </g>
          ))}
        </svg>
      )}
    </div>
  );
}
