import { describe, expect, it } from "vitest";
import { healthStatus, signed } from "./format";

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
