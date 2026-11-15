"""B4 prospective track: archive the weekly build's forward-looking scores in a tamper-evident way.

Reads the dashboard data the weekly `data` workflow writes (web/public/data/index.json and companies/*.json) and writes

    predictions_<YYYY-WW>.parquet   one row per company, fixed schema, sorted by cik
    inputs_<YYYY-WW>.zip            the exact input files (deterministic zip), so the run can be audited after the
                                    90-day artifact expiry
    manifest_<YYYY-WW>.json         SHA256 of the parquet and zip, input tree hash, row count, git SHA, data_release,
                                    frozen base rates, and the hash link to the previous week's manifest

Properties that matter:
- Deterministic: same inputs + same --built-at/--git-sha -> byte-identical parquet and identical SHA256. The only
  wall-clock value inside the hashed file is the declared build timestamp (`built_at_utc`). It is SELF-DECLARED and is
  not evidence of anything; the evidence is the release `published_at` and the OpenTimestamps proof (see the workflow).
- Append-only: refuses to overwrite an existing week (parquet, zip or manifest).
- Hash chain: each manifest carries `prev_sha256` (SHA256 of the previous week's manifest file) and `prev_week`.
  A deleted or back-filled week breaks the chain (`verify_chain`). The first week has prev = null, stated as such,
  and needs the explicit --first flag so a failed lookup cannot silently restart the chain.
- No look-ahead: only the build's own outputs are read; nothing is fetched.

Scores archived (base preset, 12-quarter simulation):
- p_breach_4q / 8q / 12q: cumulative probability that liquidity breaches its floor within h quarters. Target is
  `liquidity_floor_breach`, NOT bankruptcy (declared in the manifest); it is scored rank-only against distress labels.
  Null when the build has fewer quarters (never a fallback to another horizon).
- health_score, p_icr_below_1_5, p_downgrade_below_ig (12-quarter horizon, model).
Committed baselines, computed from the same company files (higher = riskier):
- base_rate_t1_4q / base_rate_t1_8q: constant historical 8-K Item 1.03 rate per firm-origin within h quarters, from
  engine/fintwin/data/universe_edgar.csv for the stratum "firms in today's dashboard" (see derive_event_rates).
  Stored in each week's manifest and parquet, never re-fitted afterwards. T2a (2.04/3.01) has no committed
  reference: the CSV carries 1.03 dates only.
- bl_runway_risk: 1 / (1 + cash runway in quarters); runway = cash / (-TTM FCF / 4), 0 risk if TTM FCF >= 0.
- bl_icr_risk: -(mean interest coverage of the last 4 quarters).
- bl_leverage_risk: net debt / EBITDA of the last quarter (99 if EBITDA <= 0, null if missing).
Altman Z-double-prime is NOT archived: the dashboard files carry no total assets / working capital. Adding it needs a
schema bump (SCHEMA_VERSION) and a new column, never an edit of past weeks.

Needs: pyarrow (writer; not an engine dependency; the workflow pins it) and, only for the scorer, pandas (in the
engine lock). Usage from the repo root:
    uv run --project engine --with pyarrow==26.0.1 python engine/scripts/archive_predictions.py \
        --data web/public/data --out predictions_archive (--prev-manifest FILE | --first)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
import zipfile
from pathlib import Path

SCHEMA_VERSION = "1.1.0"
CREDIT_RATING_D = 0  # index 0 of the ratings ladder is "D" (index.json meta.ratings.labels)
TARGETS = {
    "p_breach_*": "liquidity_floor_breach (cumulative within h quarters, h in the column name); rank-only vs distress labels",
    "base_rate_t1_*": "historical 8-K Item 1.03 rate per firm-origin within h quarters (T1 only; T2a has no reference)",
}

# column name -> arrow type name; order is the file's column order
COLUMNS: list[tuple[str, str]] = [
    ("cik", "int64"),
    ("ticker", "string"),
    ("asof", "string"),  # data cut-off: the build's data date (ISO), same for all rows
    ("last_quarter", "string"),  # latest fiscal quarter end in the company's data
    ("built_at_utc", "string"),  # declared (self-reported) build timestamp, ISO 8601 Z
    ("git_sha", "string"),
    ("engine_version", "string"),
    ("data_release", "string"),  # YYYY.WW
    ("schema_version", "string"),
    ("model_horizon_q", "int32"),
    ("health_score", "float64"),
    ("p_breach_4q", "float64"),
    ("p_breach_8q", "float64"),
    ("p_breach_12q", "float64"),
    ("p_icr_below_1_5", "float64"),
    ("p_downgrade_below_ig", "float64"),
    ("base_rate_t1_4q", "float64"),
    ("base_rate_t1_8q", "float64"),
    ("bl_runway_risk", "float64"),
    ("bl_icr_risk", "float64"),
    ("bl_leverage_risk", "float64"),
]


def iso_week(date_iso: str) -> tuple[int, int]:
    y, w, _ = dt.date.fromisoformat(date_iso).isocalendar()
    return y, w


def week_label(date_iso: str) -> str:
    y, w = iso_week(date_iso)
    return f"{y}-{w:02d}"


def round_label(date_iso: str) -> str:
    """Quarterly round of a data date, e.g. 2026Q4."""
    d = dt.date.fromisoformat(date_iso)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _num(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _last(seq, n: int = 1) -> list[float | None]:
    return [_num(v) for v in (seq or [])[-n:]]


def baselines(series: dict) -> dict[str, float | None]:
    """Simple committed rules from the last quarters of the company's own history."""
    cash = _last(series.get("cash"))
    fcf4 = _last(series.get("fcf"), 4)
    if cash and cash[0] is not None and len(fcf4) == 4 and None not in fcf4:
        burn_q = -sum(fcf4) / 4.0
        runway_risk = 0.0 if burn_q <= 0 else 1.0 / (1.0 + max(cash[0], 0.0) / burn_q)
    else:
        runway_risk = None
    icr4 = _last(series.get("icr"), 4)
    icr_risk = -sum(icr4) / 4.0 if len(icr4) == 4 and None not in icr4 else None
    lev = _last(series.get("nd_ebitda"))[0] if series.get("nd_ebitda") else None
    ebitda = _last(series.get("ebitda"))[0] if series.get("ebitda") else None
    if ebitda is not None and ebitda <= 0:
        lev = 99.0
    return {"bl_runway_risk": runway_risk, "bl_icr_risk": icr_risk, "bl_leverage_risk": lev}


