"""Reverse stress testing: instead of "what happens if X", ask "how big must X be to break the company?"."""

from __future__ import annotations

from typing import Any

from ..stochastic.mc import run, summarize
from ..stochastic.shocks import draw_shocks

TARGETS: dict[str, dict[str, Any]] = {
    "sales_depth": {
        "lo": 0.0,
        "hi": 0.95,
        "base": {"sales_duration": 3, "sales_recovery": 6},
        "label": "Revenue drop (held 3 quarters)",
        "unit": "pct",
    },
    "rate_bp": {"lo": 0.0, "hi": 1500.0, "base": {}, "label": "Interest-rate rise", "unit": "bp"},
    "cost_pp": {"lo": 0.0, "hi": 40.0, "base": {"cost_duration": 8}, "label": "Variable-cost increase", "unit": "pp"},
}


def breaking_point(
    p: dict, knob: str, target_p: float = 0.5, n_paths: int = 2000, seed: int = 21, iters: int = 18
) -> float | None:
    """Smallest shock size at which P(liquidity breach within horizon) >= target_p.

    Uses common random numbers so P(breach) is monotone in the shock size and bisection is well-posed.
    Returns None if even the largest shock considered does not reach the target.
    """
    spec = TARGETS[knob]
    eps = draw_shocks(p, n_paths, p["horizon"], seed)

    def prob(x: float) -> float:
        return summarize(run(p, {**spec["base"], knob: x}, eps=eps))["p_breach"]

    lo, hi = spec["lo"], spec["hi"]
    if prob(lo) >= target_p:
        return lo
    if prob(hi) < target_p:
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if prob(mid) >= target_p:
            hi = mid
        else:
            lo = mid
    return float(hi)


def reverse_stress(p: dict, n_paths: int = 2000) -> dict:
    out = {}
    for knob, spec in TARGETS.items():
        out[knob] = {
            "label": spec["label"],
            "unit": spec["unit"],
            "p10": breaking_point(p, knob, 0.10, n_paths),
            "p50": breaking_point(p, knob, 0.50, n_paths),
        }
    return out


def _fmt(x: float, unit: str) -> str:
    return f"{x * 100:.0f}%" if unit == "pct" else f"{x:.0f}{unit}"


def headline(rs: dict, level: str = "p50") -> str:
    """One sentence for the reverse-stress result (M4): the smallest single shock that breaks the company."""
    hits = [(k, v) for k, v in rs.items() if v.get(level) is not None]
    if not hits:
        return "No single shock in the tested ranges breaks the company."
    share = level[1:]
    parts = [f"{v['label'].lower()} of {_fmt(v[level], v['unit'])}" for _, v in hits]
    return f"A {share}% chance of running out of cash takes any one of: " + "; ".join(parts) + "."
