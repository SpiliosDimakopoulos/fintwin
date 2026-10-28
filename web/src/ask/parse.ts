/**
 * "Ask the twin": turn a plain-English crisis description into stress-lab settings.
 *
 * This module is the deterministic layer. It runs everywhere, instantly, and is the guardrail for the optional
 * on-device language model: whatever the model proposes passes through `clampScenario` before it reaches the
 * simulation. Language only chooses the scenario; every number shown afterwards comes from the simulation.
 */
import type { Knobs, Levers } from "../engine/types";

export type KnobKey = keyof Required<Knobs>;
export type Scenario = { knobs: Partial<Record<KnobKey, number>>; levers: Partial<Levers>; ticker?: string };
export type Interpretation = Scenario & { understood: string[]; matched: boolean };

/** Same ranges as the stress-lab sliders. */
export const RANGES: Record<KnobKey, [number, number]> = {
  sales_depth: [0, 0.95], sales_duration: [1, 8], sales_recovery: [1, 12], rate_bp: [-300, 600], spread_bp: [0, 1000],
  spread_duration: [1, 12], cost_pp: [0, 15], cost_duration: [1, 12], dio_days: [0, 120], refi_freeze: [0, 8],
};
const LEVER_KEYS: (keyof Levers)[] = ["cut_capex", "cut_payouts", "issue_debt", "draw_revolver", "issue_equity", "cut_costs", "recessions"];

/** "2020" alone is a year, not a scenario ("worse than 2020"); it triggers the preset only next to a crisis word. */
const CRISIS_WORD = "(?:crisis|shock|style|repeat|again|collapse|freeze|crash|lockdowns?|scenario)";
const PANDEMIC = new RegExp(`\\b(?:pandemic|covid|lockdowns?|shut ?downs?)\\b|\\b2020\\b[ -]*${CRISIS_WORD}\\b|\\b${CRISIS_WORD}\\s+(?:like|as in|of|from)\\s+2020\\b|\\b(?:another|repeat of|rerun of|again)\\s+2020\\b`);

/**
 * Cost shocks written as a percentage ("wages up 5%") are a change in the cost itself, while the stress-lab knob is
 * percentage points of revenue. Costs are assumed to be this share of revenue, so 5% more wages is 5% x 0.6 = 3pp.
 */
export const COST_SHARE_OF_REVENUE = 0.6;

/** Named scenarios recognised by keyword; explicit numbers in the text override them. */
const NAMED: [RegExp, Partial<Record<KnobKey, number>>, string][] = [
  [PANDEMIC, { sales_depth: 0.7, sales_duration: 3, sales_recovery: 8, spread_bp: 400, spread_duration: 6, refi_freeze: 2, rate_bp: -150 }, "a 2020-style demand freeze"],
  [/\b(2008|financial crisis|great recession|lehman)\b/, { sales_depth: 0.15, sales_duration: 3, sales_recovery: 8, spread_bp: 500, spread_duration: 6, refi_freeze: 4, rate_bp: -200, cost_pp: 1, cost_duration: 4 }, "a 2008-style recession with a credit crunch"],
  [/\bstagflation|1970s\b/, { rate_bp: 300, cost_pp: 3, cost_duration: 6, sales_depth: 0.05, sales_duration: 2, sales_recovery: 4 }, "stagflation"],
  [/\bcredit crunch\b/, { refi_freeze: 4, spread_bp: 500, spread_duration: 4 }, "a credit crunch"],
  [/\bsupply[- ]chain\b/, { dio_days: 30, cost_pp: 3, cost_duration: 4, sales_depth: 0.05 }, "a supply-chain shock"],
  [/\brecession\b/, { sales_depth: 0.12, sales_duration: 3, sales_recovery: 6, rate_bp: -150, spread_bp: 250, spread_duration: 6, cost_pp: 2, cost_duration: 4 }, "a recession"],
];

