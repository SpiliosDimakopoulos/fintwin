"""REVISION_PLAN_5 text stage (server only): filings, T1 features and dated embeddings for the panel's firm-years.

  python scripts/text_build.py fetch [--limit N]                  documents filed by each cutoff -> .cache/text
      ONE process (the SEC limit is per client); run without FINTWIN_FROZEN; stops at the first 403
  python scripts/text_build.py freeze                              text snapshot manifest (digest)
  python scripts/text_build.py features SHARD NSHARDS [--limit N] [--masked] [--vintage-control]
                                                                   T1 features and embeddings -> $FINTWIN_TEXT[/ctl]

Each firm-year at cutoff c is embedded with the vintage of its own test year and, as training data, with the vintage
of every later test year Y >= c.year + 3 (re-embedding rule; every vintage ends before the test year's cutoff).
Vintages are processed one at a time (one model in memory per process); a vintage that does not load is recorded and
skipped (T2 is then missing for that test year, as the plan says). --masked writes the masked-identity placebo under
$FINTWIN_TEXT/masked; --vintage-control writes the 2024-vintage embeddings under $FINTWIN_TEXT/v2024 (control.json
names the vintage). The extractor must be frozen before `features` runs.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fintwin.data import edgar as E  # noqa: E402
from fintwin.data import filings_text as FT  # noqa: E402
from fintwin.research import text_features as TF  # noqa: E402
from fintwin.research import text_stage as TS  # noqa: E402
from fintwin.research.__main__ import _opts, dry_tickers, research_tickers  # noqa: E402
from fintwin.research.experiments import PANEL_ORIGINS  # noqa: E402

LOCK = Path("p5_inputs/extractor.lock.json")  # committed: fixed before any filing was read
YEARS = range(2014, 2025)
CONTROL_VINTAGE = "manelalab/chrono-bert-v1-20241231"


def _firm_years(i: int, n: int, limit: int | None) -> list[tuple[int, str]]:
    keys = dry_tickers(limit) if limit else research_tickers()
    ciks = [int(k.removeprefix("CIK")) for k in keys[i::n] if k.startswith("CIK")]
    return [(c, o) for c in ciks for o in PANEL_ORIGINS if int(o[:4]) in YEARS]


def _text(rec: dict) -> str:
    return "\n\n".join(t for d in rec["documents"] for t in d["sections"].values() if t)


def fetch(limit: int | None) -> None:
    n_ok = n_fail = 0
    for cik, o in _firm_years(0, 1, limit):
        try:
            FT.filing_text(cik, o)
            n_ok += 1
        except Exception as e:  # recorded, never silent; a refusal by the SEC stops the stage (DESIGN.md, 05)
            if "403" in str(e):
                raise
            n_fail += 1
            print(json.dumps({"cik": cik, "origin": o, "error": f"{type(e).__name__}: {e}"}), flush=True)
    print(json.dumps({"fetched": n_ok, "failed": n_fail}), flush=True)


def features(i: int, n: int, limit: int | None, masked: bool, control: bool) -> None:
    TF.assert_extractor_frozen(LOCK)
    base = TS.root()
    assert base is not None, "FINTWIN_TEXT"
    out = base / ("masked" if masked else "v2024" if control else "")
    out.mkdir(parents=True, exist_ok=True)
    if control:
        (out / "control.json").write_text(json.dumps({"vintage": CONTROL_VINTAGE}), encoding="utf-8")
    texts: dict[tuple[int, str], str] = {}
    missing = 0
    for cik, o in _firm_years(i, n, limit):
        try:
            rec = FT.load_firm_year(cik, o)
        except FileNotFoundError:  # no filing stored for the firm-year (counted)
            missing += 1
            continue
        TS.write_features(out, cik, o, TF.t1_features(rec))  # T1 from the filing as filed (facts, not identity)
        text = _text(rec)
        if masked and text:
            text = TF.mask_identity(text, TF.identity_terms(E.submission_pages(cik, 24 * 365)[0]))
        if text:
            texts[(cik, o)] = text
    # (vintage, test cutoff) -> firm-years: each vintage is loaded once
    jobs: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for (cik, o), _ in texts.items():
        y0 = int(o[:4])
        for y in [y0, *range(y0 + 3, max(YEARS) + 1)]:
            test = f"{y}-02-15"
            v = CONTROL_VINTAGE if control else TF.vintage_for(test)
            if v is not None:
                jobs[v].append((cik, o, test))
    failed: dict[str, str] = {}
    for v in sorted(jobs):
        done = set()
        try:
            for cik, o, test in jobs[v]:
                if (cik, o) in done:  # the same embedding serves every later test year of this vintage
                    continue
                TS.write_embedding(out, v, cik, o, TF.embed([texts[(cik, o)]], v)[0], test)
                done.add((cik, o))
        except Exception as e:  # a vintage that does not load: T2 missing for its test years, recorded
            failed[v] = f"{type(e).__name__}: {e}"
        TF._MODELS.clear()  # one model in memory at a time
    print(json.dumps({"firm_years": len(texts), "missing": missing, "vintages": len(jobs), "failed": failed}), flush=True)


if __name__ == "__main__":
    pos, opt = _opts(sys.argv[1:])
    lim = int(opt["limit"]) if "limit" in opt else None
    if pos[0] == "fetch":
        fetch(lim)
    elif pos[0] == "freeze":
        print(json.dumps(FT.freeze_text_snapshot()))
    elif pos[0] == "features":
        features(int(pos[1]), int(pos[2]), lim, "masked" in opt, "vintage-control" in opt)
    else:
        sys.exit(f"unknown command {pos[0]}")
