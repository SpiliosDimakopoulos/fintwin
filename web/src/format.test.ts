import { describe, expect, it } from "vitest";
import { fixed, futureQuarters, healthStatus, money, pct, prettyName, quarterLabel, signed } from "./format";

describe("signed", () => {
  it("never prints '+-'", () => {
    expect(signed(28.4)).toBe("+28");
    expect(signed(-5.2)).toBe("−5");
    expect(signed(-0.2)).toBe("0");
    expect(signed(null)).toBe("–");
  });
});

describe("healthStatus labels", () => {
  it("describes model stress rather than the condition of the company", () => {
    const labels = [80, 60, 40, 10].map((h) => healthStatus(h).label);
    expect(labels).toEqual(["Low stress", "Moderate stress", "Elevated stress", "High stress"]);
    expect(labels.join(" ")).not.toMatch(/Distressed|Strained|Healthy/);
  });
});

describe("money tiers", () => {
  it("chooses the tier after rounding", () => {
    expect(money(512e6)).toBe("$512M");
    expect(money(-2.345e9)).toBe("−$2.3B");
    expect(money(999.5e6)).toBe("$1.0B");
    expect(money(999.96e9)).toBe("$1.0T");
    expect(money(999_999.6)).toBe("$1M");
    expect(money(NaN)).toBe("–");
  });
});

describe("pct and fixed", () => {
  it("print 0 rather than -0 for tiny negatives", () => {
    expect(pct(-0.001)).toBe("0%");
    expect(fixed(-0.01)).toBe("0.0");
    expect(pct(-0.25)).toBe("-25%");
  });
});

describe("quarter labels", () => {
  it("labels quarter ends, including 52/53-week fiscal year ends", () => {
    expect(quarterLabel("2025-12-31")).toBe("Q4 '25");
    expect(quarterLabel("2025-12-28")).toBe("Q4 '25");
    expect(quarterLabel("2025-03-29")).toBe("Q1 '25");
  });

  it("continues across the year boundary", () => {
    expect(futureQuarters("2025-09-30", 3)).toEqual(["Q4 '25", "Q1 '26", "Q2 '26"]);
    expect(futureQuarters("2025-12-28", 2)).toEqual(["Q1 '26", "Q2 '26"]);
  });

  it("does not depend on the local time zone", () => {
    const tz = process.env.TZ;
    try {
      process.env.TZ = "America/Los_Angeles";
      expect(quarterLabel("2025-01-01")).toBe("Q1 '25");
      expect(futureQuarters("2024-12-31", 1)).toEqual(["Q1 '25"]);
    } finally {
      if (tz === undefined) delete process.env.TZ; else process.env.TZ = tz;
    }
  });
});

describe("prettyName", () => {
  it("title-cases SEC capitals and keeps suffixes and short words", () => {
    expect(prettyName("BOEING CO")).toBe("Boeing Co.");
    expect(prettyName("BANK OF AMERICA CORP")).toBe("Bank of America Corp.");
    expect(prettyName("AT&T INC.")).toBe("AT&T Inc.");
    expect(prettyName("Apple Inc.")).toBe("Apple Inc.");
  });
});
