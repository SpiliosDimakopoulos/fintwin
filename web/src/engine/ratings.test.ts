import { describe, expect, it } from "vitest";
import { ICR_LOWER, RATINGS, SPREADS, ratingRank } from "./ratings";

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
});
