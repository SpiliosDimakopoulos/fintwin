import { describe, expect, it } from "vitest";
import { percentile } from "./summary";

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
