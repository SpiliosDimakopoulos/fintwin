"""JSON-safe conversion, a leaf module: shards import it without pulling in `export` and its dependencies, so the shard
code digest (research/__main__._code_digest) covers only code that can change a shard."""

from __future__ import annotations

import math

import numpy as np


def _clean(o, sig: int = 10):
    """JSON-safe: numpy -> python, NaN/inf -> None, floats rounded to `sig` significant digits."""
    if isinstance(o, dict):
        return {str(k): _clean(v, sig) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v, sig) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist(), sig)
    if isinstance(o, (np.floating, float)):
        x = float(o)
        return None if not math.isfinite(x) else (x if sig >= 17 else float(f"{x:.{sig}g}"))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o
