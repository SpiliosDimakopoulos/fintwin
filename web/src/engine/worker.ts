/// <reference lib="webworker" />
import { simulateBlocks } from "./model";
import { buildScenario } from "./scenario";
import { drawShocks } from "./shocks";
import { summarize } from "./summary";
import type { Knobs, Levers, Params } from "./types";

/** Requests sharing a `lane` replace each other while queued: only the newest one is computed. */
export type SimRequest = { id: number; params: Params; knobs: Knobs; levers: Levers; nPaths: number; seed: number; lane?: number };

// Shocks depend only on (company, N, seed): cache them so slider moves reuse identical draws
// (common random numbers make scenario-to-scenario differences smooth rather than noisy).
let shockKey = "";
let shocks: Float64Array | null = null;

const post = (msg: unknown) => (self as unknown as Worker).postMessage(msg);

function run(req: SimRequest) {
  const { params, knobs, levers, nPaths, seed } = req;
  const t0 = performance.now();
  const key = `${params.ticker}|${params.last_quarter}|${nPaths}|${seed}`;
  if (key !== shockKey || !shocks) {
    shocks = drawShocks(params, nPaths, params.horizon, seed);
    shockKey = key;
  }
  const out = simulateBlocks(params, buildScenario(knobs, params.horizon), shocks, nPaths, levers);
  return { summary: summarize(out), ms: performance.now() - t0 };
}

const queue: SimRequest[] = [];
let draining = false;

// One run per macrotask, so messages that arrived during a run are queued (and can supersede) before the next starts.
function drain() {
  const req = queue.shift();
  if (!req) { draining = false; return; }
  try {
    post({ id: req.id, ...run(req) });
  } catch (err) {
    post({ id: req.id, error: err instanceof Error ? err.message : String(err) });
  }
  setTimeout(drain, 0);
}

self.onmessage = (e: MessageEvent<SimRequest>) => {
  const req = e.data;
  const i = req.lane == null ? -1 : queue.findIndex((q) => q.lane === req.lane);
  if (i >= 0) {
    post({ id: queue[i].id, superseded: true });
    queue[i] = req;
  } else queue.push(req);
  if (!draining) { draining = true; setTimeout(drain, 0); }
};
