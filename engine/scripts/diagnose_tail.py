"""Diagnose one exploding v3 firm-year (paper, Table tails): calibrate at the cutoff and run the transmission design.

    uv run python scripts/diagnose_tail.py CRSP 2021-02-15

Reads live EDGAR data unless FINTWIN_FROZEN=1 with a restored snapshot; prints the F3 fixed-cost target ratio
(fixed_adj_f = F / base revenue) and the simulated against realized quarterly cash flow (% of trailing revenue)."""
import os
import sys

os.environ.setdefault("FINTWIN_SPEC", "v3")
os.environ.setdefault("FINTWIN_SELECTION", "out/rerun5_results/research/_selection/v3.json")

import numpy as np  # noqa: E402

from fintwin.data.facts import load_company  # noqa: E402
from fintwin.research import experiments as E  # noqa: E402

ticker, origin = sys.argv[1], sys.argv[2]
full = load_company(ticker)
hist = load_company(ticker, asof=origin)
q = hist.quarters
print("last known quarters (revenue, opex-ish):")
cols = [c for c in ("revenue", "operating_income", "cfo", "da") if c in q]
print(q[cols].tail(8).round(1).to_string())
p = E.calibrate(hist, E.macro_quarterly(origin), 12)
keys = ["fixed_costs", "F", "var_ratio", "v", "fixed_share", "prior_weight", "prior_tau", "lam", "fixed_adjust", "base_rev",
        "cfo_resid", "tax_rate", "seasonal"]
for k in sorted(p):
    v = p[k]
    if isinstance(v, (int, float, np.floating)) and any(s in k.lower() for s in ("fix", "var", "prior", "tau", "lam", "base", "resid", "tax", "margin", "cost")):
        print(f"  {k} = {v}")
s = E.structural(hist, p, full.quarters)
print("structural keys:", list(s)[:30])
for k in ("rev_ttm", "real_cfo", "twin_cfo", "real", "twin"):
    if k in s:
        print(k, s[k] if not isinstance(s[k], (list, dict)) else str(s[k])[:400])
nxt = full.quarters.loc[full.quarters.index > q.index[-1]].head(8)
print("realized next 8 quarters revenue/cfo:")
print(nxt[[c for c in ("revenue", "cfo") if c in nxt]].round(1).to_string())
