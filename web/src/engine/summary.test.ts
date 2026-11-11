import { describe, expect, it } from "vitest";
import { decisionOutputs, firstCovenantBreach, maturityWall, percentile, pLiquidityBelow, summarize } from "./summary";
import { OUTPUT_KEYS, type OutputKey, type Outputs } from "./types";

describe("percentile endpoints and interpolation", () => {
  it("returns the only value for a one-element array", () => {
    expect(percentile(new Float64Array([7.5]), 50)).toBe(7.5);
  });

  it("returns the first and last values at the endpoints", () => {
    const values = new Float64Array([1, 2, 3, 4]);
    expect(percentile(values, 0)).toBe(1);
    expect(percentile(values, 100)).toBe(4);
  });

  it("linearly interpolates the median", () => {
    expect(percentile(new Float64Array([1, 2, 3, 4]), 50)).toBe(2.5);
  });
});

// 3 paths x 2 quarters, values chosen so every statistic below can be checked by hand
function outputs(fill: Partial<Record<OutputKey | "cov_breach", number[]>>): Outputs {
  const N = 3, T = 2;
  const arrays = Object.fromEntries(OUTPUT_KEYS.map((k) => [k, fill[k] ? Float64Array.from(fill[k]) : new Float64Array(N * T)])) as Record<OutputKey, Float64Array>;
  return { ...arrays, N, T, ...(fill.cov_breach ? { cov_breach: Float64Array.from(fill.cov_breach) } : {}) };
}

describe("summarize on a hand-built run", () => {
  const o = outputs({
    cash: [10, 20, 30, 40, 50, 60],
    health: [40, 60, 80, 100, 20, 30],
    breach: [0, 0, 0, 1, 1, 1],
    liquidity: [5, -1, 7, 8, 9, 10],
    issued: [0, 1, 0, 2, 0, 3],
  });
  const s = summarize(o);

  it("takes band percentiles per quarter across paths", () => {
    expect(s.bands.cash[2]).toEqual([30, 40]);
    expect(s.bands.cash[0]).toEqual([12, 22]);
    expect(s.bands.cash[4]).toEqual([48, 58]);
  });

  it("averages breach and health per path", () => {
    expect(s.pBreachByQ).toEqual([1 / 3, 2 / 3]);
    expect(s.pBreach).toBe(2 / 3);
    // path means 50, 90, 25
    expect(s.healthScore).toBe(50);
    expect(s.healthP10).toBe(30);
    expect(s.healthHist[10]).toBe(1 / 3);
    expect(s.healthHist[18]).toBe(1 / 3);
    expect(s.healthHist[5]).toBe(1 / 3);
    expect(s.medianQuartersToBreach).toBe(0.5);
    expect(s.equityNeededMedian).toBe(2);
    expect(s.minLiquidityBands[2]).toBe(7);
  });
});

describe("decision helpers", () => {
  const o = outputs({ liquidity: [5, -1, 7, 8, 9, 10], cov_breach: [0, 0, 0, 1, 1, 1], revolver: [1, 2, 3, 4, 5, 6] });

  it("pLiquidityBelow looks at the first n quarters", () => {
    expect(pLiquidityBelow(o, 0)).toBe(1 / 3);
    expect(pLiquidityBelow(o, 0, 1)).toBe(0);
    expect(pLiquidityBelow(o, 8)).toBe(2 / 3);
  });

  it("firstCovenantBreach returns the first breached quarter or -1", () => {
    expect(firstCovenantBreach(o)).toEqual([-1, 1, 0]);
    expect(firstCovenantBreach(outputs({}))).toEqual([-1, -1, -1]);
  });

  it("maturityWall pads the ladder with zeros", () => {
    expect(maturityWall([3], 3)).toEqual([3, 0, 0]);
  });

  it("revolver_due follows Python's int(mq) range test", () => {
    const p = { cash_floor: 0, maturities_q: [0, 0] };
    expect(decisionOutputs(o, { ...p, revolver_maturity_q: 1.7 }).revolver_due).toEqual({ q: 1, median: 3 });
    expect(decisionOutputs(o, { ...p, revolver_maturity_q: 0.5 }).revolver_due).toBeUndefined();
    expect(decisionOutputs(o, { ...p, revolver_maturity_q: 2 }).revolver_due).toBeUndefined();
  });
});
