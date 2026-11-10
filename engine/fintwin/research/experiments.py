"""Per-company research experiments behind the paper (one JSON per company, merged by `stats.py`).

Three designs, all strictly point-in-time (the twin and every benchmark see only filings available at the cutoff):

* covid    - twins frozen on 20 Feb 2020 under several scenarios and with each feedback loop switched off, the
             accounting benchmarks an analyst would have computed on the same day, and realized 2020-21 outcomes.
* panel    - every 15 February 2013-2023: the twin's baseline verdict, the same benchmarks, and distress
             outcomes over the following eight reported quarters.
* forecast - every 15 February 2013-2025: four-quarter predictive distributions of revenue and cash from the twin,
             a seasonal random walk and an exponential-smoothing state-space model (ETS), scored by the CRPS.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import warnings
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..backtest.batch import (
    _baseline,
    _realized,
    data_legacy,
    filed_for,
    first_filed,
    following,
    rw_empirical,
    window_ok,
)
from ..backtest.scoring import crps_gaussian, crps_samples
from ..data.facts import CompanyData, contiguous, contiguous_mask, load_company
from ..data.fred import macro_quarterly as _macro_quarterly
from ..model.ratings import rating_rank
from ..model.ratings import spreads_asof as _spreads_asof
from ..model.sd_model import simulate
from ..scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario
from ..stochastic import calibrate as _cal_mod
from ..stochastic.calibrate import FIXED_SHARE_PRIOR, SPECIFIED_FIXED_SHARE_PRIOR
from ..stochastic.calibrate import calibrate as _calibrate
from ..stochastic.mc import summarize
from ..stochastic.shocks import draw_shocks
from ..universe import classify

try:  # workstream B1's switchboard; until it is merged, the local fallback below reads the same variables
    from ..stochastic import spec as _spec_mod  # type: ignore[attr-defined]
except ImportError:
    _spec_mod = None

# ---------------------------------------------------------------- specification (REVISION_PLAN_3 §0.2)
SPECS = ("v2-pre", "v2-rev", "v3")
MODEL_FIXES = tuple(f"F{i}" for i in range(1, 15))
# ids decided in this module: E1 (point = median of path totals) and the opt-in real-time recession state (SW17)
LOCAL_FIXES = {"E1": ("v3",), "SW17": ()}
# the cumulative ladder, in the pre-specified order; "+F3" is the full v3 (which also carries F6-F14 and E1)
LADDER: list[tuple[str, dict[str, str]]] = [
    ("v2-pre", {"FINTWIN_SPEC": "v2-pre"}),
    ("v2-pre+F5", {"FINTWIN_SPEC": "v2-pre", "FINTWIN_FIXES": "F5"}),
    ("v2-pre+F5+F4", {"FINTWIN_SPEC": "v2-pre", "FINTWIN_FIXES": "F5,F4"}),
    ("v2-pre+F5+F4+F1", {"FINTWIN_SPEC": "v2-pre", "FINTWIN_FIXES": "F5,F4,F1"}),
    ("v2-pre+F5+F4+F1+F2", {"FINTWIN_SPEC": "v2-pre", "FINTWIN_FIXES": "F5,F4,F1,F2"}),
    ("v3", {"FINTWIN_SPEC": "v3"}),
    ("v2-rev", {"FINTWIN_SPEC": "v2-rev"}),
]


def spec_name() -> str:
    # Unset means the same default as stochastic/spec.py, so labels and the fixes actually applied never disagree.
    default = getattr(_spec_mod, "DEFAULT_SPEC", "v3") if _spec_mod is not None else "v3"
    s = (os.environ.get("FINTWIN_SPEC") or default).strip()
    if s not in SPECS:
        raise ValueError(f"FINTWIN_SPEC={s!r}: expected one of {SPECS}")
    return s


def _fixes_env() -> list[str] | None:
    raw = os.environ.get("FINTWIN_FIXES")
    if raw is None or not raw.strip():
        return None
    return [x.strip().upper().removeprefix("MM-") for x in raw.split(",") if x.strip()]


def fix_active(fid: str) -> bool:
    """Is fix `fid` on? FINTWIN_FIXES, when set, replaces the specification's default set."""
    fid = fid.upper().removeprefix("MM-")
    if fid in MODEL_FIXES and _spec_mod is not None and hasattr(_spec_mod, "active"):
        return bool(_spec_mod.active(fid))
    fx = _fixes_env()
    if fx is not None:
        return fid in fx
    if fid in LOCAL_FIXES:
        return spec_name() in LOCAL_FIXES[fid]
    return spec_name() == "v3" and fid in MODEL_FIXES


def active_fixes() -> list[str]:
    return [f for f in (*MODEL_FIXES, *LOCAL_FIXES) if fix_active(f)]


def spec_label() -> str:
    """Name of the cache directory of this specification: the spec, plus the explicit fix list if one is set."""
    fx = _fixes_env()
    label = spec_name() + ("".join(f"+{f}" for f in fx) if fx is not None else "")
    if os.environ.get("FINTWIN_SELECTION"):
        label += "-wf"  # second pass: tau / lambda chosen walk-forward
    if data_legacy():
        label += "-legacydata"
    return re.sub(r"[^A-Za-z0-9+._-]", "_", label)


def research_prior() -> float:
    """Mean of the fixed-cost prior: the pre-specified 35%, or the revised 5% of revision 2 under v2-rev."""
    return FIXED_SHARE_PRIOR if spec_name() == "v2-rev" else SPECIFIED_FIXED_SHARE_PRIOR


def spec_record() -> dict:
    sel = os.environ.get("FINTWIN_SELECTION")
    return {
        "name": spec_name(),
        "label": spec_label(),
        "fixes": active_fixes(),
        "fixes_env": os.environ.get("FINTWIN_FIXES"),
        "prior": research_prior(),
        "selection": _digest(Path(sel)) if sel else None,
        "data_legacy": data_legacy(),
        "b1_spec": _spec_mod is not None,
    }


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else None


# ---------------------------------------------------------------- failures are counted, not swallowed (SW-3)
class Failures:
    """Attempts and failures by stage and exception type, so attrition is reported instead of silently shrinking a
    sample. `skip` records data-driven exclusions (gaps, short series), which are not errors."""

    def __init__(self) -> None:
        self.d: dict[str, dict] = {}

    def _slot(self, where: str) -> dict:
        return self.d.setdefault(where, {"n": 0, "failed": {}, "skipped": {}})

    def tried(self, where: str) -> None:
        self._slot(where)["n"] += 1

    def fail(self, where: str, why: BaseException | str) -> None:
        k = why if isinstance(why, str) else type(why).__name__
        f = self._slot(where)["failed"]
        f[k] = f.get(k, 0) + 1

    def skip(self, where: str, why: str) -> None:
        s = self._slot(where)["skipped"]
        s[why] = s.get(why, 0) + 1

    def to_dict(self) -> dict:
        return self.d


def failure_summary(shards: list[dict]) -> dict:
    """Pool the shards' failure counts: attempts, failures by type and the failed share, per stage."""
    out: dict[str, dict] = {}
    for r in shards:
        for where, s in (r.get("failures") or {}).items():
            o = out.setdefault(where, {"n": 0, "failed": {}, "skipped": {}})
            o["n"] += int(s.get("n", 0))
            for kind in ("failed", "skipped"):
                for k, v in (s.get(kind) or {}).items():
                    o[kind][k] = o[kind].get(k, 0) + int(v)
    for o in out.values():
        o["failed_share"] = sum(o["failed"].values()) / o["n"] if o["n"] else 0.0
    return out


# ---------------------------------------------------------------- inputs read once per cutoff (SW-18)
@lru_cache(maxsize=64)
def _macro_cached(asof: str | None) -> pd.DataFrame:
    return _macro_quarterly(asof)


def macro_quarterly(asof: str | None = None) -> pd.DataFrame:
    """The FRED quarterly frame at `asof`, parsed once per cutoff (a copy, so callers cannot alter the cache)."""
    return _macro_cached(asof).copy()


