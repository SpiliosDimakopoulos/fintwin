"""REVISION_PLAN_5 T1/T2: the filing-text stage between the v4p pass and the v4t pass.

Layout under FINTWIN_TEXT (a directory):
  features/<CIK>_<cutoff>.json   T1 features of the firm-year (t1_*, t1u_*, t1_restructuring_cost_usd)
  emb/<vintage>/<CIK>_<cutoff>.npy  mean embedding of the firm-year's sections under that vintage (float16)
  table.json                       per test year: the ridge weights of the three T2 scores (vintage of that year)

`text_inputs(asof, ticker)` gives the calibration its `text` assumption: the T1 features and the T2 margin score,
computed with the test year's ridge on the test year's vintage. Rules of DESIGN.md: documents filed after the cutoff
never enter (filings_text checks every read), and every embedding is computed with a vintage ending before the cutoff
(text_features.check_vintage). Ridge models are trained on cutoffs <= Y-3, as every other walk-forward choice.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

LAG = 3
RIDGE_ALPHA = 10.0  # addendum 1: one fixed penalty on standardized embeddings, not tuned
MIN_TRAIN = int(os.environ.get("FINTWIN_TEXT_MIN_TRAIN", "300"))  # the dry run lowers it to exercise the path
# The three scores of REVISION_PLAN_5 (tone, outlook, liquidity concern), each the ridge prediction of a realized label
SCORES = {
    "t2_margin": "realized minus trailing 8-quarter CFO margin, points of revenue (moves the twin's cost ratio)",
    "t2_shortfall": "realized liquidity shortfall within 8 quarters (0/1)",
    "t2_petition": "bankruptcy petition within 8 quarters (0/1)",
}


def _key(cik: int, asof: str) -> str:
    return f"CIK{int(cik):010d}_{str(asof)[:10]}"


def root() -> Path | None:
    p = os.environ.get("FINTWIN_TEXT")
    return Path(p) if p else None


def write_features(base: Path, cik: int, asof: str, feats: dict) -> None:
    d = base / "features"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_key(cik, asof)}.json").write_text(json.dumps(feats, sort_keys=True), encoding="utf-8")


def control_vintage(base: Path) -> str | None:
    """The vintage-difference control (P5-4, control 3) stores every year under one later vintage: control.json."""
    f = base / "control.json"
    return json.loads(f.read_text(encoding="utf-8")).get("vintage") if f.exists() else None


def write_embedding(base: Path, vintage: str, cik: int, asof: str, vec: np.ndarray, test_cutoff: str) -> None:
    """The firm-year's embedding under `vintage`, used for the test year of `test_cutoff`: the rule is that the vintage
    ends before the TEST cutoff (the firm-year's own, or a later year's when it serves as training data)."""
    from .text_features import check_vintage

    if control_vintage(base) != vintage:  # the labelled control deliberately breaks the rule, in its own directory
        check_vintage(vintage, test_cutoff)
    if str(asof)[:10] > str(test_cutoff)[:10]:
        raise ValueError(f"firm-year {asof} cannot train or test the year of {test_cutoff}")
    d = base / "emb" / vintage.replace("/", "__")
    d.mkdir(parents=True, exist_ok=True)
    np.save(d / f"{_key(cik, asof)}.npy", np.asarray(vec, np.float16))


def _emb(base: Path, vintage: str, cik: int, asof: str) -> np.ndarray | None:
    f = base / "emb" / vintage.replace("/", "__") / f"{_key(cik, asof)}.npy"
    return np.load(f).astype(float) if f.exists() else None


def ridge(X: np.ndarray, y: np.ndarray, alpha: float = RIDGE_ALPHA) -> dict:
    """Closed-form ridge on standardized columns; returns what `predict` needs."""
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    ym = float(y.mean())
    w = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - ym))
    return {"mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist(), "b": ym, "n": int(len(y)), "alpha": alpha}


def predict(model: dict, x: np.ndarray) -> float:
    z = (np.asarray(x, float) - np.asarray(model["mu"])) / np.asarray(model["sd"])
    return float(z @ np.asarray(model["w"]) + model["b"])


def build_table(base: Path, rows: list[dict], years: list[int]) -> dict:
    """rows: dicts with cik, origin, and the labels of SCORES (from the v4p panel's outcomes). For test year Y the
    ridge of each score is trained on firm-years with cutoffs <= Y-LAG, embedded with Y's vintage."""
    from .text_features import vintage_for

    out: dict = {"rule": f"Y-{LAG}", "alpha": RIDGE_ALPHA, "years": {}}
    for y in years:
        vint = control_vintage(base) or vintage_for(f"{y}-02-15")
        if vint is None:
            continue
        train = [r for r in rows if int(str(r["origin"])[:4]) <= y - LAG]
        X, keep = [], []
        for r in train:
            e = _emb(base, vint, r["cik"], r["origin"])
            if e is not None:
                X.append(e)
                keep.append(r)
        entry: dict = {"vintage": vint, "n_train": len(keep)}
        for score in SCORES:
            lab = np.array([float(r.get(score, np.nan)) for r in keep])
            ok = np.isfinite(lab)
            if ok.sum() >= MIN_TRAIN:
                entry[score] = ridge(np.asarray(X)[ok], lab[ok])
        out["years"][str(y)] = entry
    return out


@lru_cache(maxsize=2)
def _table(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def text_inputs(asof: str | None, ticker: str) -> dict:
    """The calibration's `text` assumption for a firm-year: T1 features, and the T2 scores of the test year's ridge on
    the firm-year's embedding under the test year's vintage ({} when the stage has nothing for it)."""
    base = root()
    if base is None or not asof or not ticker.upper().startswith("CIK"):
        return {}
    cik = int(ticker.upper().removeprefix("CIK"))
    out: dict = {}
    f = base / "features" / f"{_key(cik, asof)}.json"
    if f.exists():
        out.update(json.loads(f.read_text(encoding="utf-8")))
    tpath = base / "table.json"
    if tpath.exists():
        entry = _table(str(tpath))["years"].get(str(asof)[:4]) or {}
        e = _emb(base, entry["vintage"], cik, asof) if entry.get("vintage") else None  # the year's vintage
        if e is not None:
            for score in SCORES:
                if score in entry:
                    out[score] = predict(entry[score], e)
    return out
