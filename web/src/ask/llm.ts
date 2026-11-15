/**
 * Optional on-device language model for "Ask the twin" (WebLLM, runs on the visitor's GPU via WebGPU).
 *
 * Nothing is sent to a server and no API key is involved. The model only proposes scenario settings as JSON; the
 * result is validated and clamped by `clampScenario` before it reaches the simulation, so the model can never
 * produce a number the user sees.
 */
import type { MLCEngine } from "@mlc-ai/web-llm";
import { clampScenario, type Scenario } from "./parse";

export const MODEL = "Qwen2.5-1.5B-Instruct-q4f16_1-MLC";
export const MODEL_LABEL = "Qwen2.5 1.5B";
export const MODEL_SIZE = "about 1 GB";

export const webgpuAvailable = () => typeof navigator !== "undefined" && "gpu" in navigator;

/** Plain-language field names make a small model far more reliable than the engine's internal knob names. */
const SCHEMA = {
  type: "object",
  properties: {
    revenue_drop_pct: { type: "number", minimum: 0, maximum: 95 },
    quarters_at_bottom: { type: "integer", minimum: 1, maximum: 8 },
    recovery_quarters: { type: "integer", minimum: 1, maximum: 12 },
    interest_rate_change_bp: { type: "integer", minimum: -300, maximum: 600 },
    credit_spread_increase_bp: { type: "integer", minimum: 0, maximum: 1000 },
    debt_markets_closed_quarters: { type: "integer", minimum: 0, maximum: 8 },
    variable_cost_increase_pp: { type: "number", minimum: 0, maximum: 15 },
    extra_inventory_days: { type: "integer", minimum: 0, maximum: 120 },
    keep_paying_dividends: { type: "boolean" },
    allow_emergency_equity_raise: { type: "boolean" },
  },
  additionalProperties: false,
};

const SYSTEM = `You translate a description of an economic crisis into settings for a company cash-flow stress test.
Return a JSON object with only the fields the description states or clearly implies; omit everything else.
Units: revenue_drop_pct is the peak fall in revenue in percent; durations are in quarters (a year = 4, six months = 2);
interest rate and credit spread changes are in basis points (1 percentage point = 100); variable_cost_increase_pp is in
percentage points of revenue.
Typical crises, if named: a 2020-style pandemic or lockdown = revenue_drop_pct 70, quarters_at_bottom 3, recovery_quarters 8,
credit_spread_increase_bp 400, debt_markets_closed_quarters 2, interest_rate_change_bp -150. A 2008-style financial crisis =
revenue_drop_pct 15, credit_spread_increase_bp 500, debt_markets_closed_quarters 4, interest_rate_change_bp -200. A recession =
revenue_drop_pct 12, credit_spread_increase_bp 250, interest_rate_change_bp -150. Stagflation = interest_rate_change_bp 300,
variable_cost_increase_pp 3, revenue_drop_pct 5.`;

let engine: Promise<MLCEngine> | null = null;

export function loadModel(onProgress: (p: { progress: number; text: string }) => void): Promise<MLCEngine> {
  if (!engine) {
    engine = import("@mlc-ai/web-llm").then((w) => w.CreateMLCEngine(MODEL, { initProgressCallback: onProgress }));
    engine.catch(() => { engine = null; });
  }
  return engine;
}

type ModelOut = Partial<{
  revenue_drop_pct: number; quarters_at_bottom: number; recovery_quarters: number; interest_rate_change_bp: number;
  credit_spread_increase_bp: number; debt_markets_closed_quarters: number; variable_cost_increase_pp: number;
  extra_inventory_days: number; keep_paying_dividends: boolean; allow_emergency_equity_raise: boolean;
}>;

/** Map the model's plain-language JSON onto engine settings, then clamp. */
export function toScenario(o: ModelOut): Scenario {
  const knobs: Scenario["knobs"] = {};
  if (o.revenue_drop_pct !== undefined) knobs.sales_depth = o.revenue_drop_pct / 100;
  if (o.quarters_at_bottom !== undefined) knobs.sales_duration = o.quarters_at_bottom;
  if (o.recovery_quarters !== undefined) knobs.sales_recovery = o.recovery_quarters;
  if (o.interest_rate_change_bp !== undefined) knobs.rate_bp = o.interest_rate_change_bp;
  if (o.credit_spread_increase_bp !== undefined) knobs.spread_bp = o.credit_spread_increase_bp;
  if (o.debt_markets_closed_quarters !== undefined) knobs.refi_freeze = o.debt_markets_closed_quarters;
  if (o.variable_cost_increase_pp !== undefined) knobs.cost_pp = o.variable_cost_increase_pp;
  if (o.extra_inventory_days !== undefined) knobs.dio_days = o.extra_inventory_days;
  const levers: Scenario["levers"] = {};
  if (o.keep_paying_dividends === true) levers.cut_payouts = false;
  if (o.allow_emergency_equity_raise === true) levers.issue_equity = true;
  return clampScenario({ knobs, levers });
}

export async function interpret(text: string): Promise<Scenario | null> {
  if (!engine) return null;
  const e = await engine;
  const r = await e.chat.completions.create({
    messages: [{ role: "system", content: SYSTEM }, { role: "user", content: text.slice(0, 600) }],
    temperature: 0,
    max_tokens: 160,
    response_format: { type: "json_object", schema: JSON.stringify(SCHEMA) },
  });
  try {
    return toScenario(JSON.parse(r.choices[0]?.message?.content ?? "{}") as ModelOut);
  } catch {
    return null;
  }
}
