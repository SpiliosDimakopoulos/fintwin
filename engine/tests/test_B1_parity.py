"""B1: v2-pre / v2-rev reproduce the revision-2 code exactly.

`test_B1_v2_golden.json` was written by `_golden()` below from commit 20b2610 (rev3 before any B1 change); the
calibrated parameters and Monte Carlo summaries of three synthetic firms must match it bit for bit.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fintwin.data.facts import CompanyData
from fintwin.stochastic.calibrate import calibrate
from fintwin.stochastic.mc import run, summarize

GOLDEN = Path(__file__).with_name("test_B1_v2_golden.json")


def synthetic_company(
    n: int = 40,
    seed: int = 0,
    fixed: float = 300.0,
    v: float = 0.6,
    trend: float = 0.015,
    season_amp: float = 0.15,
    cost_season: float = 1.0,
    noise: float = 0.01,
    da_missing: bool = False,
    stale_ladder: bool = False,
    ticker: str = "SYNB1",
    fixed_infl: float = 0.0,
) -> CompanyData:
    """A firm whose cash costs are `fixed` + `v`·revenue, with costs following `cost_season` of the seasonal swing."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-03-31", periods=n, freq="QE")
    t = np.arange(n)
    season = (idx.quarter.values - 1) % 4
    sw = np.array([-1.0, -0.3, 0.3, 1.0])[season] * season_amp
    level = 1000.0 * np.exp(trend * t + 0.05 * np.sin(t / 5.0))
    rev = level * (1 + sw) * (1 + noise * rng.standard_normal(n))
    costs = fixed * (1 + fixed_infl) ** t + v * level * (1 + cost_season * sw) + noise * 50 * rng.standard_normal(n)
    ppe = 2000.0 + 5.0 * t
    da = 0.025 * ppe
    ebitda = rev - costs
    oi = ebitda - da
    debt = 1500.0 - 2.0 * t
    interest = debt * 0.045 / 4
    ebt = oi - interest
    tax = 0.22 * ebt + 3.0 * rng.standard_normal(n)
    ni = ebt - tax
    recv, inv, pay = 0.4 * rev, 0.3 * costs, 0.25 * costs
    defr = 0.05 * rev
    nwc = recv + inv - pay - defr
    sbc = 0.01 * rev
    cfo = ni + da + sbc - np.r_[0.0, np.diff(nwc)] + 0.005 * rev
    capex = 0.05 * rev
    cash = 400.0 + 3.0 * t + 20 * rng.standard_normal(n)
    q = pd.DataFrame(
        {
            "revenue": rev,
            "operating_income": oi,
            "da": np.full(n, np.nan) if da_missing else da,
            "interest_expense": interest,
            "tax": tax,
            "net_income": ni,
            "sbc": sbc,
            "cfo": cfo,
            "capex": capex,
            "dividends": np.full(n, 20.0),
            "buybacks": np.full(n, 15.0),
            "cash": cash,
            "short_investments": np.full(n, 50.0),
            "receivables": recv,
            "inventory": inv,
            "payables": pay,
            "deferred_revenue": defr,
            "ppe": ppe,
            "assets": 6000.0 + 10 * t,
            "liabilities": 3500.0 + 5 * t,
            "current_assets": cash + 50 + recv + inv + 100,
            "current_liabilities": pay + defr + 200,
            "equity": 2500.0 + 5 * t,
            "retained_earnings": 1200.0 + 4 * t,
            "short_borrowings": np.full(n, 40.0),
            "commercial_paper": np.full(n, 10.0),
            "total_debt": debt,
            "revolver_capacity": np.full(n, np.nan),
            "season": season,
        },
        index=idx,
    )
    mat_date = "2015-12-31" if stale_ladder else str(idx[-1].date())
    return CompanyData(
        ticker, 1, "Synthetic B1", str(idx[-1].date()), q, {}, [200.0, 180.0, 160.0, 150.0, 140.0, 600.0], mat_date
    )


CASES = {
    "base": {},
    "da_missing": {"da_missing": True, "seed": 1},
    "stale_seasonal": {"stale_ladder": True, "season_amp": 0.3, "cost_season": 0.1, "seed": 2},
}
PRIORS = {"rev": {}, "pre": {"fixed_share_prior": 0.35}}


def _outputs(macro) -> dict:
    res = {}
    for case, kw in CASES.items():
        for pname, a in PRIORS.items():
            p = calibrate(synthetic_company(**kw), macro, 12, a)
            sm = summarize(run(p, n_paths=300, seed=11))
            res[f"{case}/{pname}"] = {"p": p, "summary": sm}
    return json.loads(json.dumps(res, default=float))


def _golden(macro, generated_by: str) -> None:  # pragma: no cover - run once on the pre-change code
    """`generated_by` is "<commit> <date>" of the code that ran; a regeneration shows up as a one-line change to it."""
    GOLDEN.write_text(json.dumps({"_generated_by": generated_by, **_outputs(macro)}, indent=1, sort_keys=True))


@pytest.mark.parametrize("spec", ["", "v2-pre", "v2-rev"])
def test_v2_specs_reproduce_revision2_code_exactly(macro, monkeypatch, spec):
    if spec:
        monkeypatch.setenv("FINTWIN_SPEC", spec)
    else:
        monkeypatch.delenv("FINTWIN_SPEC", raising=False)
    monkeypatch.delenv("FINTWIN_FIXES", raising=False)
    gold = json.loads(GOLDEN.read_text())
    assert gold.pop("_generated_by").startswith("20b2610"), "the golden must come from the pre-change code"
    got = _outputs(macro)
    assert got.keys() == gold.keys()
    for k in gold:
        # v2-pre's default prior is the pre-specified 35%, so its default-assumption run is the old "pre" run
        want = k.replace("/rev", "/pre") if spec == "v2-pre" else k
        _same(got[k], gold[want], k)


# The golden file was written on Windows; on Linux (x86 and ARM) libm/BLAS differ in the last bits: the largest
# difference measured on 10-11-2026 was relative 8e-13 (`p/phi`, stale_seasonal). Structure, strings, booleans and
# counts must match exactly; floats to a relative 1e-9 (absolute 1e-12 near zero). Anything above is a code change.
REL, ABS = 1e-9, 1e-12


def _same(a, b, path: str) -> None:
    if isinstance(b, dict):
        assert isinstance(a, dict) and a.keys() == b.keys(), path
        for k in b:
            _same(a[k], b[k], f"{path}/{k}")
    elif isinstance(b, list):
        assert isinstance(a, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _same(x, y, f"{path}[{i}]")
    elif isinstance(b, float) and not isinstance(a, bool) and isinstance(a, (int, float)):
        assert a == pytest.approx(b, rel=REL, abs=ABS, nan_ok=True), path
    else:
        assert a == b, path


def test_parity_tolerance_still_catches_a_real_change():
    _same({"x": [1.0, 2.0]}, {"x": [1.0, 2.0 * (1 + 1e-12)]}, "ok")  # float noise passes
    with pytest.raises(AssertionError):
        _same({"x": [1.0, 2.0]}, {"x": [1.0, 2.0 * (1 + 1e-7)]}, "change")
    with pytest.raises(AssertionError):
        _same({"x": "a"}, {"x": "b"}, "string")
