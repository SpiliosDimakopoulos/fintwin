import { useEffect, useState } from "react";
import { FanChart, FanLegend } from "../charts/FanChart";
import { StripPlot } from "../charts/StripPlot";
import { Waterfall } from "../charts/Waterfall";
import { loadMemo, type Company, type Index, type Memo, type Meta } from "../data";
import { RATINGS } from "../engine/ratings";
import { fixed, futureQuarters, money, moneyTick, pct, prettyName, quarterLabel } from "../format";
import { HealthScale, IconArrow, IconExternal, Meter, Metric, MetricText, Section, Status } from "../ui";

const PARAMS: [string, string, (p: Company["params"]) => string][] = [
  ["mu", "Trend revenue growth", (p) => `${pct(Math.exp(p.mu * 4) - 1, 1)} a year`],
  ["sigma_g", "Demand volatility", (p) => `${pct(p.sigma_g, 1)} a quarter`],
  ["t_df", "Tail thickness", (p) => `Student-t, ${fixed(p.t_df, 1)} df`],
  ["F,v", "Cost structure", (p) => `${money(p.F)} fixed per quarter, ${pct(p.v)} variable`],
  ["beta_gdp", "Cyclicality", (p) => `${fixed(p.beta_gdp, 1)}× nominal GDP`],
  ["ddays", "Customer deposits", (p) => `${fixed(p.ddays, 0)} days of revenue`],
  ["coupon", "Cost of debt", (p) => pct(p.coupon, 2)],
  ["maturities", "Maturing next 4 quarters", (p) => money(p.maturities_q.slice(0, 4).reduce((a, b) => a + b, 0))],
  ["refi_ratio", "Rollover policy", (p) => `${pct(p.refi_ratio)} of maturities refinanced`],
  ["revolver_cap", "Credit facility", (p) => money(p.revolver_cap)],
  ["cash_floor", "Minimum operating cash", (p) => money(p.cash_floor)],
];

