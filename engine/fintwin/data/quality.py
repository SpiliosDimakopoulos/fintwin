"""Data-quality checks on the extracted quarterly panel."""

from __future__ import annotations

import pandas as pd

from .facts import CompanyData

RECENT_QUARTERS = 20
# Maturity ladders come from the 10-K; one older than a year plus a filing lag has missed an annual update.
LADDER_STALE_DAYS = 450


def quality_report(c: CompanyData) -> dict:
    q = c.quarters
    if q.empty:
        raise ValueError(f"{c.ticker}: no reported quarters")
    bs_gap = (q["assets"] - q["liabilities"] - q["equity"]).abs() / q["assets"]
    cash_change = q["cash"].diff()
    last = q.index[-1]
    ladder_age_days = (last - pd.Timestamp(c.maturities_date)).days if c.maturities_date else None
    core = ["revenue", "operating_income", "da", "net_income", "cfo", "capex", "cash", "total_debt", "equity"]
    recent = q.tail(RECENT_QUARTERS)
    return {
        "ticker": c.ticker,
        "quarters": len(q),
        "first": q.index[0].date().isoformat(),
        "last": last.date().isoformat(),
        "balance_sheet_identity_max_gap_pct": round(float(bs_gap.tail(RECENT_QUARTERS).max() * 100), 3),
        "core_completeness_last20_pct": round(float(recent[core].notna().mean().mean() * 100), 1),
        "missing_by_field_last20": {
            k: int(v) for k, v in recent[core + ["interest_expense"]].isna().sum().items() if v
        },
        "maturity_ladder_date": c.maturities_date,
        "maturity_ladder_stale": ladder_age_days is None or ladder_age_days > LADDER_STALE_DAYS,
        "cash_change_observed": int(cash_change.notna().sum()),
        "notes": c.notes,
    }
