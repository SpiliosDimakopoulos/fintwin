import { describe, expect, it } from "vitest";
import { clampScenario, findCompany, parseScenario } from "./parse";

const NAMES = { CCL: "Carnival Corp", AAPL: "Apple Inc.", BA: "Boeing Co", AAL: "American Airlines Group", AEP: "American Electric Power" };

describe("parseScenario", () => {
  it("reads a demand shock with its duration and a credit freeze", () => {
    const r = parseScenario("Revenue falls 40% for a year and banks stop lending for 6 months", NAMES);
    expect(r.knobs).toMatchObject({ sales_depth: 0.4, sales_duration: 4, refi_freeze: 2 });
    expect(r.understood).toContain("revenue down 40% for 4 quarters");
  });

  it("converts rate moves in percent, points and basis points", () => {
    expect(parseScenario("rates rise 3%").knobs.rate_bp).toBe(300);
    expect(parseScenario("interest rates up 150bp").knobs.rate_bp).toBe(150);
    expect(parseScenario("the fed cuts rates by 2 points").knobs.rate_bp).toBe(-200);
    expect(parseScenario("credit spreads widen 400 bps for two years").knobs).toMatchObject({ spread_bp: 400, spread_duration: 8 });
  });

  it("starts from a named crisis and lets explicit numbers override it", () => {
    const r = parseScenario("a pandemic but sales only drop 30%");
    expect(r.knobs).toMatchObject({ sales_depth: 0.3, refi_freeze: 2, spread_bp: 400 });
    expect(r.understood[0]).toBe("starting from a 2020-style demand freeze");
    expect(parseScenario("another 2008").knobs).toMatchObject({ refi_freeze: 4, spread_bp: 500 });
  });

  it("handles costs, inventory, recovery and management levers", () => {
    const r = parseScenario("wages up 5 points for 6 quarters, 45 extra days of inventory, sales recover over 3 years, and the company keeps paying dividends");
    expect(r.knobs).toMatchObject({ cost_pp: 5, cost_duration: 6, dio_days: 45, sales_recovery: 12 });
    expect(r.levers).toEqual({ cut_payouts: false });
    expect(parseScenario("they raise equity").levers).toEqual({ issue_equity: true });
  });

  it("clamps to the slider ranges and says when it understood nothing", () => {
    expect(parseScenario("revenue drops 140%").knobs.sales_depth).toBe(0.95);
    expect(parseScenario("rates up 20%").knobs.rate_bp).toBe(600);
    const none = parseScenario("tell me a joke");
    expect(none.matched).toBe(false);
    expect(none.understood).toEqual([]);
  });

  it("finds the company by ticker or unambiguous name", () => {
    expect(findCompany("What if Carnival loses half its bookings?", NAMES)).toBe("CCL");
    expect(findCompany("stress AAPL", NAMES)).toBe("AAPL");
    expect(findCompany("it is not on the list", NAMES)).toBeUndefined();
    expect(findCompany("American companies", NAMES)).toBeUndefined(); // ambiguous
  });
});

describe("clampScenario (guardrail for model output)", () => {
  it("drops unknown keys, non-numbers and out-of-range values", () => {
    const out = clampScenario({ knobs: { sales_depth: 3, rate_bp: Number.NaN, bogus: 1, refi_freeze: 2.6 } as never, levers: { issue_equity: true, launch_rockets: true } as never });
    expect(out.knobs).toEqual({ sales_depth: 0.95, refi_freeze: 3 });
    expect(out.levers).toEqual({ issue_equity: true });
  });
});

describe("model output mapping", () => {
  it("maps plain-language fields to engine settings and clamps them", async () => {
    const { toScenario } = await import("./llm");
    const sc = toScenario({ revenue_drop_pct: 70, quarters_at_bottom: 3, debt_markets_closed_quarters: 20, interest_rate_change_bp: -150, keep_paying_dividends: true });
    expect(sc.knobs).toEqual({ sales_depth: 0.7, sales_duration: 3, refi_freeze: 8, rate_bp: -150 });
    expect(sc.levers).toEqual({ cut_payouts: false });
  });
});

describe("interpretation guards (WEB M6)", () => {
  it("reads a percentage cost increase as a change in the cost, converted to points of revenue", () => {
    const r = parseScenario("wages up 5% for two years");
    expect(r.knobs.cost_pp).toBe(3); // 5% x 60% of revenue
    expect(r.knobs.cost_duration).toBe(8);
    expect(r.understood.join(" ")).toMatch(/5% higher costs read as 3pp/);
    expect(parseScenario("inflation up 10%", {}, 0.5).knobs.cost_pp).toBe(5);
  });

  it("keeps explicit percentage points of revenue as they are", () => {
    expect(parseScenario("costs up 4 percentage points").knobs.cost_pp).toBe(4);
    expect(parseScenario("wages up 5 points for 6 quarters").knobs.cost_pp).toBe(5);
  });

  it("does not treat a bare year 2020 as the pandemic scenario", () => {
    expect(parseScenario("this is worse than 2020").matched).toBe(false);
    expect(parseScenario("a 2020-style freeze").knobs.sales_depth).toBe(0.7);
    expect(parseScenario("another 2020").knobs.sales_depth).toBe(0.7);
    expect(parseScenario("covid again").knobs.sales_depth).toBe(0.7);
  });

  it("does not mistake common words or shouting for companies", () => {
    const names = { MTCH: "Match Group, Inc.", TGT: "Target Corp", ALL: "Allstate Corp", IT: "Gartner Inc", CCL: "Carnival Corp" };
    expect(findCompany("Revenue will match last year", names)).toBeUndefined();
    expect(findCompany("What if the target is missed", names)).toBeUndefined();
    expect(findCompany("what if ALL customers leave", names)).toBeUndefined();
    expect(findCompany("IT spending falls 20%", names)).toBeUndefined();
    expect(findCompany("WHAT IF CCL LOSES HALF ITS BOOKINGS", names)).toBeUndefined();
    expect(findCompany("Stress $ALL with a recession", names)).toBe("ALL");
    expect(findCompany("Carnival loses half its bookings", names)).toBe("CCL");
    expect(findCompany("CCL loses half its bookings", names)).toBe("CCL");
  });
});
