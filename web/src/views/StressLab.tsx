import { useEffect, useMemo, useState } from "react";
import { AskTwin } from "../ask/AskTwin";
import { describe, type Scenario } from "../ask/parse";
import { Columns, ProbLine, Tornado } from "../charts/Bars";
import { FanChart, FanLegend } from "../charts/FanChart";
import { ShockPreview } from "../charts/ShockPreview";
import { SobolChart } from "../charts/SobolChart";
import { Waterfall } from "../charts/Waterfall";
import type { Company, Meta } from "../data";
import { INVESTMENT_GRADE_MIN_RANK, RATINGS } from "../engine/ratings";
import { KNOB_DEFAULTS } from "../engine/scenario";
import type { Knobs, Levers } from "../engine/types";
import { fixed, futureQuarters, money, moneyTick, pct } from "../format";
import { useSimulation } from "../hooks";
import { decode, encode } from "../scenarioUrl";
import { Delta, Metric, MetricText, ModelNote, Section, Skeleton, Status } from "../ui";

type KnobKey = keyof Required<Knobs>;
type Slider = { key: KnobKey; label: string; min: number; max: number; step: number; fmt: (v: number) => string };
const GROUPS: { title: string; sliders: Slider[] }[] = [
  { title: "Demand", sliders: [
    { key: "sales_depth", label: "Revenue falls by", min: 0, max: 0.95, step: 0.01, fmt: (v) => (v ? `${Math.round(v * 100)}%` : "—") },
    { key: "sales_duration", label: "Stays at the bottom for", min: 1, max: 8, step: 1, fmt: (v) => `${v} qtr${v > 1 ? "s" : ""}` },
    { key: "sales_recovery", label: "Takes to recover", min: 1, max: 12, step: 1, fmt: (v) => `${v} qtr${v > 1 ? "s" : ""}` },
  ] },
  { title: "Financing", sliders: [
    { key: "rate_bp", label: "Interest rates", min: -300, max: 600, step: 25, fmt: (v) => (v ? `${v > 0 ? "+" : "−"}${Math.abs(v)}bp` : "—") },
    { key: "spread_bp", label: "Credit spreads", min: 0, max: 1000, step: 25, fmt: (v) => (v ? `+${v}bp` : "—") },
    { key: "refi_freeze", label: "Debt markets closed for", min: 0, max: 8, step: 1, fmt: (v) => (v ? `${v} qtr${v > 1 ? "s" : ""}` : "—") },
  ] },
  { title: "Operations", sliders: [
    { key: "cost_pp", label: "Variable costs", min: 0, max: 15, step: 0.5, fmt: (v) => (v ? `+${v}pp` : "—") },
    { key: "dio_days", label: "Inventory build-up", min: 0, max: 120, step: 5, fmt: (v) => (v ? `+${v} days` : "—") },
  ] },
];
const LEVERS: { key: keyof Levers; label: string; desc: string }[] = [
  { key: "cut_payouts", label: "Suspend dividends and buybacks", desc: "when cash or coverage is stressed" },
  { key: "cut_capex", label: "Cut capex to maintenance", desc: "when stressed" },
  { key: "cut_costs", label: "Restructure fixed costs", desc: "after two quarters of squeezed margins" },
  { key: "issue_debt", label: "Raise new debt", desc: "as far as markets will lend" },
  { key: "draw_revolver", label: "Draw the credit facility", desc: "committed bank lines" },
  { key: "issue_equity", label: "Emergency equity raise", desc: "dilutive last resort" },
  { key: "recessions", label: "Random recessions", desc: "NBER base rates since 1947" },
];
const clampIcr = (bands: number[][]) => bands.map((r) => r.map((v) => Math.max(Math.min(v, 30), -10)));

/** A readable description of a custom scenario, e.g. "Revenue down 40% for 4 quarters; debt markets closed for 2 quarters." */
function customDescription(k: Required<Knobs>, levers: Levers, meta: Meta): string {
  const kd: Partial<Required<Knobs>> = Object.fromEntries((Object.keys(KNOB_DEFAULTS) as KnobKey[]).filter((n) => k[n] !== KNOB_DEFAULTS[n]).map((n) => [n, k[n]]));
  if (kd.sales_depth) { kd.sales_duration = k.sales_duration; kd.sales_recovery = k.sales_recovery; }
  if (kd.spread_bp) kd.spread_duration = k.spread_duration;
  if (kd.cost_pp) kd.cost_duration = k.cost_duration;
  const lv = Object.fromEntries((Object.keys(levers) as (keyof Levers)[]).filter((n) => levers[n] !== meta.levers[n]).map((n) => [n, levers[n]]));
  const lines = describe({ knobs: kd, levers: lv });
  return lines.length ? `${lines.join("; ").replace(/^./, (ch) => ch.toUpperCase())}.` : "Your own combination of shocks.";
}

