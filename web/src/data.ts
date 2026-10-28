import type { Knobs, Levers, Params } from "./engine/types";

export type PresetSummary = {
  health_score: number; health_p10: number; p_breach: number; p_icr_below_1_5: number;
  p_downgrade_below_ig: number; median_quarters_to_breach: number | null; rating_dist: number[];
  bands?: Record<string, number[][]>; p_breach_by_q?: number[];
  components?: { liq: number; cov: number; lev: number; solv: number }; health_mean?: number;
};

export type ReverseItem = { label: string; unit: "pct" | "bp" | "pp"; p10: number | null; p50: number | null };

export type Company = {
  ticker: string; name: string; cik: number; sector: string; edgar_url: string;
  quality: {
    quarters: number; first: string; last: string; balance_sheet_identity_max_gap_pct: number;
    core_completeness_last20_pct: number; maturity_ladder_date: string | null; maturity_ladder_stale: boolean;
    notes: string[]; missing_by_field_last20: Record<string, number>;
  };
  params: Params;
  history: {
    dates: string[];
    series: Record<"revenue" | "ebitda" | "net_income" | "cfo" | "capex" | "fcf" | "cash" | "debt" | "equity" | "icr"
      | "nd_ebitda" | "rating", (number | null)[]>;
    provenance: Record<string, (string | null)[]>;
  };
  presets: Record<string, PresetSummary>;
  reverse_stress: Record<string, ReverseItem>;
  tornado: { knob: string; value: number; label: string; d_health: number; d_p_breach: number }[];
  sobol?: { rows: import("./charts/SobolChart").SobolRow[]; output_sd: number; interaction_share: number; n_runs: number; insensitive: boolean };
};

export type Memo = {
  ticker: string; generated_by: string; as_of: string; attempts: number; unverified_numbers: number[];
  fact_sheet: unknown; verdict: "Strong" | "Adequate" | "Healthy" | "Watch" | "Strained" | "Weak" | "Distressed"; headline: string; summary: string;
  key_risks: { risk: string; evidence: string }[]; resilience: string[]; scenario_notes: { scenario: string; note: string }[];
  watch_list: string[];
};

type VarCalibration = {
  n: number; raw: { coverage90: number; coverage50: number }; conformal: { coverage90: number; coverage50: number };
  conformal_factors: Record<string, { c90: number; c50: number }>; crps_skill_vs_naive: number; median_case_skill: number;
  share_cases_beating_naive: number; regime_ablation: { crps_with: number; crps_without: number; improvement_pct: number };
  pit_hist: number[]; by_year: Record<string, { cov90: number; n: number; skill: number }>; by_horizon: Record<string, number>;
};
export type Calibration = {
  n_companies: number; n_forecasts: number; origins: string[]; horizon: number;
  vars: Record<"revenue" | "cash_like", VarCalibration>;
  cross_section: { n: number; spearman: number; p_value: number; ci95: number[]; quintile_median_burn: number[]; rows: CrossRow[] };
};

export type Meta = {
  generated: string; horizon: number;
  ratings: { labels: string[]; icr_lower: (number | null)[]; spreads: number[] };
  knobs: Record<string, { default: number; desc: string }>;
  presets: Record<string, { label: string; desc: string; knobs: Knobs }>;
  levers: Levers;
};

export type IndexEntry = {
  name: string; sector: string; gics?: string; showcase: boolean; last_quarter: string;
  matrix: Record<string, { health: number; p_breach: number }>;
};
export type Index = { companies: Record<string, IndexEntry>; meta: Meta };

type Bands = number[][];
export type ForecastBacktest = {
  ticker: string; cutoff: string; cutoff_label: string; stress: string; last_quarter_known: string; horizon: number;
  scores: Record<string, { n: number; coverage50: number; coverage90: number; stress_coverage90: number; crps: number;
    crps_baseline: number; crps_skill: number; pit: number[] }>;
  series: Record<string, { history: { dates: string[]; values: number[] }; realized: { dates: string[]; values: (number | null)[] };
    base_bands: Bands; stress_bands: Bands }>;
  structural: { dates: string[]; actual_cum_fcf: number[]; model_cum_fcf_bands: Bands; final_error_pct: number;
    corr: number | null } | Record<string, never>;
  pre_shock: Record<"base" | "stress", { health_score: number; p_breach: number; p_icr_below_1_5: number;
    p_downgrade_below_ig: number }>;
};
export type CrossRow = {
  ticker: string; name: string; health_base: number; health_stress: number; p_breach_stress: number;
  realized_burn_ratio: number | null; realized_debt_raise_pct_rev: number; realized_min_cum_fcf_pct_rev: number | null;
};
export type Backtest = {
  cutoffs: Record<string, { date: string; label: string; stress: string }>;
  forecast: Record<string, ForecastBacktest>;
  aggregate: Record<string, { coverage50: number; coverage90: number; median_crps_skill: number;
    share_beating_baseline: number; cases: number }>;
  cross_section: { cutoff: string; rows: CrossRow[]; stats: Record<string, { spearman: number; p_value: number; n: number }>;
    failed: Record<string, string> };
};

