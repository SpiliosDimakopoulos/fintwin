"""Rule-based analyst notes: a credit-memo-style narrative generated deterministically from simulation output.

No language model and no API key: every sentence is a template filled with numbers taken straight from the
company's exported results, so the figures are correct by construction. The optional LLM memo module
(fintwin.memo) writes freer prose from the same fact sheet when an API key is available.

    uv run python -m fintwin.notes            # all companies in the snapshot
    uv run python -m fintwin.notes CCL AAPL
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .model.ratings import INVESTMENT_GRADE_MIN_RANK, RATINGS
from .scenarios.reverse_stress import TARGETS

DATA = Path(__file__).resolve().parents[2] / "web" / "public" / "data"
RULE_BASED = "FinTwin rule-based analyst"


def _money(x: float) -> str:
    a = abs(x)
    s = "−" if x < 0 else ""
    return f"{s}${a / 1e9:.1f}B" if a >= 1e9 else f"{s}${a / 1e6:.0f}M"


def _pct(x: float, d: int = 0) -> str:
    return f"{x * 100:.{d}f}%"


def _ttm_revenue(c: dict) -> float | None:
    """Revenue over the last 4 quarters; None when one is missing, which would silently understate the sum."""
    last4 = c["history"]["series"]["revenue"][-4:]
    return sum(last4) if len(last4) == 4 and all(x is not None for x in last4) else None


def fact_sheet(c: dict, meta: dict) -> dict:
    """Compact, human-readable facts used by both the rule-based notes and the optional LLM memo."""
    p = c["params"]
    hist = c["history"]["series"]
    last_rating = next((r for r in reversed(hist["rating"]) if r is not None), None)
    rev_ttm = _ttm_revenue(c)
    sheet = {
        "company": c["name"],
        "ticker": c["ticker"],
        "sector": c["sector"],
        "last_reported_quarter": p["last_quarter"],
        "horizon_quarters": p["horizon"],
        "simulated_paths": c.get("n_paths", 5000),
        "reported": {
            "revenue_last_4_quarters": _money(rev_ttm) if rev_ttm is not None else "n/a (a quarter is missing)",
            "cash_and_short_term_investments": _money(p["cash0"]),
            "total_debt": _money(p["debt0"]),
            "synthetic_rating_today": RATINGS[int(last_rating)] if last_rating is not None else "n/a",
            "debt_maturing_next_4_quarters": _money(sum(p["maturities_q"][:4])),
            "committed_credit_facility": _money(p["revolver_cap"]),
            "customer_deposits_days_of_revenue": round(p["ddays"]),
        },
        "calibrated_structure": {
            "fixed_costs_per_quarter": _money(p["F"]),
            "variable_cost_share_of_revenue_pct": round(p["v"] * 100),
            "trend_growth_pct_per_year": round(((1 + p["mu"]) ** 4 - 1) * 100, 1),
            "demand_volatility_pct_per_quarter": round(p["sigma_g"] * 100, 1),
            "average_cost_of_debt_pct": round(p["coupon"] * 100, 1),
            "revenue_sensitivity_to_gdp": round(p.get("beta_gdp", 1.5), 1),
        },
        "scenarios": {},
        "reverse_stress": {},
        "sensitivity_tornado_health_change": {t["label"]: round(t["d_health"], 1) for t in c["tornado"]},
    }
    for key, v in c["presets"].items():
        sheet["scenarios"][meta["presets"][key]["label"]] = {
            "description": meta["presets"][key]["desc"],
            "health_score_0_100": round(v["health_score"]),
            "health_score_unluckiest_10pct": round(v["health_p10"]),
            "prob_liquidity_breach_pct": round(v["p_breach"] * 100, 1),
            "prob_interest_coverage_below_1_5x_pct": round(v["p_icr_below_1_5"] * 100),
            "prob_sub_investment_grade_at_horizon_pct": round(v["p_downgrade_below_ig"] * 100),
        }
    for r in c["reverse_stress"].values():
        unit = {"pct": "% revenue drop", "bp": "bp rate rise", "pp": "pp cost increase"}[r["unit"]]
        conv = (lambda v: round(v * 100)) if r["unit"] == "pct" else (lambda v: round(v))
        sheet["reverse_stress"][r["label"]] = {
            "shock_for_50pct_breach": f"{conv(r['p50'])}{unit}"
            if r["p50"] is not None
            else "not reached (company can fund itself)",
            "shock_for_10pct_breach": f"{conv(r['p10'])}{unit}" if r["p10"] is not None else "not reached",
        }
    if c.get("sobol"):
        sheet["global_sensitivity_total_order_pct"] = {
            r["label"]: round(min(r["ST"], 1) * 100) for r in c["sobol"]["rows"]
        }
    return sheet


def _verdict(h: float) -> str:
    """Same bands and labels as the dashboard's health status pill."""
    return "Healthy" if h >= 70 else "Watch" if h >= 50 else "Strained" if h >= 30 else "Distressed"