export function StressLab({ c, meta, preset: initialPreset, query = "", setPreset: syncUrl, names = {}, onCompany }: {
  c: Company; meta: Meta; preset: string; query?: string; setPreset: (p: string, q: string) => void;
  names?: Record<string, string>; onCompany?: (ticker: string, query: string) => void;
}) {
  // Local state drives the UI; the URL mirrors it so any scenario can be shared as a link.
  const startPreset = meta.presets[initialPreset] || initialPreset === "custom" ? initialPreset : "pandemic";
  const [preset, setPreset] = useState(startPreset);
  const [knobs, setKnobs] = useState<Knobs>(() => decode(query, meta, startPreset).knobs);
  const [levers, setLevers] = useState<Levers>(() => decode(query, meta, startPreset).levers);
  const [copied, setCopied] = useState(false);
  useEffect(() => { syncUrl(preset, encode(knobs, levers, meta, preset)); }, [preset, knobs, levers]); // eslint-disable-line react-hooks/exhaustive-deps
  const copyLink = () => {
    navigator.clipboard?.writeText(location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); });
  };
  const [nPaths, setNPaths] = useState(5000);
  const [showPaths, setShowPaths] = useState(false);
  const stress = useSimulation(c.params, knobs, levers, nPaths);
  const base = useSimulation(c.params, useMemo(() => ({}), []), levers, nPaths);
  const T = c.params.horizon;
  const fut = futureQuarters(c.params.last_quarter, T);
  const k = { ...KNOB_DEFAULTS, ...knobs };
  const isBase = Object.entries(k).every(([kk, v]) => v === KNOB_DEFAULTS[kk as KnobKey]);
  const s = stress.summary, b = base.summary;
  const title = meta.presets[preset]?.label ?? "Custom scenario";
  const desc = meta.presets[preset]?.desc ?? customDescription(k, levers, meta);

  // "Ask the twin": a described crisis replaces the scenario (or opens the named company with it)
  const applyAsk = (sc: Scenario) => {
    const lv = { ...meta.levers, ...sc.levers };
    // never navigate away silently: a company name found in the text may be a false positive
    if (sc.ticker && sc.ticker !== c.ticker && onCompany && window.confirm(`Open ${names[sc.ticker] ?? sc.ticker} (${sc.ticker}) with this scenario? Cancel keeps ${c.ticker} and applies the scenario here.`)) {
      onCompany(sc.ticker, encode(sc.knobs as Knobs, lv, meta, "custom")); return;
    }
    setPreset("custom");
    setKnobs({ ...sc.knobs });
    setLevers(lv);
  };

  const choose = (key: string) => { setPreset(key); setKnobs({ ...meta.presets[key].knobs }); };
  const layers = (key: "cash" | "health" | "revenue" | "icr") => {
    if (!s || !b) return [];
    const tf = key === "icr" ? clampIcr : (x: number[][]) => x;
    return isBase ? [{ label: "Baseline", color: "var(--s1)", bands: tf(s.bands[key]) }]
      : [{ label: "Baseline", color: "var(--muted)", bands: tf(b.bands[key]) }, { label: title, color: "var(--s2)", bands: tf(s.bands[key]) }];
  };
  const legendLayers = isBase ? [{ label: "Baseline", color: "var(--s1)" }] : [{ label: "Baseline", color: "var(--muted)" }, { label: title, color: "var(--s2)" }];

  return (
    <div className="lab fade-in">
      <aside className="panel lab-controls" aria-label="Scenario controls" id="scenario-controls">
        <h4>Scenario</h4>
        <div className="chips" style={{ margin: "6px 0 2px" }}>
          {Object.entries(meta.presets).map(([key, v]) => (
            <button key={key} className="chip" aria-pressed={preset === key} onClick={() => choose(key)} title={v.desc}>{v.label}</button>
          ))}
        </div>
        <div style={{ margin: "14px 0 2px" }}><ShockPreview knobs={k} T={T} /></div>
        {GROUPS.map((g) => (
          <div key={g.title}>
            <h4>{g.title}</h4>
            {g.sliders.map((sl) => {
              const v = k[sl.key], off = v === KNOB_DEFAULTS[sl.key] && (sl.key === "sales_depth" || sl.key === "rate_bp" || sl.key === "spread_bp" || sl.key === "refi_freeze" || sl.key === "cost_pp" || sl.key === "dio_days");
              return (
                <label className="slider" key={sl.key}>
                  <span className="slider-top"><span>{sl.label}</span><b className={off ? "off" : undefined}>{sl.fmt(v)}</b></span>
                  <input type="range" min={sl.min} max={sl.max} step={sl.step} value={v} aria-valuetext={sl.fmt(v) === "—" ? "off" : sl.fmt(v)}
                    onChange={(e) => { setPreset("custom"); setKnobs({ ...k, [sl.key]: +e.target.value }); }} />
                </label>
              );
            })}
          </div>
        ))}
        <h4>What management may do</h4>
        {LEVERS.map((l) => (
          <label className="toggle" key={l.key}>
            <span>{l.label}<div className="t-desc">{l.desc}</div></span>
            <span className="switch"><input type="checkbox" checked={levers[l.key]} onChange={(e) => setLevers({ ...levers, [l.key]: e.target.checked })} /><span /></span>
          </label>
        ))}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 14, gap: 8, paddingTop: 12, borderTop: "1px solid var(--rule)" }}>
          <label className="muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>Paths
            <select value={nPaths} onChange={(e) => setNPaths(+e.target.value)} style={{ padding: "3px 6px" }}>
              {[1000, 5000, 10000, 20000].map((n) => <option key={n} value={n}>{n.toLocaleString()}</option>)}
            </select>
          </label>
          <span className="muted mono" style={{ fontSize: 11, display: "inline-flex", gap: 6, alignItems: "center" }}>
            {stress.busy ? <><span className="busy-dot" /> simulating</> : `${stress.ms.toFixed(0)} ms in browser`}
          </span>
        </div>
        <button className="btn" style={{ width: "100%", marginTop: 10 }} onClick={copyLink}>{copied ? "Link copied" : "Copy link to this scenario"}</button>
      </aside>

      <div>
        <AskTwin names={names} onApply={applyAsk} />
        <div style={{ marginBottom: 22 }}>
          <div className="eyebrow">{c.ticker} · stress lab</div>
          <h1 className="display h-l" style={{ margin: "8px 0 6px" }}>{title}</h1>
          <p className="sub">{desc}</p>
          <a className="only-narrow btn" href="#scenario-controls" style={{ marginTop: 12, textDecoration: "none" }}
            onClick={(e) => { e.preventDefault(); document.getElementById("scenario-controls")?.scrollIntoView({ behavior: "smooth" }); }}>Adjust scenario ↓</a>
        </div>

        {!s || !b ? <Skeleton h={560} /> : (
          <>
            <div className="metrics" style={{ ["--n" as string]: 4 }}>
              <Metric label={<>Health score <Status health={s.healthScore} /></>} value={s.healthScore} format={(v) => v.toFixed(0)} unit="/100"
                foot={isBase ? `unluckiest 10%: ${s.healthP10.toFixed(0)}` : <Delta value={s.healthScore - b.healthScore} fmt={(x) => x.toFixed(0)} />} />
              <Metric label="Runs out of cash" value={s.pBreach * 100} format={(v) => v.toFixed(s.pBreach < 0.1 ? 1 : 0)} unit="%"
                foot={isBase ? "within 3 years" : <Delta value={(s.pBreach - b.pBreach) * 100} fmt={(x) => `${x.toFixed(1)}pp`} goodIfPositive={false} />}
                info="Cash goes negative after drawing the credit facility and raising whatever new debt the market will provide." />
              <Metric label="Sub-investment-grade rating at horizon" value={s.pSubIG * 100} format={(v) => v.toFixed(0)} unit="%"
                foot={s.medianQuartersToBreach != null ? `breach typically in quarter ${s.medianQuartersToBreach + 1}` : "chance of a sub-investment-grade synthetic rating after 3 years"} />
              <MetricText label="New debt raised" value={money(s.debtIssuedMedian)}
                foot={levers.issue_equity ? `plus ${money(s.equityNeededMedian)} of equity` : "median, to defend the cash buffer"} />
            </div>

            <ModelNote />

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, margin: "22px 0 6px", flexWrap: "wrap" }}>
              <FanLegend layers={legendLayers} reported={false} />
              <button className="btn" onClick={() => setShowPaths(!showPaths)}>{showPaths ? "Hide" : "Show"} individual paths</button>
            </div>
            <div className="cols-2" style={{ rowGap: 30 }}>
              <div>
                <div className="chart-title">Cash</div>
                <div className="chart-sub">after every management response · below zero means the company has run out</div>
                <FanChart futureLabels={fut} history={[c.params.cash0]} histLabels={["Now"]} legend={false} layers={layers("cash")}
                  samplePaths={showPaths ? s.samplePaths.cash : undefined} refLine={{ y: 0, label: "out of cash" }} format={(x) => money(x)} tick={moneyTick} />
              </div>
              <div>
                <div className="chart-title">Health score</div>
                <div className="chart-sub">liquidity, coverage, leverage and Altman Z″ combined, 0–100</div>
                <FanChart futureLabels={fut} legend={false} layers={layers("health")} samplePaths={showPaths ? s.samplePaths.health : undefined}
                  yMin={0} yMax={100} format={(x) => x.toFixed(0)} tick={(x) => `${x}`} />
              </div>
              <div>
                <div className="chart-title">Revenue</div>
                <div className="chart-sub">per quarter</div>
                <FanChart futureLabels={fut} legend={false} layers={layers("revenue")} format={(x) => money(x)} tick={moneyTick} />
              </div>
              <div>
                <div className="chart-title">Interest coverage</div>
                <div className="chart-sub">trailing EBIT ÷ interest; sets the rating and the price of new debt</div>
                <FanChart futureLabels={fut} legend={false} layers={layers("icr")} refLine={{ y: 1.5, label: "1.5× junk line" }}
                  format={(x) => `${fixed(x, 1)}×`} tick={(x) => `${x}×`} />
              </div>
            </div>

            {!isBase && (
              <Section eyebrow="Attribution" title="Why the score moves"
                note="The change in average health, split into its four weighted components plus the penalty for paths that run out of cash.">
                <Waterfall base={b.components} scen={s.components} baseMean={b.healthMean} scenMean={s.healthMean} scenLabel={title} />
              </Section>
            )}

            <Section eyebrow="Timing and ratings" title="When it breaks, and where the rating lands">
              <div className="cols-2">
                <div>
                  <div className="chart-title">Probability of having run out of cash</div>
                  <div className="chart-sub">{levers.recessions ? "dashed: share of paths in a recession" : "cumulative, by quarter"}</div>
                  <ProbLine labels={fut} values={s.pBreachByQ} secondary={levers.recessions ? s.pRecessionByQ : undefined} />
                </div>
                <div>
                  <div className="chart-title">Synthetic rating after three years</div>
                  <div className="chart-sub">share of paths in each rating bucket</div>
                  <Columns ariaLabel="Share of simulated paths in each synthetic rating after three years" labels={RATINGS} values={s.ratingDist} format={(x) => pct(x)}
                    highlight={(i) => (i >= INVESTMENT_GRADE_MIN_RANK ? "var(--s1)" : "var(--s2)")} />
                  <div className="legend" style={{ marginTop: 6 }}>
                    <span><span className="sw" style={{ background: "var(--s1)" }} />Investment grade</span>
                    <span><span className="sw" style={{ background: "var(--s2)" }} />Speculative grade</span>
                  </div>
                </div>
              </div>
            </Section>
          </>
        )}

        <Section eyebrow="Sensitivity" title="What it would take to break it">
          <div className="metrics" style={{ ["--n" as string]: 3, marginBottom: 30 }}>
            {Object.entries(c.reverse_stress).map(([key, r]) => {
              const f = (v: number) => (r.unit === "pct" ? `−${pct(v)}` : r.unit === "bp" ? `+${v.toFixed(0)}bp` : `+${v.toFixed(1)}pp`);
              return (
                <MetricText key={key} label={r.label} value={r.p50 == null ? "never" : f(r.p50)}
                  foot={r.p50 == null ? "even odds of breach not reached" : r.p10 === 0 ? "for even odds · risk already ≥10% today" : r.p10 == null ? "for even odds" : `for even odds · 10% odds at ${f(r.p10)}`}
                  info="Reverse stress test: the smallest shock giving a 50% probability of running out of cash, found by bisection with common random numbers." />
              );
            })}
          </div>
          <div className="cols-2">
            <div>
              <div className="chart-title">One shock at a time</div>
              <div className="chart-sub">change in health score versus baseline</div>
              <Tornado rows={c.tornado.map((t) => ({ label: t.label, value: t.d_health, detail: `runs-out-of-cash odds ${t.d_p_breach >= 0 ? "+" : "−"}${Math.abs(t.d_p_breach * 100).toFixed(1)}pp` }))}
                format={(x) => (x > 0 ? "+" : "") + x.toFixed(1)} />
            </div>
            {c.sobol ? (
              <div>
                <div className="chart-title">All shocks at once</div>
                <div className="chart-sub">Sobol indices: share of health-score variance explained · {pct(c.sobol.interaction_share)} comes from interactions</div>
                {c.sobol.insensitive
                  ? <p className="muted">The health score barely moves across the whole scenario space (s.d. {c.sobol.output_sd.toFixed(1)} points).</p>
                  : <SobolChart rows={c.sobol.rows} />}
              </div>
            ) : <div className="muted" style={{ alignSelf: "center" }}>Global sensitivity is computed for the 30 core companies.</div>}
          </div>
        </Section>
      </div>
    </div>
  );
}