@lru_cache(maxsize=64)
def _spreads_cached(asof: str | None) -> tuple | None:
    s = _spreads_asof(asof)
    return None if s is None else tuple(s)


def spreads_asof(asof: str | None) -> list[float] | None:
    s = _spreads_cached(asof)
    return None if s is None else list(s)


COVID_CUT = "2020-02-20"
PANEL_ORIGINS = [f"{y}-02-15" for y in range(2013, 2025)]
FORECAST_ORIGINS = [f"{y}-02-15" for y in range(2013, 2026)]
SCENARIOS = ["base", "rates_200", "sales_20", "recession", "pandemic", "credit_crunch"]
ABLATIONS: dict[str, dict] = {
    "full": {},
    "no_r1": {"loop_r1": False},
    "no_r2": {"loop_r2": False},
    "no_b1": {"cut_capex": False, "cut_payouts": False},
    "no_b2": {"cut_costs": False},
    "no_loops": {"loop_r1": False, "loop_r2": False, "cut_capex": False, "cut_payouts": False, "cut_costs": False},
}
H_FC = 4
FREEZE = PRESETS["pandemic"]["knobs"]
DEPTHS = (0.0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6, 0.8)
DEMAND = {"sales_duration": 3, "sales_recovery": 8, "spread_bp": 200, "spread_duration": 4}


def data_vintage(cik: int) -> dict:
    """Which data the run used: the hash of the cached companyfacts file and the filings read by the XBRL fallback."""
    import hashlib

    from ..data import edgar
    from ..data.facts import company_facts

    path = edgar.CACHE_DIR / f"companyfacts_{cik:010d}.json.gz"
    raw = company_facts(cik)
    return {
        "facts_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        "xbrl_fallback": list(raw.get("_fallback", [])),
    }


# ---------------------------------------------------------------- walk-forward tau (MM-F1) and lambda (MM-F3)
# Grids over B1's prior s.d. multiplier `prior_tau` and partial-adjustment speed `fixed_adj_lambda` (per quarter).
# B1's own grids take precedence when it defines them.
TAU_GRID: tuple[float, ...] = tuple(getattr(_cal_mod, "TAU_GRID", (0.05, 0.10, 0.15, 0.25, 0.50)))
LAMBDA_GRID: tuple[float, ...] = tuple(getattr(_cal_mod, "LAMBDA_GRID", (0.0, 0.10, 0.20, 0.35, 0.50)))
WF_KEYS = {"tau": "prior_tau", "lam": "fixed_adj_lambda"}
WF_LAG = 3  # revision 2's rule: test year Y uses cutoffs up to Y-3, whose eight outcome quarters were all reported
WF_MIN_PAST = 500


def wf_grid() -> dict[str, dict]:
    """Calibration variants the shard evaluates so that tau and lambda can be chosen on earlier years only. Each grid
    is one-dimensional around B1's defaults (lambda is searched at the default tau, and vice versa)."""
    g: dict[str, dict] = {}
    if fix_active("F1"):
        g |= {f"tau_{t:.2f}": {WF_KEYS["tau"]: float(t)} for t in TAU_GRID}
    if fix_active("F3"):
        g |= {f"lam_{v:.2f}": {WF_KEYS["lam"]: float(v)} for v in LAMBDA_GRID}
    return g


def walk_forward_select(
    years: np.ndarray, real: np.ndarray, preds: dict[str, np.ndarray], lag: int = WF_LAG, min_past: int = WF_MIN_PAST
) -> dict[int, dict]:
    """For each test year Y, the grid value with the lowest median absolute error over firm-years of cutoffs <= Y-lag.

    Years with fewer than `min_past` usable earlier firm-years get no selection (the default applies). Ties go to the
    first value in grid order, so the result does not depend on dictionary order of equal errors.
    """
    years = np.asarray(years)
    real = np.asarray(real, float)
    out: dict[int, dict] = {}
    for y in sorted(set(years.tolist())):
        past = years <= y - lag
        err: dict[str, float] = {}
        n = 0
        for name, x in preds.items():
            x = np.asarray(x, float)
            m = past & np.isfinite(x) & np.isfinite(real)
            n = max(n, int(m.sum()))
            if m.sum() >= min_past:
                err[name] = float(np.median(np.abs(x[m] - real[m])))
        if not err:
            continue
        best = min(err, key=lambda k: (err[k], list(preds).index(k)))
        out[int(y)] = {"choice": best, "n_past": n, "median_ae": err}
    return out


def select_from_panel(rows: list[dict]) -> dict:
    """Selection table from shard panel rows: {"tau": {year: value}, "lambda": {...}} plus the evidence."""
    years, real, grid = [], [], []
    for r in rows:
        st = r.get("structural") or {}
        if st.get("real_cfo") is None or not st.get("grid"):
            continue
        years.append(int(str(r["origin"])[:4]))
        real.append(float(np.sum(st["real_cfo"])))
        # score each value with the specification's own point forecast (E1 total, or the v2 sum of medians)
        point = "cfo" if st.get("e1", True) else "cfo_sm"
        grid.append({k: {"cfo": (v or {}).get(point)} for k, v in st["grid"].items()})
    out: dict = {"rule": f"Y-{WF_LAG}", "min_past": WF_MIN_PAST, "n_rows": len(years)}
    for fam, key in (("tau", "tau"), ("lam", "lambda")):
        names = sorted({k for g in grid for k in g if k.startswith(fam + "_")}, key=lambda k: float(k.split("_")[1]))
        if not names:
            continue
        preds = {k: np.array([(g.get(k) or {}).get("cfo", np.nan) for g in grid], float) for k in names}
        sel = walk_forward_select(np.array(years), np.array(real), preds)
        out[key] = {str(y): float(s["choice"].split("_")[1]) for y, s in sel.items()}
        out[f"{key}_evidence"] = {str(y): s for y, s in sel.items()}
    return out


def select_from_shards(cache: Path) -> dict:
    rows = []
    for f in sorted(cache.glob("*.json")):
        rows += json.loads(f.read_text(encoding="utf-8")).get("panel", [])
    return select_from_panel(rows)