const base = import.meta.env.BASE_URL;
const cache = new Map<string, Promise<unknown>>();
function getJson<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    cache.set(path, fetch(`${base}${path}`).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(path) as Promise<T>;
}

export const loadIndex = () => getJson<Index>("data/index.json");
export const loadBacktest = () => getJson<Backtest>("data/backtest.json");
export const loadCalibration = () => getJson<Calibration>("data/calibration.json").catch(() => null);

/** Headline results of the research paper (written by engine/scripts/research_assets.py). */
export type ResearchSummary = {
  samples: { universe: number; firm_years: number; firms: number; transmission_firm_years: number; bankruptcies: number };
  ladder: { key: string; label: string; median_ae: number }[];
  incremental: { twin_vs_4q: number; "16q_vs_4q": number; twin_vs_16q: number; encompassing_t: number };
  combination: Record<"cfo" | "fcf", Record<"N3" | "N3+N5" | "N3+T1", number>>;
  bankruptcy: Record<"all" | "weak", Record<"twin" | "formula" | "ohlson_o" | "altman_z2", number>> & { weak_share: number };
};
export type BuildReport = { generated: string; failed: Record<string, string>; n_companies: number };
export const loadBuildReport = () => getJson<BuildReport>("data/build_report.json").catch(() => null);
export const loadResearch = () => getJson<ResearchSummary>("data/research_summary.json").catch(() => null);
export const loadMemo = (t: string) => getJson<Memo>(`data/memos/${t}.json`).catch(() => null);

/** Snapshot first; fall back to the optional local live API (`python -m fintwin.api`) for unseen tickers. */
export async function loadCompany(ticker: string): Promise<Company> {
  try {
    return await getJson<Company>(`data/companies/${encodeURIComponent(ticker)}.json`);
  } catch {
    cache.delete(`data/companies/${encodeURIComponent(ticker)}.json`);
    // The local live API exists only in development; on the static site an unknown ticker is simply not in the snapshot.
    if (!import.meta.env.DEV) throw new Error(`No snapshot for ${ticker}. The static site covers the companies listed in the matrix.`);
    const r = await fetch(`/api/company/${encodeURIComponent(ticker)}`);
    if (!r.ok) throw new Error(r.status === 404 ? `No snapshot for ${ticker}. Start the live API to fetch any ticker.` : `Live API error ${r.status}`);
    return r.json();
  }
}

export type Vintage = { asof: string; last_quarter: string; health: number; health_p10: number; p_breach: number; params: Omit<import("./engine/types").Params, "_sources"> };
export type Timeline = { ticker: string; series: { dates: string[]; revenue: (number | null)[]; cash: (number | null)[]; debt: (number | null)[] }; vintages: Vintage[] };
export const loadTimeline = (t: string) => getJson<Timeline>(`data/timeline/${t}.json`).catch(() => null);

export type ChangeDriver = { component: "liq" | "cov" | "lev" | "solv"; label: string; points: number };
export type Mover = {
  ticker: string; name: string; sector: string; health_before: number; health_after: number; delta: number;
  stress_before: number | null; stress_after: number | null; p_breach_before: number; p_breach_after: number;
  new_filing: boolean; quarter: string | null; drivers: ChangeDriver[];
};
export type ChangeWeek = {
  date: string; previous: string | null; n_companies: number; n_new_filings: number; n_weaker: number; n_stronger: number;
  movers: Mover[]; new_filings: { ticker: string; name: string; quarter: string | null }[]; added: string[]; removed: string[];
};
export type Changes = { threshold: number; weeks: ChangeWeek[] };
export const loadChanges = () => getJson<Changes>("data/changes.json").catch(() => null);