const WORD_NUM: Record<string, number> = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, twelve: 12, eighteen: 18, twenty: 20, "twenty-four": 24 };
const DOWN = /\b(fall|falls|fell|falling|drop|drops|dropped|down|declin\w*|collaps\w*|plung\w*|plummet\w*|slump\w*|shrink\w*|sink\w*|tank\w*|halv\w*|lose|loses|lost|cut|cuts|lower|decrease\w*|crash\w*|evaporat\w*)\b/;
const UP = /\b(rise|rises|rising|rose|up|hike\w*|increase\w*|jump\w*|climb\w*|higher|spike\w*|surge\w*|soar\w*|widen\w*|double\w*)\b/;

const clamp = (k: KnobKey, v: number) => Math.min(Math.max(v, RANGES[k][0]), RANGES[k][1]);

/** Quarters from "for 3 quarters", "for a year", "for six months", "18 months". */
function duration(s: string): number | undefined {
  const m = s.match(/(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|eighteen|twenty|twenty-four)\s+(quarters?|qtrs?|months?|years?)/);
  if (!m) return undefined;
  const n = /^\d/.test(m[1]) ? +m[1] : WORD_NUM[m[1]];
  const unit = m[2];
  const q = unit.startsWith("year") ? n * 4 : unit.startsWith("month") ? n / 3 : n;
  return Math.max(1, Math.round(q));
}

function percent(s: string): number | undefined {
  const m = s.match(/(\d+(?:\.\d+)?)\s*(%|percent|per cent)/);
  if (m) return +m[1] / 100;
  if (/\b(halv\w*|half|by 50)\b/.test(s)) return 0.5;
  if (/\ba third\b/.test(s)) return 1 / 3;
  if (/\b(two thirds|two-thirds)\b/.test(s)) return 2 / 3;
  return undefined;
}

/** Basis points from "200bp", "2%", "2 percentage points", "3 points". */
function bps(s: string): number | undefined {
  const bp = s.match(/(\d+(?:\.\d+)?)\s*(bp|bps|basis points?)/);
  if (bp) return +bp[1];
  const pts = s.match(/(\d+(?:\.\d+)?)\s*(%|percent|per cent|percentage points?|pp|points?)/);
  return pts ? Math.round(+pts[1] * 100) : undefined;
}

