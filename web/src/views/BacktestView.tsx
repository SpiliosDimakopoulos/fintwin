import { useEffect, useState } from "react";
import { Columns } from "../charts/Bars";
import { FanChart, FanLegend } from "../charts/FanChart";
import { Scatter } from "../charts/Scatter";
import { loadBacktest, loadCalibration, loadResearch, type Backtest, type Calibration, type ResearchSummary } from "../data";
import { fixed, money, moneyTick, pct, prettyName, quarterLabel, signed, UNIVERSE_TEXT } from "../format";
import { ExtLink, LoadError, Metric, MetricText, ModelNote, PAPER_URL, Section, Skeleton, SpecStamp } from "../ui";
import { fragilityBuckets, SEVERE_BURN_PCT } from "./crossSection";

const VARS: Record<string, string> = { revenue: "Revenue", cash_like: "Cash", total_debt: "Debt" };

export function BacktestView({ onOpen, generated }: { onOpen: (t: string) => void; generated?: string }) {
  const [bt, setBt] = useState<Backtest | null>(null);
  // undefined while loading, null when the file could not be fetched
  const [cal, setCal] = useState<Calibration | null | undefined>(undefined);
  const [res, setRes] = useState<ResearchSummary | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    loadBacktest().then(setBt).catch((e) => { console.error(e); setFailed(true); });
    loadCalibration().then(setCal);
    loadResearch().then(setRes);
  }, []);
  if (failed || cal === null) return <LoadError what="the evidence data" />;
  if (!bt || !cal) return <Skeleton h={600} />;

  const xs = cal.cross_section;
  const { rows, fragileSevere, robustSevere } = fragilityBuckets(xs);
  const severeFoot = `cash burn worse than ${-SEVERE_BURN_PCT}% of revenue`;

  return (
    <div className="fade-in">
      <Section>
        <div className="eyebrow">Evidence</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>Does the twin know anything?</h1>
        <p className="lede">The tests below are out of sample: each twin is calibrated only on facts <i>filed</i> before its test date,
          so later restatements stay invisible. The results are mostly negative for simulation against simple rules. Two caveats:
          the dashboard backtests use today's rating table (Damodaran, Jan 2026) rather than the table of the test date, and the
          model's settings were chosen by the authors, with a sensitivity analysis, not fitted to each test outcome.</p>
        <p className="muted" style={{ maxWidth: 760, fontSize: 13.5, margin: "10px 0 0" }}>Two sets of results appear on this page.
          <b> Findings 1 and 2</b> come from the research sample ({UNIVERSE_TEXT}, including firms that later disappeared), as
          reported in the paper's pre-specified and revised specifications. <b>Findings 3 and 4</b> and the February 2020 illustration
          come from this dashboard's own sample of current S&amp;P 500 companies, run with the live product specification.</p>
        <figure style={{ margin: "24px 0 0" }}>
          <img src={`${import.meta.env.BASE_URL}findings.png`} width={2227} height={838} loading="lazy"
            style={{ width: "100%", height: "auto", borderRadius: 6, border: "1px solid var(--rule)" }}
            alt="Two panels from the research paper. Left: out-of-sample error of eight-quarter operating cash flow given the realized revenue, for simple margin rules, a regression, the twin and blends. The 16-quarter margin is more accurate than the twin alone, and blending a simple regression into the margin does almost as well as blending in the twin. Right: AUC for a bankruptcy petition within two years among US-GAAP filers reporting in USD with at least $50M of revenue; the twin, its own scoring formula without simulation and the Ohlson score are close to level. The exact values are given in Findings 1 and 2 below." />
          <figcaption className="muted" style={{ marginTop: 8, fontSize: 13 }}>The research paper in one picture.{" "}
            <ExtLink href={PAPER_URL}>Read the paper</ExtLink>.</figcaption>
        </figure>
      </Section>

      {res && <ResearchFindings r={res} />}
      {res === null && <LoadError what="the research findings" />}

      <Section eyebrow="Illustration" title="February 2020 in the dashboard's companies: fragility, mostly persistence">
        <SpecStamp generated={generated} />
        <div className="metrics" style={{ ["--n" as string]: 4, marginBottom: 28 }}>
          <Metric label="Rank correlation" value={xs.spearman} format={(v) => `ρ ${v.toFixed(2)}`} foot={`95% CI ${fixed(xs.ci95[0], 2)}–${fixed(xs.ci95[1], 2)}`}
            info="Spearman correlation between the twin's demand-freeze health score (Feb 2020 data) and realized cumulative free cash flow, 2020Q1–2021Q2." />
          <MetricText label="Significance" value={xs.p_value != null ? (xs.p_value < 1e-6 ? "p < 10⁻⁶" : `p = ${xs.p_value.toExponential(1)}`) : "–"} foot={`${xs.n} companies`} />
          <Metric label="Severe burn, fragile two-fifths" value={fragileSevere * 100} format={(v) => v.toFixed(0)} unit="%" foot={severeFoot} />
          <Metric label="Severe burn, robust two-fifths" value={robustSevere * 100} format={(v) => v.toFixed(0)} unit="%" foot="same threshold" />
        </div>
        <Scatter points={rows.map((r) => ({ id: r.ticker, x: r.health_stress, y: r.realized_min_cum_fcf_pct_rev as number, label: r.ticker,
          detail: `${prettyName(r.name)} · debt raised ${fixed(r.realized_debt_raise_pct_rev, 0)}% of revenue` }))}
          xLabel="Twin health under a demand freeze (Feb 2020)" yLabel="Worst cumulative FCF 2020–21, % of revenue"
          xFmt={(x) => x.toFixed(0)} yFmt={(y) => `${y.toFixed(0)}%`}
          labelIds={["CCL", "RCL", "NCLH", "BA", "AAL", "MSFT", "GOOGL", "WMT", "LVS", "EXPE", "WYNN"]} onClick={onOpen} />
        <p className="muted" style={{ marginTop: 10, maxWidth: 760 }}>Every company receives the same generic shock, so this measures structural fragility, not who the
          pandemic actually hit. Walmart is the visible miss: fragile to a demand collapse it never suffered.</p>
        <p className="muted" style={{ marginTop: 6, maxWidth: 760 }}>This is the dashboard's own sample of today's S&amp;P 500
          companies, so it inherits survivorship bias; Findings 1 and 2 above come from the survivorship-free research sample.{" "}
          <ExtLink href={PAPER_URL}>Read the paper</ExtLink>.</p>
      </Section>

      <SpecStamp generated={generated} />
      <CalibrationFinding cal={cal} />

      <CaseExplorer bt={bt} />

      <Section eyebrow="Limits" title="Where it is wrong">
        <ul className="prose" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
          <li>Unconditional forecasts cannot see a regime break coming: Carnival's revenue fell about 99% in 2020, beyond even the harshest preset.</li>
          <li>Cash forecasts lose to a random walk on average. Treasury decisions are discretionary, and seasonal working-capital swings are only partly modelled.</li>
          <li>Generic XBRL tags miss industry detail: Boeing's programme accounting, Netflix's content spending.</li>
          <li>Conformal rescaling fixes average coverage, not coverage within a crisis year.</li>
          <li>The risk probabilities and stress labels are model outputs under stated assumptions; they have not been calibrated against realised events and are not credit opinions.</li>
        </ul>
      </Section>
      <ModelNote />
    </div>
  );
}