@lru_cache(maxsize=4)
def _selection(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def selected_assumptions(asof: str | None) -> dict:
    """tau / lambda selected walk-forward for the cutoff's year (FINTWIN_SELECTION points at the table); {} otherwise."""
    path = os.environ.get("FINTWIN_SELECTION")
    if not path or not asof:
        return {}
    sel, y = _selection(path), str(pd.Timestamp(asof).year)
    out = {}
    for key, name in (("tau", WF_KEYS["tau"]), ("lambda", WF_KEYS["lam"])):
        v = (sel.get(key) or {}).get(y)
        if v is not None:
            out[name] = float(v)
    return out


# NBER announcement dates of the turning points after 2008 (nber.org/research/business-cycle-dating): before a
# trough is announced, a forecaster at the cutoff still believes the economy is in recession (SW-17).
NBER_ANNOUNCED = [("2007-12-01", "peak", "2008-12-01"), ("2009-06-01", "trough", "2010-09-20"),
                  ("2020-02-01", "peak", "2020-06-08"), ("2020-04-01", "trough", "2021-07-19")]  # fmt: skip


def realtime_recession(asof: str) -> bool | None:
    """In recession as known on `asof` from announced turning points only (None before 2008: not tracked)."""
    t = pd.Timestamp(asof)
    known = [(kind, pd.Timestamp(date)) for date, kind, ann in NBER_ANNOUNCED if pd.Timestamp(ann) <= t]
    if t < pd.Timestamp("2008-12-01"):
        return None
    return bool(known) and known[-1][0] == "peak"


def calibrate(hist: CompanyData, macro: pd.DataFrame, horizon: int = 12, assumptions: dict | None = None) -> dict:
    """Calibration with the rating-spread table that was published at the cutoff (the product uses January 2026's)."""
    # research runs keep the pre-specified 35% prior (5% under v2-rev); tau / lambda chosen walk-forward if a table
    # is given, otherwise B1's defaults
    a = {"fixed_share_prior": research_prior(), **selected_assumptions(hist.asof), **(assumptions or {})}
    p = _calibrate(hist, macro, horizon, a)
    pit = spreads_asof(hist.asof)
    if pit is not None:
        p["spreads"] = pit
    if fix_active("SW17") and hist.asof:
        rt = realtime_recession(hist.asof)
        if rt is not None:
            p["rec_state0"] = 1.0 if rt else 0.0
    return p


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def usable(hist: CompanyData, asof: str) -> bool:
    """16 consecutive reported quarters of history (D1: gap rows are calendar quarters without a filing, so the row
    count is not enough), and a company that was still filing: the last known quarter is recent.

    Without the second condition a company that stopped filing in 2016 would enter a 2019 cutoff with stale data.
    """
    q = hist.quarters
    return window_ok(q, 16) and (pd.Timestamp(asof) - q.index[-1]).days <= 200


def _ttm(q: pd.DataFrame, col: str) -> float:
    """Sum of the last four quarters of `col`; NaN unless they are four consecutive quarters with `col` reported."""
    s = q[col].tail(4)
    if data_legacy():
        return float(s.sum()) if s.notna().sum() == 4 else np.nan
    return float(s.sum()) if window_ok(q, 4) and window_ok(q, 4, col) else np.nan


def _following(
    full: pd.DataFrame, last: pd.Timestamp, n: int, fails: Failures | None = None, where: str = ""
) -> pd.DataFrame:
    """The next `n` quarters after `last`, or an empty frame if any is unreported or a gap row (SW-4, D1); the reason
    is recorded as an exclusion under `where`, never silently."""
    nxt, why = following(full, last, n)
    if why and fails is not None:
        fails.skip(where, why)
    return nxt


def health_at_open(p: dict) -> float:
    """The twin's health formula evaluated on the opening balance sheet, without any simulation.

    Mirrors the scoring block of model.sd_model (runway, coverage rating, leverage, Altman Z'') with no sector
    norms, so comparing it with the simulated score isolates what the simulation adds to the formula.
    """
    ebit, ebitda = float(np.sum(p["ebit_ttm0"])), float(np.sum(p["ebitda_ttm0"]))
    interest = float(np.sum(p["interest_ttm0"]))
    icr = ebit / max(interest, 1e-9)
    access = 1.0 if icr >= 1.5 else 0.6 if icr >= 0.8 else 0.3
    burn = max(p["F"] + interest / 4 + p["maturities_q"][0] * (1 - access), 1e-9)
    s_liq = float(np.clip((p["cash0"] + p["revolver_cap"]) / burn / 8.0, 0.0, 1.0)) * 100
    s_cov = float(rating_rank(np.array([icr]))[0]) / 14.0 * 100
    nd = (p["debt0"] - p["cash0"]) / ebitda if ebitda > 0 else 99.0
    s_lev = float(np.clip((6.0 - nd) / 6.0, 0.0, 1.0)) * 100 if ebitda > 0 else 0.0
    assets = p["cash0"] + p["ar0"] + p["inv0"] + p["ppe0"] + p["other_net0"] + p["other_liab0"]
    liabilities = max(assets - p["equity0"], 1e-9)
    wc = p["cash0"] + p["ar0"] + p["inv0"] - p["ap0"] - p["def0"] + p["wc_other0"]
    z = (6.56 * wc + 3.26 * p["retained0"] + 6.72 * ebit) / max(assets, 1e-9) + 1.05 * p["equity0"] / liabilities
    s_solv = float(np.clip((z - 1.1) / 1.5, 0.0, 1.0)) * 100
    return 0.3 * s_liq + 0.3 * s_cov + 0.2 * s_lev + 0.2 * s_solv


def features(c: CompanyData, p: dict) -> dict:
    """Accounting benchmarks on the information set of the cutoff (higher-is-riskier orientation is set in stats)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return _features(c, p)


def _features(c: CompanyData, p: dict) -> dict:
    # numpy scalars throughout: a zero balance-sheet item gives inf/NaN (then None), not a ZeroDivisionError that
    # would turn the whole company into an error entry (SW-15)
    F = np.float64
    q = c.quarters
    last = q.iloc[-1]
    rev = F(_ttm(q, "revenue"))
    ebit = F(np.sum(p["ebit_ttm0"]))
    ebitda = F(np.sum(p["ebitda_ttm0"]))
    interest = F(np.sum(p["interest_ttm0"]))
    ni = F(_ttm(q, "net_income"))
    if data_legacy():
        ni_prev = F(q["net_income"].iloc[-8:-4].sum()) if len(q) >= 8 else F(np.nan)
    else:  # the four quarters before the TTM window, consecutive and reported (a gap row would sum as 0)
        ni_prev = F(q["net_income"].iloc[-8:-4].sum()) if window_ok(q, 8, "net_income") else F(np.nan)
    cfo = F(_ttm(q, "cfo"))
    cash = F(np.nansum([last["cash"], last["short_investments"]]))
    debt = F(last["total_debt"]) if np.isfinite(last["total_debt"]) else F(0.0)
    ta, tl, ca, cl = (F(last[k]) for k in ("assets", "liabilities", "current_assets", "current_liabilities"))
    eq, re = F(last["equity"]), F(last["retained_earnings"])
    if not np.isfinite(tl) and np.isfinite(ta) and np.isfinite(eq):
        tl = ta - eq
    wc = ca - cl
    # Altman (1968) Z'' for non-manufacturers (book equity); Ohlson (1980) O-score; Zmijewski (1984)
    z2 = 6.56 * wc / ta + 3.26 * re / ta + 6.72 * ebit / ta + 1.05 * eq / tl
    o = (
        -1.32
        - 0.407 * np.log(max(ta, 1.0) / 1e6)
        + 6.03 * tl / ta
        - 1.43 * wc / ta
        + 0.0757 * cl / ca
        - 1.72 * float(tl > ta)
        - 2.37 * ni / ta
        - 1.83 * cfo / tl
        + 0.285 * float(ni < 0 and ni_prev < 0)
        - 0.521 * (ni - ni_prev) / max(abs(ni) + abs(ni_prev), 1e-9)
    )
    zm = -4.336 - 4.513 * ni / ta + 5.679 * tl / ta + 0.004 * ca / cl
    # an analyst's static stress test of the same scenario: liquidity / cash needs over a three-quarter freeze,
    # with fixed costs, interest and maturities due, and the contribution of the revenue that remains
    rev_q = rev / 4
    need_q = max(p["F"] + interest / 4 - (1 - p["v"]) * (1 - FREEZE["sales_depth"]) * rev_q, 0.0)
    due = float(np.sum(p["maturities_q"][:3]))
    static = (cash + p["revolver_cap"]) / max(3 * need_q + due, 1e-9)
    yoy = np.log(q["revenue"] / q["revenue"].shift(4)).dropna().tail(20)
    fcf = _ttm(q, "cfo") - _ttm(q, "capex")
    return {
        "fcf_margin": _f(fcf / rev),
        "capex_rev": _f(_ttm(q, "capex") / rev),
        "health_t0": _f(health_at_open(p)),
        "z2": _f(z2),
        "o_score": _f(o),
        "zmijewski": _f(zm),
        "nd_ebitda": _f((debt - cash) / ebitda) if ebitda > 0 else 20.0,
        "icr": _f(np.clip(ebit / interest, -10, 100)) if interest > 0 else 100.0,
        "cash_rev": _f(cash / rev),
        "current_ratio": _f(ca / cl),
        "debt_assets": _f(debt / ta),
        "due_cash": _f(float(np.sum(p["maturities_q"][:4])) / max(cash, 1e-9)),
        "rev_vol": _f(yoy.std()),
        "fixed_share": _f(4 * p["F"] / max(4 * p["F"] + p["v"] * rev, 1e-9)),
        "static_cover": _f(min(static, 50.0)),
        "log_rev": _f(np.log(max(rev, 1.0))),
    }


SHORTFALL_Q = (4, 8)


def shortfall(sim: dict, p: dict, k: int) -> float:
    """P(cash + undrawn revolver < 0 in some quarter within the first k), E12. The undrawn line is the simulated
    capacity (`revolver_cap` path when the model reports one, e.g. a facility cut on a covenant breach) less draws."""
    cap = sim.get("revolver_cap", p["revolver_cap"])
    cap = np.asarray(cap, float)[:, :k] if np.ndim(cap) == 2 else float(cap)
    undrawn = np.maximum(cap - sim["revolver"][:, :k], 0.0)
    return float(np.mean((sim["cash"][:, :k] + undrawn < 0).any(1)))


def _run(p: dict, knobs: dict, levers: dict, n: int, horizon: int, seed: int) -> dict:
    eps = draw_shocks(p, n, horizon, seed=seed)
    sim = simulate(p, build_scenario(knobs, horizon), eps, {**DEFAULT_LEVERS, **levers})
    sm = summarize(sim)
    out = {"health": sm["health_score"], "p_breach": sm["p_breach"], "health_p10": sm["health_p10"]}
    out |= {f"short{k}": shortfall(sim, p, k) for k in SHORTFALL_Q if k <= horizon}
    return out


def covid(ticker: str, full: pd.DataFrame | None, fails: Failures | None = None) -> dict | None:
    hist = load_company(ticker, asof=COVID_CUT)
    if not usable(hist, COVID_CUT):
        return None
    p = calibrate(hist, macro_quarterly(COVID_CUT), 8)
    tol = p.get("sector_tol", 1.0)
    raw = {**p, "sector_tol": 1.0}  # primary analysis: no sector norms (those are estimated from later data)
    out: dict = {
        "ticker": ticker,
        "name": hist.name,
        "sector": classify(ticker)[0],
        "last_quarter": str(hist.quarters.index[-1].date()),
    }
    out["scenarios"] = {k: _run(raw, PRESETS[k]["knobs"], {}, 2000, 8, 7) for k in SCENARIOS}
    out["ablations"] = {k: _run(raw, FREEZE, lv, 2000, 8, 7) for k, lv in ABLATIONS.items()}
    # loops act through trailing coverage and the maturity wall, so they get more room over three years
    p12 = {**calibrate(hist, macro_quarterly(COVID_CUT), 12), "sector_tol": 1.0}
    out["ablations_h12"] = {k: _run(p12, FREEZE, lv, 2000, 12, 7) for k, lv in ABLATIONS.items()}
    out["sector_adjusted"] = _run({**p, "sector_tol": tol}, FREEZE, {}, 2000, 8, 7)
    out["features"] = features(hist, p)
    out["realized"] = covid_outcomes(hist, full, fails) if full is not None else {}
    out["structural"] = structural(hist, raw, full, macro_quarterly(COVID_CUT), fails=fails) if full is not None else {}
    # the stress score under a demand freeze of each depth: `stats` evaluates it at the company's industry shock
    out["depth_grid"] = {f"{d:.2f}": _run(raw, {**FREEZE, "sales_depth": d}, {}, 1000, 8, 7)["health"] for d in DEPTHS}
    return out


# Judgement calls varied in the sensitivity analysis: calibration assumptions (`calib`) and model assumptions (`p`).
SENSITIVITY: dict[str, dict] = {
    "revolver_low": {"calib": {"revolver_share": 0.04}},
    "revolver_high": {"calib": {"revolver_share": 0.15}},
    "fixed_prior_low": {"calib": {"fixed_share_prior": 0.20}},
    "fixed_prior_high": {"calib": {"fixed_share_prior": 0.50}},
    "prior_weak": {"calib": {"prior_weight": 0.5}},
    "prior_strong": {"calib": {"prior_weight": 8.0}},
    "no_shrinkage": {"calib": {"growth_shrink": 1.0, "beta_shrink": 1.0}},
    # grid of fixed-cost priors (weight 2, as specified) and the unshrunk estimate, from which `stats` selects a revised
    # specification walk-forward, globally and by industry
    **{
        f"prior_share_{int(x * 100):02d}": {"calib": {"fixed_share_prior": x}}
        for x in (0.05, 0.10, 0.15, 0.25, 0.30, 0.45)
    },
    "prior_none": {"calib": {"prior_weight": 0.0}},
    "access_strict": {"p": {"access_icr": (2.5, 1.5)}},
    "access_lenient": {"p": {"access_icr": (1.0, 0.5), "access_levels": (0.8, 0.5)}},
    "cuts_fast": {"p": {"cut_delay": 1, "cut_speed": 0.08, "cut_floor": 0.75}},
    "spreads_2026": {"p": {}},  # the product's January 2026 rating table instead of the table published at the cutoff
    "spreads_baa": {"p": {}},  # the 2026 table rescaled by the Baa spread known at the cutoff
}
EVENTS = ("cash_half", "debt_raise", "div_cut", "capex_cut")


def _spread_scale(asof: str) -> float:
    """Rating spreads are Damodaran's January 2026 table; rescale them by the Baa-Treasury spread known at `asof`."""
    from ..data.fred import fred_series

    s = fred_series("BAA10Y")
    ref = float(s[(s.index >= "2025-12-01") & (s.index <= "2026-01-31")].mean())
    now = float(s[s.index <= pd.Timestamp(asof)].tail(63).mean())
    return float(np.clip(now / ref, 0.5, 3.0)) if np.isfinite(now) and ref > 0 else 1.0


def _margin(pre: pd.DataFrame, cash: pd.Series, k: int) -> float:
    c, r = cash.tail(k), pre["revenue"].tail(k)
    if c.notna().sum() < k or r.notna().sum() < k or r.sum() <= 0 or not window_ok(pre, k):
        return np.nan
    return float(c.sum() / r.sum())


def _cash_rule(pre: pd.DataFrame, cash: pd.Series, dynamic: bool) -> np.ndarray | None:
    """Per-company regression of quarterly cash flow on revenue (and its change) over the last 16 quarters.

    The static version is operating leverage without simulation (cash = a + b * revenue, i.e. a fixed and a
    variable part); the dynamic version adds working-capital timing (cash also responds to the change in revenue).
    """
    d = pd.DataFrame({"rev": pre["revenue"], "y": cash})
    d["drev"] = d["rev"].diff()
    d = d.dropna().tail(16)
    if len(d) < 12:
        return None
    X = np.column_stack([np.ones(len(d)), d["rev"], *([d["drev"]] if dynamic else [])])
    return np.linalg.lstsq(X, d["y"].to_numpy(float), rcond=None)[0]


def _apply_rule(beta: np.ndarray | None, rev: np.ndarray, rev_prev: float) -> np.ndarray:
    if beta is None:
        return np.full(len(rev), np.nan)
    out = beta[0] + beta[1] * rev
    if len(beta) == 3:
        out = out + beta[2] * np.diff(np.concatenate([[rev_prev], rev]))
    return out


def _probs(sim: dict, p: dict, n_q: int, rev_ttm: float, capex_pre: float) -> dict:
    """Share of simulated paths on which each liquidity event happens (same definitions as the realized events)."""
    cash = sim["cash"][:, :n_q]
    debt = (sim["debt"] + sim["revolver"])[:, :n_q]
    div4, capex4 = sim["dividends"][:, :4].sum(1), sim["capex"][:, :4].sum(1)
    raise_ = (debt - p["debt0"]) / rev_ttm
    out: dict = {
        "cash_half": float(np.mean(cash.min(1) < 0.5 * p["cash0"])) if p["cash0"] > 0 else None,
        "debt_raise": float(np.mean(raise_.max(1) > 0.05)),
        "div_cut": float(np.mean(div4 < 0.5 * 4 * p["div_q"])) if p["div_q"] > 0 else None,
        "capex_cut": float(np.mean(capex4 < 0.75 * capex_pre)) if capex_pre > 0 else None,
    }
    # the same events at other thresholds, and when they happen (cumulative probability by quarter)
    out["grid"] = {
        "cash": {f"{x}": float(np.mean(cash.min(1) < x * p["cash0"])) for x in (0.3, 0.5, 0.7)}
        if p["cash0"] > 0
        else {},
        "debt": {f"{x}": float(np.mean(raise_.max(1) > x)) for x in (0.03, 0.05, 0.10)},
        "div": {f"{x}": float(np.mean(div4 < (1 - x) * 4 * p["div_q"])) for x in (0.25, 0.5)} if p["div_q"] > 0 else {},
        "capex": {f"{x}": float(np.mean(capex4 < (1 - x) * capex_pre)) for x in (0.25, 0.5)} if capex_pre > 0 else {},
    }
    out["timing"] = {
        "cash_half": [float(np.mean((cash[:, : k + 1] < 0.5 * p["cash0"]).any(1))) for k in range(n_q)]
        if p["cash0"] > 0
        else None,
        "debt_raise": [float(np.mean((raise_[:, : k + 1] > 0.05).any(1))) for k in range(n_q)],
    }
    return out


QLEVELS = (2.5, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 97.5)


def density(tot: np.ndarray, real: float) -> dict:
    """Compact predictive density of an 8-quarter total (% of trailing revenue): 21 quantiles, mean and s.d., plus
    the CRPS and PIT against the realized total computed on all paths (E2)."""
    tot = np.asarray(tot, float)
    return {
        "q": [round(float(v), 3) for v in np.percentile(tot, QLEVELS)],
        "mean": round(float(tot.mean()), 4),
        "sd": round(float(tot.std(ddof=1)), 4),
        "crps": round(crps_samples(tot, real), 5),
        "pit": round(float(np.mean(tot <= real)), 5),
    }


def structural(
    hist: CompanyData,
    p: dict,
    full: pd.DataFrame,
    macro: pd.DataFrame | None = None,
    n_q: int = 8,
    fails: Failures | None = None,
) -> dict:
    """Feed the revenue that actually followed the cutoff into the twin and compare its cash response with reality.

    Predicting *which* shock hits a company is the scenario's job; translating a given revenue path into cash is
    the simulation's job. This isolates the second. Every rival sees the same realized revenue, quarter by quarter:
    trailing cash-flow margins over 4, 8 and 16 quarters (the sector-shrunk margin is built in `stats`), and two
    per-company regressions of cash flow on revenue, without and with working-capital timing. Paths are stored as
    % of trailing revenue, so totals, worst cumulative values and further rules can be computed downstream.

    The same run yields the liquidity decisions a risk user cares about (cash halves, new borrowing, dividend and
    capex cuts) for the twin, each loop ablation, a static runway calculation with the same inputs, and reality.
    """
    fails = fails if fails is not None else Failures()
    fails.tried("structural")  # the denominator of the exclusion shares
    pre = hist.quarters
    nxt = _following(full, pre.index[-1], n_q, fails, "structural")
    rev_ttm = _ttm(pre, "revenue")
    if len(nxt) < n_q:
        return {}
    if nxt["revenue"].isna().any() or not np.isfinite(rev_ttm) or rev_ttm <= 0:
        fails.skip("structural", "revenue")
        return {}
    rev = nxt["revenue"].to_numpy(float)
    cfo, capex = nxt["cfo"].to_numpy(float), nxt["capex"].to_numpy(float)
    if not (np.isfinite(cfo).all() and np.isfinite(capex).all()):
        fails.skip("structural", "cash_flow")
        return {}
    T = int(p["horizon"])
    scn = build_scenario({}, T)
    override = np.full(T, np.nan)
    override[:n_q] = rev
    scn["revenue_override"] = override
    eps = draw_shocks(p, 500, T, seed=3)

    def pc(x) -> list[float]:
        return [round(float(v) / rev_ttm * 100, 4) for v in x]

    def tot(x: np.ndarray) -> np.ndarray:  # path-level 8-quarter totals, % of trailing revenue
        return x[:, :n_q].sum(1) / rev_ttm * 100

    def med_tot(x: np.ndarray) -> float:  # E1: the median of the path totals, not the sum of per-quarter medians
        return round(float(np.median(tot(x))), 4)

    pre_cfo, pre_fcf = pre["cfo"], pre["cfo"] - pre["capex"]
    capex_pre = float(pre["capex"].tail(4).sum()) if data_legacy() else _ttm(pre, "capex")
    ebitda_real = (nxt["operating_income"] + nxt["da"].fillna(0)).to_numpy(float)
    out: dict = {
        "rev": pc(rev),
        "real_cfo": pc(cfo),
        "real_fcf": pc(cfo - capex),
        "real_ebitda": pc(ebitda_real) if np.isfinite(ebitda_real).all() else None,
        "real_capex": pc(capex),
        "m": {f"{n}{k}": _f(_margin(pre, c, k)) for n, c in (("cfo", pre_cfo), ("fcf", pre_fcf)) for k in (4, 8, 16)},
    }
    rev_prev = float(pre["revenue"].iloc[-1])
    for name, cash in (("cfo", pre_cfo), ("fcf", pre_fcf)):
        out[f"ols_{name}"] = pc(_apply_rule(_cash_rule(pre, cash, False), rev, rev_prev))
        out[f"dyn_{name}"] = pc(_apply_rule(_cash_rule(pre, cash, True), rev, rev_prev))
    probs = {}
    for k, lv in ABLATIONS.items():
        sim = simulate(p, scn, eps, {**DEFAULT_LEVERS, **lv})
        probs[k] = _probs(sim, p, n_q, rev_ttm, capex_pre)
        if k in ("full", "no_loops"):
            tag = "twin" if k == "full" else "noloops"
            out[f"{tag}_cfo"] = pc(np.median(sim["cfo"][:, :n_q], axis=0))
            out[f"{tag}_fcf"] = pc(np.median(sim["fcf"][:, :n_q], axis=0))
            out[f"{tag}_cfo_tot"] = med_tot(sim["cfo"])
            out[f"{tag}_fcf_tot"] = med_tot(sim["fcf"])
            if k == "full":
                out["twin_ebitda"] = pc(np.median(sim["ebitda"][:, :n_q], axis=0))
                out["twin_capex"] = pc(np.median(sim["capex"][:, :n_q], axis=0))
                out["twin_ebitda_tot"] = med_tot(sim["ebitda"])
                out["twin_capex_tot"] = med_tot(sim["capex"])
                out["dens"] = {
                    v: density(tot(sim[v]), float(np.sum(x)) / rev_ttm * 100)
                    for v, x in (("cfo", cfo), ("fcf", cfo - capex))
                }
    out["probs"] = probs
    # the point forecast of the specification: E1 (median of path totals) in v3, the sum of per-quarter medians in
    # v2-pre; both are always stored, so v2-pre can be reported both ways
    out["e1"] = fix_active("E1")
    for v in ("cfo", "fcf"):
        out[f"twin_{v}_sm"] = round(float(np.sum(out[f"twin_{v}"])), 4)
        out[f"twin_{v}_point"] = out[f"twin_{v}_tot"] if out["e1"] else out[f"twin_{v}_sm"]

    # realized liquidity decisions
    cash_like = (nxt["cash"] + nxt["short_investments"].fillna(0)).to_numpy(float)
    debt = nxt["total_debt"].to_numpy(float)
    div_pre = float(pre["dividends"].tail(4).fillna(0).sum())
    out["events"] = {
        "cash_half": bool(np.nanmin(cash_like) < 0.5 * p["cash0"])
        if p["cash0"] > 0 and np.isfinite(cash_like).any()
        else None,
        "debt_raise": bool((np.nanmax(debt) - p["debt0"]) / rev_ttm > 0.05) if np.isfinite(debt).any() else None,
        "div_cut": bool(nxt["dividends"].head(4).fillna(0).sum() < 0.5 * div_pre) if div_pre > 0 else None,
        "capex_cut": bool(capex[:4].sum() < 0.75 * capex_pre) if capex_pre > 0 else None,
    }

    def first(mask: np.ndarray) -> int | None:
        hit = np.flatnonzero(mask)
        return int(hit[0]) + 1 if len(hit) else None

    raise_real = (debt - p["debt0"]) / rev_ttm
    out["realized_cont"] = {
        "cash_min_ratio": _f(np.nanmin(cash_like) / p["cash0"])
        if p["cash0"] > 0 and np.isfinite(cash_like).any()
        else None,
        "debt_raise_ratio": _f(np.nanmax(raise_real)) if np.isfinite(debt).any() else None,
        "div_ratio": _f(nxt["dividends"].head(4).fillna(0).sum() / div_pre) if div_pre > 0 else None,
        "capex_ratio": _f(capex[:4].sum() / capex_pre) if capex_pre > 0 else None,
        "t_cash_half": first(cash_like < 0.5 * p["cash0"]) if p["cash0"] > 0 else None,
        "t_debt_raise": first(np.nan_to_num(raise_real, nan=-1) > 0.05),
    }
    # an analyst's static runway with the same inputs: the trailing FCF margin on the realized revenue, minus the
    # current dividend and buyback run-rate and the maturities the company does not usually refinance
    fcf_m = out["m"]["fcf4"]
    if fcf_m is not None:
        payout_q = div_pre / 4 + float(pre["buybacks"].tail(4).fillna(0).sum()) / 4
        mat = np.asarray(p["maturities_q"][:n_q], float) * (1 - p["refi_ratio"])
        path = p["cash0"] + np.cumsum(fcf_m * rev - payout_q - mat)
        fcf4 = fcf_m * rev[:4].sum()
        out["static"] = {
            "cash_min": _f(path.min() / max(p["cash0"], 1e-9)),
            "fin_need": _f(max(p["cash_target"] - path.min(), 0.0) / rev_ttm * 100),
            "div_pressure": _f(min(div_pre / fcf4, 50.0)) if fcf4 > 0 else 50.0,
            "rev4": _f(rev[:4].sum() / rev_ttm),
        }

    # sensitivity of the transmission result and of the baseline verdict to the model's judgement calls
    if macro is not None:
        sens = {}
        for name, var in SENSITIVITY.items():
            fails.tried("sens")
            try:
                pv = calibrate(hist, macro, T, var["calib"]) if "calib" in var else dict(p)
                pv = {**pv, "sector_tol": 1.0, **var.get("p", {})}
                if name in ("spreads_2026", "spreads_baa"):
                    pv.pop("spreads", None)
                if name == "spreads_baa":
                    pv["spread_scale"] = _spread_scale(str((pre.index[-1] + pd.Timedelta(days=45)).date()))
                sim = simulate(pv, scn, draw_shocks(pv, 500, T, seed=3), DEFAULT_LEVERS)
                base = simulate(pv, build_scenario({}, T), draw_shocks(pv, 1000, T, seed=5), DEFAULT_LEVERS)
                sens[name] = {
                    "cfo": pc(np.median(sim["cfo"][:, :n_q], axis=0)),
                    "fcf": pc(np.median(sim["fcf"][:, :n_q], axis=0)),
                    "cfo_tot": med_tot(sim["cfo"]),
                    "fcf_tot": med_tot(sim["fcf"]),
                    "probs": _probs(sim, pv, n_q, rev_ttm, capex_pre),
                    "health": summarize(base)["health_score"],
                }
            except Exception as e:  # a variant that cannot be calibrated is skipped, but counted by type
                fails.fail("sens", e)
                out.setdefault("sens_failed", {})[name] = type(e).__name__
        out["sens"] = sens
        # walk-forward grids of tau / lambda (only when F1 / F3 are on); `select` picks one per cutoff year from
        # earlier years, and a second pass (FINTWIN_SELECTION) runs the whole shard at the chosen values
        grid = {}
        for name, a in ({} if os.environ.get("FINTWIN_SELECTION") else wf_grid()).items():
            fails.tried("grid")
            try:
                pv = {**calibrate(hist, macro, T, a), "sector_tol": 1.0}
                sim = simulate(pv, scn, draw_shocks(pv, 500, T, seed=3), DEFAULT_LEVERS)
                grid[name] = {
                    "cfo": med_tot(sim["cfo"]),
                    "fcf": med_tot(sim["fcf"]),
                    "cfo_sm": round(float(np.sum(np.median(sim["cfo"][:, :n_q], axis=0))) / rev_ttm * 100, 4),
                }
            except Exception as e:
                fails.fail("grid", e)
        if grid:
            out["grid"] = grid
    return out


def _cumulative(pre: pd.DataFrame, window: pd.DataFrame, rev_ttm: float) -> tuple[float, float]:
    """Cumulative FCF over the window and its excess over the pre-cutoff run-rate, % of trailing revenue.

    Worst cumulative values (`_abnormal_burn`, `burn`) are drawdowns: for a firm with positive cash flow they equal the
    first quarter. For rank correlations the whole window is the better continuous outcome.
    """
    run_rate = (_ttm(pre, "cfo") - _ttm(pre, "capex")) / 4
    fcf = window["cfo"] - window["capex"]
    if not data_legacy() and not np.isfinite(fcf.to_numpy(float)).all():
        return np.nan, np.nan  # D4: a missing quarter is unknown, not zero burn
    total = float(fcf.fillna(0).sum() / rev_ttm * 100)
    if not np.isfinite(run_rate):
        return total, np.nan
    return total, float((fcf.fillna(run_rate) - run_rate).sum() / rev_ttm * 100)


def _fcf_path(window: pd.DataFrame) -> pd.Series | None:
    """Quarterly FCF over an outcome window: None if any quarter is missing (D4; the legacy layer counted it as 0)."""
    fcf = window["cfo"] - window["capex"]
    if data_legacy():
        return fcf.fillna(0)
    return fcf if np.isfinite(fcf.to_numpy(float)).all() else None


def _abnormal_burn(pre: pd.DataFrame, window: pd.DataFrame, rev_ttm: float) -> float:
    """Worst cumulative free cash flow *relative to the company's own pre-cutoff run-rate*, % of revenue.

    Raw cumulative FCF mostly measures a persistent propensity to burn cash (capex-heavy utilities, growth companies
    burn every year); a stress test claims to predict the deterioration a shock causes, so the outcome subtracts the
    trailing four-quarter FCF run-rate from every quarter of the window.
    """
    run_rate = (_ttm(pre, "cfo") - _ttm(pre, "capex")) / 4
    if not np.isfinite(run_rate):
        return np.nan
    fcf = window["cfo"] - window["capex"]
    if not data_legacy() and not np.isfinite(fcf.to_numpy(float)).all():
        return np.nan
    gap = (fcf.fillna(run_rate) - run_rate).cumsum()
    return float(min(gap.min(), 0.0) / rev_ttm * 100)


def covid_outcomes(hist: CompanyData, full: pd.DataFrame, fails: Failures | None = None) -> dict:
    fails = fails if fails is not None else Failures()
    fails.tried("covid_outcomes")
    pre = hist.quarters
    rev_ttm = _ttm(pre, "revenue")
    win = full[(full.index > pd.Timestamp("2020-01-15")) & (full.index <= pd.Timestamp("2021-07-15"))]
    if len(win) < 4 or not np.isfinite(rev_ttm) or rev_ttm <= 0:
        fails.skip("covid_outcomes", "short")
        return {}
    if not data_legacy() and not contiguous(win, len(win)):
        fails.skip("covid_outcomes", "gap")  # SW-4 / D1: a hole in the window would shift every cumulative value
        return {}
    path = _fcf_path(win)
    fcf = path.cumsum() if path is not None else pd.Series(np.nan, index=win.index)
    yoy = (full["revenue"] / full["revenue"].shift(4) - 1).reindex(win.index)
    cash_like = (full["cash"] + full["short_investments"].fillna(0)).reindex(win.index)
    cash_pre = float(pre["cash"].iloc[-1] + np.nan_to_num(pre["short_investments"].iloc[-1]))
    div_pre = float(pre["dividends"].tail(4).fillna(0).sum())
    post = win[win.index > pd.Timestamp("2020-04-15")].head(4)
    div_post = float(post["dividends"].fillna(0).sum())
    cum, abn_cum = _cumulative(pre, win, rev_ttm)
    return {
        "burn": _f(fcf.min() / rev_ttm * 100),
        "abn_burn": _f(_abnormal_burn(pre, win, rev_ttm)),
        "cum_fcf": _f(cum),
        "abn_cum_fcf": _f(abn_cum),
        "rev_drop": _f(yoy.min() * 100),
        "debt_raise": _f((win["total_debt"].max() - pre["total_debt"].iloc[-1]) / rev_ttm * 100),
        "cash_min_ratio": _f(cash_like.min() / cash_pre) if cash_pre > 0 else None,
        "div_payer": bool(div_pre > 0),
        "div_cut": bool(div_pre > 0 and len(post) == 4 and div_post < 0.5 * div_pre),
    }


def _liquidity_realized(pre: pd.DataFrame, nxt: pd.DataFrame, rev_ttm: float) -> dict:
    """What happened to liquidity within 4 and 8 quarters: the lowest cash-like balance relative to the opening one and
    the largest rise in total debt (% of trailing revenue). `distress.liquidity_frame` turns them, with the credit
    events, into the realized shortfall label of E12."""
    cash0 = float(pre["cash"].iloc[-1] + np.nan_to_num(pre["short_investments"].iloc[-1]))
    debt0 = float(pre["total_debt"].iloc[-1])
    cash = (nxt["cash"] + nxt["short_investments"].fillna(0)).to_numpy(float)
    debt = nxt["total_debt"].to_numpy(float)
    out: dict = {}
    for k in SHORTFALL_Q:
        c, d = cash[:k], debt[:k]
        out[f"cash_min_ratio{k}"] = _f(np.min(c) / cash0) if cash0 > 0 and np.isfinite(c).all() else None
        out[f"debt_raise{k}"] = (
            _f((np.max(d) - debt0) / rev_ttm) if np.isfinite(debt0) and np.isfinite(d).all() else None
        )
    return out


def _distress(hist: CompanyData, full: pd.DataFrame, filed: dict | None = None, fails: Failures | None = None) -> dict:
    """Outcomes over the eight reported quarters after the cutoff's last known quarter."""
    fails = fails if fails is not None else Failures()
    fails.tried("outcome")
    pre = hist.quarters
    nxt = _following(full, pre.index[-1], 8, fails, "outcome")
    rev_ttm = _ttm(pre, "revenue")
    if len(nxt) < 8:
        return {}
    if not np.isfinite(rev_ttm) or rev_ttm <= 0:
        fails.skip("outcome", "revenue")
        return {}
    path = _fcf_path(nxt)
    fcf = path.cumsum() if path is not None else pd.Series(np.nan, index=nxt.index)
    both = pd.concat([pre.tail(4), nxt])
    ebit = (both["operating_income"]).rolling(4).sum().tail(8)
    intr = both["interest_expense"].rolling(4).sum().tail(8)
    yoy_ok = pd.Series(True, index=both.index)
    if not data_legacy():  # trailing sums and year-on-year changes only over consecutive quarters (D1)
        ebit = ebit.where(contiguous_mask(both, 4, "operating_income").tail(8))
        intr = intr.where(contiguous_mask(both, 4, "interest_expense").tail(8))
        yoy_ok = contiguous_mask(both, 5)
    icr = (ebit / intr.where(intr > 0)).dropna()
    icr0 = _ttm(pre, "operating_income") / max(_ttm(pre, "interest_expense"), 1e-9)
    div_pre = float(pre["dividends"].tail(4).fillna(0).sum())
    div_post = float(nxt["dividends"].head(4).fillna(0).sum())
    return {
        "burn8": _f(fcf.min() / rev_ttm * 100),
        "cum8": _f(_cumulative(pre, nxt, rev_ttm)[0]),
        "abn_cum8": _f(_cumulative(pre, nxt, rev_ttm)[1]),
        "abn_burn8": _f(_abnormal_burn(pre, nxt, rev_ttm)),
        "icr0": _f(icr0),
        "icr_min": _f(icr.min()) if len(icr) else None,
        "div_payer": bool(div_pre > 0),
        "div_cut": bool(div_pre > 0 and div_post < 0.5 * div_pre),
        "rev_drop8": _f(
            ((nxt["revenue"] / both["revenue"].shift(4).reindex(nxt.index) - 1).where(yoy_ok.reindex(nxt.index))).min()
            * 100
        ),
        **_liquidity_realized(pre, nxt, rev_ttm),
        # when the last outcome quarter was first reported (D10): a model trained for a later cutoff may use this
        # firm-year only if this date precedes that cutoff
        "outcome_filed": filed_for((filed or {}).get("revenue"), nxt.index[-1]),
        "outcome_filed4": filed_for((filed or {}).get("revenue"), nxt.index[3]),
    }


def _ets_samples(
    y: np.ndarray, h: int, log: bool, seasonal: bool, n: int = 2000, fails: Failures | None = None
) -> np.ndarray | None:
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    fails = fails if fails is not None else Failures()
    fails.tried("ets")
    y = y[np.isfinite(y)][-40:]
    if log:
        if (y <= 0).any():
            fails.skip("ets", "non_positive")
            return None
        y = np.log(y)
    if len(y) < 12:
        fails.skip("ets", "short_series")
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = ETSModel(
                y,
                error="add",
                trend="add" if seasonal else None,
                damped_trend=seasonal,
                seasonal="add" if seasonal else None,
                seasonal_periods=4 if seasonal else None,
            ).fit(disp=False)
            sims = np.asarray(m.simulate(h, anchor="end", repetitions=n, rng=np.random.default_rng(3))).reshape(h, n)
    except Exception as e:  # the comparison with ETS is then restricted to fitted rows; the count is reported
        fails.fail("ets", e)
        return None
    return np.exp(sims) if log else sims


def forecasts(
    ticker: str,
    full_data: CompanyData,
    hists: dict[str, CompanyData],
    fails: Failures | None = None,
    filed: dict | None = None,
    origins: list[str] | None = None,
) -> list[dict]:
    fails = fails if fails is not None else Failures()
    full = full_data.quarters
    rows: list[dict] = []
    for origin in origins if origins is not None else FORECAST_ORIGINS:
        hist = hists.get(origin)
        if hist is None or not usable(hist, origin):
            continue
        fails.tried("forecast")
        try:
            rows += _forecast_origin(origin, hist, full, fails, filed)
        except Exception as e:  # one unusable vintage must not drop the company's other forecasts
            fails.fail("forecast", e)
    return rows


def _forecast_origin(
    origin: str, hist: CompanyData, full: pd.DataFrame, fails: Failures | None = None, filed: dict | None = None
) -> list[dict]:
    fails = fails if fails is not None else Failures()
    rows: list[dict] = []
    why: dict = {}
    real = _realized(full, hist.quarters.index[-1], why)
    if len(real) < H_FC:
        fails.skip("forecast", why.get("realized", "short"))
        return rows
    p = calibrate(hist, macro_quarterly(origin), H_FC)
    out = simulate(p, build_scenario({}, H_FC), draw_shocks(p, 2000, H_FC, seed=11), DEFAULT_LEVERS)
    q = hist.quarters
    scale = _ttm(q, "revenue") / 4
    series = {
        "revenue": q["revenue"].to_numpy(float),
        "cash_like": (q["cash"] + q["short_investments"].fillna(0)).to_numpy(float),
    }
    ets = {
        "revenue": _ets_samples(series["revenue"], H_FC, log=True, seasonal=True, fails=fails),
        "cash_like": _ets_samples(series["cash_like"], H_FC, log=False, seasonal=False, fails=fails),
    }
    for var, key in (("revenue", "revenue"), ("cash_like", "cash")):
        for h in range(H_FC):
            y = float(real[var].iloc[h])
            if not np.isfinite(y):
                continue
            mu_b, sd_b = _baseline(q, var, h + 1)
            e = ets[var]
            emp = rw_empirical(q, var, h + 1)
            rows.append(
                {
                    "origin": origin,
                    "var": var,
                    "h": h + 1,
                    "scale": _f(scale),
                    "crps_twin": crps_samples(out[key][:, h], y),
                    "crps_rw": crps_gaussian(mu_b, sd_b, y),
                    "crps_ets": crps_samples(e[h], y) if e is not None else None,
                    "pit_ets": float(np.mean(e[h] <= y)) if e is not None else None,
                    # for conditional coverage: the realized value, the twin's quantiles and the quarter forecast
                    "y": y,
                    "q": [float(v) for v in np.percentile(out[key][:, h], [5, 25, 50, 75, 95])],
                    "pit_twin": float(np.mean(out[key][:, h] <= y)),
                    "target": str(real.index[h].date()),
                    # D10: the date the target quarter was first reported (conformal and training windows use it)
                    "filed": filed_for((filed or {}).get("revenue" if var == "revenue" else "cash"), real.index[h]),
                    "rw_mu": _f(mu_b),
                    "rw_sd": _f(sd_b),
                    "crps_rw_emp": crps_samples(emp, y) if emp is not None else None,
                    "pit_rw_emp": float(np.mean(emp <= y)) if emp is not None else None,
                }
            )
    return rows


# ---------------------------------------------------------------- credit events from 8-K items (M9)
CREDIT_ITEMS = ("1.03", "2.04", "3.01")  # bankruptcy or receivership; acceleration of an obligation; delisting notice
COC_ITEMS = ("2.01", "5.01")  # completion of an acquisition; change in control
COC_WINDOW = pd.Timedelta(days=30)


def _has_item(items: pd.Series, item: str) -> pd.Series:
    return items.str.contains(rf"(?<![\d.]){re.escape(item)}(?![\d])", regex=True)


def credit_events_from(filings: pd.DataFrame) -> dict:
    """Filing dates of 8-Ks carrying each credit item, from an EDGAR `submissions` filings table.

    Items 2.04 and 3.01 are also filed when a company is acquired (change-of-control acceleration, delisting after a
    merger): such filings are dropped when the same 8-K, or one within 30 days, reports item 2.01 or 5.01. The number
    dropped is kept. Voluntary listing transfers under 3.01 cannot be told apart from the items alone.
    """
    out: dict = {k: [] for k in CREDIT_ITEMS}
    if filings is None or filings.empty or "form" not in filings:
        return out
    items = filings["items"].fillna("").astype(str) if "items" in filings else pd.Series("", index=filings.index)
    is8k = filings["form"].isin(["8-K", "8-K/A"])
    dates = pd.to_datetime(filings["filingDate"], errors="coerce")
    coc_same = _has_item(items, COC_ITEMS[0]) | _has_item(items, COC_ITEMS[1])
    coc_dates = pd.DatetimeIndex(dates[is8k & coc_same].dropna())
    for it in CREDIT_ITEMS:
        m = is8k & _has_item(items, it) & dates.notna()
        if it != "1.03":
            near = np.array(
                [pd.notna(d) and bool(len(coc_dates)) and bool((abs(coc_dates - d) <= COC_WINDOW).any()) for d in dates]
            )
            drop = m & (coc_same | near)
            out[f"{it}_coc_dropped"] = int(drop.sum())
            m = m & ~drop
        out[it] = sorted({str(d.date()) for d in dates[m]})
    return out


def credit_events(cik: int) -> dict:
    from ..data.edgar_universe import submissions

    return credit_events_from(submissions(cik)["filings"])


@contextmanager
def _timed(acc: dict, stage: str):
    """Wall-clock seconds per stage (the rev3 cost model, REV3_LIGHT_PLAN B1). Timing only: no effect on results."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        acc[stage] = round(acc.get(stage, 0.0) + time.perf_counter() - t0, 3)


def company(
    ticker: str, with_forecasts: bool = True, years: set[int] | None = None, fails: Failures | None = None
) -> dict:
    """All designs for one company. `ticker` is a ticker, a ``CIK0000012345`` key or a legacy ``XXX~2020`` key.

    `years` restricts the cutoffs (dry runs); the COVID design runs only if 2020 is among them.
    """
    fails = fails if fails is not None else Failures()
    panel_origins = [o for o in PANEL_ORIGINS if years is None or int(o[:4]) in years]
    fc_origins = [o for o in FORECAST_ORIGINS if years is None or int(o[:4]) in years]
    is_bk = "~" in ticker
    full_data = None if is_bk else load_company(ticker)
    res: dict = {
        "ticker": ticker,
        "cik": int(full_data.cik) if full_data else None,
        "bankrupt_2020": is_bk,
        "spec": spec_record(),
        "errors": {},
    }
    tm: dict = {}
    res["_timing"] = tm
    filed: dict = {}
    if full_data is not None:
        res["data"] = data_vintage(int(full_data.cik))
        fails.tried("filed")
        try:
            filed = first_filed(int(full_data.cik))
        except Exception as e:  # D10 then falls back to the fixed lag downstream, and the count says how often
            fails.fail("filed", e)
        fails.tried("credit_events")
        try:
            res["credit_events"] = credit_events(int(full_data.cik))
        except Exception as e:
            fails.fail("credit_events", e)
            res["credit_events"] = None
    if years is None or 2020 in years:
        fails.tried("covid")
        try:
            with _timed(tm, "covid"):
                res["covid"] = covid(ticker, None if full_data is None else full_data.quarters, fails)
        except Exception as e:
            res["errors"]["covid"] = f"{type(e).__name__}: {e}"
            fails.fail("covid", e)
    if full_data is None:
        res["failures"] = fails.to_dict()
        return res
    hists: dict[str, CompanyData] = {}
    for origin in fc_origins if with_forecasts else panel_origins:
        fails.tried("load")
        try:
            with _timed(tm, "load"):
                hists[origin] = load_company(ticker, asof=origin)
        except Exception as e:
            res["errors"][origin] = f"{type(e).__name__}: {e}"
            fails.fail("load", e)
    panel = []
    for origin in panel_origins:
        hist = hists.get(origin)
        if hist is None or not usable(hist, origin):
            continue
        fails.tried("panel")
        try:
            with _timed(tm, "calibrate"):
                p = calibrate(hist, macro_quarterly(origin), 12)
            raw = {**p, "sector_tol": 1.0}
            with _timed(tm, "depth_grid"):
                dg = {f"{d:.2f}": _run(raw, {**DEMAND, "sales_depth": d}, {}, 1000, 12, 7) for d in DEPTHS}
            with _timed(tm, "base3"):
                runs3 = {
                    "base": _run(raw, {}, {}, 1500, 12, 5),
                    "recession": _run(raw, PRESETS["recession"]["knobs"], {}, 1500, 12, 5),
                    "base_no_loops": _run(raw, {}, ABLATIONS["no_loops"], 1500, 12, 5),
                }
            feats = features(hist, p)
            with _timed(tm, "outcome"):
                outcome = _distress(hist, full_data.quarters, filed, fails)
            with _timed(tm, "structural"):
                st = structural(hist, raw, full_data.quarters, macro_quarterly(origin), fails=fails)
            row = {
                "origin": origin,
                **runs3,
                "features": feats,
                "outcome": outcome,
                "structural": st,
                # stress score under a generic demand shock of each depth (no market closure), so that `stats`
                # can give each firm its industry's realized shock in any episode (2015-16, 2020, 2022)
                "depth_grid": {k: v["health"] for k, v in dg.items()},
                "rec_state0": p.get("rec_state0"),
                "rec_realtime": realtime_recession(origin),
                "selected": selected_assumptions(origin) or None,
            }
            # E12: P(cash + undrawn < 0 within 4 / 8 quarters) at each shock depth and under the Recession preset
            row["liquidity"] = {
                "grid": {k: [v.get("short4"), v.get("short8")] for k, v in dg.items()},
                "recession": [row["recession"].get("short4"), row["recession"].get("short8")],
                "base": [row["base"].get("short4"), row["base"].get("short8")],
            }
            panel.append(row)
        except Exception as e:
            res["errors"][f"panel {origin}"] = f"{type(e).__name__}: {e}"
            fails.fail("panel", e)
    res["panel"] = panel
    if with_forecasts:
        try:
            with _timed(tm, "forecasts"):
                res["forecasts"] = forecasts(ticker, full_data, hists, fails, filed, fc_origins)
        except Exception as e:
            res["errors"]["forecasts"] = f"{type(e).__name__}: {e}"
            fails.fail("forecasts", e)
    res["failures"] = fails.to_dict()
    return res
