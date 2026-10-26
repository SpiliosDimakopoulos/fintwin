"""The company universe and sector norms.

Universe: current S&P 500 constituents outside Financials and Real Estate (bank and REIT balance sheets do not
fit a corporate cash-flow model), one share class per company, plus a few former members that matter for the
COVID test. Note the survivorship bias this implies for backtests: today's index members are, by construction,
companies that survived to today.

Sector tolerance: leverage that would be alarming for a software company is normal for a regulated utility.
For the health score only, each GICS sector gets a tolerance factor = its median net debt / EBITDA relative to
the universe median, clipped to [1, 2]. It is derived from the data, not hand-tuned.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
UNIVERSE_CSV = HERE / "data" / "universe_sp500.csv"
NORMS_JSON = HERE / "data" / "sector_norms.json"

# Former index members or notable non-members kept for the 2020 cross-section (GICS classification).
EXTRAS = [
    ("AAL", "American Airlines Group", "Industrials", "Passenger Airlines"),
    ("M", "Macy's", "Consumer Discretionary", "Broadline Retail"),
    ("KSS", "Kohl's", "Consumer Discretionary", "Broadline Retail"),
    ("WYNN", "Wynn Resorts", "Consumer Discretionary", "Casinos & Gaming"),
    ("INTC", "Intel", "Information Technology", "Semiconductors"),
]


@lru_cache(maxsize=1)
def universe() -> pd.DataFrame:
    """Load, augment, and return the sorted company universe DataFrame."""
    u = pd.read_csv(UNIVERSE_CSV)
    extra = pd.DataFrame(EXTRAS, columns=["ticker", "name", "sector", "industry"])
    extra = extra[~extra["ticker"].isin(u["ticker"])]
    return pd.concat([u, extra], ignore_index=True).sort_values("ticker").reset_index(drop=True)


def tickers() -> list[str]:
    """Return the company tickers in the configured universe."""
    return universe()["ticker"].tolist()


def classify(ticker: str) -> tuple[str, str]:
    """(GICS sector, GICS sub-industry) for a ticker; empty strings if unknown (live API tickers)."""
    if ticker.upper().startswith("CIK"):  # EDGAR research universe: Fama-French 12 industry from the SIC code
        u = _edgar()
        hit = u[u["key"] == ticker.upper()]
        return (str(hit["industry"].iloc[0]), "") if len(hit) else ("", "")
    if "~" in ticker:  # delisted 2020 Chapter 11 filers used in the research sample
        bk = pd.read_csv(Path(__file__).with_name("data") / "bankruptcies_2020.csv")
        hit = bk[bk["key"] == ticker.upper()]
        return (str(hit["sector"].iloc[0]), "") if len(hit) else ("", "")
    u = universe()
    row = u[u["ticker"] == ticker.upper()]
    if row.empty:
        return "", ""
    return str(row["sector"].iloc[0]), str(row["industry"].iloc[0])


@lru_cache(maxsize=1)
def _edgar() -> pd.DataFrame:
    return pd.read_csv(HERE / "data" / "universe_edgar.csv")


@lru_cache(maxsize=1)
def _norms() -> dict:
    return json.loads(NORMS_JSON.read_text(encoding="utf-8")) if NORMS_JSON.exists() else {}


def sector_tolerance(ticker: str) -> float:
    """Return the sector leverage tolerance for ``ticker``, defaulting to 1.0."""
    return float(_norms().get("tolerance", {}).get(classify(ticker)[0], 1.0))


def compute_norms(leverage: dict[str, float]) -> dict:
    """leverage: ticker -> net debt / EBITDA (positive EBITDA only). Writes and returns the norms table."""
    df = pd.DataFrame({"ticker": list(leverage), "nd_ebitda": list(leverage.values())})
    df["sector"] = [classify(t)[0] for t in df["ticker"]]
    df = df[(df["sector"] != "") & df["nd_ebitda"].between(-5, 15)]
    overall = float(df["nd_ebitda"].median())
    by = df.groupby("sector")["nd_ebitda"].agg(["median", "count"])
    tol = {
        s: (round(float(min(max(r["median"] / max(overall, 0.5), 1.0), 2.0)), 3) if r["count"] >= 3 else 1.0)
        for s, r in by.iterrows()
    }
    out = {
        "universe_median_nd_ebitda": round(overall, 3),
        "sector_median_nd_ebitda": {s: round(float(r["median"]), 3) for s, r in by.iterrows()},
        "tolerance": tol,
        "n": int(len(df)),
    }
    NORMS_JSON.write_text(json.dumps(out, indent=1), encoding="utf-8")
    _norms.cache_clear()
    return out