const SHORT: Record<string, string> = { N1: "4q margin", N2: "8q", N3: "16q", N4: "Shrunk", N5: "Regr.", N6: "Regr.+Δ",
  T0: "Twin, no loops", T1: "Twin" };

function ResearchFindings({ r }: { r: ResearchSummary }) {
  const c = r.combination;
  const gain = (v: "cfo" | "fcf", k: "N3+N5" | "N3+T1") => (1 - c[v][k] / c[v].N3) * 100;
  return (
    <>
      <Section eyebrow="Finding 1" title="Given the revenue that happened, the twin alone is the least accurate model">
        <SpecStamp>Research sample. Results shown are from the research export; the paper reports the pre-specified and the revised specification side by side.</SpecStamp>
        <p className="sub" style={{ marginBottom: 20, maxWidth: 760 }}>{r.samples.transmission_firm_years.toLocaleString()} firm-years of
          non-financial filers ({UNIVERSE_TEXT}), 2014–2024. Each model gets the revenue each company actually reported and predicts its operating
          cash flow over the next eight quarters.</p>
        <div className="metrics" style={{ ["--n" as string]: 4, marginBottom: 28 }}>
          <Metric label="Old headline statistic" value={r.incremental.twin_vs_4q} format={(v) => `ρ ${v.toFixed(2)}`}
            foot={`a 16-quarter margin alone: ${r.incremental["16q_vs_4q"].toFixed(2)}`}
            info="Correlation of each model's departure from a four-quarter margin with the realized departure. Any smoother estimate of the margin scores well: it measured mean reversion." />
          <Metric label="Information beyond the best rule" value={r.incremental.twin_vs_16q} format={(v) => `ρ ${v.toFixed(2)}`}
            foot={`encompassing t = ${r.incremental.encompassing_t.toFixed(1)} (clustered by firm; see the paper for the two-way version)`} />
          <Metric label="Blend into 16q margin, operating CF" value={gain("cfo", "N3+T1")} format={(v) => v.toFixed(1)} unit="% less error"
            foot={`a simple regression blended in: ${gain("cfo", "N3+N5").toFixed(1)}%`} />
          <Metric label="Blend into 16q margin, free CF" value={gain("fcf", "N3+T1")} format={(v) => v.toFixed(1)} unit="% less error"
            foot={`a simple regression blended in: ${gain("fcf", "N3+N5").toFixed(1)}%`} />
        </div>
        <div className="chart-title">Median error by model (percentage points of trailing revenue)</div>
        <Columns ariaLabel="Median error by model, percentage points of trailing revenue" labels={r.ladder.map((m) => SHORT[m.key] ?? m.label)} values={r.ladder.map((m) => m.median_ae)} format={(x) => x.toFixed(1)}
          highlight={(i) => (r.ladder[i].key.startsWith("T") ? "var(--s1)" : "var(--ink-2)")} />
      </Section>

      <Section eyebrow="Finding 2" title="It ranks bankruptcies well, but no better than its own score without simulation">
        <p className="sub" style={{ marginBottom: 20, maxWidth: 760 }}>{r.samples.bankruptcies} bankruptcy petitions (8-K Item 1.03) within two
          years of a cutoff, among {r.samples.universe.toLocaleString()} firms ({UNIVERSE_TEXT}, excluding financials), including those that later disappeared.</p>
        <div className="metrics" style={{ ["--n" as string]: 4 }}>
          <Metric label="Twin, simulated" value={r.bankruptcy.all.twin} format={(v) => `AUC ${v.toFixed(2)}`} foot={`already-weak firms: ${r.bankruptcy.weak.twin.toFixed(2)}`} />
          <Metric label="Twin's formula, no simulation" value={r.bankruptcy.all.formula} format={(v) => `AUC ${v.toFixed(2)}`} foot={`already-weak firms: ${r.bankruptcy.weak.formula.toFixed(2)}`} />
          <Metric label="Ohlson O-score" value={r.bankruptcy.all.ohlson_o} format={(v) => `AUC ${v.toFixed(2)}`} foot={`already-weak firms: ${r.bankruptcy.weak.ohlson_o.toFixed(2)}`} />
          <Metric label="Altman Z''" value={r.bankruptcy.all.altman_z2} format={(v) => `AUC ${v.toFixed(2)}`} foot={`already-weak firms: ${r.bankruptcy.weak.altman_z2.toFixed(2)}`} />
        </div>
      </Section>
    </>
  );
}

