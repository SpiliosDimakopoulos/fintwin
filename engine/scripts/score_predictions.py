"""B4 scoring SKELETON: score an archived round against later credit events. Not run in CI, not yet validated.

NO RANKING CLAIMS IN YEAR ONE. The dashboard universe is about 392 large caps, where 8-K 1.03 events run at roughly
0-2 a year (the full 5,300-firm universe has ~25-30). Most year-one metrics will therefore be UNDEFINED (no events) or
meaningless; the output always carries the event counts and says so. Do not publish a leaderboard from it.

Rules (ADR-003 section 3)
- Per row status: event / survived / exited_non_distress / exited_unknown. Primary set = event + survived. Firms
  acquired, merged, taken private or deregistered inside the window are NOT negatives. exited_unknown is negative only
  in the labelled sensitivity variant. Rows with a 1.03 in the 730 days before asof (prior case) are excluded.
  Counts per status are printed.
- Targets: T1 = Item 1.03. T2a = 1.03, or 2.04 / 3.01 not accompanied by 2.01 / 5.01 in the same 8-K (accession).
- Windows: (asof, asof + 91*h days], h = 4 or 8 quarters; a window not fully elapsed at --scored-on is refused.
- p_breach_* is a liquidity-floor breach, not bankruptcy: it is scored RANK-ONLY (PR-AUC, ROC AUC). No Brier or log
  score on it. Brier / log score are reported only for the constant committed base rate, as a reference, next to the
  EMPIRICAL event rate. The committed reference exists for T1 (1.03) only.
- Rounds: official scoring uses only the archive whose asof is in the first 14 days of the quarter (earliest such);
  none -> round VOID, no fallback. --exits is mandatory (frozen universe = the companies in it).
  Scoring any other week needs --week and is labelled DIAGNOSTIC.

Inputs
- archive dir with predictions_*.parquet and manifest_*.json (the SHA256 and the hash chain are verified first)
- labels CSV: cik, filed (YYYY-MM-DD), accession, items (e.g. "2.04;2.01"; rows of one accession are merged)
- optional exits CSV: cik, date, reason (acquired|merged|going_private|deregistered|unknown)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

CLIP = 1e-6
RANK_ONLY = ["bl_runway_risk", "bl_icr_risk", "bl_leverage_risk"]
NON_DISTRESS_EXITS = {"acquired", "merged", "going_private", "deregistered"}
TARGETS = ("T1", "T2a")


def _archive_module():
    spec = importlib.util.spec_from_file_location(
        "archive_predictions", Path(__file__).with_name("archive_predictions.py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pr_auc(y: list[int], s: list[float]) -> float | None:
    """Average precision (step interpolation); ties are grouped. None when there are no events."""
    pos = sum(y)
    if pos == 0:
        return None
    order = sorted(range(len(y)), key=lambda i: -s[i])
    tp = fp = 0
    ap = 0.0
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and s[order[j]] == s[order[i]]:
            j += 1
        dtp = sum(y[k] for k in order[i:j])
        tp += dtp
        fp += (j - i) - dtp
        ap += (dtp / pos) * (tp / (tp + fp))
        i = j
    return ap


def roc_auc(y: list[int], s: list[float]) -> float | None:
    """Mann-Whitney AUC with tie-averaged ranks. None unless both classes are present."""
    pos = sum(y)
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return None
    order = sorted(range(len(y)), key=lambda i: s[i])
    rank_sum = 0.0
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and s[order[j]] == s[order[i]]:
            j += 1
        avg = (i + 1 + j) / 2.0
        rank_sum += avg * sum(y[k] for k in order[i:j])
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def brier(y: list[int], p: list[float]) -> float:
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y, strict=False)) / len(y)


def log_score(y: list[int], p: list[float]) -> float:
    tot = 0.0
    for pi, yi in zip(p, y, strict=False):
        pi = min(max(pi, CLIP), 1 - CLIP)
        tot += -math.log(pi if yi else 1 - pi)
    return tot / len(y)


def load_events(path: Path) -> list[dict]:
    """One dict per accession: cik, filed, items (set). Rows of the same accession are merged."""
    acc: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            e = acc.setdefault(
                r["accession"].strip(),
                {"cik": int(r["cik"]), "filed": dt.date.fromisoformat(r["filed"]), "items": set()},
            )
            e["items"] |= {i.strip() for i in r["items"].replace(",", ";").split(";") if i.strip()}
    return list(acc.values())


def load_exits(path: Path | None) -> dict[int, tuple[dt.date, str]]:
    out: dict[int, tuple[dt.date, str]] = {}
    if path:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[int(r["cik"])] = (dt.date.fromisoformat(r["date"]), r["reason"].strip().lower())
    return out


def qualifies(items: set[str], target: str) -> bool:
    if "1.03" in items:
        return True
    return target == "T2a" and bool(items & {"2.04", "3.01"}) and not (items & {"2.01", "5.01"})


def row_status(cik: int, asof: dt.date, end: dt.date, events: list[dict], exits: dict, target: str) -> str:
    """event | survived | exited_non_distress | exited_unknown | excluded_prior_case (ADR-003 section 3)."""
    mine = [e for e in events if e["cik"] == cik]
    if any("1.03" in e["items"] and asof - dt.timedelta(days=730) <= e["filed"] <= asof for e in mine):
        return "excluded_prior_case"
    if any(asof < e["filed"] <= end and qualifies(e["items"], target) for e in mine):
        return "event"
    ex = exits.get(cik)
    if ex and asof < ex[0] <= end:
        return "exited_non_distress" if ex[1] in NON_DISTRESS_EXITS else "exited_unknown"
    return "survived"


def select_first_in_round(manifests: list[dict], rnd: str) -> dict | None:
    """Official archive of a round = the earliest archive whose asof is within the first 14 days of the quarter.
    None means the round is VOID: there is no fallback to a later week (that would choose the origin by omission)."""

    def early(m):
        d = dt.date.fromisoformat(m["asof"])
        return (d - dt.date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)).days < 14

    cand = sorted((m for m in manifests if m["round"] == rnd and early(m)), key=lambda m: (m["asof"], m["week"]))
    return cand[0] if cand else None


def score_archive(
    parquet: Path, manifest: dict, events: list[dict], exits: dict, scored_on: dt.date, *, official: bool
) -> dict:
    import pyarrow.parquet as pq

    digest = hashlib.sha256(parquet.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise SystemExit(f"SHA256 mismatch for {parquet.name}: the archive was altered or is not the manifest's file")
    df = pq.read_table(parquet).to_pandas()
    asof = dt.date.fromisoformat(manifest["asof"])
    res: dict = {
        "week": manifest["week"],
        "round": manifest["round"],
        "asof": manifest["asof"],
        "scored_on": scored_on.isoformat(),
        "label": "official (first archive of the round)" if official else "DIAGNOSTIC (not an official round score)",
        "note": "no ranking claims in year one; ~392 large caps give ~0-2 events a year, so many metrics are undefined",
        "horizons": {},
    }
    for h in (4, 8):
        end = asof + dt.timedelta(days=91 * h)
        if end > scored_on:
            res["horizons"][f"{h}q"] = {"status": "immature", "window_end": end.isoformat()}
            continue
        res["horizons"][f"{h}q"] = {}
        for target in TARGETS:
            status = [row_status(int(c), asof, end, events, exits, target) for c in df["cik"]]
            counts = {s: status.count(s) for s in sorted(set(status))}
            prim = [i for i, s in enumerate(status) if s in ("event", "survived")]
            y = [1 if status[i] == "event" else 0 for i in prim]
            entry: dict = {
                "status_counts": counts,
                "n_primary": len(prim),
                "events": sum(y),
                "empirical_rate": (sum(y) / len(y)) if y else None,
                "window_end": end.isoformat(),
            }

            def usable(name, rows):
                return [i for i in rows if df[name].iloc[i] == df[name].iloc[i]]  # drops NaN

            m = f"p_breach_{h}q"
            for name in [m] + RANK_ONLY:
                rows = usable(name, prim)
                yy = [1 if status[i] == "event" else 0 for i in rows]
                ss = [float(df[name].iloc[i]) for i in rows]
                entry[name] = {
                    "n": len(rows),
                    "pr_auc": pr_auc(yy, ss),
                    "roc_auc": roc_auc(yy, ss),
                    "scoring": "rank-only",
                }
            # sensitivity: exited_unknown counted as negative
            sens = [i for i, s in enumerate(status) if s in ("event", "survived", "exited_unknown")]
            rows = usable(m, sens)
            yy = [1 if status[i] == "event" else 0 for i in rows]
            entry["sensitivity_unknown_as_negative"] = {
                "n": len(rows),
                "pr_auc": pr_auc(yy, [float(df[m].iloc[i]) for i in rows]),
            }
            # reference: committed constant base rate beside the empirical rate
            br = manifest["base_rates"]["stratum"][f"{h}q"]["rate"] if target == "T1" else None  # T2a: none committed
            entry["base_rate_reference"] = {
                "committed_rate": br,
                "empirical_rate": entry["empirical_rate"],
                "brier": brier(y, [br] * len(y)) if y and br is not None else None,
                "log_score": log_score(y, [br] * len(y)) if y and br is not None else None,
            }
            res["horizons"][f"{h}q"][target] = entry
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archive_dir", type=Path)
    ap.add_argument("labels", type=Path)
    ap.add_argument("--exits", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--round", help="official: score the first archive of this round, e.g. 2026Q4")
    g.add_argument("--week", help="DIAGNOSTIC: score one specific week, e.g. 2026-45")
    ap.add_argument("--scored-on", type=dt.date.fromisoformat, default=dt.date.today())
    a = ap.parse_args(argv)
    if a.round and not a.exits:
        ap.error("--exits is mandatory with --round (without exits, acquired firms would count as survivors)")

    paths = sorted(a.archive_dir.glob("manifest_*.json"))
    problems = _archive_module().verify_chain(paths)
    if problems:
        raise SystemExit("hash chain broken:\n" + "\n".join(problems))
    manifests = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    if a.round:
        m = select_first_in_round(manifests, a.round)
    else:
        m = next((x for x in manifests if x["week"] == a.week), None)
    if m is None:
        raise SystemExit(
            "round is VOID: no archive with asof in the first 14 days of the quarter"
            if a.round
            else "no matching archive"
        )
    res = score_archive(
        a.archive_dir / m["file"], m, load_events(a.labels), load_exits(a.exits), a.scored_on, official=bool(a.round)
    )
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
