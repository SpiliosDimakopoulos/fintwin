"""Quick console view of forecast + structural backtests."""

import argparse

from fintwin.backtest.walk_forward import forecast_backtest

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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    for t in args.tickers:
        for c in ["pre_covid", "pre_hikes"]:
            r = forecast_backtest(t, c)
            cov = {
                v: (round(s["coverage50"], 2), round(s["coverage90"], 2), round(s["crps_skill"], 2))
                for v, s in r["scores"].items()
            }
            st = r["structural"]
            print(
                f"{t:5s} {c:9s} cov50/cov90/skill={cov} struct_err={st.get('final_error_pct', float('nan')):.0f}% "
                f"corr={st.get('corr') or float('nan'):.2f} base_health={r['pre_shock']['base']['health_score']:.0f} "
                f"stress_pbreach={r['pre_shock']['stress']['p_breach']:.2f}"
            )


if __name__ == "__main__":
    main()
