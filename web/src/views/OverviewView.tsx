import { useEffect, useState } from "react";
import { Scatter } from "../charts/Scatter";
import { loadCalibration, type Calibration, type Index } from "../data";
import { fixed, pct, prettyName, shortcutLabel, signed } from "../format";
import { ExtLink, IconArrow, LoadError, Meter, Metric, ModelNote, PAPER_URL, rowClick, Section, SpecStamp, Status } from "../ui";
import { fragilityBuckets } from "./crossSection";
import { HeroSim } from "./HeroSim";

const FEATURED: Record<string, string> = {
  CCL: "Cruise operator that lost almost all revenue in 2020",
  BA: "Aerospace manufacturer carrying heavy debt",
  AAPL: "Cash-rich technology company",
  INTC: "Chipmaker in the middle of a capital-intensive turnaround",
  TSLA: "Growth manufacturer with little debt",
  NFLX: "Subscription business funded by debt",
};

const HOW_IT_WORKS = [
  ["01", "Read the filings", "Fifteen years of 10-K and 10-Q facts from SEC EDGAR for US-GAAP filers reporting in USD, de-cumulated into quarters and frozen at the date they were filed, so a backtest never sees a later restatement."],
  ["02", "Rebuild the machine", "Cash, receivables, inventory, deposits, debt and equity become stocks connected by flows. Feedback loops link coverage, credit ratings, market access and management responses."],
  ["03", "Replay the future", "Demand, margin, rate and financing shocks are calibrated on each company's own history. 5,000 paths, 12 quarters ahead, recomputed live as you move a slider."],
];

const LIMITS = [
  ["Regime breaks", "It cannot see one coming. Carnival's 2020 revenue fell 99%, beyond even the harshest preset."],
  ["Cash forecasts", "On average they lose to a simple random walk. Treasury decisions are discretionary, and seasonal working capital is only partly modelled."],
  ["Industry detail", "Generic XBRL tags miss things like Boeing's programme accounting or Netflix's content spending."],
  ["Sector norms", "Leverage thresholds are only partly sector-adjusted (a per-sector tolerance estimated from peers), so regulated utilities and other unusual capital structures can still read weaker than a credit analyst would rate them."],
];

