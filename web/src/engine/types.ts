export type Params = {
  ticker: string; name: string; last_quarter: string; horizon: number; history_quarters: number;
  seasonal: number[]; season0: number; base_rev0: number;
  mu: number; phi: number; sigma_g: number; g0: number; t_df: number; rho_gm: number;
  rec_hazard: number; rec_exit: number; rec_drift: number; rec_vol_mult: number; rec_state0: number; beta_gdp: number;
  F: number; v: number; rho_m: number; sigma_m: number; infl: number;
  target_margin: number; cut_delay: number; cut_speed: number; cut_floor: number;
  dso: number; dio: number; dpo: number; ddays: number; tau_ar: number; tau_inv: number;
  dep_rate: number; capex_ratio: number; maint_capex: number; sbc_ratio: number; ocf_ratio: number;
  tax_rate: number; coupon: number; floating: number; refi_ratio: number; sigma_fin: number; cash_target: number; cash_cap: number;
  div_q: number; bb_ratio: number; revolver_cap: number; cash_floor: number; maturities_q: number[];
  r0: number; term_premium: number; kappa: number; theta: number; sigma_r: number;
  cash0: number; ar0: number; inv0: number; ap0: number; def0: number; ppe0: number; debt0: number;
  equity0: number; other_net0: number; other_liab0: number; wc_other0: number; retained0: number;
  ebit_ttm0: number[]; ebitda_ttm0: number[]; interest_ttm0: number[];
  _sources: Record<string, string>;
  sector_tol?: number;
  // revision 3 (optional; absent in v2 exports)
  m_dev0?: number; t_scale?: number; t_mix_indep?: number;
  fixed_adj_lambda?: number; fixed_adj_lambda_down?: number; fixed_adj_f?: number;
  ladder_unknown?: number; fixed_share_sd?: number; da_imputed_share?: number;
  rev_ttm0?: number; icr_materiality?: number;
  cov_max_nd_ebitda?: number | null; cov_min_icr?: number | null; cov_cure_q?: number; cov_revolver_avail?: number;
  revolver_maturity_q?: number | null;
  payout_class?: string; payout_floor_ni?: number; payout_keep_div?: number;
  _param_draws?: Partial<Params>[];
};

export type Knobs = Partial<{
  sales_depth: number; sales_duration: number; sales_recovery: number; rate_bp: number; spread_bp: number;
  spread_duration: number; cost_pp: number; cost_duration: number; dio_days: number; refi_freeze: number;
}>;

export type Levers = {
  recessions: boolean; cut_capex: boolean; cut_payouts: boolean; issue_debt: boolean; draw_revolver: boolean;
  issue_equity: boolean; cut_costs: boolean;
  /** Revision-3 switches (off unless true), the same ids as FINTWIN_FIXES: model-side F3, F6, F11 and extensions M1, M5. */
  F3?: boolean; F6?: boolean; F11?: boolean; M1?: boolean; M5?: boolean;
};

export type Scenario = {
  sales_shock: Float64Array; rate_shift: Float64Array; spread_shift: Float64Array;
  cost_shift: Float64Array; dio_shift: Float64Array; refi_access: Float64Array;
};

export const OUTPUT_KEYS = [
  "revenue", "ebitda", "ebit", "net_income", "cfo", "fcf", "capex", "cash", "debt", "revolver", "liquidity",
  "interest", "icr", "nd_ebitda", "rating", "zscore", "health", "breach", "equity", "issued", "fixed_cost_mult",
  "debt_issued", "recession", "dividends", "buybacks", "h_liq", "h_cov", "h_lev", "h_solv",
] as const;
/** Present only when M1 is on. */
/** Weights of the health score components (sd_model.py); Waterfall.tsx decomposes the score with them. */
export const HEALTH_WEIGHTS = { liq: 0.3, cov: 0.3, lev: 0.2, solv: 0.2 } as const;
export const M1_OUTPUT_KEYS = ["cov_breach", "revolver_avail"] as const;
export type OutputKey = (typeof OUTPUT_KEYS)[number];
/** Each output is a row-major [N * T] matrix (path-major). */
export type Outputs = Record<OutputKey, Float64Array> & { N: number; T: number; cov_breach?: Float64Array; revolver_avail?: Float64Array };
