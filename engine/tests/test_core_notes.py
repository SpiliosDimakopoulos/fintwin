"""Memo number checker, reverse-stress headline and the rule-based note (quality pass EC-01, EC-03, EC-04, EC-16)."""

from __future__ import annotations

import copy

import pytest

from fintwin.memo import _numbers, unverified_numbers
from fintwin.notes import write_note
from fintwin.scenarios.reverse_stress import TARGETS, headline


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("as of 2025-03-31", [2025, 3, 31]),
        ("the 2024-25 slump", [2024, 25]),
        ("Q3-2026", [3, 2026]),
        ("cash -5, debt (−7) and [-1.5]", [-5, -7, -1.5]),
        ("debt -$4,567.8", [-4567.8]),
    ],
)
def test_hyphen_in_dates_and_ranges_is_not_a_minus(text, want):
    assert _numbers(text) == want


def test_strict_check_accepts_a_year_range():
    assert unverified_numbers({"x": "a 2024-25 slump"}, {"n": 25}, strict=True) == []


def _rs(sales_p50=0.4, rate_p50=None, cost_p50=12.0):
    out = {}
    for k, p50 in (("sales_depth", sales_p50), ("rate_bp", rate_p50), ("cost_pp", cost_p50)):
        out[k] = {"label": TARGETS[k]["label"], "unit": TARGETS[k]["unit"], "p10": p50, "p50": p50}
    return out


def test_headline_lists_the_breaking_shocks():
    h = headline(_rs())
    assert h.startswith("A 50% chance of running out of cash takes any one of:")
    assert "of 40%" in h and "of 12pp" in h and "rate" not in h


def test_headline_says_when_the_baseline_already_breaches():
    lo = {k: TARGETS[k]["lo"] for k in TARGETS}
    h = headline(_rs(lo["sales_depth"], lo["rate_bp"], lo["cost_pp"]))
    assert h == "Even with no shock the chance of running out of cash is already 50% or more."
    assert headline(_rs(None, None, None)) == "No single shock in the tested ranges breaks the company."


def _company() -> dict:
    preset = {
        "health_score": 62.0,
        "health_p10": 40.0,
        "p_breach": 0.02,
        "p_icr_below_1_5": 0.1,
        "p_downgrade_below_ig": 0.1,
    }
    return {
        "ticker": "TST",
        "name": "Test Co",
        "sector": "Industrials",
        "n_paths": 3000,
        "params": {
            "last_quarter": "2025-12-31",
            "horizon": 12,
            "cash0": 500e6,
            "debt0": 2e9,
            "maturities_q": [100e6] * 12,
            "revolver_cap": 300e6,
            "ddays": 5.0,
            "F": 300e6,
            "v": 0.5,
            "mu": 0.01,
            "sigma_g": 0.05,
            "coupon": 0.05,
            "_sources": {},
        },
        "history": {"series": {"rating": [9, 9, 10, 10], "revenue": [1e9, 1.1e9, 1e9, 1.2e9]}},
        "presets": {"base": dict(preset), "sales_20": {**preset, "health_score": 45.0, "p_breach": 0.08}},
        "reverse_stress": _rs(),
        "tornado": [
            {"knob": "sales_depth", "value": 0.3, "label": "Revenue -30%", "d_health": -12.0, "d_p_breach": 0.05},
            {"knob": "rate_bp", "value": 300, "label": "Rates +300bp", "d_health": -2.0, "d_p_breach": 0.0},
        ],
    }


META = {
    "presets": {
        "base": {"label": "Baseline", "desc": "no shock"},
        "sales_20": {"label": "Sales -20%", "desc": "Revenue falls 10%, then 20%, then recovers over 6 quarters."},
    }
}


def test_note_uses_the_run_settings():
    c = _company()
    note = write_note(c, META)
    assert "Across 3,000 simulated 12-quarter futures" in note["summary"]
    demand = next(r for r in note["key_risks"] if r["risk"] == "Demand sensitivity")
    assert demand["evidence"].startswith("A 30% revenue fall")
    assert "fixed costs are about" in demand["evidence"]
    assert "breaks (50% breach odds) at a 40% revenue drop" in note["headline"]


def test_note_without_a_breaking_revenue_drop_names_the_tested_range():
    c = _company()
    c["reverse_stress"] = _rs(sales_p50=None)
    note = write_note(c, META)
    hi, dur = TARGETS["sales_depth"]["hi"], TARGETS["sales_depth"]["base"]["sales_duration"]
    assert f"can fund itself even through a {hi:.0%} revenue drop over {dur} quarters" in note["headline"]


def test_note_when_the_baseline_already_breaches():
    c = _company()
    c["reverse_stress"] = _rs(sales_p50=TARGETS["sales_depth"]["lo"])
    note = write_note(c, META)
    assert "already has even odds of running out of cash with no revenue shock" in note["headline"]
    assert "0% revenue drop" not in note["headline"]


def test_note_skips_the_fixed_share_when_a_quarter_is_missing():
    c = copy.deepcopy(_company())
    c["history"]["series"]["revenue"][-2] = None
    note = write_note(c, META)
    demand = next(r for r in note["key_risks"] if r["risk"] == "Demand sensitivity")
    assert "fixed costs" not in demand["evidence"] and demand["evidence"].endswith("percentage points.")
    assert note["fact_sheet"]["reported"]["revenue_last_4_quarters"].startswith("n/a")