export function OverviewView({ index, onOpen, onGo, onStress }: { index: Index; onOpen: (t: string) => void; onGo: (v: string) => void; onStress: (preset: string) => void }) {
  // undefined while loading, null when the file could not be fetched
  const [cal, setCal] = useState<Calibration | null | undefined>(undefined);
  useEffect(() => { loadCalibration().then(setCal); }, []);
  const xs = cal?.cross_section;
  const buckets = xs ? fragilityBuckets(xs) : null;

  return (
    <div className="fade-in">
      <Section>
        <div className="hero">
          <div>
            <div className="eyebrow" style={{ marginBottom: 14 }}>A financial digital twin of {Object.keys(index.companies).length} public companies</div>
            <h1 className="display h-xl">What happens to a company's cash when the world breaks?</h1>
            <p className="lede" style={{ marginTop: 18 }}>
              FinTwin reads each company's SEC filings, rebuilds its finances as a system of stocks, flows and feedback
              loops, and replays the next three years thousands of times under the crisis you choose, right in your browser.
            </p>
            <div style={{ display: "flex", gap: 12, marginTop: 26, flexWrap: "wrap" }}>
              <button className="btn btn-primary btn-lg" onClick={() => onStress("pandemic")}>Stress-test Carnival <IconArrow /></button>
              <button className="btn btn-lg" onClick={() => onGo("time")}>Rewind to February 2020</button>
              <button className="btn btn-lg" onClick={() => onGo("backtest")}>See the evidence</button>
            </div>
          </div>
          <HeroSim meta={index.meta} onOpen={onStress} />
        </div>
      </Section>

      {cal === undefined && <div className="skeleton" style={{ height: 120, marginBottom: 8 }} aria-hidden />}
      {cal === null && <LoadError what="the backtest summary" />}
      {cal && xs && <SpecStamp generated={index.meta.generated} />}
      {cal && xs && (
        <div className="metrics" style={{ ["--n" as string]: 4, marginBottom: 8 }}>
          <Metric label="Pre-COVID fragility ranking" value={xs.spearman} format={(v) => `ρ ${v.toFixed(2)}`}
            foot={`${xs.n} companies · mostly persistence, see the paper`}
            info="Spearman rank correlation between each company's twin health score under a demand freeze, computed from filings available on 20 Feb 2020, and its realized cumulative free cash flow in 2020–21." />
          <Metric label="Out-of-sample forecasts" value={cal.n_forecasts} format={(v) => Math.round(v).toLocaleString()}
            foot={`${cal.n_companies} companies, cutoffs ${cal.origins[0].slice(0, 4)}–${cal.origins[cal.origins.length - 1].slice(0, 4)}`}
            info="Every forecast uses only facts filed before its cutoff date (point-in-time vintages), so later restatements never leak in. Rating spreads come from today's table (Damodaran, Jan 2026), not from the cutoff date." />
          <Metric label="Revenue accuracy vs naive" value={cal.vars.revenue.crps_skill_vs_naive * 100} format={(v) => signed(v)} unit="%"
            foot={`cash: ${signed(cal.vars.cash_like.crps_skill_vs_naive * 100)}% · CRPS against a seasonal random walk`}
            info="Continuous ranked probability score, a proper scoring rule for probabilistic forecasts. Positive means better than the benchmark." />
          <Metric label="Calibrated interval coverage" value={cal.vars.revenue.conformal.coverage90 * 100} format={(v) => v.toFixed(0)} unit="%"
            foot={`target 90% · raw bands ${pct(cal.vars.revenue.raw.coverage90)}`}
            info="Online conformal rescaling: each year's interval width is corrected using only earlier years' errors." />
        </div>
      )}
      {cal && xs && (
        <p className="muted" style={{ maxWidth: 820, margin: "10px 0 8px" }}>In plain terms: ρ near 1 would mean the twin ranked the
          companies in the order their cash actually held up; a positive accuracy figure means the forecasts beat simply repeating
          last year's pattern; and a calibrated 90% range should contain the real outcome about 9 times in 10.</p>
      )}

      {xs && buckets && (
        <Section eyebrow="The February 2020 test" title="Frozen before the pandemic: what it saw, and what it could not">
          <div className="cols-main">
            <div>
              <Scatter points={buckets.rows.map((r) => ({ id: r.ticker, x: r.health_stress, y: r.realized_min_cum_fcf_pct_rev as number, label: r.ticker,
                detail: prettyName(r.name) }))}
                xLabel="Twin health under a demand freeze (Feb 2020)" yLabel="Worst cumulative FCF 2020–21, % of revenue"
                xFmt={(x) => x.toFixed(0)} yFmt={(y) => `${y.toFixed(0)}%`}
                labelIds={["CCL", "RCL", "NCLH", "BA", "AAL", "EXPE", "MSFT", "GOOGL", "WMT", "LVS"]} onClick={onOpen} />
            </div>
            <div className="prose" style={{ fontSize: 14.5 }}>
              <p>Every twin was calibrated using only filings available on <b>20 February 2020</b>, then hit with the same
                generic shock: revenue down 70% for three quarters, debt markets shut for two.</p>
              <p>The research paper finds that this ranking is mostly persistence. A company's trailing free-cash-flow margin
                ranks the same outcome better, and measured against each company's own pre-2020 run-rate, no balance-sheet model,
                this one included, saw who the shock would hit. The picture below is an illustration, not evidence of foresight.</p>
              <p>In this dashboard sample, <b>{pct(buckets.fragileSevere)}</b> of the twin's most fragile two-fifths suffered a
                severe cash burn (worse than 10% of a year's revenue), against <b>{pct(buckets.robustSevere)}</b> of the most
                robust two-fifths. The cruise lines and Boeing sit in the bottom-left corner. Walmart is the visible miss, fragile
                to a demand collapse it never suffered.</p>
              <p>What the twin does carry is statistical information about cash flow that is not in a simple margin rule, given the
                revenue that actually happened. The paper finds that this information does not improve out-of-sample forecasts
                by itself; see the Evidence page.</p>
              <p className="muted">Spearman ρ = {fixed(xs.spearman, 2)}, 95% bootstrap interval {fixed(xs.ci95[0], 2)}–{fixed(xs.ci95[1], 2)}.
                {" "}<ExtLink href={PAPER_URL}>Read the paper</ExtLink>.</p>
            </div>
          </div>
        </Section>
      )}

      <ModelNote />

      <Section eyebrow="Explore" title="Six twins to start with" right={<button className="btn-link" onClick={() => onGo("compare")}>All {Object.keys(index.companies).length} companies →</button>}
        note="Health is a 0–100 score from the twin's simulations: higher is safer, under 30 is high stress. A demand freeze is a 2020-style collapse in revenue, with debt markets closed for a time.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Company</th><th style={{ width: "34%" }}><span className="sr-only">Profile</span></th><th style={{ width: 180 }}>Health today</th><th style={{ width: 180 }}>In a demand freeze</th></tr>
            </thead>
            <tbody>
              {Object.keys(FEATURED).filter((t) => index.companies[t]).map((t) => {
                const e = index.companies[t];
                const b = e.matrix.base.health, s = e.matrix.pandemic?.health ?? b;
                return (
                  <tr key={t} className="clickable" {...rowClick(() => onOpen(t))}>
                    <td><a className="row-link" href={`#twin/${t}`}><span className="tk-cell">{t}</span> <span style={{ marginLeft: 8 }}>{prettyName(e.name)}</span></a></td>
                    <td className="muted" style={{ fontSize: 13 }}>{FEATURED[t]}</td>
                    <td><div className="meter-cell"><Meter value={b} /><span className="num">{b.toFixed(0)}</span></div></td>
                    <td><div className="meter-cell"><Meter value={s} /><span className="num">{s.toFixed(0)}</span></div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: "6px 18px", marginTop: 12, flexWrap: "wrap" }}>
          <Status health={80} label="70–100 low stress" /><Status health={60} label="50–69 moderate" /><Status health={40} label="30–49 elevated" /><Status health={10} label="0–29 high stress" />
          <span className="muted" style={{ marginLeft: "auto" }}>Press <span className="kbd">{shortcutLabel}</span> to open any company</span>
        </div>
      </Section>

      <Section eyebrow="How it works" title="From filings to a distribution of futures">
        <div className="cols-3">
          {HOW_IT_WORKS.map(([n, t, d]) => (
            <div key={n} className="rule-left" style={{ borderLeftColor: "var(--rule-2)" }}>
              <div className="eyebrow">{n}</div>
              <h3 className="display h-s" style={{ margin: "6px 0 8px" }}>{t}</h3>
              <p className="sub" style={{ fontSize: 13.5 }}>{d}</p>
            </div>
          ))}
        </div>
        <p style={{ marginTop: 22 }}><button className="btn-link" onClick={() => onGo("method")}>Read the method →</button></p>
      </Section>

      <Section eyebrow="Limits" title="What it does not do well">
        <div className="cols-2" style={{ rowGap: 22 }}>
          {LIMITS.map(([t, d]) => (
            <div key={t}><div style={{ fontWeight: 500, marginBottom: 4 }}>{t}</div><p className="sub" style={{ fontSize: 13.5 }}>{d}</p></div>
          ))}
        </div>
      </Section>
    </div>
  );
}
