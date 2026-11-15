import { ExtLink, PAPER_URL, Section } from "../ui";

const STEPS: [string, string, string][] = [
  ["Point-in-time filings", "SEC EDGAR XBRL", "Every number a US-GAAP filer reporting in USD has tagged in its 10-K and 10-Q filings, with ordered fallbacks for tags that change over time. Year-to-date cash flows are de-cumulated into quarters (Q4 = full year minus nine months). Impairments are added back to operating income, as a credit analyst would. Each fact keeps the date it was filed, so a backtest only sees the filings an analyst could have seen. Rating spreads, however, come from a single recent table (Damodaran, Jan 2026)."],
  ["A stock-and-flow twin", "system dynamics", "Nine stocks: cash, receivables, inventory, payables, customer deposits, PP&E, debt, revolver and equity. Flows connect them through first-order delays, and four feedback loops tie coverage, credit ratings, market access and management responses together. The balance sheet balances on every path, every quarter, and property-based tests enforce it."],
  ["Calibrated uncertainty", "Monte Carlo", "Demand, margin, interest-rate and financing shocks are fitted to each company's own history: robust volatilities, Student-t tails, demand–margin correlation, a Vasicek short rate and a Markov recession regime with NBER base rates. 5,000 paths run in a Web Worker in a fraction of a second."],
];

export function MethodView() {
  return (
    <div className="fade-in">
      <Section>
        <div className="eyebrow">Method</div>
        <h1 className="display h-l" style={{ margin: "8px 0 10px" }}>How the twin is built</h1>
        <p className="lede">Three layers, each testable on its own. The live dashboard runs the product specification; the
          {" "}<ExtLink href={PAPER_URL}>technical paper</ExtLink> reports the pre-specified and the revised specifications, with the full derivation, calibration estimators and evaluation.</p>
      </Section>

      {STEPS.map(([title, tag, body], i) => (
        <Section key={title}>
          <div className="cols-main" style={{ gridTemplateColumns: "minmax(0, 0.8fr) minmax(0, 1.6fr)" }}>
            <div>
              <div className="eyebrow">{String(i + 1).padStart(2, "0")} · {tag}</div>
              <h2 className="display h-m" style={{ marginTop: 8 }}>{title}</h2>
            </div>
            <p className="prose">{body}</p>
          </div>
        </Section>
      ))}

      <Section eyebrow="Core equations" title="One quarter, one path">
        <div className="eq">{`g_t      = μ + φ(g_{t-1} − μ) + σ_g (1 + 0.5 s_t) ε_t + δ s_t     demand growth, Student-t shocks, recession regime s_t
Rev_t    = B_{t-1} · e^{g_t} · Season_q · (1 + shock_t)
Costs_t  = F (1+π)^t · cut_t + (v + m_t) · Rev_t                   operating leverage, mean-reverting margin shock m_t
r_t      = r_{t-1} + κ(θ − r_{t-1}) + σ_r η_t                      Vasicek short rate
spread_t = Rating(EBIT_ttm / Interest_ttm)                          coverage → rating → spread        (loop R1)
AR_t     = AR_{t-1}  + (DSO/91 · Rev_t   − AR_{t-1})  / τ_AR        first-order delays
Inv_t    = Inv_{t-1} + (DIO/91 · Costs_t − Inv_{t-1}) / τ_Inv
Cash_t   = Cash_{t-1} + CFO_t − Capex_t − Payouts_t − Maturities_t + Refinancing_t + NewDebt_t + Revolver_t
Access_t = 1 · 0.6 · 0.3  as coverage ≥ 1.5× · ≥ 0.8× · below,  0 when markets are shut      (loop R2)
Breach   = Cash_t < 0 after the revolver, available debt markets and (optional) equity`}</div>
      </Section>

      <Section eyebrow="Scoring" title="The health score">
        <div className="cols-2">
          <p className="prose">A 0–100 composite with four parts: 30% liquidity runway (cash plus undrawn facility against
            fixed costs, interest and maturities that cannot be refinanced), 30% synthetic rating, 20% net debt to EBITDA, and
            20% Altman Z″. A path that has run out of cash is capped at 25. The headline is the median across 5,000 paths of each path's average.</p>
          <p className="prose">Reverse stress tests find the smallest shock that gives even odds of running out of cash, by
            bisection with common random numbers. Sobol indices split the variance of the health score across six simultaneous
            shocks into first-order effects and interactions.</p>
        </div>
      </Section>

      <Section eyebrow="Engineering" title="Two engines, one answer">
        <p className="prose">A NumPy reference engine handles calibration, backtests and exports. A line-for-line TypeScript port runs the same
          model in your browser. Golden runs exported from Python, with identical pre-drawn shocks, must match to one part in a million
          on the output series that the parity test compares. The committed golden runs are re-checked when the data pipeline rebuilds them, not on every code change.</p>
      </Section>
    </div>
  );
}