def _company_files(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "companies").glob("*.json"), key=lambda p: p.name)


def derive_icr_d_proxy_rate(data_dir: Path, horizons: tuple[int, ...] = (4, 8)) -> dict:
    """DIAGNOSTIC ONLY (icr_d_proxy_rate), not a baseline: counts transient ICR-implied D quarters, ~10x real events.

    Data: the quarterly `rating` series in each company file (model rating from interest coverage; 0 = D).
    Origin set: every (company, quarter t) with t + h inside the history and rating[t] != D (the analogue of ADR-003's
    exclusion of firms already in a case). Event: rating == D in any of quarters t+1..t+h. Rate = events / origins.
    Kept in the manifest under diagnostics only.
    """
    out = {}
    for h in horizons:
        n = k = 0
        for f in _company_files(data_dir):
            d = json.loads(f.read_text(encoding="utf-8"))
            r = [_num(v) for v in (((d.get("history") or {}).get("series") or {}).get("rating") or [])]
            for t in range(len(r) - h):
                if r[t] is None or r[t] == CREDIT_RATING_D:
                    continue
                win = r[t + 1 : t + 1 + h]
                if any(v is None for v in win):
                    continue
                n += 1
                k += any(v == CREDIT_RATING_D for v in win)
        out[f"{h}q"] = {"rate": (k / n) if n else None, "origins": n, "events": k}
    return out


DATA_CUT = dt.date(2026, 10, 31)  # the universe snapshot date; windows ending after it are right-censored and dropped
ORIGIN_FIRST, ORIGIN_LAST = dt.date(2012, 3, 31), dt.date(2024, 12, 31)


