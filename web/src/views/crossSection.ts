import type { Calibration } from "../data";

/** Worse than this cumulative FCF, as % of a year's revenue, counts as a severe cash burn. */
export const SEVERE_BURN_PCT = -10;

/** The February 2020 cross-section split into the twin's most fragile and most robust two-fifths. */
export function fragilityBuckets(xs: Calibration["cross_section"]) {
  const rows = xs.rows.filter((r) => r.realized_min_cum_fcf_pct_rev != null);
  const sorted = [...rows].sort((a, b) => a.health_stress - b.health_stress);
  const k = Math.floor((sorted.length * 2) / 5);
  const severe = (rs: typeof rows) => rs.filter((r) => (r.realized_min_cum_fcf_pct_rev ?? 0) < SEVERE_BURN_PCT).length / Math.max(rs.length, 1);
  return { rows, fragileSevere: severe(sorted.slice(0, k)), robustSevere: severe(sorted.slice(-k)) };
}