function CalibrationFinding({ cal }: { cal: Calibration }) {
  const [v, setV] = useState<"revenue" | "cash_like">("revenue");
  const c = cal.vars[v];
  const years = Object.keys(c.by_year).sort();
  return (
    <Section eyebrow="Finding 3" title={`${cal.n_forecasts.toLocaleString()} forecasts: skilful on revenue, honest about uncertainty`}
      right={<div className="segmented" role="group" aria-label="Variable">
        <button aria-pressed={v === "revenue"} onClick={() => setV("revenue")}>Revenue</button>
        <button aria-pressed={v === "cash_like"} onClick={() => setV("cash_like")}>Cash</button>
      </div>}>
      <p className="sub" style={{ marginBottom: 20, maxWidth: 760 }}>{cal.n_companies} companies, yearly point-in-time cutoffs from {cal.origins[0].slice(0, 4)} to {cal.origins[cal.origins.length - 1].slice(0, 4)},
        each forecasting the next {cal.horizon} reported quarters with 2,000 paths.</p>
      <div className="metrics" style={{ ["--n" as string]: 4, marginBottom: 30 }}>
        <Metric label="Accuracy vs naive" value={c.crps_skill_vs_naive * 100} format={(x) => signed(x)} unit="%"
          foot={`twin wins ${pct(c.share_cases_beating_naive)} of forecasts`} info="CRPS skill against a seasonal random walk with historical spread. Positive means better." />
        <MetricText label="90% bands, raw → calibrated" value={`${pct(c.raw.coverage90)} → ${pct(c.conformal.coverage90)}`} foot="target 90%"
          info="Online conformal rescaling: each year's band width is corrected using only earlier years' errors." />
        <MetricText label="50% bands, raw → calibrated" value={`${pct(c.raw.coverage50)} → ${pct(c.conformal.coverage50)}`} foot="target 50%" />
        <Metric label="Recession regime" value={-c.regime_ablation.improvement_pct} format={(x) => `${x <= 0 ? "−" : "+"}${Math.abs(x).toFixed(1)}`} unit="% CRPS"
          foot="ablation, same random shocks" info="Adding Markov recessions with NBER base rates changes forecast error very little at a one-year horizon." />
      </div>
      <div className="cols-2">
        <div>
          <div className="chart-title">Where outcomes fell inside the forecast</div>
          <div className="chart-sub">PIT histogram: flat means calibrated; the U-shape says raw bands are too narrow</div>
          <Columns ariaLabel="Share of outcomes by forecast percentile decile; flat is calibrated" labels={c.pit_hist.map((_, i) => `${i * 10}`)} values={c.pit_hist} format={(x) => pct(x)} highlight={() => "var(--ink-2)"} />
        </div>
        <div>
          <div className="chart-title">Raw 90% coverage by cutoff year</div>
          <div className="chart-sub">vermillion: windows that contain the 2020 shock</div>
          <Columns ariaLabel="Raw 90% band coverage by cutoff year" labels={years.map((y) => `'${y.slice(2)}`)} values={years.map((y) => c.by_year[y].cov90)} format={(x) => pct(x)}
            highlight={(i) => (years[i] === "2019" || years[i] === "2020" ? "var(--s2)" : "var(--ink-2)")} />
        </div>
      </div>
    </Section>
  );
}

