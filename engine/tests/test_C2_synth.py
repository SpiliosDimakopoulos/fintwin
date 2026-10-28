"""Synthetic firm shared by the C2 tests (no network, no cache)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fintwin.data.facts import CompanyData


def quarters(n: int = 48, start: str = "2010-03-31", seed: int = 0, drop: tuple[int, ...] = ()) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="QE")
    t = np.arange(n)
    rev = 1000 * (1.01**t) * (1 + 0.05 * np.sin(t * np.pi / 2)) * (1 + 0.03 * rng.standard_normal(n))
    cfo = 0.15 * rev + 10 * rng.standard_normal(n)
    q = pd.DataFrame(
        {
            "revenue": rev,
            "cfo": cfo,
            "capex": 0.05 * rev,
            "cash": 400 + 5.0 * t,
            "short_investments": np.zeros(n),
            "total_debt": np.full(n, 1500.0),
            "dividends": np.full(n, 10.0),
            "buybacks": np.full(n, 5.0),
            "operating_income": 0.1 * rev,
            "da": 0.04 * rev,
            "interest_expense": np.full(n, 19.0),
            "net_income": 0.07 * rev,
            "assets": np.full(n, 5000.0),
            "liabilities": np.full(n, 3200.0),
            "current_assets": np.full(n, 1500.0),
            "current_liabilities": np.full(n, 800.0),
            "equity": np.full(n, 1800.0),
            "retained_earnings": np.full(n, 900.0),
        },
        index=pd.DatetimeIndex(idx, name="end"),
    )
    if drop:
        q = q.drop(q.index[list(drop)])
    return q


def company(q: pd.DataFrame, asof: str | None = None) -> CompanyData:
    return CompanyData("TEST", 1, "Test Co", asof, q, {}, [], None)


def split(q: pd.DataFrame, cut: str) -> tuple[CompanyData, pd.DataFrame]:
    """History known at `cut` (quarters ending 45+ days before it) and the full series."""
    hist = q[q.index <= pd.Timestamp(cut) - pd.Timedelta(days=45)]
    return company(hist, cut), q
