"""Ablation: forecast backtest with vs without the recession regime (same shocks, same cutoffs)."""

import argparse
import json

import numpy as np
import pandas as pd

import fintwin.scenarios.presets as presets
from fintwin.backtest import walk_forward as wf

DEFAULT_TICKERS = ["AAPL", "TSLA", "CCL", "BA", "INTC", "NFLX"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tickers",
        nargs="*",
        default=DEFAULT_TICKERS,
        help="Tickers to evaluate (default: %(default)s)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def aggregate(flag: bool, tickers: list[str] | None = None) -> dict:
    if tickers is None:
        tickers = DEFAULT_TICKERS
    presets.DEFAULT_LEVERS["recessions"] = flag
    rows = []
    for t in tickers:
        for ck in wf.CUTOFFS:
            r = wf.forecast_backtest(t, ck)
            for var, s in r["scores"].items():
                rows.append(
                    {
                        "var": var,
                        "cov50": s["coverage50"],
                        "cov90": s["coverage90"],
                        "skill": s["crps_skill"],
                        "crps": s["crps"],
                        "n": s["n"],
                    }
                )
    df = pd.DataFrame(rows)
    return {
        v: {
            "coverage50": round(float(np.average(g.cov50, weights=g.n)), 3),
            "coverage90": round(float(np.average(g.cov90, weights=g.n)), 3),
            "median_crps_skill": round(float(g.skill.median()), 3),
            "share_beating_baseline": round(float((g.skill > 0).mean()), 3),
        }
        for v, g in df.groupby("var")
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    out = {"without_regime": aggregate(False, args.tickers), "with_regime": aggregate(True, args.tickers)}
    print(json.dumps(out, indent=1))
    json.dump(out, open("../web/public/data/ablation_regime.json", "w"), indent=1)


if __name__ == "__main__":
    main()
