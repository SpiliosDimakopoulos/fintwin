"""Global (Sobol) sensitivity of the transmission result to every assumed parameter at once (plan 2, item 4.1).

    python -m fintwin.research sobol-shard 3 16   # -> .cache/sobol/<spec>/<key>_<year>.json
    python -m fintwin.research sobol-stats        # -> docs/paper/sobol_assumptions.json (and .cache/sobol/<spec>.json)

The one-at-a-time analysis varies each judgement call alone. Here all eight vary jointly over wide ranges in a Saltelli
design shared by every firm-year, so interactions show up. For a random sample of firm-years (cutoffs 2016-2022), each
design point recalibrates the twin, feeds it the realized revenue, and records its eight-quarter operating cash flow.
The outputs are the median absolute error across firm-years, the incremental correlation against the four-quarter
margin and the elasticity ratio (twin slope / realized slope on the revenue change), each as a function of the design
point; Sobol indices (Saltelli 2010, Jansen 1999) decompose their variance.

Revision 3 (P8, model_mechanics.md §3): the base sample is a scrambled Sobol sequence with N = 256 (not N = 64
pseudo-random points), and the confidence intervals resample firm-years as well as design points. With F1 on, the
prior's weight is replaced by its s.d. tau.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FACTORS_V2 = [
    ("fixed_share_prior", 0.02, 0.60, "calib", "Fixed-cost prior"),
    ("prior_weight", 0.0, 10.0, "calib", "Weight of the prior"),
    ("revolver_share", 0.02, 0.20, "calib", "Credit line when untagged"),
    ("growth_shrink", 0.0, 1.0, "calib", "Weight on own trend growth"),
    ("beta_shrink", 0.0, 1.0, "calib", "Weight on own GDP beta"),
    ("access_hi", 1.0, 3.0, "p", "Coverage below which access is cut"),
    ("cut_speed", 0.0, 0.10, "p", "Restructuring speed"),
    ("cut_floor", 0.70, 1.00, "p", "Restructuring floor"),
]
# under MM-F1 the weight is no longer a free constant: the data weight follows from n var(rev) / sigma^2, and the prior
# enters through its s.d. tau (B1's `prior_tau`, a multiple of the cost ratio)
TAU_FACTOR = ("prior_tau", 0.02, 0.60, "calib", "Prior s.d. (tau)")
N_BASE = 256  # a power of two, as the Sobol sequence requires for its balance properties
N_SAMPLE = 320
SEED = 41
CACHE_ROOT = Path(__file__).resolve().parents[2] / ".cache" / "sobol"
CACHE = CACHE_ROOT  # legacy name
OUT = Path(__file__).resolve().parents[3] / "docs" / "paper" / "sobol_assumptions.json"
# the specification of the paper's main results, evaluated on the same firm-years as a reference point
SPECIFIED_V2 = [0.35, 2.0, 0.08, 0.5, 0.5, 1.5, 0.04, 0.85]
SPECIFIED_TAU = 0.15


def factors() -> list[tuple]:
    from .experiments import fix_active

    return [TAU_FACTOR if f[0] == "prior_weight" else f for f in FACTORS_V2] if fix_active("F1") else list(FACTORS_V2)


FACTORS = FACTORS_V2  # module-level view for callers that import it; `factors()` follows the specification


def specified() -> list[float]:
    from .experiments import fix_active, research_prior

    s = list(SPECIFIED_V2)
    s[0] = research_prior()
    if fix_active("F1"):
        s[1] = SPECIFIED_TAU
    return s


def cache_dir() -> Path:
    from .experiments import spec_label

    return CACHE_ROOT / spec_label()


def design(
    n_base: int = N_BASE, seed: int = SEED, k: int | None = None
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Saltelli matrices A, B and AB_i from one scrambled Sobol sample of dimension 2k (A: first k, B: last k)."""
    from scipy.stats import qmc

    fs = factors()
    k = k or len(fs)
    lo = np.array([f[1] for f in fs[:k]])
    hi = np.array([f[2] for f in fs[:k]])
    u = qmc.Sobol(d=2 * k, scramble=True, seed=np.random.default_rng(seed)).random_base2(int(np.log2(n_base)))
    A = lo + u[:, :k] * (hi - lo)
    B = lo + u[:, k:] * (hi - lo)
    AB = [np.where(np.arange(k) == i, B, A) for i in range(k)]
    return A, B, AB


def points() -> np.ndarray:
    A, B, AB = design()
    return np.vstack([A, B, *AB, np.array([specified()])])


def sample(seed: int = 7) -> list[tuple[str, int]]:
    from .__main__ import research_tickers

    rng = np.random.default_rng(seed)
    keys = research_tickers()
    return [(keys[i], int(rng.integers(2016, 2023))) for i in rng.choice(len(keys), 4 * N_SAMPLE, replace=False)]


