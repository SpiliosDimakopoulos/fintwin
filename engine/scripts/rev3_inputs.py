"""Extract the small cross-specification inputs of the revision-3 paper from a rerun's _results directory.

    python scripts/rev3_inputs.py engine/out/rerun5_results/research/_results

Writes docs/paper/rev3/inputs.json: the confirmatory v3-vs-v2-pre test, headline numbers of every specification and the
descriptive ladder (fixed 1,000-firm sample). rev3_assets.py turns it into macros and tables.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "engine" / "out" / "rerun5_results" / "research" / "_results"
OUT = ROOT / "docs" / "paper" / "rev3" / "inputs.json"


def get(d, *path):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return None
        d = d[p]
    return d


def headline(r: dict) -> dict:
    t = r["transmission"]["panel"]
    cfo = t["cfo"]
    lv = cfo["levels"]
    out = {
        "n": t["n"],
        "mae": {k: get(lv, k, "median_ae") for k in ("N1", "N3", "N6", "T0", "T1")},
        "incr_T1_vs_N3": get(cfo, "incremental", "N3", "T1", "rho"),
        "enc_t_two_way": get(cfo, "encompassing", "all_two_way", "t", "T1"),
        "enc_t_tG1": get(cfo, "encompassing", "all_two_way_tG1", "t", "T1"),
        "elasticity_ratio": get(r, "plan2", "overreaction", "cfo", "ratio"),
        "hybrid_gain_pct": get(t, "inference", "gains", "cfo", "N3+T1_vs_N3", "gain_pct"),
        "bk_auc_twin": get(r, "bankruptcy_panel", "all", "auc", "twin_base") or get(r, "credit_events", "bk8", "twin", "auc"),
        "crps": {k: get(r, "density", "cfo", "crps", k) for k in ("twin", "gaussian", "empirical")},
        "brier8": {k: get(r, "liquidity", "shortfall", "8", "recession", k, "brier") for k in ("twin", "logit", "altman_z2")},
        "verdict_H2": get(t, "verdict"),
    }
    return out


def main() -> None:
    res: dict = {"source": str(SRC.relative_to(ROOT)) if SRC.is_relative_to(ROOT) else str(SRC), "specs": {}, "ladder": {},
                 "cross_spec": {}}
    for spec in ("v2-pre", "v2-rev", "v3", "v3-wf"):
        res["specs"][spec] = headline(json.loads((SRC / f"{spec}.json").read_text(encoding="utf-8")))
    rungs = ["v2-pre-legacydata", "v2-pre", "v2-pre+F5", "v2-pre+F5+F4", "v2-pre+F5+F4+F1", "v2-pre+F5+F4+F1+F2", "v3",
             "v2-pre+F5+F4+F1-wf", "v2-pre+F5+F4+F1+F2-wf", "v3-wf"]
    for k in rungs:
        p = SRC / f"{k}_s1000.json"
        if p.exists():
            res["ladder"][k] = headline(json.loads(p.read_text(encoding="utf-8")))
    for p in sorted(SRC.glob("cross_spec_*.json")):
        res["cross_spec"][p.stem.removeprefix("cross_spec_")] = json.loads(p.read_text(encoding="utf-8"))
    sel = SRC.parent / "_selection" / "v3.json"
    if sel.exists():
        d = json.loads(sel.read_text(encoding="utf-8"))
        res["selection"] = {"rule": d["rule"], "tau": d["tau"], "lambda": d["lambda"]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(res['ladder'])} rungs, {len(res['cross_spec'])} cross-spec tests)")


if __name__ == "__main__":
    main()
