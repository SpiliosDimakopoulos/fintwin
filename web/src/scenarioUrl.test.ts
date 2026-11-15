import { describe, expect, it } from "vitest";
import type { Meta } from "./data";
import { decode, encode } from "./scenarioUrl";

const META = {
  presets: { pandemic: { label: "Demand freeze", desc: "", knobs: { sales_depth: 0.7, sales_duration: 3 } }, base: { label: "Baseline", desc: "", knobs: {} } },
  levers: { cut_capex: true, cut_payouts: true, issue_debt: true, draw_revolver: true, issue_equity: false, cut_costs: true, recessions: true },
} as unknown as Meta;

describe("decode (shared-link scenarios)", () => {
  it("clamps out-of-range values to the slider ranges", () => {
    const { knobs } = decode("k=sales_depth:5;rate_bp:1e9;refi_freeze:-3;cost_pp:99", META, "base");
    expect(knobs).toEqual({ sales_depth: 0.95, rate_bp: 600, refi_freeze: 0, cost_pp: 15 });
  });

  it("rounds integer-valued knobs", () => {
    expect(decode("k=sales_duration:2.6", META, "base").knobs.sales_duration).toBe(3);
  });

  it("ignores prototype keys and non-numbers", () => {
    const { knobs, levers } = decode("k=constructor:1;toString:2;__proto__:3;sales_depth:abc;rate_bp:;spread_bp:100&off=constructor,hasOwnProperty&on=toString", META, "base");
    expect(knobs).toEqual({ spread_bp: 100 });
    expect(Object.keys(levers).sort()).toEqual(Object.keys(META.levers).sort());
    expect(levers.cut_capex).toBe(true);
  });

  it("keeps the preset's own knobs and lets valid link values override them", () => {
    expect(decode("k=sales_depth:0.4", META, "pandemic").knobs).toEqual({ sales_depth: 0.4, sales_duration: 3 });
  });

  it("round-trips what encode writes", () => {
    const q = encode({ sales_depth: 0.4, rate_bp: 100 }, { ...META.levers, cut_payouts: false }, META, "base");
    const back = decode(q, META, "base");
    expect(back.knobs).toEqual({ sales_depth: 0.4, rate_bp: 100 });
    expect(back.levers.cut_payouts).toBe(false);
  });
});
