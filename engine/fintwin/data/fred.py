"""FRED macro series via the public CSV endpoint (no API key), cached on disk."""

from __future__ import annotations

import io
import math
import time
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .edgar import FrozenMiss, fetch, fill_only, frozen, write_atomic

VINTAGES = Path(__file__).with_name("gdp_vintages.csv")
# FRED GDPDEF (GDP implicit price deflator, 2017 = 100, quarterly, observations dated at the quarter's start),
# committed like the GDP vintages so frozen runs and tests need no fetch. Refresh: fred_series("GDPDEF") saved here.
DEFLATOR = Path(__file__).with_name("gdpdef.csv")
DEFLATOR_LAG = pd.Timedelta(days=60)  # a quarter's deflator is used 60 days after the quarter ends (advance release
# about 30 days after; 59 in the 2019 shutdown)

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "fred"
SERIES = {
    "short_rate": "DGS3MO",  # 3-month Treasury, % p.a.
    "long_rate": "DGS10",  # 10-year Treasury, % p.a.
    "credit_spread": "BAA10Y",  # Moody's Baa minus 10y Treasury, % p.a.
}


def fred_series(series_id: str, max_age_hours: float = 24) -> pd.Series:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{series_id}.csv"
    if frozen() and not path.exists():
        raise FrozenMiss(f"not in the frozen snapshot: {path.name}")
    if not path.exists() or (
        not (frozen() or fill_only()) and time.time() - path.stat().st_mtime > max_age_hours * 3600
    ):
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        write_atomic(path, fetch(url, sec=False).text.encode("utf-8"))
    df = pd.read_csv(io.StringIO(path.read_text(encoding="utf-8")))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna() / 100.0


def macro_quarterly(asof: str | None = None) -> pd.DataFrame:
    """Quarter-average rates in decimal form, truncated at `asof`."""
    df = pd.DataFrame({k: fred_series(v) for k, v in SERIES.items()})
    if asof:
        df = df[df.index <= pd.Timestamp(asof)]
    return df.resample("QE").mean().dropna()


def gdp_vintage(asof: str) -> pd.Series | None:
    """Nominal GDP as published on `asof` (Philadelphia Fed Real-Time Data Set, vintages from 2010).

    A quarterly vintage is dated about the middle of the quarter's second month; it is used from the 20th.
    """
    v = _vintages()
    if v is None:
        return None
    t = pd.Timestamp(asof)
    dated = {c: pd.Timestamp(int(c[:4]), 3 * int(c[-1]) - 1, 20) for c in v.columns}
    usable = [c for c, d in dated.items() if d <= t]
    if not usable:
        return None
    s = v[max(usable, key=lambda c: dated[c])].dropna()
    s.index = pd.PeriodIndex(s.index.str.replace(":", ""), freq="Q").to_timestamp(how="end").normalize()
    return s.astype(float)


@lru_cache(maxsize=1)
def _vintages() -> pd.DataFrame | None:
    return pd.read_csv(VINTAGES, index_col=0) if VINTAGES.exists() else None


# NBER turning points and the dates they were announced (nber.org/research/business-cycle-dating): (turning-point
# month, kind, announcement date), in date order. Every point whose announcement could fall after the first cutoffs
# is listed; earlier points were all announced long before any cutoff, so today's USREC is their real-time history.
NBER_ANNOUNCED = [
    ("2001-03-01", "peak", "2001-11-26"),
    ("2001-11-01", "trough", "2003-07-17"),
    ("2007-12-01", "peak", "2008-12-01"),
    ("2009-06-01", "trough", "2010-09-20"),
    ("2020-02-01", "peak", "2020-06-08"),
    ("2020-04-01", "trough", "2021-07-19"),
]


def _g2_active() -> bool:
    from ..stochastic import spec as S  # imports nothing from fintwin: no cycle

    return S.active("G2")


def realtime_usrec(usrec: pd.Series, asof: str) -> pd.Series:
    """USREC (monthly, 0/1) as a forecaster could know it on `asof` (REVISION_PLAN_5, G2).

    Only turning points announced by `asof` are known. From the first unannounced turning point on, every month keeps
    the regime the last announced point opened: USREC's own value in that point's month (0 in a peak month, 1 in a
    trough month, FRED's convention), so a recession dated but not yet ended is still running at the cutoff.
    """
    t = pd.Timestamp(asof)
    pending = [pd.Period(d, "M") for d, _, ann in NBER_ANNOUNCED if pd.Timestamp(ann) > t]
    if not pending:
        return usrec
    first = min(pending)
    months = usrec.index.to_period("M")
    at_first = usrec[months == first]
    if at_first.empty:  # the turning point lies after the series' end: nothing to override
        return usrec
    out = usrec.copy()
    out[months > first] = float(at_first.iloc[0])
    return out


@lru_cache(maxsize=1)
def _deflator() -> pd.Series:
    df = pd.read_csv(DEFLATOR)
    s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(), index=pd.to_datetime(df.iloc[:, 0]))
    return s.dropna().resample("QE").last().dropna()


def deflator_to_2014(asof: str | None) -> float:
    """Factor turning dollars of the cutoff into 2014 dollars: the 2014 average GDP deflator over the latest one
    published by `asof` (today's revised values; no vintage file exists for the deflator). The 2014 level is a fixed
    base, a unit choice, not information about the cutoff. `asof=None`: the latest value."""
    d = _deflator()
    base = float(d[d.index.year == 2014].mean())
    known = d if asof is None else d[d.index + DEFLATOR_LAG <= pd.Timestamp(asof)]
    if known.empty:
        raise ValueError(f"no GDP deflator published by {asof}")
    return base / float(known.iloc[-1])


def recession_regime(asof: str | None = None, realtime: bool | None = None) -> dict:
    """Markov recession regime from NBER-dated US recessions (FRED USREC) and nominal GDP, post-1947.

    Returns quarterly entry hazard, exit probability, the nominal-GDP growth shortfall per recession quarter,
    whether the economy is in recession at `asof`, and quarterly YoY nominal GDP growth for beta estimation.
    `realtime` (default: fix G2 of the active specification) uses only the turning points announced by `asof`.
    """
    usrec = fred_series("USREC") * 100
    if asof and (_g2_active() if realtime is None else realtime):
        usrec = realtime_usrec(usrec, asof)
    rec = usrec.resample("QE").max()
    gdp = (fred_series("GDP") * 100).resample("QE").last()
    vint = gdp_vintage(asof) if asof else None
    if vint is not None:  # point in time: the GDP history as it was published on the cutoff, not today's revision
        gdp = vint
    if asof:
        rec, gdp = rec[rec.index <= pd.Timestamp(asof)], gdp[gdp.index <= pd.Timestamp(asof)]
    rec = rec[rec.index >= "1947-01-01"]
    starts = int(((rec == 1) & (rec.shift(1) == 0)).sum())
    in_rec = float(rec.sum())
    yoy = gdp.apply(math.log).diff(4).dropna()
    r = rec.reindex(yoy.index, method="nearest")
    shortfall_q = float(yoy[r == 0].mean() - yoy[r == 1].mean()) / 4.0
    return {
        "hazard": starts / max(len(rec) - in_rec, 1.0),
        "exit": starts / max(in_rec, 1.0),
        "gdp_shortfall_q": shortfall_q,
        "in_recession_now": bool(rec.iloc[-1] == 1) if len(rec) else False,
        "gdp_yoy": yoy,
        "n_recessions": starts,
    }
