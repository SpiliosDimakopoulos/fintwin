"""Audit the shards of finished runs before the next stage spends hours on them (rerun 5, WP7).

Every bug of the 12-11-2026 review (None health and quantiles from a diverged simulation, revenue booked as 0,
negative quarters from mixed vintages, units failing in one spec only) was visible in the shards hours before the
stats stage crashed on it. This script reads every shard of the given runs and fails (exit 1) on a RED finding;
WARN findings are reported only. Outside the fintwin package, so editing it never makes shards stale.

  python scripts/audit_shards.py --root .cache/research --runs v2-pre v3 v2-rev --out out/audit_universe.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

# RED thresholds (share of rows / firms); anything non-finite or out of range is RED at any count
MAX_NEG_REVENUE_SHARE = 0.001  # realized revenue < 0 among revenue forecast rows (a genuine negative quarter is rare)
MAX_UNIT_DIFF_SHARE = 0.001  # firm-years with a panel row in one spec of a run tag and none in another
# WARN thresholds
WARN_CRPS_RATIO = 50.0


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and not math.isfinite(x))


class Audit:
    def __init__(self) -> None:
        self.red: dict[str, Counter] = defaultdict(Counter)
        self.warn: dict[str, Counter] = defaultdict(Counter)
        self.examples: dict[str, list] = defaultdict(list)
        self.units: dict[str, set] = {}
        self.rows: Counter = Counter()

    def hit(self, level: str, run: str, what: str, firm: str) -> None:
        (self.red if level == "RED" else self.warn)[run][what] += 1
        key = f"{run}:{what}"
        if len(self.examples[key]) < 5:
            self.examples[key].append(firm)

    def shard(self, run: str, r: dict) -> None:
        t = r.get("ticker", "?")
        panel = r.get("panel") or []
        for pr in panel:
            self.units.setdefault(run, set()).add((t, pr.get("origin")))
            self.rows[f"{run}:panel"] += 1
            for sc in ("base", "recession"):
                s = pr.get(sc) or {}
                h, pb = s.get("health"), s.get("p_breach")
                if _bad(h) or _bad(pb):
                    self.hit("RED", run, f"panel.{sc} health/p_breach missing or non-finite", t)
                elif not (0 <= h <= 100) or not (0 <= pb <= 1):
                    self.hit("RED", run, f"panel.{sc} health/p_breach out of range", t)
            lr = (pr.get("features") or {}).get("log_rev")
            if lr is not None and lr <= 0:
                self.hit("WARN", run, "panel log_rev <= 0 (no revenue at the cutoff)", t)
            dg = pr.get("depth_grid") or {}
            if dg.get("0.80") is not None and dg.get("0.00") is not None and dg["0.80"] > dg["0.00"] + 0.5:
                self.hit("WARN", run, "depth grid: health higher at 80% than at 0% (model behaviour, D5)", t)
            b, rec = (pr.get("base") or {}).get("health"), (pr.get("recession") or {}).get("health")
            if b == 100.0 and rec == 100.0:
                self.hit("WARN", run, "health at the 100 ceiling in base and recession (AUC ties)", t)
        for fr in r.get("forecasts") or []:
            self.rows[f"{run}:forecasts"] += 1
            q, y = fr.get("q"), fr.get("y")
            if q is None or any(_bad(v) for v in q) or _bad(y) or _bad(fr.get("crps_twin")):
                self.hit("RED", run, "forecast q / y / crps_twin missing or non-finite", t)
                continue
            if any(a > b + 1e-9 * max(1.0, abs(b)) for a, b in zip(q, q[1:], strict=False)):
                self.hit("RED", run, "forecast quantiles not monotone", t)
            if fr.get("var") == "revenue" and y < 0:
                self.hit("WARN", run, "realized revenue < 0", t)
                self.rows[f"{run}:neg_revenue"] += 1
            if fr.get("var") == "revenue":
                self.rows[f"{run}:revenue_rows"] += 1
            if fr.get("var") == "cash_like" and max(q) == min(q):
                self.hit("WARN", run, "cash forecast with all quantiles equal", t)
            rw = fr.get("crps_rw")
            if rw and not _bad(rw) and rw > 0 and fr["crps_twin"] > WARN_CRPS_RATIO * rw:
                self.hit("WARN", run, f"crps_twin > {WARN_CRPS_RATIO:g}x crps_rw", t)
        c = r.get("covid") or {}
        for k, s in (c.get("scenarios") or {}).items():
            if _bad(s.get("health")):
                self.hit("RED", run, f"covid.{k} health missing or non-finite", t)
        for e in (r.get("errors") or {}).values():
            self.warn[run][f"error: {str(e).split(':')[0][:60]}"] += 1

    def finish(self, groups: list[list[str]]) -> dict:
        for run in list(self.rows):
            if run.endswith(":neg_revenue"):
                name = run.split(":")[0]
                share = self.rows[run] / max(1, self.rows[f"{name}:revenue_rows"])
                if share > MAX_NEG_REVENUE_SHARE:
                    self.red[name][f"realized revenue < 0 in {share:.2%} of revenue rows"] += 1
        for g in groups:  # runs of one tag must cover the same firm-years (a unit failing in one spec only)
            present = [r for r in g if r in self.units]
            union = set().union(*(self.units[r] for r in present)) if present else set()
            for r in present:
                missing = union - self.units[r]
                if union and len(missing) / len(union) > MAX_UNIT_DIFF_SHARE:
                    self.red[r][f"{len(missing)} firm-years with a panel row in another spec of {g} but not here"] += 1
                    self.examples[f"{r}:unit diff"] = [list(m) for m in sorted(missing)[:5]]
        return {
            "red": {k: dict(v) for k, v in self.red.items() if v},
            "warn": {k: dict(v) for k, v in self.warn.items() if v},
            "rows": dict(self.rows),
            "examples": dict(self.examples),
            "thresholds": {"neg_revenue_share": MAX_NEG_REVENUE_SHARE, "unit_diff_share": MAX_UNIT_DIFF_SHARE},
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".cache/research")
    ap.add_argument(
        "--runs", nargs="+", required=True, help="run directories; runs listed in one --group compare units"
    )
    ap.add_argument("--group", nargs="+", action="append", default=[], help="runs of one tag (same firms expected)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    au = Audit()
    for run in a.runs:
        d = Path(a.root) / run
        files = sorted(d.glob("*.json"))
        if not files:
            au.red[run]["no shards"] += 1
        for f in files:
            try:
                au.shard(run, json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                au.red[run]["unreadable shard"] += 1
    rep = au.finish(a.group)
    text = json.dumps(rep, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(json.dumps({"red": rep["red"], "warn_runs": sorted(rep["warn"])}, indent=1))
    return 1 if rep["red"] else 0


if __name__ == "__main__":
    sys.exit(main())
