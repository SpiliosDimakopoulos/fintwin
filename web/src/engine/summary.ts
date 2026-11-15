import { INVESTMENT_GRADE_MIN_RANK, RATINGS } from "./ratings";
import type { OutputKey, Outputs } from "./types";

export const BANDS = [5, 25, 50, 75, 95] as const;
export const BAND_VARS = ["revenue", "ebitda", "fcf", "cash", "liquidity", "debt", "icr", "nd_ebitda", "health",
  "zscore", "interest"] as const satisfies readonly OutputKey[];

/** numpy-style percentile with linear interpolation on a sorted copy. */
export function percentile(sorted: Float64Array, q: number): number {
  const pos = ((sorted.length - 1) * q) / 100;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

const sortedCopy = (a: ArrayLike<number>) => Float64Array.from(a).sort();
const median = (a: ArrayLike<number>) => percentile(sortedCopy(a), 50);

function column(m: Float64Array, N: number, T: number, t: number): Float64Array {
  const c = new Float64Array(N);
  for (let n = 0; n < N; n++) c[n] = m[n * T + t];
  return c;
}

export type Summary = {
  bands: Record<(typeof BAND_VARS)[number], number[][]>; // [band][t]
  pBreachByQ: number[];
  pRecessionByQ: number[];
  components: { liq: number; cov: number; lev: number; solv: number };
  healthMean: number;
  pBreach: number;
  pIcrBelow15: number;
  pSubIG: number;
  ratingDist: number[];
  healthScore: number;
  healthP10: number;
  healthHist: number[]; // histogram of path-average health, 20 bins of 5 points
  medianQuartersToBreach: number | null;
  minLiquidityBands: number[];
  equityNeededMedian: number;
  debtIssuedMedian: number;
  samplePaths: { cash: number[][]; health: number[][] };
};

export function summarize(o: Outputs, nSample = 40): Summary {
  const { N, T } = o;
  const bands = {} as Summary["bands"];
  for (const k of BAND_VARS) {
    bands[k] = BANDS.map(() => new Array(T).fill(0));
    for (let t = 0; t < T; t++) {
      const col = column(o[k], N, T, t).sort();
      BANDS.forEach((b, j) => (bands[k][j][t] = percentile(col, b)));
    }
  }
  const pBreachByQ = Array.from({ length: T }, (_, t) => {
    let s = 0;
    for (let n = 0; n < N; n++) s += o.breach[n * T + t];
    return s / N;
  });
  const pRecessionByQ = Array.from({ length: T }, (_, t) => {
    let s = 0;
    for (let n = 0; n < N; n++) s += o.recession[n * T + t];
    return s / N;
  });
  const mean = (a: Float64Array) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i]; return s / a.length; };
  const components = { liq: mean(o.h_liq), cov: mean(o.h_cov), lev: mean(o.h_lev), solv: mean(o.h_solv) };
  const healthAvg = mean(o.health);
  const ratingDist = new Array(RATINGS.length).fill(0);
  let icrLow = 0, subIG = 0;
  const healthMean = new Float64Array(N), minLiq = new Float64Array(N), eqSum = new Float64Array(N), debtSum = new Float64Array(N);
  const breachQ: number[] = [];
  for (let n = 0; n < N; n++) {
    const last = n * T + T - 1;
    ratingDist[Math.max(o.rating[last], 0)] += 1 / N;
    if (o.rating[last] < INVESTMENT_GRADE_MIN_RANK) subIG++;
    let h = 0, ml = Infinity, mi = Infinity, eq = 0, dbt = 0, fb = -1;
    for (let t = 0; t < T; t++) {
      const i = n * T + t;
      h += o.health[i];
      ml = Math.min(ml, o.liquidity[i]);
      mi = Math.min(mi, o.icr[i]);
      eq += o.issued[i];
      dbt += o.debt_issued[i];
      if (fb < 0 && o.breach[i]) fb = t;
    }
    healthMean[n] = h / T;
    minLiq[n] = ml;
    if (mi < 1.5) icrLow++;
    eqSum[n] = eq;
    debtSum[n] = dbt;
    if (fb >= 0) breachQ.push(fb);
  }
  const hs = sortedCopy(healthMean);
  const ml = sortedCopy(minLiq);
  const healthHist = new Array(20).fill(0);
  healthMean.forEach((h) => (healthHist[Math.min(Math.floor(h / 5), 19)] += 1 / N));
  const pick = Array.from({ length: Math.min(nSample, N) }, (_, j) => Math.floor((j * N) / Math.min(nSample, N)));
  return {
    bands, pBreachByQ, pRecessionByQ, components, healthMean: healthAvg, pBreach: pBreachByQ[T - 1], pIcrBelow15: icrLow / N, pSubIG: subIG / N, ratingDist,
    healthScore: percentile(hs, 50), healthP10: percentile(hs, 10), healthHist,
    medianQuartersToBreach: breachQ.length ? median(breachQ) : null,
    minLiquidityBands: BANDS.map((b) => percentile(ml, b)),
    equityNeededMedian: median(eqSum), debtIssuedMedian: median(debtSum),
    samplePaths: {
      cash: pick.map((n) => Array.from(o.cash.subarray(n * T, n * T + T))),
      health: pick.map((n) => Array.from(o.health.subarray(n * T, n * T + T))),
    },
  };
}

