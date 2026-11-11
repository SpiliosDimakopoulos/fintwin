# Methodology

## 1. Data pipeline (`engine/fintwin/data`)

**Source.** The SEC EDGAR XBRL `companyfacts` endpoint provides every number a company has tagged in its 10-K/10-Q filings. Requests carry a declared User-Agent, stay under 10 requests/s and are cached on disk. Interest rates come from FRED's public CSV endpoint (DGS3MO, DGS10, BAA10Y).

**Four data problems and how each is handled.**

1. **Tag drift.** Companies switch tags over time (e.g. `SalesRevenueNet` became `RevenueFromContractWithCustomerExcludingAssessedTax` after ASC 606). Each field has an ordered list of fallback tags, merged period by period. Debt is assembled from current, noncurrent, commercial-paper and short-term components. Operating income is rebuilt as pre-tax income + interest for filers that never tag it.
2. **Year-to-date reporting.** 10-Q cash-flow facts are cumulative, and Q4 exists only inside the 10-K annual figure. Facts that share a start date are differenced (H1 − Q1, 9M − H1, FY − 9M) to recover discrete quarters. 52/53-week fiscal calendars are snapped onto a common quarter spine within ±12 days.
3. **Impairments.** Non-cash goodwill, intangible and long-lived asset write-downs are added back to operating income ("adjusted EBIT"), taking the largest of the overlapping tag measurements per quarter. Without it, one write-down (Kraft Heinz: $9B in a quarter) sends trailing coverage negative and the synthetic rating to D.
4. **Look-ahead bias.** `load_company(ticker, asof=date)` keeps only facts *filed* on or before `date`, and the latest such filing wins. This reproduces the information set an analyst actually had, so later restatements can't leak into a backtest.

Every value keeps its accession number, and the dashboard links to the filing.

## 2. The stock-and-flow model (`engine/fintwin/model/sd_model.py`)

Quarterly time step, 12-quarter horizon, vectorized across Monte Carlo paths.

**Stocks:** cash, receivables, inventory, payables, customer deposits / deferred revenue, net PP&E, term debt, revolver, equity, and other net assets.

**Flows and rules (per path, per quarter):**

| Flow | Rule |
|---|---|
| Demand | g_t = μ + φ(g_{t−1} − μ) + σ_g ε^d_t, applied to deseasonalized revenue, then season and scenario shock |
| Costs | F(1+π)^t · cut_t + (v + m_t + Δv_t) · Rev_t, i.e. fixed + variable (operating leverage), with m_t an AR(1) margin shock |
| D&A | δ · PP&E_{t−1} |
| Interest | debt × blended coupon + revolver × (r + spread + 150bp); interest income on cash |
| Working capital | receivables and inventory adjust toward DSO/DIO targets with first-order delays (τ = 1q, 2q); payables and customer deposits move immediately |
| Capex | κ · Rev, cut to maintenance (0.8 × D&A) when stressed |
| Payouts | fixed dividend + buybacks as a share of positive FCF, suspended when stressed |
| Debt | scheduled maturities (XBRL maturity ladder); rollover share inferred from the 2-year debt trend; new issuance to defend a cash target; calibrated discretionary financing noise; excess cash swept into paydown |
| Backstops | revolver up to the committed facility; optional emergency equity |

**Feedback loops**

* **R1 Leverage–spread spiral.** TTM interest coverage sets a synthetic rating through Damodaran's Jan-2026 table. The rating sets the spread on new and refinanced debt, and the blended coupon updates as debt rolls. Higher interest lowers coverage, which closes the loop.
* **R2 Market-access cliff.** Market access is 100% at ICR ≥ 1.5, 60% at ≥ 0.8 and 30% below that, and 0% while markets are frozen. Unfunded maturities must be paid from cash.
* **B1 Cash conservation.** When cash < 1.5 × floor or ICR < 2.5, payouts stop and capex falls to maintenance.
* **B2 Delayed restructuring.** After 2 quarters below the target margin, fixed costs fall 4% per quarter, to a floor of −15%.

**Accounting identity.** Assets − liabilities − equity is constant along every path. A Hypothesis property test checks this across random scenarios and lever combinations, to 1e-10 relative error.

## 3. Calibration (`engine/fintwin/stochastic/calibrate.py`)

| Parameter | Estimator |
|---|---|
| Seasonality | median ratio-to-centered-MA4 over 8 years (robust to crisis quarters) |
| μ | median deseasonalized log-growth over 12 quarters, shrunk 50% toward 1.2%/q (no extrapolation of hyper-growth) |
| φ, σ_g | AR(1) on 32 quarters; σ from the MAD of residuals, so crises go into the tails instead of inflating σ |
| Tail df | Student-t MLE on standardized residuals, clipped to [3, 30] |
| F, v | penalized least squares of cash operating costs on revenue, shrunk toward a 35% fixed-cost share when revenue hasn't varied enough to identify the slope |
| DSO/DIO/DPO/deposit days | last 4 quarters |
| Coupon | interest expense / debt, last reported quarters |
| Rollover share | 1 + Δdebt(8q) / (2 × next-year maturities), clipped to [0, 1] |
| Cash floor | half the company's 10th-percentile cash balance over 12 quarters (revealed minimum operating cash) |
| Recession regime | Markov switching; entry 4.5%/q and mean length 4.2q from NBER dates since 1947; revenue cyclicality β from nominal GDP, shrunk toward 1.5 |
| Financing noise | MAD of quarterly % debt changes |
| Short rate | Vasicek AR(1) on quarterly 3M T-bill since 2000 |

Every parameter's provenance is exported and shown in the dashboard. Assumptions are labelled as such.

## 4. Monte Carlo and outputs

Shocks are drawn as [N, T, 5] standardized arrays (demand, margin, rate, financing, and a regime uniform). Demand and margin are correlated and share a chi-square mixing variable (Student-t), rescaled to unit variance. The core model is deterministic given the shocks, which is what makes cross-language parity testable.

**Health score (0–100)** is a weighted composite:

| Weight | Component | Scale |
|---|---|---|
| 30% | Liquidity runway: (cash + undrawn revolver) ÷ (fixed costs + interest + unfundable maturities) | 8 quarters or more = 100 |
| 30% | Synthetic rating | rank / 14 |
| 20% | Net debt / EBITDA | 0× = 100, 6× = 0 |
| 20% | Altman Z'' (book version) | 1.1 → 2.6 maps to 0 → 100 |

A path that has breached is capped at 25. The headline score is the median over paths of each path's average.

**Liquidity breach** means cash < 0 after the revolver, accessible debt markets and (if enabled) equity.

**Reverse stress** finds the shock size at which P(breach) = 50% (and 10%), by bisection with common random numbers.

## 5. Two engines

The Python engine runs calibration, backtests and exports. `web/src/engine/model.ts` is a port that follows the Python step by step, running in a Web Worker. `web/src/engine/model.test.ts` loads golden runs exported from Python (parameters, scenario, levers and the exact shocks) and requires ≤ 1e-6 relative agreement on 11 output series across 4 companies and scenarios.
