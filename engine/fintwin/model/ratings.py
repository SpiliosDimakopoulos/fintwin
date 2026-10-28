"""Synthetic credit rating from interest coverage (Damodaran, large non-financial firms, Jan 2026).

Source: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html
Rank 0 = D ... 14 = AAA. Spreads are over the risk-free rate, decimal p.a.
"""

import numpy as np

# Lower ICR bound of each bucket (bucket i covers [LOWER[i], LOWER[i+1]) ).
ICR_LOWER = np.array([-np.inf, 0.2, 0.65, 0.8, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 4.25, 5.5, 6.5, 8.5])
RATINGS = ["D", "C", "CC", "CCC", "B-", "B", "B+", "BB", "BB+", "BBB", "A-", "A", "A+", "AA", "AAA"]
SPREADS = np.array(
    [0.19, 0.16, 0.1261, 0.0885, 0.0509, 0.0321, 0.0275, 0.0184, 0.0138, 0.0111, 0.0089, 0.0078, 0.0070, 0.0055, 0.0040]
)
INVESTMENT_GRADE_MIN_RANK = 9  # BBB


def spreads_asof(asof: str | None) -> list[float] | None:
    """The rating-spread table published before `asof` (Damodaran's January tables, archived by the Wayback
    Machine; data/rating_spreads.csv), ordered like SPREADS (D ... AAA). None if no vintage precedes `asof`."""
    if asof is None:
        return None
    from pathlib import Path

    import pandas as pd

    f = Path(__file__).resolve().parents[1] / "data" / "rating_spreads.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f, dtype={"snapshot": str})
    t = t[t["snapshot"].str[:8] <= pd.Timestamp(asof).strftime("%Y%m%d")]
    if t.empty:
        return None
    row = t.sort_values("snapshot").iloc[-1]
    return [float(row[c]) for c in reversed(ORDER_DAMODARAN)]


ORDER_DAMODARAN = ["AAA", "AA", "A+", "A", "A-", "BBB", "BB+", "BB", "B+", "B", "B-", "CCC", "CC", "C", "D"]


def rating_rank(icr: np.ndarray) -> np.ndarray:
    return np.searchsorted(ICR_LOWER, icr, side="right") - 1


def rating_spread(icr: np.ndarray) -> np.ndarray:
    return SPREADS[rating_rank(icr)]


# MM-F11: coverage is only meaningful when interest is material. Below this share of TTM revenue the company is
# treated as debt-free for rating purposes, and a net-cash company is floored at the lowest investment-grade bucket
# (BBB, ICR 2.5): its coverage is undefined, not catastrophic, so it must not be rated D or trigger the B1 cuts.
ICR_MATERIALITY = 0.001
NET_CASH_ICR = 2.5


def effective_icr(icr, interest_ttm, revenue_ttm, net_cash, materiality: float = ICR_MATERIALITY):
    """ICR used for rating, spread, market access and the B1 stress test under MM-F11."""
    immaterial = interest_ttm <= materiality * np.abs(revenue_ttm)
    return np.where(immaterial & (net_cash >= 0) & (icr < NET_CASH_ICR), NET_CASH_ICR, icr)
