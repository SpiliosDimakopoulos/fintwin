/// <reference lib="webworker" />
import { simulateBlocks } from "./model";
import { buildScenario } from "./scenario";
import { drawShocks } from "./shocks";
import { summarize } from "./summary";
import type { Knobs, Levers, Params } from "./types";

export type SimRequest = { id: number; params: Params; knobs: Knobs; levers: Levers; nPaths: number; seed: number };

// Shocks depend only on (company, N, seed): cache them so slider moves reuse identical draws
// (common random numbers make scenario-to-scenario differences smooth rather than noisy).
let shockKey = "";
let shocks: Float64Array | null = null;

self.onmessage = (e: MessageEvent<SimRequest>) => {
  const { id, params, knobs, levers, nPaths, seed } = e.data;
  const t0 = performance.now();
  const key = `${params.ticker}|${params.last_quarter}|${nPaths}|${seed}`;
  if (key !== shockKey || !shocks) {
    shocks = drawShocks(params, nPaths, params.horizon, seed);
    shockKey = key;
  }
  const out = simulateBlocks(params, buildScenario(knobs, params.horizon), shocks, nPaths, levers);
  const summary = summarize(out);
  (self as unknown as Worker).postMessage({ id, summary, ms: performance.now() - t0 });
};