function CaseExplorer({ bt }: { bt: Backtest }) {
  const [ticker, setTicker] = useState("CCL");
  const [cut, setCut] = useState("pre_covid");
  const [v, setV] = useState("revenue");
  const tickers = [...new Set(Object.values(bt.forecast).map((f) => f.ticker))];
  const fb = bt.forecast[`${ticker}:${cut}`];
  const series = fb?.series[v];
  const sc = fb?.scores[v];
  const structural = fb && "dates" in fb.structural ? fb.structural : null;
  const stressLabel = cut === "pre_covid" ? "Demand freeze" : "Stagflation";
  const n = series?.realized.dates.length ?? 0;
  return (
    <>
      <Section eyebrow="Finding 4a" title="Case by case: forecast against what was reported"
        right={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div className="segmented" role="group" aria-label="Company">
              {tickers.map((t) => <button key={t} aria-pressed={t === ticker} onClick={() => setTicker(t)}>{t}</button>)}
            </div>
            <div className="segmented" role="group" aria-label="Cutoff">
              <button aria-pressed={cut === "pre_covid"} onClick={() => setCut("pre_covid")}>Feb 2020</button>
              <button aria-pressed={cut === "pre_hikes"} onClick={() => setCut("pre_hikes")}>Jan 2022</button>
            </div>
            <div className="segmented" role="group" aria-label="Variable">
              {Object.entries(VARS).map(([key, l]) => <button key={key} aria-pressed={v === key} onClick={() => setV(key)}>{l}</button>)}
            </div>
          </div>
        }>
        {series && sc ? (
          <>
            <FanLegend layers={[{ label: "Baseline", color: "var(--s1)" }, { label: stressLabel, color: "var(--s2)" }]} realized="Actually reported" />
            <div style={{ marginTop: 10 }}>
              <FanChart histLabels={series.history.dates.map(quarterLabel)} history={series.history.values} legend={false}
                futureLabels={series.realized.dates.map(quarterLabel)}
                layers={[{ label: "Baseline", color: "var(--s1)", bands: series.base_bands.map((r) => r.slice(0, n)) },
                  { label: stressLabel, color: "var(--s2)", bands: series.stress_bands.map((r) => r.slice(0, n)) }]}
                realized={series.realized.values} realizedLabel="Actually reported" format={(x) => money(x)} tick={moneyTick} height={300} />
            </div>
            <div className="metrics" style={{ ["--n" as string]: 4, marginTop: 20 }}>
              <Metric label="Inside the 50% band" value={sc.coverage50 * 100} format={(x) => x.toFixed(0)} unit="%" foot={`${sc.n} quarters`} />
              <Metric label="Inside the 90% band" value={sc.coverage90 * 100} format={(x) => x.toFixed(0)} unit="%" foot="baseline forecast" />
              <Metric label={`Inside the ${stressLabel.toLowerCase()} band`} value={sc.stress_coverage90 * 100} format={(x) => x.toFixed(0)} unit="%" foot="90% band" />
              <Metric label="Accuracy vs naive" value={sc.crps_skill * 100} format={(x) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(0)}`} unit="%" foot="CRPS skill" />
            </div>
          </>
        ) : <p className="muted">No realized data for this case.</p>}
      </Section>

      {structural && (
        <Section eyebrow="Finding 4b" title="Given the real revenue, does the machine burn cash like the company did?"
          note="The twin is fed the realized revenue path, so only its internal mechanics (costs, working capital, capex, financing) produce the cash flow.">
          <FanLegend layers={[{ label: "Twin", color: "var(--s1)" }]} reported={false} realized="Actual" />
          <div style={{ marginTop: 10 }}>
            <FanChart futureLabels={structural.dates.map(quarterLabel)} legend={false}
              layers={[{ label: "Twin", color: "var(--s1)", bands: structural.model_cum_fcf_bands }]}
              realized={structural.actual_cum_fcf} realizedLabel="Actual" format={(x) => money(x)} tick={moneyTick} height={240} />
          </div>
          <p className="muted" style={{ marginTop: 10 }}>{ticker}: cumulative free cash flow error {fixed(structural.final_error_pct, 0)}% at the end of the window,
            quarter-to-quarter correlation {fixed(structural.corr, 2)}.</p>
        </Section>
      )}
    </>
  );
}
