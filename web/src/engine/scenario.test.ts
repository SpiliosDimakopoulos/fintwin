import { describe, expect, it } from "vitest";
import { buildScenario } from "./scenario";

describe("buildScenario (mirror of presets.build_scenario)", () => {
  it("holds the trough, recovers linearly and halves the first quarter when hold > 1", () => {
    const s = buildScenario({ sales_depth: 0.4, sales_duration: 2, sales_recovery: 3 }, 6);
    expect(Array.from(s.sales_shock)).toEqual([-0.2, -0.4, -0.4 * 0.75, -0.4 * 0.5, -0.4 * 0.25, 0]);
  });

  it("does not halve a one-quarter shock", () => {
    expect(buildScenario({ sales_depth: 0.4, sales_duration: 1, sales_recovery: 1 }, 3).sales_shock[0]).toBe(-0.4);
  });

  it("ramps rates over two quarters and closes markets for refi_freeze quarters", () => {
    const s = buildScenario({ rate_bp: 200, spread_bp: 300, spread_duration: 2, refi_freeze: 1, cost_pp: 2, cost_duration: 1 }, 3);
    expect(Array.from(s.rate_shift)).toEqual([0.01, 0.02, 0.02]);
    expect(Array.from(s.spread_shift)).toEqual([0.03, 0.03, 0]);
    expect(Array.from(s.refi_access)).toEqual([0, 1, 1]);
    expect(Array.from(s.cost_shift)).toEqual([0.02, 0, 0]);
  });
});