// ---------------------------------------------------------------- M7: decision outputs (mirror of sd_model.py)

/** P(cash + undrawn revolver < x in any of the first n quarters); n omitted = whole horizon. */
export function pLiquidityBelow(out: Outputs, x: number, n?: number): number {
  const { N, T } = out, m = Math.min(n || T, T);
  let hit = 0;
  for (let i = 0; i < N; i++) {
    let mn = Infinity;
    for (let t = 0; t < m; t++) mn = Math.min(mn, out.liquidity[i * T + t]);
    if (mn < x) hit++;
  }
  return hit / N;
}

/** Contractual term-debt maturities by quarter (the calibrated ladder), zero-padded to T. */
export function maturityWall(maturities: number[], T: number): number[] {
  return Array.from({ length: T }, (_, t) => maturities[t] ?? 0);
}

/** Per path, the first quarter (0-based) of a covenant breach, -1 if none (needs M1 on). */
export function firstCovenantBreach(out: Outputs): number[] {
  const { N, T } = out, cb = out.cov_breach;
  return Array.from({ length: N }, (_, i) => {
    for (let t = 0; t < T && cb; t++) if (cb[i * T + t] > 0) return t;
    return -1;
  });
}

export type DecisionOutputs = {
  runway_q_median: number; runway_q_p10: number; runway_censored_share: number;
  funding_gap_p50: number; funding_gap_p95: number; funding_gap_mean: number; p_funding_gap: number;
  maturity_wall: number[];
  revolver_due?: { q: number; median: number };
  p_liquidity_below?: { x: number; n: number; p: number };
  p_cov_breach?: number; first_cov_breach_q_median?: number | null;
};

/** Runway (first quarter with liquidity < 0, censored at T), funding gap, maturity wall, P(liquidity < x), covenant. */
export function decisionOutputs(
  out: Outputs,
  p: { cash_floor: number; maturities_q: number[]; revolver_maturity_q?: number | null },
  x?: number,
  n?: number,
): DecisionOutputs {
  const { N, T } = out;
  const runway = new Float64Array(N), gap = new Float64Array(N);
  for (let i = 0; i < N; i++) {
    runway[i] = T;
    for (let t = 0; t < T; t++) if (out.liquidity[i * T + t] < 0) { runway[i] = t; break; }
    let g = 0;
    for (let t = 0; t < T; t++) g = Math.max(g, p.cash_floor - out.cash[i * T + t]);
    gap[i] = g;
  }
  const gs = sortedCopy(gap);
  const res: DecisionOutputs = {
    runway_q_median: median(runway),
    runway_q_p10: percentile(sortedCopy(runway), 10),
    runway_censored_share: runway.filter((r) => r >= T).length / N,
    funding_gap_p50: percentile(gs, 50),
    funding_gap_p95: percentile(gs, 95),
    funding_gap_mean: gap.reduce((s, v) => s + v, 0) / N,
    p_funding_gap: gap.filter((v) => v > 0).length / N,
    maturity_wall: maturityWall(p.maturities_q, T),
  };
  // truncate before the range test, as Python's `0 < int(mq) < T`: mq in (0, 1) has no quarter before it
  const q = Math.trunc(p.revolver_maturity_q ?? 0);
  if (q > 0 && q < T) {
    res.revolver_due = { q, median: median(Array.from({ length: N }, (_, i) => out.revolver[i * T + q - 1])) };
  }
  if (x !== undefined) res.p_liquidity_below = { x, n: n || T, p: pLiquidityBelow(out, x, n) };
  if (out.cov_breach) {
    const hit = firstCovenantBreach(out).filter((f) => f >= 0);
    res.p_cov_breach = hit.length / N;
    res.first_cov_breach_q_median = hit.length ? median(hit) : null;
  }
  return res;
}
