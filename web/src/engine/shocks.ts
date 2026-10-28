/**
 * Seeded shock generator for the browser engine. Same distributional recipe as
 * engine/fintwin/stochastic/shocks.py (correlated demand/margin shocks, shared Student-t mixing,
 * unit variance), but its own PRNG, so draws are reproducible per seed without matching numpy bit-for-bit.
 */
import type { Params } from "./types";

/** xoshiro128** — small, fast, good-quality 32-bit generator. */
function xoshiro128ss(seed: number) {
  let a = 0x9e3779b9 ^ seed, b = 0x243f6a88 ^ (seed * 31), c = 0xb7e15162, d = 0x12345678 ^ (seed << 7);
  const next = () => {
    const r = Math.imul(Math.imul(b, 5) << 7 | Math.imul(b, 5) >>> 25, 9);
    const t = b << 9;
    c ^= a; d ^= b; b ^= c; a ^= d; c ^= t;
    d = d << 11 | d >>> 21;
    return (r >>> 0) / 4294967296;
  };
  for (let i = 0; i < 20; i++) next(); // warm up
  return next;
}

export function makeRng(seed: number) {
  const uniform = xoshiro128ss(seed);
  let spare: number | null = null;
  const normal = () => {
    if (spare !== null) { const s = spare; spare = null; return s; }
    let u = 0;
    while (u === 0) u = uniform();
    const v = uniform();
    const r = Math.sqrt(-2 * Math.log(u));
    spare = r * Math.sin(2 * Math.PI * v);
    return r * Math.cos(2 * Math.PI * v);
  };
  /** Marsaglia–Tsang gamma(shape, 1). */
  const gamma = (shape: number): number => {
    if (shape < 1) return gamma(shape + 1) * Math.pow(uniform(), 1 / shape);
    const d = shape - 1 / 3, c = 1 / Math.sqrt(9 * d);
    for (;;) {
      let x: number, v: number;
      do { x = normal(); v = 1 + c * x; } while (v <= 0);
      v = v * v * v;
      const u = uniform();
      if (u < 1 - 0.0331 * x ** 4 || Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
    }
  };
  return { uniform, normal, chisq: (df: number) => 2 * gamma(df / 2) };
}

export function drawShocks(p: Params, N: number, T: number, seed = 7): Float64Array {
  const rng = makeRng(seed);
  const eps = new Float64Array(N * T * 5);
  // F7: p.t_scale makes the MAD s.d. 1; F8: p.t_mix_indep gives demand and margin their own mixing variable
  const rho = p.rho_gm, df = p.t_df, tScale = p.t_scale ?? Math.sqrt((df - 2) / df), indep = !!p.t_mix_indep;
  for (let i = 0; i < N * T; i++) {
    const z0 = rng.normal(), z1 = rng.normal(), z2 = rng.normal(), z3 = rng.normal();
    let g = z0, m = rho * z0 + Math.sqrt(1 - rho * rho) * z1;
    if (df < 30) {
      const wG = rng.chisq(df) / df;
      const kG = tScale / Math.sqrt(wG);
      const kM = indep ? tScale / Math.sqrt(rng.chisq(df) / df) : kG;
      g *= kG; m *= kM;
    }
    eps[i * 5] = g; eps[i * 5 + 1] = m; eps[i * 5 + 2] = z2; eps[i * 5 + 3] = z3; eps[i * 5 + 4] = rng.uniform();
  }
  return eps;
}