def _one(key: str, year: int, X: np.ndarray) -> dict | str:
    """The firm-year's outputs at every design point, or the reason it is excluded (a data rule, not an error)."""
    from ..data.facts import load_company
    from ..model.sd_model import simulate
    from ..scenarios.presets import DEFAULT_LEVERS, build_scenario
    from ..stochastic.shocks import draw_shocks
    from .experiments import _margin, _ttm, calibrate, fix_active, following, macro_quarterly, usable

    origin = f"{year}-02-15"
    hist = load_company(key, asof=origin)
    if not usable(hist, origin):
        return "not_usable"
    full = load_company(key).quarters
    pre = hist.quarters
    nxt, why = following(full, pre.index[-1], 8)  # empty if unreported ("short") or holding a gap row (D1)
    if why:
        return f"outcome_{why}"
    if nxt["revenue"].isna().any() or nxt["cfo"].isna().any():
        return "outcome_missing"
    rev_ttm = _ttm(pre, "revenue")
    if not rev_ttm > 50e6:
        return "small"
    m4 = _margin(pre, pre["cfo"], 4)
    if not np.isfinite(m4):
        return "no_margin"
    rev = nxt["revenue"].to_numpy(float)
    macro = macro_quarterly(origin)
    fs = factors()
    e1 = fix_active("E1")
    twin, twin_sm = [], []
    for x in X:
        calib = {f[0]: float(v) for f, v in zip(fs, x, strict=True) if f[3] == "calib"}
        pv = {f[0]: float(v) for f, v in zip(fs, x, strict=True) if f[3] == "p"}
        p = {**calibrate(hist, macro, 12, calib), "sector_tol": 1.0}
        p["access_icr"] = (pv["access_hi"], 0.53 * pv["access_hi"])
        p["cut_speed"], p["cut_floor"] = pv["cut_speed"], pv["cut_floor"]
        scn = build_scenario({}, 12)
        override = np.full(12, np.nan)
        override[:8] = rev
        scn["revenue_override"] = override
        sim = simulate(p, scn, draw_shocks(p, 200, 12, seed=3), DEFAULT_LEVERS)
        twin_sm.append(float(np.median(sim["cfo"][:, :8], axis=0).sum() / rev_ttm * 100))
        twin.append(float(np.median(sim["cfo"][:, :8].sum(1)) / rev_ttm * 100))
    return {
        "key": key,
        "year": year,
        "real": float(nxt["cfo"].sum() / rev_ttm * 100),
        "n1": float(m4 * rev.sum() / rev_ttm * 100),
        "rev_change": float(rev.sum() / rev_ttm * 100 / 2 - 100),
        "twin": twin if e1 else twin_sm,  # the specification's point forecast (E1 or the v2 sum of medians)
        "twin_sm": twin_sm,
        "n_base": N_BASE,
        "factors": [f[0] for f in fs],
    }


def shard(i: int, n: int) -> None:
    from ..export import _clean
    from .__main__ import _stamp_of, stamp

    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    X = points()
    st = stamp()
    done, failed, excluded = 0, {}, {}
    for k, (key, year) in enumerate(sample()):
        if k % n != i or done >= N_SAMPLE // n:
            continue
        out = d / f"{key}_{year}.json"
        if out.exists() and _stamp_of(out) == st:
            done += 1
            continue
        try:
            r = _one(key, year, X)
        except Exception as e:  # a firm that cannot be loaded is skipped, and counted by type (SW-3)
            failed[type(e).__name__] = failed.get(type(e).__name__, 0) + 1
            print(f"  {key} {year}: {type(e).__name__}: {e}", flush=True)
            continue
        if isinstance(r, str):  # a data exclusion (not usable, outcome window short or with a gap, ...), not an error
            excluded[r] = excluded.get(r, 0) + 1
            continue
        r["_stamp"] = st
        out.write_text(json.dumps(_clean(r)), encoding="utf-8")
        done += 1
        print(f"  {key} {year} done ({done})", flush=True)
    report = {"failed": failed, "excluded": excluded}  # exceptions by type vs data exclusions by reason
    (d / f"_failures_{i}_of_{n}.txt").write_text(json.dumps(report), encoding="utf-8")


