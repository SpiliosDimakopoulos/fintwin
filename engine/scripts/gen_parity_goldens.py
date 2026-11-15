"""Regenerate the Python/TypeScript parity goldens that need no network data (SW-1).

uv run python scripts/gen_parity_goldens.py            # from engine/

1. Adds every output key to the existing ticker goldens (web/src/engine/__golden__/{TICKER}_{preset}.json, written by
   fintwin.export.golden_cases with 12 of 29 keys), re-simulating the stored params/eps/levers/knobs. Params, eps and
   knobs are not touched.
2. Writes synthetic-firm goldens (synth_*.json) covering sector_tol != 1, a recession start state and the revision-3
   switches on and off (F3, F6, F11, M1 with a revolver maturity, M5 reit/utility, F7/F8 shock keys), with ALL outputs and,
   where relevant, the M7 decision outputs. Cheap (64 paths x 12 quarters), safe to run on any PC.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE / "tests"))
from conftest import make_params  # noqa: E402

from fintwin.model import sd_model  # noqa: E402
from fintwin.scenarios.presets import DEFAULT_LEVERS, PRESETS, build_scenario  # noqa: E402
from fintwin.stochastic import spec  # noqa: E402
from fintwin.stochastic.shocks import draw_shocks  # noqa: E402

GOLDEN = ENGINE.parent / "web" / "src" / "engine" / "__golden__"
N, T = 64, 12
OFF = {k: False for k in ("F3", "F6", "F11", "M1", "M5")}
# M7 decision outputs are computed only for cases with a stated liquidity threshold
M7_X = 150.0


def _js(o):
    if isinstance(o, dict):
        return {k: _js(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_js(v) for v in o]
    if isinstance(o, np.ndarray):
        return _js(o.tolist())
    if isinstance(o, (np.floating, np.integer, np.bool_)):
        return o.item()
    return o


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(_js(obj), allow_nan=False, separators=(",", ":")), encoding="utf-8")


def expected_all(out: dict) -> dict:
    return {k: v for k, v in out.items() if k != "identity_gap"}


def run(p, knobs, levers, eps):
    with spec.using("v2-pre", "none"):  # explicit lever keys decide; the environment must not
        return sd_model.simulate(p, build_scenario(knobs, p["horizon"]), eps, levers)


def augment_existing() -> int:
    n = 0
    for f in sorted(GOLDEN.glob("*.json")):
        if f.name.startswith("synth_"):
            continue
        g = json.loads(f.read_text(encoding="utf-8"))
        eps = np.asarray(g["eps"], float)
        out = run(g["params"], g["knobs"], g["levers"], eps)
        g["expected"] = expected_all(out)
        _write(f, g)
        n += 1
    return n


def lev(**over) -> dict:
    return {**DEFAULT_LEVERS, **OFF, **over}


def synthetic_cases() -> dict[str, tuple[dict, dict, dict, bool]]:
    pand = PRESETS["pandemic"]["knobs"]
    crunch = PRESETS["credit_crunch"]["knobs"]
    lev_firm = dict(debt0=2600.0, interest_ttm0=[40.0] * 4, ebit_ttm0=[70.0] * 4, ebitda_ttm0=[120.0] * 4)
    net_cash = dict(debt0=60.0, cash0=900.0, interest_ttm0=[0.2] * 4, maturities_q=[5.0] * 12, coupon=0.04)
    v3 = dict(t_scale=0.93, t_mix_indep=1.0, m_dev0=0.04, fixed_adj_lambda=0.35, fixed_adj_lambda_down=0.15, fixed_adj_f=0.27)
    return {
        # sector tolerance and recession start state, no switches (the v2-rev product path)
        "synth_sector_tol": (make_params(sector_tol=1.8, **lev_firm), pand, lev(), False),
        "synth_sector_tol_low": (make_params(sector_tol=0.6, **lev_firm), crunch, lev(), False),
        "synth_rec_state0": (make_params(rec_state0=1.0, **lev_firm), {}, lev(), False),
        "synth_rec_state0_tol": (make_params(rec_state0=1.0, sector_tol=1.5), pand, lev(issue_equity=True), False),
        # switches off with their keys present: must equal the plain run
        "synth_v3keys_switches_off": (make_params(**v3), pand, lev(), False),
        # single switches on
        "synth_f6": (make_params(m_dev0=0.04), {}, lev(F6=True), False),
        "synth_f3_lambda05": (make_params(fixed_adj_lambda=0.5, fixed_adj_f=0.27), PRESETS["pandemic"]["knobs"], lev(F3=True), False),
        "synth_f3_asym": (make_params(fixed_adj_lambda=0.4, fixed_adj_lambda_down=0.1, fixed_adj_f=0.3), crunch, lev(F3=True), False),
        "synth_f11_netcash": (make_params(**net_cash), crunch, lev(F11=True), False),
        "synth_f11_off_netcash": (make_params(**net_cash), crunch, lev(), False),
        "synth_m1_maturity": (
            make_params(revolver_maturity_q=6, cov_revolver_avail=0.0, revolver_cap=300.0, **lev_firm),
            PRESETS["credit_crunch"]["knobs"],
            lev(M1=True),
            True,
        ),
        "synth_m1_f11_nocov_icr": (
            make_params(cov_max_nd_ebitda=None, cov_min_icr=3.5, cov_cure_q=0, cov_revolver_avail=0.3, **lev_firm),
            pand,
            lev(M1=True, F11=True),
            True,
        ),
        "synth_m5_reit": (make_params(payout_class="reit", div_q=5.0), pand, lev(M5=True), False),
        "synth_m5_utility": (make_params(payout_class="utility", div_q=12.0, **lev_firm), pand, lev(M5=True), False),
        # everything revision-3 at once, with F7/F8 shock keys and F3/F6 values
        "synth_v3_all": (
            make_params(payout_class="reit", revolver_maturity_q=8, **v3, **lev_firm),
            crunch,
            lev(F3=True, F6=True, F11=True, M1=True, M5=True),
            True,
        ),
    }


def main() -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    print(f"augmented {augment_existing()} existing goldens with all output keys")
    for name, (p, knobs, levers, decisions) in synthetic_cases().items():
        eps = draw_shocks(p, N, p["horizon"], seed=11)
        out = run(p, knobs, levers, eps)
        g = {"params": p, "knobs": knobs, "levers": levers, "eps": eps, "expected": expected_all(out)}
        if decisions:
            g["decisions"] = sd_model.decision_outputs(out, p, x=M7_X)
        _write(GOLDEN / f"{name}.json", g)
        note = ""
        if "cov_breach" in out:
            note = f" cov_breach_end={out['cov_breach'][:, -1].mean():.2f}"
        print(f"{name}: breach={out['breach'][:, -1].mean():.2f} rating_end={out['rating'][:, -1].mean():.1f}{note}")


if __name__ == "__main__":
    main()