def write_note(c: dict, meta: dict) -> dict:
    p, pr = c["params"], c["presets"]
    base = pr["base"]
    h = base["health_score"]
    labels = {k: meta["presets"][k]["label"] for k in pr}
    worst_key = min((k for k in pr if k != "base"), key=lambda k: pr[k]["health_score"])
    worst = pr[worst_key]
    rating_hist = [r for r in c["history"]["series"]["rating"] if r is not None]
    rating = RATINGS[int(rating_hist[-1])] if rating_hist else None
    rev_ttm = _ttm_revenue(c)
    mat4 = sum(p["maturities_q"][:4])
    fixed_share = p["F"] / max(p["F"] + p["v"] * rev_ttm / 4, 1e-9) if rev_ttm is not None else None
    rs = c["reverse_stress"]["sales_depth"]
    rs_t = TARGETS["sales_depth"]
    n_paths = c.get("n_paths", 5000)
    tornado = sorted(c["tornado"], key=lambda t: t["d_health"])
    sob = c.get("sobol")
    verdict = _verdict(h)

    # ---- headline & summary ----
    if rs["p50"] is None:
        breaking = (
            f"can fund itself even through a {_pct(rs_t['hi'])} revenue drop over "
            f"{rs_t['base']['sales_duration']} quarters"
        )
    elif rs["p50"] == rs_t["lo"]:  # breaking_point returns the lower bound when the baseline already breaches
        breaking = "already has even odds of running out of cash with no revenue shock"
    else:
        breaking = f"breaks (50% breach odds) at a {_pct(rs['p50'])} revenue drop"
    headline = (
        f"{verdict} credit profile: health {h:.0f}/100 under baseline, {worst['health_score']:.0f} under "
        f"{labels[worst_key].lower()}; the company {breaking}."
    )
    summary = [
        f"{c['name']} enters the simulation with {_money(p['cash0'])} of cash and short-term investments against "
        f"{_money(p['debt0'])} of debt"
        + (f" and a synthetic {rating} rating from interest coverage." if rating else ".")
    ]
    summary.append(
        f"Across {n_paths:,} simulated {p['horizon']}-quarter futures the median health score is {h:.0f}, with the "
        f"unluckiest tenth of paths at {base['health_p10']:.0f} or below and a {_pct(base['p_breach'], 1)} chance "
        "of exhausting liquidity under business as usual."
    )
    if sob and not sob["insensitive"]:
        top = sob["rows"][0]
        summary.append(
            f"Globally, {top['label'].lower()} explains about {_pct(min(top['ST'], 1))} of the variance of the "
            f"health score across the stress space, and interactions between shocks add {_pct(sob['interaction_share'])}."
        )
    else:
        summary.append(
            f"The most damaging single shock is {tornado[0]['label'].lower()}, which moves the health score by "
            f"{tornado[0]['d_health']:+.1f} points."
        )

    # ---- risks ----
    risks = []
    rev_t = next((t for t in c["tornado"] if t["knob"] == "sales_depth"), None)
    if rev_t and rev_t["d_health"] < -5:
        evidence = (
            f"A {_pct(rev_t['value'])} revenue fall lowers the health score by {abs(rev_t['d_health']):.1f} points and "
            f"raises breach odds by {rev_t['d_p_breach'] * 100:.1f} percentage points"
        )
        if fixed_share is not None:
            evidence += (
                f"; fixed costs are about {_pct(fixed_share)} of the cost base, so losses scale faster than revenue"
            )
        risks.append({"risk": "Demand sensitivity", "evidence": evidence + "."})
    elif fixed_share is not None and fixed_share > 0.4:
        risks.append(
            {
                "risk": "Operating leverage",
                "evidence": f"Fixed costs are about {_pct(fixed_share)} of the cost base ({_money(p['F'])} a quarter).",
            }
        )
    if mat4 > p["cash0"]:
        risks.append(
            {
                "risk": "Refinancing wall",
                "evidence": f"{_money(mat4)} of debt matures in the next four quarters against {_money(p['cash0'])} "
                "of cash; repayment depends on continued market access.",
            }
        )
    if base["p_icr_below_1_5"] > 0.2:
        risks.append(
            {
                "risk": "Thin interest coverage",
                "evidence": f"In {_pct(base['p_icr_below_1_5'])} of baseline paths trailing coverage falls below 1.5×, "
                "the point where market access narrows and spreads jump.",
            }
        )
    if base["p_breach"] > 0.05:
        risks.append(
            {
                "risk": "Liquidity under normal conditions",
                "evidence": f"Even without a stress scenario, {_pct(base['p_breach'], 1)} of paths run out of cash "
                "after drawing the revolver and tapping available debt markets.",
            }
        )
    if p["ddays"] > 30:
        risks.append(
            {
                "risk": "Customer-deposit refunds",
                "evidence": f"About {p['ddays']:.0f} days of revenue are held as customer deposits; a demand stop "
                "turns them into a cash outflow on top of operating losses.",
            }
        )
    if base["p_downgrade_below_ig"] > 0.25:
        risks.append(
            {
                "risk": "Downgrade to speculative grade",
                "evidence": f"{_pct(base['p_downgrade_below_ig'])} of baseline paths end the horizon below BBB.",
            }
        )
    if not risks:
        risks.append(
            {
                "risk": "Severe demand collapse",
                "evidence": f"Only an extreme scenario ({labels[worst_key].lower()}) moves the health score "
                f"materially, to {worst['health_score']:.0f}.",
            }
        )

    # ---- resilience ----
    resilience = []
    if p["cash0"] >= mat4:
        resilience.append(f"Cash of {_money(p['cash0'])} covers the next four quarters of maturities ({_money(mat4)}).")
    if p["revolver_cap"] > 0:
        assumed = p.get("_sources", {}).get("revolver_cap", "").startswith("assumption")
        resilience.append(
            f"A committed credit facility of about {_money(p['revolver_cap'])} backstops liquidity"
            + (" (size assumed: not tagged in filings)." if assumed else ".")
        )
    if rating_hist and rating_hist[-1] >= INVESTMENT_GRADE_MIN_RANK:
        resilience.append(
            f"Interest coverage implies an investment-grade synthetic rating ({rating}), keeping refinancing cheap."
        )
    if c["reverse_stress"]["rate_bp"]["p50"] is None:
        resilience.append(
            f"No interest-rate rise up to {TARGETS['rate_bp']['hi']:,.0f}bp produces even odds of a liquidity breach."
        )
    if rs["p50"] is None or rs["p50"] > 0.5:
        resilience.append("It would take a revenue collapse of more than half to make a cash shortfall likely.")
    resilience = resilience[:4] or ["Few structural buffers: resilience relies on market access and management cuts."]

    # ---- scenario notes ----
    notes = []
    for k in sorted((k for k in pr if k != "base"), key=lambda k: pr[k]["health_score"]):
        v = pr[k]
        d = round(v["health_score"]) - round(h)
        notes.append(
            {
                "scenario": labels[k],
                "note": f"Health {v['health_score']:.0f} ({'+' if d >= 0 else '−'}{abs(d):.0f} vs baseline), breach probability "
                f"{_pct(v['p_breach'], 1)}, sub-investment-grade at horizon {_pct(v['p_downgrade_below_ig'])}.",
            }
        )

    # ---- watch list ----
    watch = [
        f"Quarterly cash relative to the next 12 months of maturities (now {_money(p['cash0'])} vs {_money(mat4)})."
    ]
    watch.append(
        f"Variable-cost ratio versus the calibrated {_pct(p['v'])} of revenue: a sustained rise signals margin squeeze."
    )
    if p["ddays"] > 30:
        watch.append("Customer-deposit balance: falling deposits are the earliest sign of weakening forward demand.")
    watch.append("Trailing interest coverage approaching 1.5×, where the twin's market-access loop starts to bind.")

    return {
        "ticker": c["ticker"],
        "generated_by": f"{RULE_BASED} (deterministic, no language model)",
        "as_of": p["last_quarter"],
        "attempts": 1,
        "unverified_numbers": [],
        "fact_sheet": fact_sheet(c, meta),
        "verdict": verdict,
        "headline": headline,
        "summary": " ".join(summary),
        "key_risks": risks[:5],
        "resilience": resilience,
        "scenario_notes": notes,
        "watch_list": watch,
    }


def _is_rule_based(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("generated_by", "").startswith(RULE_BASED)
    except (OSError, ValueError):
        return True  # unreadable file: safe to regenerate


def build(tickers: list[str] | None = None) -> None:
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    out = DATA / "memos"
    out.mkdir(exist_ok=True)
    written = 0
    for t in tickers or sorted(index["companies"]):
        c = json.loads((DATA / "companies" / f"{t}.json").read_text(encoding="utf-8"))
        path = out / f"{t}.json"
        if path.exists() and not _is_rule_based(path):
            continue  # never overwrite a committed Claude memo (fintwin.memo writes the same path)
        note = write_note(c, index["meta"])
        path.write_text(json.dumps(note, indent=1, ensure_ascii=False), encoding="utf-8")
        written += 1
    print(f"wrote {written} analyst notes")


if __name__ == "__main__":
    build([a.upper() for a in sys.argv[1:]] or None)