def _est(fA: np.ndarray, fB: np.ndarray, fAB: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    var = np.var(np.concatenate([fA, fB]), ddof=1)
    if not var > 1e-12:  # a constant output has no variance to decompose
        nan = np.full(len(fAB), np.nan)
        return nan, nan
    s1 = np.array([np.mean(fB * (g - fA)) / var for g in fAB])
    st = np.array([0.5 * np.mean((fA - g) ** 2) / var for g in fAB])
    return s1, st


def indices(f: np.ndarray, n_base: int, k: int, rng: np.random.Generator, n_boot: int = 500, boot_f=None) -> list[dict]:
    """First-order (Saltelli 2010) and total (Jansen 1999) indices with bootstrap CIs. `boot_f`, if given, is a list
    of output vectors recomputed on firm-year resamples; each bootstrap draw then also resamples design points, so the
    interval covers both sources of noise. S1 is reported raw (not clipped to [0, ST])."""
    fs = factors()

    def split(v):
        return v[:n_base], v[n_base : 2 * n_base], [v[(2 + i) * n_base : (3 + i) * n_base] for i in range(k)]

    fA, fB, fAB = split(f)
    s1, st = _est(fA, fB, fAB)
    draws = []
    for b in range(n_boot):
        v = boot_f[b % len(boot_f)] if boot_f else f
        a, bb, ab = split(v)
        idx = rng.integers(0, n_base, n_base)
        draws.append(_est(a[idx], bb[idx], [g[idx] for g in ab]))
    b1, bt = np.array([d[0] for d in draws]), np.array([d[1] for d in draws])

    def ci(x):
        x = x[np.isfinite(x)]
        return np.percentile(x, [2.5, 97.5]).tolist() if len(x) else [None, None]

    return [
        {
            "factor": fs[i][0],
            "label": fs[i][4],
            "range": [fs[i][1], fs[i][2]],
            "S1": float(s1[i]),
            "ST": float(st[i]),
            "S1_ci": ci(b1[:, i]),
            "ST_ci": ci(bt[:, i]),
        }
        for i in range(k)
    ]


def _outputs(T: np.ndarray, real: np.ndarray, n1: np.ndarray, dx: np.ndarray) -> dict[str, np.ndarray]:
    """Per design point: median absolute error, incremental rank correlation and the elasticity ratio."""
    from scipy.stats import spearmanr

    mae = np.median(np.abs(T - real[:, None]), axis=0)
    incr = np.array([spearmanr(T[:, j] - n1, real - n1)[0] for j in range(T.shape[1])])
    out = {"median_ae": mae, "incremental": incr}
    if np.isfinite(dx).all() and np.std(dx) > 0:
        X = np.column_stack([np.ones(len(dx)), dx - dx.mean()])
        slope_real = np.linalg.lstsq(X, real, rcond=None)[0][1]
        slopes = np.linalg.lstsq(X, T, rcond=None)[0][1]
        out["elasticity_ratio"] = slopes / slope_real if slope_real else np.full(T.shape[1], np.nan)
    return out


def stats(n_boot: int = 500, seed: int = 3) -> dict:
    from scipy.stats import spearmanr

    d = cache_dir()
    rows = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))]
    stamps = {r.get("_stamp") for r in rows}
    if len(stamps) > 1:
        raise SystemExit(f"Sobol shards under {len(stamps)} stamps in {d}: rerun the stale ones")
    real = np.array([r["real"] for r in rows])
    n1 = np.array([r["n1"] for r in rows])
    dx = np.array([r.get("rev_change", np.nan) for r in rows], float)
    T_all = np.array([r["twin"] for r in rows])  # firm-years x design points (+ the specified point last)
    k = len(factors())
    has_ref = T_all.shape[1] == N_BASE * (k + 2) + 1
    T = T_all[:, :-1] if has_ref else T_all
    rng = np.random.default_rng(seed)
    outs = _outputs(T, real, n1, dx)
    # firm-year resamples of every output vector (the 320 firm-years are themselves a sample)
    boots: dict[str, list[np.ndarray]] = {name: [] for name in outs}
    for _ in range(min(n_boot, 200)):
        idx = rng.integers(0, len(rows), len(rows))
        o = _outputs(T[idx], real[idx], n1[idx], dx[idx])
        for name in boots:
            if name in o:
                boots[name].append(o[name])
    out: dict = {
        "n_firm_years": int(len(rows)),
        "n_points": int(T.shape[1]),
        "n_base": N_BASE,
        "design": "scrambled Sobol (scipy.stats.qmc), Saltelli A/B/AB_i",
        "factors": [f[0] for f in factors()],
        "specified": {
            "median_ae": float(np.median(np.abs(T_all[:, -1] - real))),
            "incremental": float(spearmanr(T_all[:, -1] - n1, real - n1)[0]),
        }
        if has_ref
        else None,
    }
    for name, f in outs.items():
        out[name] = {
            "mean": float(np.nanmean(f)),
            "min": float(np.nanmin(f)),
            "max": float(np.nanmax(f)),
            "indices": indices(f, N_BASE, k, rng, n_boot, boots[name] or None),
        }
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    (CACHE_ROOT / f"{d.name}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out
