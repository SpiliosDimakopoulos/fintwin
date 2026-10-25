"""Stress scenarios as a few interpretable knobs, expanded into per-quarter shock paths."""

from __future__ import annotations

from typing import Any

import numpy as np

KNOBS = {
    # name: (default, description)
    "sales_depth": (0.0, "Peak revenue drop vs. baseline (0.2 = -20%)"),
    "sales_duration": (2, "Quarters at the trough"),
    "sales_recovery": (6, "Quarters to recover to baseline"),
    "rate_bp": (0, "Parallel shift in the short rate, basis points (persistent)"),
    "spread_bp": (0, "Credit-spread widening, basis points"),
    "spread_duration": (4, "Quarters the spread shock lasts"),
    "cost_pp": (0.0, "Variable-cost ratio increase, percentage points"),
    "cost_duration": (4, "Quarters the cost shock lasts"),
    "dio_days": (0, "Extra inventory days (supply-chain shock)"),
    "refi_freeze": (0, "Quarters with debt markets closed"),
}

PRESETS: dict[str, dict[str, Any]] = {
    "base": {"label": "Baseline", "desc": "Calibrated business-as-usual dynamics.", "knobs": {}},
    "rates_200": {"label": "Rates +200bp", "desc": "Persistent 2pp rise in short rates.", "knobs": {"rate_bp": 200}},
    "sales_20": {
        "label": "Sales -20%",
        "desc": "Revenue falls 20%, holds 2 quarters, recovers over 6.",
        "knobs": {"sales_depth": 0.2},
    },
    "recession": {
        "label": "Recession",
        "desc": "Demand -12%, spreads +250bp, cost pressure, policy rate cuts.",
        "knobs": {
            "sales_depth": 0.12,
            "sales_duration": 3,
            "sales_recovery": 6,
            "rate_bp": -150,
            "spread_bp": 250,
            "spread_duration": 6,
            "cost_pp": 2.0,
            "cost_duration": 4,
        },
    },
    "pandemic": {
        "label": "Demand freeze",
        "desc": "2020-style shutdown: revenue -70%, markets shut 2 quarters.",
        "knobs": {
            "sales_depth": 0.7,
            "sales_duration": 3,
            "sales_recovery": 8,
            "spread_bp": 400,
            "spread_duration": 6,
            "refi_freeze": 2,
            "rate_bp": -150,
        },
    },
    "stagflation": {
        "label": "Stagflation (2022)",
        "desc": "Rates +300bp, input costs +3pp, mild demand dip.",
        "knobs": {
            "rate_bp": 300,
            "cost_pp": 3.0,
            "cost_duration": 6,
            "sales_depth": 0.05,
            "sales_duration": 2,
            "sales_recovery": 4,
        },
    },
    "credit_crunch": {
        "label": "Credit crunch",
        "desc": "Debt markets closed for a year, spreads +500bp.",
        "knobs": {"refi_freeze": 4, "spread_bp": 500, "spread_duration": 4},
    },
    "supply_chain": {
        "label": "Supply-chain shock",
        "desc": "Inventory +30 days, costs +3pp, sales -5%.",
        "knobs": {"dio_days": 30, "cost_pp": 3.0, "cost_duration": 4, "sales_depth": 0.05},
    },
    # Calibrated to 2008-09 data from FRED, with quarter 0 = 2008Q4 (the quarter after Lehman):
    # - sales: total business sales (TOTBUSSMSA, nominal like reported revenue) fell 20.3% from 2008Q2 to
    #   2009Q2 and were back at the old peak in 2011Q3; 3 quarters at the trough and 7 to recover is the
    #   least-squares fit of build_scenario's sales path to that drop at a 20% depth.
    # - spreads: Moody's Baa minus 10-year Treasury (BAA10Y) went from 1.63% (2007H1 average) to 5.58%
    #   (2008Q4 average), about +400bp, and stayed above half that widening for 3 quarters (2008Q4-2009Q2).
    # - refi_freeze: the two loan-officer surveys after Lehman (Oct 2008, Jan 2009) had a net 84% and 64%
    #   of banks tightening C&I standards (DRTSCILM); by Apr 2009 it was 40%.
    # - rate_bp: the 3-month bill (TB3MS) fell 500bp, from 5.03% (Feb 2007) to 0.03% (Dec 2008). -300bp is
    #   the lowest value the dashboard slider allows.
    # Input costs fell in 2008-09 (PPIACO -15% from 2008Q3 to 2009Q1), so there is no cost shock.
    "gfc_2008": {
        "label": "Financial crisis (2008)",
        "desc": "2008-09 style: revenue -20%, spreads +400bp, debt markets shut 2 quarters, rates -300bp.",
        "knobs": {
            "sales_depth": 0.2,
            "sales_duration": 3,
            "sales_recovery": 7,
            "spread_bp": 400,
            "spread_duration": 3,
            "refi_freeze": 2,
            "rate_bp": -300,
        },
    },
}

DEFAULT_LEVERS = {
    "recessions": True,
    "cut_capex": True,
    "cut_payouts": True,
    "issue_debt": True,
    "draw_revolver": True,
    "issue_equity": False,
    "cut_costs": True,
}


def knobs_with_defaults(knobs: dict) -> dict:
    return {k: knobs.get(k, d) for k, (d, _) in KNOBS.items()}


def build_scenario(knobs: dict, horizon: int) -> dict:
    k = knobs_with_defaults(knobs)
    T = horizon
    t = np.arange(T)

    depth, hold, rec = k["sales_depth"], int(k["sales_duration"]), max(int(k["sales_recovery"]), 1)
    sales = np.zeros(T)
    for i in t:
        if i < hold:
            sales[i] = -depth
        elif i < hold + rec:
            sales[i] = -depth * (1 - (i - hold + 1) / (rec + 1))
    # The demand shock hits revenue gradually: the first quarter takes half the blow.
    if T and hold > 0:
        sales[0] = -depth * 0.5 if hold > 1 else sales[0]

    ramp = np.minimum((t + 1) / 2.0, 1.0)
    return {
        "sales_shock": sales,
        "rate_shift": k["rate_bp"] / 1e4 * ramp,
        "spread_shift": np.where(t < int(k["spread_duration"]), k["spread_bp"] / 1e4, 0.0),
        "cost_shift": np.where(t < int(k["cost_duration"]), k["cost_pp"] / 100.0, 0.0),
        "dio_shift": np.full(T, float(k["dio_days"])),
        "refi_access": np.where(t < int(k["refi_freeze"]), 0.0, 1.0),
    }
