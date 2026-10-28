/**
 * Cross-implementation parity: the TypeScript engine must reproduce the Python reference engine
 * on golden runs (same parameters, scenario, levers and pre-drawn shocks).
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { simulate, simulateBlocks } from "./model";
import { buildScenario } from "./scenario";
import { drawShocks } from "./shocks";
import { decisionOutputs, summarize } from "./summary";
import { OUTPUT_KEYS, type Levers, type Outputs, type Params } from "./types";

const DIR = join(__dirname, "__golden__");
const files = readdirSync(DIR).filter((f) => f.endsWith(".json"));

describe("parity with Python engine", () => {
  it("has golden cases", () => expect(files.length).toBeGreaterThan(0));

  for (const f of files) {
    it(f, () => {
      const g = JSON.parse(readFileSync(join(DIR, f), "utf-8"));
      const p: Params = g.params;
      const eps3d: number[][][] = g.eps;
      const N = eps3d.length, T = p.horizon;
      const eps = new Float64Array(N * T * 5);
      eps3d.forEach((path, n) => path.forEach((q, t) => q.forEach((v, k) => (eps[(n * T + t) * 5 + k] = v))));
      const out = simulate(p, buildScenario(g.knobs, T), eps, N, g.levers as Levers);
      let worst = 0;
      // every key the Python engine produced must be compared (the old goldens checked 12 of 29)
      const keys = Object.keys(g.expected);
      for (const k of OUTPUT_KEYS) expect(keys, `${f} lacks ${k}`).toContain(k);
      if (g.levers.M1) expect(keys).toContain("cov_breach");
      for (const [key, rows] of Object.entries(g.expected as Record<string, number[][]>)) {
        const got = out[key as keyof Outputs] as Float64Array;
        rows.forEach((row, n) => row.forEach((want, t) => {
          const have = got[n * T + t];
          const rel = Math.abs(have - want) / Math.max(Math.abs(want), 1);
          worst = Math.max(worst, rel);
          if (rel > 1e-6) throw new Error(`${key}[${n},${t}] ts=${have} py=${want}`);
        }));
      }
      expect(worst).toBeLessThan(1e-6);
      if (g.decisions) {
        const d = decisionOutputs(out, p, g.decisions.p_liquidity_below?.x) as Record<string, unknown>;
        for (const [k, want] of Object.entries(g.decisions as Record<string, unknown>)) {
          expect(JSON.parse(JSON.stringify(d[k])), k).toEqual(want === null ? null : expect.anything());
          const flat = (v: unknown): number[] => (typeof v === "number" ? [v] : v && typeof v === "object" ? Object.values(v).flatMap(flat) : []);
          flat(want).forEach((w, i) => expect(Math.abs(flat(d[k])[i] - w) / Math.max(Math.abs(w), 1), `${k}[${i}]`).toBeLessThan(1e-6));
        }
      }
    });
  }
});

describe("browser shock generator", () => {
  const p = JSON.parse(readFileSync(join(DIR, files[0]), "utf-8")).params as Params;
  it("is reproducible per seed and has unit variance", () => {
    const a = drawShocks(p, 4000, 12, 1), b = drawShocks(p, 4000, 12, 1);
    expect(a).toEqual(b);
    for (let k = 0; k < 4; k++) {
      let s = 0, s2 = 0;
      const n = a.length / 5;
      for (let i = 0; i < n; i++) { s += a[i * 5 + k]; s2 += a[i * 5 + k] ** 2; }
      expect(Math.abs(s / n)).toBeLessThan(0.05);
      expect(Math.abs(s2 / n - 1)).toBeLessThan(0.12);
    }
  });
  it("runs 5,000 paths fast and summarizes", () => {
    const t0 = performance.now();
    const eps = drawShocks(p, 5000, p.horizon, 7);
    const out = simulate(p, buildScenario({ sales_depth: 0.3 }, p.horizon), eps, 5000, {
      recessions: true, cut_capex: true, cut_payouts: true, issue_debt: true, draw_revolver: true, issue_equity: false, cut_costs: true,
    });
    const s = summarize(out);
    const ms = performance.now() - t0;
    expect(s.healthScore).toBeGreaterThanOrEqual(0);
    expect(ms).toBeLessThan(2000);
  });
});

describe("revision-3 switch plumbing", () => {
  const load = (n: string) => JSON.parse(readFileSync(join(DIR, n), "utf-8"));
  const run = (g: { params: Params; knobs: never; levers: Levers; eps: number[][][] }, lev: Partial<Levers>, p: Partial<Params> = {}) => {
    const pp = { ...g.params, ...p }, T = pp.horizon, N = g.eps.length;
    const eps = new Float64Array(N * T * 5);
    g.eps.forEach((path, n) => path.forEach((q, t) => q.forEach((v, k) => (eps[(n * T + t) * 5 + k] = v))));
    return { out: simulateBlocks(pp, buildScenario(g.knobs, T), eps, N, { ...g.levers, ...lev }), N, T, eps };
  };

  it("ignores F3/F6 keys while the switches are off and changes with them on", () => {
    const g = load("synth_v3keys_switches_off.json");
    const off = run(g, {}).out, on = run(g, { F3: true, F6: true }).out;
    const plain = run(g, {}, { m_dev0: 0, fixed_adj_lambda: 0, fixed_adj_lambda_down: 0 }).out;
    expect(Array.from(off.ebitda)).toEqual(Array.from(plain.ebitda));
    expect(Array.from(on.ebitda)).not.toEqual(Array.from(off.ebitda));
  });

  it("splits paths into parameter-draw blocks like numpy array_split", () => {
    const g = load("synth_f6.json");
    const draws = [{ F: 250 }, { F: 300 }, { F: 350 }];
    const { out, N, T, eps } = run(g, {}, { _param_draws: draws });
    // N = 64 -> blocks of 22, 21, 21
    const sizes = [22, 21, 21];
    let start = 0;
    sizes.forEach((n, i) => {
      const block = simulate({ ...g.params, ...draws[i] }, buildScenario(g.knobs, T),
        eps.subarray(start * T * 5, (start + n) * T * 5), n, g.levers);
      expect(Array.from(out.ebitda.subarray(start * T, (start + n) * T))).toEqual(Array.from(block.ebitda));
      start += n;
    });
    expect(start).toBe(N);
  });
});