export function parseScenario(text: string, names: Record<string, string> = {}, costShare = COST_SHARE_OF_REVENUE): Interpretation {
  const raw = text.trim();
  const s = raw.toLowerCase();
  const knobs: Partial<Record<KnobKey, number>> = {};
  const levers: Partial<Levers> = {};
  const understood: string[] = [];

  for (const [re, preset, label] of NAMED) {
    if (re.test(s)) {
      Object.assign(knobs, preset, knobs); // earlier (more specific) matches win
      understood.push(`starting from ${label}`);
      break;
    }
  }

  // clause by clause, so a duration belongs to the shock it is written next to
  for (const c of s.split(/[,;.]|\band\b|\bthen\b|\bwhile\b|\bwith\b/).map((x) => x.trim()).filter(Boolean)) {
    const d = duration(c);
    if (/\b(revenue|sales|demand|top[- ]line|bookings|orders|traffic|customers|volumes?)\b/.test(c) && (DOWN.test(c) || /\bcollapse/.test(c))) {
      const p = percent(c) ?? (/\bcollaps|evaporat|disappear/.test(c) ? 0.6 : undefined);
      if (p !== undefined) knobs.sales_depth = p;
      if (d !== undefined) knobs[/\brecover/.test(c) ? "sales_recovery" : "sales_duration"] = d;
      if (p === undefined && d === undefined && knobs.sales_depth === undefined) knobs.sales_depth = 0.2;
    } else if (/\brecover/.test(c) && d !== undefined) {
      knobs.sales_recovery = d;
    }
    if (/\b(interest rates?|rates|fed|policy rate|yields?|central bank)\b/.test(c) && !/\bspread/.test(c)) {
      const b = bps(c);
      if (UP.test(c)) knobs.rate_bp = b ?? 200;
      else if (DOWN.test(c)) knobs.rate_bp = -(b ?? 150);
    }
    if (/\b(spreads?|borrowing costs?|cost of debt|credit costs?)\b/.test(c) && (UP.test(c) || /\bwiden/.test(c))) {
      knobs.spread_bp = bps(c) ?? 300;
      if (d !== undefined) knobs.spread_duration = d;
    }
    if (/\b(debt|credit|bond|capital|funding|financing) markets?\b.*\b(clos\w*|shut\w*|freez\w*|frozen|dr(y|ies) up|unavailable)\b/.test(c)
      || /\b(banks?|lenders?|investors?)\b.*\b(stop|stops|refuse|refuses|won'?t|will not|no longer)\b.*\blend/.test(c)
      || /\b(no|can'?t|cannot|unable to)\b.*\b(refinanc\w*|borrow\w*)\b/.test(c)) {
      knobs.refi_freeze = d ?? 2;
    }
    if (/\b(costs?|wages?|input prices?|raw materials?|energy prices?|inflation|commodit\w*)\b/.test(c) && UP.test(c) && !/\bborrowing|cost of debt/.test(c)) {
      const m = c.match(/(\d+(?:\.\d+)?)\s*(%|percentage points?|pp|points?|percent|per cent)/);
      if (m) {
        const relative = m[2] === "%" || m[2] === "percent" || m[2] === "per cent"; // a % change of the cost, not pp of revenue
        knobs.cost_pp = relative ? +(+m[1] * costShare).toFixed(1) : +m[1];
        if (relative) understood.push(`${m[1]}% higher costs read as ${knobs.cost_pp}pp of revenue (costs assumed ${Math.round(costShare * 100)}% of revenue)`);
      } else knobs.cost_pp = knobs.cost_pp ?? 3;
      if (d !== undefined) knobs.cost_duration = d;
    }
    const inv = c.match(/inventor\w*.*?(\d+)\s*days|(\d+)\s*(more|extra)?\s*days of inventor/);
    if (inv) knobs.dio_days = +(inv[1] ?? inv[2]);
  }

  if (/\b(keep|keeps|maintain|maintains|continue|continues)\b.*\b(dividends?|buybacks?|payouts?)\b|\bno (dividend|payout) cuts?\b/.test(s)) levers.cut_payouts = false;
  if (/\b(raise|raises|issue|issues|sell|sells)\b.*\b(equity|shares|stock)\b/.test(s)) levers.issue_equity = true;
  if (/\bno (new )?debt\b|\bcan'?t raise debt\b/.test(s)) levers.issue_debt = false;
  if (/\b(revolver|credit line|credit facility|bank line)\b.*\b(unavailable|pulled|withdrawn|cancel\w*|cut)\b/.test(s)) levers.draw_revolver = false;
  if (/\bno (layoffs|restructuring|cost cuts)\b/.test(s)) levers.cut_costs = false;

  const ticker = findCompany(raw, names);
  const clamped = clampScenario({ knobs, levers, ticker });
  understood.push(...describe(clamped));
  const matched = Object.keys(clamped.knobs).length > 0 || Object.keys(clamped.levers).length > 0;
  return { ...clamped, understood: matched ? understood : [], matched };
}

/** Tickers that are also everyday words: accepted only as "$ALL" or "(ALL)", never as a bare capitalised word. */
const WORD_TICKERS = new Set(["A", "ALL", "IT", "ON", "NOW", "KEY", "CAT", "LOW", "FAST", "ARE", "ANY", "ONE", "BIG", "FOR", "HAS", "CAN", "NEW", "TOP", "WELL", "LIVE", "BEST", "EVER", "GAS", "HOME", "LIFE", "MAIN", "REAL", "SEE", "TECH", "TRUE", "WAY", "WELL", "OUT", "SO", "BY", "AN", "AS", "AT", "BE", "DO", "GO", "HE", "IF", "IN", "IS", "NO", "OF", "OR", "TO", "UP", "US", "WE", "AND", "BUT", "THE", "WAS", "NOT", "YOU", "ALLY", "MET", "ICE", "HAL", "PEG", "RE", "EL", "LH", "BR", "L", "ES"]);
/** First words of company names that are plain English; a name must match on more than this one word. */
const COMMON_FIRST_WORDS = new Set(["match", "target", "block", "ross", "general", "american", "united", "first", "global", "world", "health", "energy", "south", "north", "national", "western", "digital", "public", "service", "services", "international", "capital", "group", "partners", "regions", "best", "live", "fast", "home", "life", "mark", "dollar", "universal", "southern", "eastern", "central", "pacific", "atlantic", "great", "real", "direct", "key", "marathon", "community", "federal", "royal", "steel", "ball", "dominion"]);
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Uppercase tickers written as such ("AAPL", "CCL") or a company's name ("Carnival", "Boeing"). */
export function findCompany(text: string, names: Record<string, string>): string | undefined {
  // a fully upper-case sentence ("WHAT IF ALL REVENUE FALLS") says nothing about tickers
  const shouting = /\s/.test(text.trim()) && text === text.toUpperCase();
  if (!shouting) {
    for (const t of text.match(/\b[A-Z]{1,5}\b/g) ?? []) {
      if (!(Object.prototype.hasOwnProperty.call(names, t))) continue;
      if (t.length < 2) continue;
      if (WORD_TICKERS.has(t) && !new RegExp(`(?:\\$|\\()${t}\\b`).test(text)) continue;
      return t;
    }
  }
  const lower = ` ${text.toLowerCase().replace(/[^a-z0-9& ]/g, " ")} `;
  const hits = Object.entries(names).filter(([, n]) => {
    const words = n.toLowerCase().replace(/[^a-z0-9& ]/g, " ").split(/\s+/).filter(Boolean);
    const first = words[0] ?? "";
    // a one-word match needs a distinctive word that the user wrote with a capital letter ("Carnival", not "carnival rides")
    const capitalised = first.length >= 4 && new RegExp(`\\b${escapeRe(first.charAt(0).toUpperCase() + first.slice(1))}\\b`).test(text);
    const single = capitalised && !COMMON_FIRST_WORDS.has(first) && lower.includes(` ${first} `);
    return single || (words.length > 1 && lower.includes(` ${words.slice(0, 2).join(" ")} `));
  });
  return hits.length === 1 ? hits[0][0] : undefined;
}

/** The guardrail: keep only known settings, as finite numbers inside the slider ranges. */
export function clampScenario(sc: Scenario): Scenario {
  const knobs: Partial<Record<KnobKey, number>> = {};
  for (const [k, v] of Object.entries(sc.knobs ?? {})) {
    if (k in RANGES && typeof v === "number" && Number.isFinite(v)) {
      const key = k as KnobKey;
      const val = clamp(key, v);
      knobs[key] = key.endsWith("_duration") || key === "sales_recovery" || key === "refi_freeze" || key === "dio_days" ? Math.round(val) : val;
    }
  }
  const levers: Partial<Levers> = {};
  for (const [k, v] of Object.entries(sc.levers ?? {})) if ((LEVER_KEYS as string[]).includes(k) && typeof v === "boolean") levers[k as keyof Levers] = v;
  return { knobs, levers, ticker: sc.ticker };
}

const q = (n: number) => `${n} quarter${n === 1 ? "" : "s"}`;
export function describe(sc: Scenario): string[] {
  const k = sc.knobs, out: string[] = [];
  if (k.sales_depth !== undefined) out.push(`revenue down ${Math.round(k.sales_depth * 100)}%${k.sales_duration ? ` for ${q(k.sales_duration)}` : ""}${k.sales_recovery ? `, recovering over ${q(k.sales_recovery)}` : ""}`);
  if (k.rate_bp) out.push(`interest rates ${k.rate_bp > 0 ? "+" : "−"}${Math.abs(k.rate_bp)}bp`);
  if (k.spread_bp) out.push(`credit spreads +${k.spread_bp}bp${k.spread_duration ? ` for ${q(k.spread_duration)}` : ""}`);
  if (k.refi_freeze) out.push(`debt markets closed for ${q(k.refi_freeze)}`);
  if (k.cost_pp) out.push(`variable costs +${k.cost_pp}pp of revenue${k.cost_duration ? ` for ${q(k.cost_duration)}` : ""}`);
  if (k.dio_days) out.push(`inventory +${k.dio_days} days`);
  const L = sc.levers;
  if (L.cut_payouts === false) out.push("dividends and buybacks kept");
  if (L.issue_equity) out.push("emergency equity raise allowed");
  if (L.issue_debt === false) out.push("no new debt");
  if (L.draw_revolver === false) out.push("credit facility unavailable");
  if (L.cut_costs === false) out.push("no restructuring");
  return out;
}