export function TwinView({ c, meta, index, onStress, onMachine, onOpen, onRewind }: { c: Company; meta: Meta; index: Index; onStress: (preset: string) => void; onMachine: () => void; onOpen: (t: string) => void; onRewind: () => void }) {
  const [memo, setMemo] = useState<Memo | null>(null);
  useEffect(() => { setMemo(null); loadMemo(c.ticker).then(setMemo); }, [c.ticker]);
  const base = c.presets.base;
  const h = c.history;
  const T = c.params.horizon;
  const fut = futureQuarters(c.params.last_quarter, T);
  const tailLabels = h.dates.map(quarterLabel).slice(-16);
  const tail = (k: keyof typeof h.series) => h.series[k].slice(-16);
  const lastRating = [...h.series.rating].reverse().find((r) => r != null);
  const rev = c.reverse_stress.sales_depth;
  const prov = (field: string) => (h.provenance[field] ?? []).at(-1);
  const asOf = new Date(c.params.last_quarter + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

  return (
    <div className="fade-in">
      {/* ---------- masthead ---------- */}
      <Section>
        <div className="cols-main" style={{ alignItems: "end" }}>
          <div>
            <div className="eyebrow">{c.ticker} · {c.sector || "Company"} · filings to {asOf}</div>
            <h1 className="display h-l" style={{ margin: "10px 0 14px" }}>{prettyName(c.name)}</h1>
            {memo && <p className="lede">{memo.headline}</p>}
            <div style={{ display: "flex", gap: 10, marginTop: 20, flexWrap: "wrap" }}>
              <button className="btn" style={{ background: "var(--ink)", color: "var(--page)", borderColor: "var(--ink)", display: "inline-flex", gap: 8, alignItems: "center" }}
                onClick={() => onStress("pandemic")}>Stress-test {c.ticker} <IconArrow /></button>
              <button className="btn" onClick={onRewind}>Rewind in time</button>
              <button className="btn" onClick={onMachine}>See the mechanics</button>
            </div>
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6 }}>
              <span className="eyebrow">Health score</span>
              <Status health={base.health_score} />
            </div>
            <div className="display num" style={{ fontSize: 64, lineHeight: 1 }}>{base.health_score.toFixed(0)}<span className="muted" style={{ fontSize: 18, marginLeft: 4 }}>/100</span></div>
            <div style={{ marginTop: 14 }}><HealthScale value={base.health_score} p10={base.health_p10} /></div>
            <p className="muted" style={{ marginTop: 6 }}>Median of 5,000 simulated {T}-quarter futures. The shaded band reaches down to the unluckiest 10% of paths ({base.health_p10.toFixed(0)}).</p>
          </div>
        </div>
      </Section>

      <div className="metrics" style={{ ["--n" as string]: 4 }}>
        <Metric label="Runs out of cash" value={base.p_breach * 100} format={(v) => v.toFixed(base.p_breach < 0.1 ? 1 : 0)} unit="%"
          foot="probability within 3 years" info="Share of simulated paths where cash goes negative after drawing the revolver and using whatever debt markets will lend." />
        <MetricText label="Synthetic rating" value={lastRating != null ? RATINGS[lastRating] : "–"}
          foot={`${pct(base.p_downgrade_below_ig)} chance of junk in 3 years`} info="Mapped from trailing interest coverage with Damodaran's table for large non-financial firms (Jan 2026)." />
        <MetricText label="Breaking point" value={rev.p50 == null ? "none" : `−${pct(rev.p50)}`}
          foot={rev.p50 == null ? "funds itself through a 95% drop" : "revenue drop for 50% breach odds"}
          info="Reverse stress test: the smallest revenue drop, held for three quarters, that gives even odds of running out of cash. Solved by bisection." />
        <Metric label="Coverage under 1.5×" value={base.p_icr_below_1_5 * 100} format={(v) => v.toFixed(0)} unit="%"
          foot="probability within 3 years" info="Below 1.5× interest coverage the synthetic rating is single-B or worse and the twin narrows access to new debt." />
      </div>

      {/* ---------- peers ---------- */}
      {index.companies[c.ticker] && (
        <Section eyebrow="Context" title={`Among ${Object.keys(index.companies).length} companies`}
          note={`Each dot is one company's twin; ${c.sector || "sector"} peers in blue. Hover any dot to compare, click to open it.`}>
          <StripPlot compact height={40} focus={c.ticker} peers={c.sector}
            rows={[{ key: "base", label: "Baseline" }, { key: "recession", label: "Recession" }, { key: "pandemic", label: "Demand freeze" }]}
            items={Object.entries(index.companies).map(([t, e]) => ({ id: t, name: e.name, group: e.sector,
              values: { base: e.matrix.base.health, recession: e.matrix.recession.health, pandemic: e.matrix.pandemic.health } }))}
            onPick={onOpen} />
        </Section>
      )}

      {/* ---------- analyst notes ---------- */}
      {memo && (
        <Section eyebrow="Analyst notes" title="Reading the twin" note="Written by a rule-based analyst from this company's simulation results. No language model, so every figure comes straight from the model output.">
          <p className="prose" style={{ marginBottom: 28 }}>{memo.summary}</p>
          <div className="cols-2">
            <div>
              <h3 className="eyebrow" style={{ marginBottom: 10 }}>Risks</h3>
              <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none", display: "grid", gap: 14 }}>
                {memo.key_risks.map((r, i) => (
                  <li key={i} style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 4 }}>
                    <span className="mono muted" style={{ fontSize: 12, paddingTop: 2 }}>{String(i + 1).padStart(2, "0")}</span>
                    <div><div style={{ fontWeight: 500 }}>{r.risk}</div><div className="sub" style={{ fontSize: 13.5 }}>{r.evidence}</div></div>
                  </li>
                ))}
              </ol>
            </div>
            <div style={{ display: "grid", gap: 26, alignContent: "start" }}>
              <div>
                <h3 className="eyebrow" style={{ marginBottom: 10 }}>Buffers</h3>
                <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }} className="sub">{memo.resilience.map((r, i) => <li key={i}>{r}</li>)}</ul>
              </div>
              <div>
                <h3 className="eyebrow" style={{ marginBottom: 10 }}>Watch in the next filings</h3>
                <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }} className="sub">{memo.watch_list.map((r, i) => <li key={i}>{r}</li>)}</ul>
              </div>
            </div>
          </div>
        </Section>
      )}

      {/* ---------- scenarios ---------- */}
      <Section eyebrow="Scenarios" title="How it holds up" note="Each row is a full Monte Carlo run on this company's twin. Choose a row to explore it in the stress lab.">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Scenario</th><th style={{ width: "36%" }}>Health</th><th className="r">Runs out of cash</th><th className="r">Junk at horizon</th><th className="r">Coverage &lt;1.5×</th><th style={{ width: 24 }}><span className="sr-only">Open</span></th></tr></thead>
            <tbody>
              {Object.entries(meta.presets).map(([k, v]) => {
                const s = c.presets[k];
                const d = s.health_score - base.health_score;
                return (
                  <tr key={k} className="clickable" onClick={() => onStress(k)}>
                    <td><div style={{ fontWeight: k === "base" ? 500 : 400 }}>{v.label}</div><div className="muted">{v.desc}</div></td>
                    <td style={{ verticalAlign: "middle" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 30px 46px", gap: 10, alignItems: "center" }}>
                        <Meter value={s.health_score} /><span className="num">{s.health_score.toFixed(0)}</span>
                        <span className="num muted" style={{ fontSize: 12 }}>{k === "base" || Math.round(d) === 0 ? "" : `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(0)}`}</span>
                      </div>
                    </td>
                    <td className="r" style={{ verticalAlign: "middle" }}>{pct(s.p_breach, s.p_breach > 0 && s.p_breach < 0.1 ? 1 : 0)}</td>
                    <td className="r" style={{ verticalAlign: "middle" }}>{pct(s.p_downgrade_below_ig)}</td>
                    <td className="r" style={{ verticalAlign: "middle" }}>{pct(s.p_icr_below_1_5)}</td>
                    <td style={{ verticalAlign: "middle", color: "var(--muted)" }}><IconArrow /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      {c.presets.pandemic?.components && base.components && (
        <Section eyebrow="Attribution" title="Why a demand freeze hurts it"
          note="Average health under the baseline and under a demand freeze, with the drop split into its four weighted components and the penalty for running out of cash.">
          <Waterfall base={base.components} scen={c.presets.pandemic.components} baseMean={base.health_mean ?? base.health_score}
            scenMean={c.presets.pandemic.health_mean ?? c.presets.pandemic.health_score} scenLabel="Demand freeze" />
        </Section>
      )}

      {/* ---------- history and baseline forecast ---------- */}
      <Section eyebrow="Baseline" title="Four years reported, three simulated" right={<FanLegend layers={[{ label: "Simulated", color: "var(--s1)" }]} />}>
        <div className="cols-3">
          {([
            ["Revenue", "per quarter", "revenue", base.bands!.revenue],
            ["Cash and short-term investments", "end of quarter", "cash", base.bands!.cash],
            ["Debt", "term debt incl. new issuance", "debt", base.bands!.debt],
          ] as const).map(([title, sub, key, bands]) => (
            <div key={key}>
              <div className="chart-title">{title}</div>
              <div className="chart-sub">{sub}</div>
              <FanChart histLabels={tailLabels} history={tail(key)} futureLabels={fut} legend={false}
                ariaLabel={`${title} ${key === "revenue" ? "per quarter" : key === "cash" ? "at quarter end" : "including new issuance"}, simulated 5-95% band`}
                layers={[{ label: "Simulated", color: "var(--s1)", bands }]} format={(x) => money(x)} tick={moneyTick} height={210} />
            </div>
          ))}
        </div>
      </Section>

      {/* ---------- model card ---------- */}
      <Section eyebrow="Model card" title="What the twin learned from the filings"
        right={<span className="muted" style={{ display: "inline-flex", gap: 14 }}>
          <a href={c.edgar_url} target="_blank" rel="noreferrer">EDGAR filings <IconExternal /></a>
          {prov("revenue") && <a href={prov("revenue")!} target="_blank" rel="noreferrer">latest revenue fact <IconExternal /></a>}
        </span>}>
        <div className="cols-main">
          <div className="table-wrap">
            <table>
              <tbody>
                {PARAMS.map(([key, label, f]) => {
                  const src = c.params._sources[key];
                  const assumed = src?.startsWith("assumption");
                  return (
                    <tr key={label}>
                      <td style={{ width: "36%" }}>{label}</td>
                      <td className="num">{f(c.params)}</td>
                      <td className="muted" style={{ fontSize: 12 }}>{assumed ? <><span style={{ color: "var(--serious)" }}>assumption</span> · {src!.replace(/^assumption:?\s*/, "")}</> : (src ?? "model default")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div>
            <h3 className="eyebrow" style={{ marginBottom: 12 }}>Data quality</h3>
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "1fr auto", rowGap: 10, columnGap: 16 }}>
              <dt className="sub">Quarters extracted</dt><dd className="num" style={{ margin: 0 }}>{c.quality.quarters}</dd>
              <dt className="sub">Coverage</dt><dd className="num" style={{ margin: 0 }}>{c.quality.first.slice(0, 4)}–{c.quality.last.slice(0, 4)}</dd>
              <dt className="sub">Balance-sheet identity gap</dt><dd className="num" style={{ margin: 0 }}>{fixed(c.quality.balance_sheet_identity_max_gap_pct, 2)}%</dd>
              <dt className="sub">Core fields complete</dt><dd className="num" style={{ margin: 0 }}>{fixed(c.quality.core_completeness_last20_pct, 0)}%</dd>
              <dt className="sub">Debt maturity schedule</dt><dd style={{ margin: 0 }}>{c.quality.maturity_ladder_stale ? "assumed" : c.quality.maturity_ladder_date}</dd>
            </dl>
            {c.quality.notes.length > 0 && (
              <ul className="muted" style={{ margin: "16px 0 0", paddingLeft: 16, display: "grid", gap: 4 }}>
                {c.quality.notes.map((n) => <li key={n}>{n.charAt(0).toUpperCase() + n.slice(1)}</li>)}
              </ul>
            )}
          </div>
        </div>
      </Section>
    </div>
  );
}
