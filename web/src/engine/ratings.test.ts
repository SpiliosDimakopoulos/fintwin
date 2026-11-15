import { describe, expect, it } from "vitest";
import { ICR_LOWER, RATINGS, SPREADS, effectiveIcr, ratingRank } from "./ratings";

describe("rating rank boundaries", () => {
  it.each(ICR_LOWER.map((threshold, rank) => [threshold, rank]))(
    "maps ICR boundary %s to rank %i",
    (threshold, rank) => {
      expect(ratingRank(threshold)).toBe(rank);
    },
  );

  it("maps negative infinity to D and 100 to AAA", () => {
    expect(ratingRank(Number.NEGATIVE_INFINITY)).toBe(0);
    expect(ratingRank(100)).toBe(14);
  });

  it("keeps the rating tables aligned", () => {
    expect(RATINGS).toHaveLength(ICR_LOWER.length);
    expect(SPREADS).toHaveLength(ICR_LOWER.length);
  });

  it("fails safe on NaN coverage: rank 0 (worst), never AAA (SW-9)", () => {
    expect(ratingRank(Number.NaN)).toBe(0);
    expect(SPREADS[ratingRank(Number.NaN)]).toBe(SPREADS[0]);
  });

  it("floors immaterial-interest net-cash coverage at BBB (MM-F11)", () => {
    expect(effectiveIcr(0.1, 0.01, 1000, 5)).toBe(2.5);
    expect(effectiveIcr(0.1, 0.01, 1000, -5)).toBe(0.1); // net debt: no floor
    expect(effectiveIcr(0.1, 5, 1000, 5)).toBe(0.1); // material interest: no floor
    expect(effectiveIcr(4, 0.01, 1000, 5)).toBe(4);
  });
});
