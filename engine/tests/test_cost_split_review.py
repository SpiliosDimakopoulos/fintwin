"""External review of 14-11-2026, appendix: the fixed/variable cost split on synthetic firms.

The review showed that the revision-2 estimator returned a fixed share of about 0.24 for firms whose costs are
exactly proportional to revenue. As a result, it understated costs at current revenue by 1.4-3.2 points for growing
firms. The v3 estimator (`_posterior_split`) must recover both a true share of 0 and a true share of 0.35, and leave
no level bias at the firm's current size.
"""

import numpy as np
import pytest

from fintwin.stochastic.calibrate import _posterior_split

GROWTH = (0.0, 0.012, 0.03, -0.02)


def _cell(true_share: float, g: float, tau: float, n_firms: int = 400, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    t = np.arange(16)
    shares, bias = [], []
    for _ in range(n_firms):
        rev = 100 * np.exp(g * t) * np.exp(rng.normal(0, 0.03, 16))
        costs = true_share * 85.0 + 0.85 * (1 - true_share) * rev + rng.normal(0, 0.01, 16) * rev.mean()
        o = _posterior_split(rev, costs, 0.35, tau)
        F, v = o["F"], o["v"]
        shares.append(F / (F + v * rev.mean()))
        bias.append(((F + v * rev[-4:]).sum() - costs[-4:].sum()) / rev[-4:].sum() * 100)
    return float(np.mean(shares)), float(np.mean(bias))


@pytest.mark.parametrize("tau", [0.5, np.inf])
@pytest.mark.parametrize("g", GROWTH)
@pytest.mark.parametrize("true_share", [0.0, 0.35])
def test_split_recovers_share_and_has_no_level_bias(true_share, g, tau):
    share, bias = _cell(true_share, g, tau)
    assert abs(share - true_share) <= 0.06, f"estimated fixed share {share:.3f} for true {true_share}"
    assert abs(bias) <= 0.3, f"cost bias at current revenue {bias:+.2f} points of revenue"
