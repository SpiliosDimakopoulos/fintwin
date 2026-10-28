// Damodaran (Jan 2026) interest-coverage -> synthetic rating table, large non-financial firms.
export const ICR_LOWER = [-Infinity, 0.2, 0.65, 0.8, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 4.25, 5.5, 6.5, 8.5];
export const RATINGS = ["D", "C", "CC", "CCC", "B-", "B", "B+", "BB", "BB+", "BBB", "A-", "A", "A+", "AA", "AAA"];
export const SPREADS = [0.19, 0.16, 0.1261, 0.0885, 0.0509, 0.0321, 0.0275, 0.0184, 0.0138,
  0.0111, 0.0089, 0.0078, 0.007, 0.0055, 0.004];
export const INVESTMENT_GRADE_MIN_RANK = 9;

/** Equivalent of numpy searchsorted(ICR_LOWER, icr, side="right") - 1. */
export function ratingRank(icr: number): number {
  if (Number.isNaN(icr)) return 0; // SW-9: an undefined coverage fails safe, as the worst rating (never AAA)
  let r = -1;
  for (let i = 0; i < ICR_LOWER.length; i++) if (ICR_LOWER[i] <= icr) r = i;
  return r;
}

// MM-F11: coverage is only meaningful when interest is material; a net-cash company with immaterial interest is
// floored at the lowest investment-grade bucket (BBB, ICR 2.5).
export const ICR_MATERIALITY = 0.001;
export const NET_CASH_ICR = 2.5;

export function effectiveIcr(icr: number, interestTtm: number, revenueTtm: number, netCash: number, materiality = ICR_MATERIALITY): number {
  return interestTtm <= materiality * Math.abs(revenueTtm) && netCash >= 0 && icr < NET_CASH_ICR ? NET_CASH_ICR : icr;
}
