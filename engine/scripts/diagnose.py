"""Print calibrated parameters and headline stress results for a set of tickers."""

import argparse
import time

import numpy as np

from fintwin.data.facts import load_company
from fintwin.data.fred import macro_quarterly
from fintwin.scenarios.presets import PRESETS
from fintwin.stochastic.calibrate import calibrate
from fintwin.stochastic.mc import run, summarize

DEFAULT_TICKERS = ["AAPL", "TSLA", "CCL", "BA", "INTC", "NFLX"]
KEYS = [
    "mu",
    "phi",
    "sigma_g",
    "t_df",
    "v",
    "sigma_m",
    "dso",
    "dio",
    "dpo",
    "dep_rate",
    "capex_ratio",
    "ocf_ratio",
    "coupon",
    "bb_ratio",
    "tax_rate",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tickers",
        nargs="*",
        default=DEFAULT_TICKERS,
        help="Tickers to evaluate (default: %(default)s)",
    )
    parser.add_argument(
        "--asof",
        default=None,
        help="Cutoff date in YYYY-MM-DD format (default: None)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    macro = macro_quarterly(args.asof)
    for t in args.tickers:
        p = calibrate(load_company(t, asof=args.asof), macro)
        print(
            "==",
            t,
            p["last_quarter"],
            {k: round(p[k], 4) for k in KEYS},
            f"F={p['F'] / 1e9:.2f}bn cash={p['cash0'] / 1e9:.1f}bn debt={p['debt0'] / 1e9:.1f}bn rcf={p['revolver_cap'] / 1e9:.1f}bn",
        )
        for s in ["base", "rates_200", "sales_20", "recession", "pandemic", "credit_crunch"]:
            t0 = time.time()
            out = run(p, PRESETS[s]["knobs"], n_paths=5000)
            sm = summarize(out)
            print(
                f"  {s:14s} health={sm['health_score']:5.1f} p_breach={sm['p_breach']:.3f} "
                f"p_icr<1.5={sm['p_icr_below_1_5']:.3f} subIG={sm['p_downgrade_below_ig']:.2f} "
                f"idgap={np.abs(out['identity_gap']).max():.1e} {time.time() - t0:.2f}s"
            )


if __name__ == "__main__":
    main()
