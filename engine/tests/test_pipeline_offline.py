"""End-to-end tests of the data -> calibration -> export -> notes path, fully offline.

A synthetic company is written in SEC XBRL `companyfacts` form (10-Qs with year-to-date cash flows and 10-Ks
with full-year totals and a maturity ladder), so the real parsing code runs against realistic structure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import fintwin.data.facts as facts
from fintwin.backtest.batch import _scores
from fintwin.data.quality import quality_report
from fintwin.notes import fact_sheet, write_note
from fintwin.scenarios.reverse_stress import reverse_stress
from fintwin.sensitivity.tornado import tornado
from fintwin.stochastic.calibrate import calibrate
from fintwin.stochastic.mc import run, summarize
from fintwin.universe import classify, compute_norms

YEARS = range(2013, 2025)


def _fact(start, end, val, filed, form, accn):
    return {
        "start": start,
        "end": end,
        "val": float(val),
        "filed": filed,
        "form": form,
        "accn": accn,
        "fy": 0,
        "fp": "",
    }


def synthetic_companyfacts() -> dict:
    """Calendar-year company: growing seasonal revenue, ~20% EBITDA margin, steady balance sheet."""
    rng = np.random.default_rng(0)
    dur: dict[str, list] = {}
    inst: dict[str, list] = {}
    q_ends = ["03-31", "06-30", "09-30", "12-31"]
    season = [0.9, 1.0, 1.0, 1.1]
    rev_level = 1000.0
    for y in YEARS:
        ytd = {k: 0.0 for k in ("rev", "oi", "da", "int", "tax", "ni", "cfo", "capex", "div", "bb", "sbc")}
        for qi, qe in enumerate(q_ends):
            rev_level *= 1.012
            rev = rev_level * season[qi] * (1 + rng.normal(0, 0.02))
            oi = 0.15 * rev
            vals = {
                "rev": rev,
                "oi": oi,
                "da": 0.05 * rev,
                "int": 12.0,
                "tax": 0.2 * (oi - 12),
                "ni": 0.8 * (oi - 12),
                "cfo": 0.8 * (oi - 12) + 0.05 * rev,
                "capex": 0.06 * rev,
                "div": 20.0,
                "bb": 15.0,
                "sbc": 0.01 * rev,
            }
            end = f"{y}-{qe}"
            filed = f"{y + 1}-02-20" if qi == 3 else f"{y}-{(qi + 1) * 3 + 1:02d}-28"
            form, accn = ("10-K", f"k{y}") if qi == 3 else ("10-Q", f"q{y}{qi}")
            for k, v in vals.items():
                ytd[k] += v
                # cash-flow style items are reported year-to-date; income items also as discrete quarters
                if k in ("cfo", "capex", "div", "bb", "sbc"):
                    dur.setdefault(k, []).append(_fact(f"{y}-01-01", end, ytd[k], filed, form, accn))
                else:
                    # income statement: discrete quarter in each 10-Q, plus the year-to-date figure (FY in the 10-K)
                    if qi < 3:
                        dur.setdefault(k, []).append(_fact(f"{y}-{qi * 3 + 1:02d}-01", end, v, filed, form, accn))
                    if qi > 0:
                        dur.setdefault(k, []).append(_fact(f"{y}-01-01", end, ytd[k], filed, form, accn))
            bs = {
                "cash": 300 + 2 * qi,
                "ar": 0.4 * rev,
                "inv": 0.3 * rev,
                "ap": 0.35 * rev,
                "ppe": 2000 + y,
                "assets": 4000 + 10 * y % 7,
                "liab": 2200,
                "ca": 1200,
                "cl": 700,
                "eq": 1800 + 10 * y % 7,
                "re": 900,
                "ltd_nc": 1000,
                "ltd_c": 100,
                "def": 0.1 * rev,
            }
            for k, v in bs.items():
                inst.setdefault(k, []).append({"end": end, "val": float(v), "filed": filed, "form": form, "accn": accn})
        for k, v in zip(("m1", "m2", "m3", "m4", "m5", "m6"), (100, 120, 130, 140, 150, 460), strict=True):
            inst.setdefault(k, []).append(
                {"end": f"{y}-12-31", "val": float(v), "filed": f"{y + 1}-02-20", "form": "10-K", "accn": f"k{y}"}
            )
    tags = {
        "rev": "Revenues",
        "oi": "OperatingIncomeLoss",
        "da": "DepreciationDepletionAndAmortization",
        "int": "InterestExpense",
        "tax": "IncomeTaxExpenseBenefit",
        "ni": "NetIncomeLoss",
        "cfo": "NetCashProvidedByUsedInOperatingActivities",
        "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
        "div": "PaymentsOfDividends",
        "bb": "PaymentsForRepurchaseOfCommonStock",
        "sbc": "ShareBasedCompensation",
        "cash": "CashAndCashEquivalentsAtCarryingValue",
        "ar": "AccountsReceivableNetCurrent",
        "inv": "InventoryNet",
        "ap": "AccountsPayableCurrent",
        "ppe": "PropertyPlantAndEquipmentNet",
        "assets": "Assets",
        "liab": "Liabilities",
        "ca": "AssetsCurrent",
        "cl": "LiabilitiesCurrent",
        "eq": "StockholdersEquity",
        "re": "RetainedEarningsAccumulatedDeficit",
        "ltd_nc": "LongTermDebtNoncurrent",
        "ltd_c": "LongTermDebtCurrent",
        "def": "ContractWithCustomerLiabilityCurrent",
        "m1": "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        "m2": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
        "m3": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree",
        "m4": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour",
        "m5": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive",
        "m6": "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive",
    }
    gaap = {tags[k]: {"units": {"USD": v}} for k, v in {**dur, **inst}.items()}
    return {"facts": {"us-gaap": gaap}}


@pytest.fixture
def offline(monkeypatch, macro):
    cf = synthetic_companyfacts()
    monkeypatch.setattr(facts, "company_facts", lambda cik: cf)
    monkeypatch.setattr(facts, "ticker_to_cik", lambda t: (123, "Synthetic Industries Inc"))
    return macro


def test_xbrl_to_quarterly_panel(offline):
    c = facts.load_company("SYN")
    q = c.quarters
    assert len(q) == 48
    # Q4 revenue recovered from the 10-K total minus nine months; Q4 capex from YTD differencing
    assert q["revenue"].notna().all() and q["capex"].notna().all() and (q["capex"] > 0).all()
    assert q["total_debt"].iloc[-1] == pytest.approx(1100)
    assert c.maturities[:2] == [100.0, 120.0]
    rep = quality_report(c)
    assert rep["core_completeness_last20_pct"] == 100.0


def test_point_in_time_vintage_hides_later_filings(offline):
    early = facts.load_company("SYN", asof="2018-02-15")
    assert early.quarters.index[-1] == pd.Timestamp("2017-09-30")  # the FY2017 10-K was filed on 2018-02-20


def test_calibration_recovers_structure(offline):
    p = calibrate(facts.load_company("SYN"), offline, 12)
    assert 0.0 < p["mu"] < 0.03
    assert p["seasonal"][3] > p["seasonal"][0]  # Q4 strongest season
    assert 0.3 < p["v"] < 1.0 and p["F"] >= 0
    assert p["coupon"] == pytest.approx(12 * 4 / 1100, rel=0.05)
    assert p["_sources"]["maturities"].startswith("XBRL maturity schedule")
    sm = summarize(run(p, n_paths=400))
    assert 0 <= sm["health_score"] <= 100


def test_stress_tools_and_notes(offline):
    from fintwin.export import company_block, meta_block

    block = company_block("SYN", offline, n_paths=600)
    assert set(block["presets"]) >= {"base", "pandemic"}
    assert block["presets"]["pandemic"]["health_score"] <= block["presets"]["base"]["health_score"]
    p = block["params"]
    rs = reverse_stress(p, n_paths=300)
    assert set(rs) == {"sales_depth", "rate_bp", "cost_pp"}
    assert len(tornado(p, n_paths=300)) == 6
    note = write_note(block, meta_block())
    assert note["verdict"] in {"Healthy", "Watch", "Strained", "Distressed"}
    assert note["key_risks"] and note["watch_list"]
    assert fact_sheet(block, meta_block())["ticker"] == "SYN"


def test_conformal_scores_and_norms(tmp_path, monkeypatch):
    df = pd.DataFrame({"y": [10.0, 12.0], "q_reg": [[8, 9, 10, 11, 12], [8, 9, 10, 11, 12]]})
    sc = _scores(df, "reg")
    assert list(sc["hit90"]) == [True, True] and sc["s90"].iloc[1] == pytest.approx(1.0)
    import fintwin.universe as u

    monkeypatch.setattr(u, "NORMS_JSON", tmp_path / "norms.json")
    out = compute_norms({"NEE": 5.0, "DUK": 5.5, "SO": 6.0, "AAPL": 0.2, "MSFT": 0.1, "NVDA": -0.5, "ADBE": 0.3})
    assert out["tolerance"]["Utilities"] == 2.0
    assert classify("AAPL")[0] == "Information Technology"