def _quarter_ends(a: dt.date, b: dt.date) -> list[dt.date]:
    out = []
    for y in range(a.year, b.year + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = dt.date(y, m, d)
            if a <= q <= b:
                out.append(q)
    return out


def derive_event_rates(universe_csv: Path, stratum_ciks: set[int], horizons: tuple[int, ...] = (4, 8)) -> dict:
    """Frozen historical 8-K Item 1.03 rate per firm-origin, from universe_edgar.csv (`bankruptcy_8k` = 1.03 dates).

    Unit: (firm, calendar quarter-end origin) with the firm active at the origin (first_year <= origin <= last
    periodic filing, else end of last_year). Origins 2012-03-31..2024-12-31; an origin whose window ends after
    DATA_CUT is dropped (right-censoring). Event: a 1.03 filed in (origin, origin + 91*h days]. Origins with a 1.03 in
    the 730 days before are excluded (firm already in a case; ADR-003 section 3). rate = events / origins.
    Strata: `stratum` = firms whose CIK is in the current dashboard index (the committed baseline);
    `all_universe` = every firm in the file. Caveat: the stratum is today's survivors-by-selection, so its historical
    rate is likely a lower bound for a live roster; the all-universe rate is stored beside it. T1 only: the file has no
    2.04 / 3.01 dates, so T2a has no committed reference.
    """
    import csv

    def parse(x):
        return dt.date.fromisoformat(x.strip()) if x and x.strip() else None

    firms = []
    with open(universe_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ev = sorted(dt.date.fromisoformat(x) for x in (r["bankruptcy_8k"] or "").split(";") if x.strip())
            fy = int(float(r["first_year"])) if r["first_year"] else None
            ly = int(float(r["last_year"])) if r["last_year"] else None
            if fy is None or ly is None:
                continue
            end = parse(r["last_periodic"]) or dt.date(ly, 12, 31)
            firms.append((int(r["cik"]), dt.date(fy, 1, 1), end, ev))
    origins = _quarter_ends(ORIGIN_FIRST, ORIGIN_LAST)
    out: dict = {"stratum": {}, "all_universe": {}}
    for name, member in (("stratum", lambda c: c in stratum_ciks), ("all_universe", lambda c: True)):
        for h in horizons:
            n = k = nf = 0
            for cik, start, end, ev in firms:
                if not member(cik):
                    continue
                nf += 1
                for o in origins:
                    stop = o + dt.timedelta(days=91 * h)
                    if stop > DATA_CUT or not (start <= o <= end):
                        continue
                    if any(o - dt.timedelta(days=730) <= e <= o for e in ev):
                        continue
                    n += 1
                    k += any(o < e <= stop for e in ev)
            out[name][f"{h}q"] = {"rate": (k / n) if n else None, "events": k, "origins": n, "firms": nf}
    out["definition"] = derive_event_rates.__doc__.strip()
    out["period"] = f"origins {ORIGIN_FIRST}..{ORIGIN_LAST}, data cut {DATA_CUT}"
    out["universe_csv_sha256"] = sha256_file(universe_csv)
    out["t2a_reference"] = None
    out["t2a_note"] = "no committed T2a (2.04/3.01) reference: universe_edgar.csv carries 1.03 dates only"
    return out


def build_rows(
    data_dir: Path, *, asof: str, built_at: str, git_sha: str, engine_version: str, data_release: str, base_rates: dict
) -> list[dict]:
    rows = []
    for f in _company_files(data_dir):
        d = json.loads(f.read_text(encoding="utf-8"))
        base = (d.get("presets") or {}).get("base") or {}
        params = d.get("params") or {}
        try:
            cik = int(d["cik"])
        except (KeyError, TypeError, ValueError):
            continue  # no identifier, cannot be scored later
        byq = base.get("p_breach_by_q") or []

        def pq(q: int, byq=byq) -> float | None:
            return _num(byq[q - 1]) if len(byq) >= q else None  # null when absent: no fallback to another horizon

        row = {
            "cik": cik,
            "ticker": str(d.get("ticker") or f.stem),
            "asof": asof,
            "last_quarter": str(params.get("last_quarter") or ""),
            "built_at_utc": built_at,
            "git_sha": git_sha,
            "engine_version": engine_version,
            "data_release": data_release,
            "schema_version": SCHEMA_VERSION,
            "model_horizon_q": int(params.get("horizon") or 12),
            "health_score": _num(base.get("health_score")),
            "p_breach_4q": pq(4),
            "p_breach_8q": pq(8),
            "p_breach_12q": pq(12),
            "p_icr_below_1_5": _num(base.get("p_icr_below_1_5")),
            "p_downgrade_below_ig": _num(base.get("p_downgrade_below_ig")),
            "base_rate_t1_4q": base_rates["stratum"]["4q"]["rate"],
            "base_rate_t1_8q": base_rates["stratum"]["8q"]["rate"],
        }
        row.update(baselines((d.get("history") or {}).get("series") or {}))
        rows.append(row)
    rows.sort(key=lambda r: (r["cik"], r["ticker"]))
    return rows


def write_parquet(rows: list[dict], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    types = {"int64": pa.int64(), "int32": pa.int32(), "string": pa.string(), "float64": pa.float64()}
    schema = pa.schema([(n, types[t]) for n, t in COLUMNS])
    table = pa.Table.from_pylist(rows, schema=schema)
    # fixed options; no pandas metadata; no dictionary so the bytes do not depend on encoding heuristics
    pq.write_table(
        table, path, compression="zstd", use_dictionary=False, write_statistics=False, data_page_version="2.0"
    )


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_files(data_dir: Path) -> list[Path]:
    fixed = [data_dir / n for n in ("index.json", "build_report.json") if (data_dir / n).exists()]
    return sorted(fixed + _company_files(data_dir), key=lambda p: p.relative_to(data_dir).as_posix())


def tree_sha256(data_dir: Path) -> str:
    """Hash of the whole input: sorted lines 'relative/path<TAB>sha256' over index, build_report and companies/*.json."""
    h = hashlib.sha256()
    for p in input_files(data_dir):
        h.update(f"{p.relative_to(data_dir).as_posix()}\t{sha256_file(p)}\n".encode())
    return h.hexdigest()


def write_inputs_zip(data_dir: Path, path: Path) -> None:
    """Deterministic zip (sorted, fixed timestamps and modes) of the input files."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in input_files(data_dir):
            zi = zipfile.ZipInfo(p.relative_to(data_dir).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, p.read_bytes())


def verify_chain(manifest_paths: list[Path]) -> list[str]:
    """Return a list of problems (empty = chain intact). Skipped weeks are fine; a missing or altered link is not."""
    ms = {}
    for p in manifest_paths:
        m = json.loads(p.read_text(encoding="utf-8"))
        ms[m["week"]] = (p, m)
    problems = []
    for i, week in enumerate(sorted(ms)):
        p, m = ms[week]
        prev_week = m.get("prev_week")
        if i == 0 and m.get("prev_sha256") is None:
            continue  # the first week of the chain
        if m.get("prev_sha256") is None:
            problems.append(f"{week}: prev_sha256 is null but it is not the first week")
        elif prev_week not in ms:
            problems.append(f"{week}: previous week {prev_week} is missing (deleted or not downloaded)")
        elif sha256_file(ms[prev_week][0]) != m["prev_sha256"]:
            problems.append(f"{week}: prev_sha256 does not match {prev_week}")
        elif prev_week >= week:
            problems.append(f"{week}: prev_week {prev_week} is not earlier")
    return problems


def _git_sha() -> str:
    env = os.environ.get("GITHUB_SHA")
    if env:
        return env
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _engine_version(root: Path) -> str:
    try:
        for line in (root / "engine" / "pyproject.toml").read_text(encoding="utf-8").splitlines():
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def archive(
    data_dir: Path,
    out_dir: Path,
    *,
    built_at: str | None = None,
    git_sha: str | None = None,
    engine_version: str | None = None,
    repo_root: Path | None = None,
    prev_manifest: Path | None = None,
    first: bool = False,
    universe_csv: Path | None = None,
) -> tuple[Path, Path]:
    if (prev_manifest is None) == (not first):
        raise SystemExit("give exactly one of --prev-manifest FILE or --first (first week of the chain, prev = null)")
    index = json.loads((data_dir / "index.json").read_text(encoding="utf-8"))
    asof = str((index.get("meta") or {}).get("generated") or "")
    if not asof:
        raise SystemExit("index.json has no meta.generated: cannot determine the data cut-off")
    week = week_label(asof)
    y, w = iso_week(asof)
    data_release = f"{y}.{w:02d}"
    built_at = built_at or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    git_sha = git_sha or _git_sha()
    root = repo_root or Path(__file__).resolve().parents[2]
    engine_version = engine_version or _engine_version(root)

    prev_sha = prev_week = None
    if prev_manifest is not None:
        prev_week = json.loads(prev_manifest.read_text(encoding="utf-8"))["week"]
        prev_sha = sha256_file(prev_manifest)
        if prev_week >= week:
            raise SystemExit(f"previous manifest is for {prev_week}, which is not before {week}")

    out_dir.mkdir(parents=True, exist_ok=True)
    pq_path = out_dir / f"predictions_{week}.parquet"
    zip_path = out_dir / f"inputs_{week}.zip"
    mf_path = out_dir / f"manifest_{week}.json"
    for p in (pq_path, zip_path, mf_path):
        if p.exists():
            raise SystemExit(f"refusing to overwrite {p}: archived weeks are immutable")

    universe_csv = universe_csv or root / "engine" / "fintwin" / "data" / "universe_edgar.csv"
    ciks = set()
    for f in _company_files(data_dir):
        try:
            ciks.add(int(json.loads(f.read_text(encoding="utf-8"))["cik"]))
        except (KeyError, TypeError, ValueError):
            pass
    base_rates = derive_event_rates(universe_csv, ciks)
    if base_rates["stratum"]["4q"]["rate"] is None or base_rates["stratum"]["8q"]["rate"] is None:
        raise SystemExit("cannot derive baseline rates: no firm-origins for the dashboard stratum in the universe file")
    rows = build_rows(
        data_dir,
        asof=asof,
        built_at=built_at,
        git_sha=git_sha,
        engine_version=engine_version,
        data_release=data_release,
        base_rates=base_rates,
    )
    if not rows:
        raise SystemExit("no company files with a cik found: nothing to archive")
    write_parquet(rows, pq_path)
    write_inputs_zip(data_dir, zip_path)

    try:
        import pyarrow

        writer = f"pyarrow {pyarrow.__version__}"
    except ImportError:  # pragma: no cover
        writer = "unknown"
    manifest = {
        "week": week,
        "round": round_label(asof),
        "data_release": data_release,
        "asof": asof,
        "built_at_utc": built_at,
        "built_at_note": "self-declared by the builder; evidence of timing is the release published_at and the OpenTimestamps proof",
        "git_sha": git_sha,
        "engine_version": engine_version,
        "schema_version": SCHEMA_VERSION,
        "parquet_writer": writer,
        "file": pq_path.name,
        "sha256": sha256_file(pq_path),
        "rows": len(rows),
        "columns": [n for n, _ in COLUMNS],
        "targets": TARGETS,
        "base_rates": base_rates,
        "diagnostics": {"icr_d_proxy_rate": derive_icr_d_proxy_rate(data_dir), "note": "not a baseline"},
        "inputs_tree_sha256": tree_sha256(data_dir),
        "inputs_files": len(input_files(data_dir)),
        "inputs_zip": zip_path.name,
        "inputs_zip_sha256": sha256_file(zip_path),
        "script_sha256": sha256_file(Path(__file__)),
        "prev_week": prev_week,
        "prev_sha256": prev_sha,
        "prev_note": None
        if prev_sha
        else "first week of the chain: there is no previous manifest (prev_sha256 = null)",
    }
    mf_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pq_path, mf_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", type=Path, default=Path("web/public/data"))
    ap.add_argument("--out", type=Path, default=Path("predictions_archive"))
    ap.add_argument("--built-at", help="declared build timestamp (ISO, Z); default: now UTC")
    ap.add_argument("--git-sha")
    ap.add_argument("--prev-manifest", type=Path, help="previous week's manifest (from the previous release)")
    ap.add_argument("--universe-csv", type=Path, help="default: engine/fintwin/data/universe_edgar.csv")
    ap.add_argument("--first", action="store_true", help="this is the first week of the chain (prev = null)")
    a = ap.parse_args(argv)
    pq_path, mf_path = archive(
        a.data,
        a.out,
        built_at=a.built_at,
        git_sha=a.git_sha,
        prev_manifest=a.prev_manifest,
        first=a.first,
        universe_csv=a.universe_csv,
    )
    print(pq_path, mf_path)
    print(json.loads(mf_path.read_text())["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
