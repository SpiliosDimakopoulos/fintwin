import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { drawShocks, makeRng } from "./shocks";
import type { Params } from "./types";

const DIR = join(__dirname, "__golden__");
const goldenFiles = readdirSync(DIR).filter((file) => file.endsWith(".json"));
const baseParams = JSON.parse(readFileSync(join(DIR, goldenFiles[0]), "utf-8")).params as Params;
const N = 20_000;

function channel(values: Float64Array, index: number, size: number): number[] {
  return Array.from({ length: size }, (_, i) => values[i * 5 + index]);
}

function sampleCorrelation(a: number[], b: number[]): number {
  const meanA = a.reduce((sum, value) => sum + value, 0) / a.length;
  const meanB = b.reduce((sum, value) => sum + value, 0) / b.length;
  let cross = 0, squareA = 0, squareB = 0;
  for (let i = 0; i < a.length; i++) {
    const da = a[i] - meanA, db = b[i] - meanB;
    cross += da * db;
    squareA += da * da;
    squareB += db * db;
  }
  return cross / Math.sqrt(squareA * squareB);
}

function sampleKurtosis(values: number[]): number {
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  let second = 0, fourth = 0;
  for (const value of values) {
    const squared = (value - mean) ** 2;
    second += squared;
    fourth += squared ** 2;
  }
  return (fourth / values.length) / (second / values.length) ** 2;
}

describe("browser shock distribution", () => {
  it.each([0.3, -0.5])("tracks demand/margin correlation at rho=%s", (rho) => {
    const eps = drawShocks({ ...baseParams, rho_gm: rho }, N, 1, 73);
    const observed = sampleCorrelation(channel(eps, 0, N), channel(eps, 1, N));

    expect(Math.abs(observed - rho)).toBeLessThan(0.03);
  });

  it("keeps the uniform channel in [0, 1) with mean near one half", () => {
    const values = drawShocks(baseParams, N, 1, 89);
    const uniforms = channel(values, 4, N);
    const mean = uniforms.reduce((sum, value) => sum + value, 0) / uniforms.length;

    expect(uniforms.every((value) => value >= 0 && value < 1)).toBe(true);
    expect(Math.abs(mean - 0.5)).toBeLessThan(0.01);
  });

  it("has heavier Student-t tails and near-Gaussian tails at high degrees of freedom", () => {
    const student = channel(drawShocks({ ...baseParams, t_df: 6 }, N, 1, 101), 0, N);
    const gaussian = channel(drawShocks({ ...baseParams, t_df: 30 }, N, 1, 101), 0, N);

    expect(sampleKurtosis(student)).toBeGreaterThan(3.5);
    expect(sampleKurtosis(gaussian)).toBeGreaterThan(2.7);
    expect(sampleKurtosis(gaussian)).toBeLessThan(3.3);
  });

  it("is reproducible per seed, changes with seed, and returns N*T*5 values", () => {
    const first = drawShocks(baseParams, 40, 3, 17);
    const repeat = drawShocks(baseParams, 40, 3, 17);
    const different = drawShocks(baseParams, 40, 3, 18);

    expect(first).toEqual(repeat);
    expect(first).not.toEqual(different);
    expect(first).toHaveLength(40 * 3 * 5);
  });

  it.each([1, 6])("has chi-square mean near df=%s", (df) => {
    const rng = makeRng(127 + df);
    const mean = Array.from({ length: N }, () => rng.chisq(df)).reduce((sum, value) => sum + value, 0) / N;

    expect(Math.abs(mean - df)).toBeLessThan(df === 1 ? 0.12 : 0.2);
  });
});
