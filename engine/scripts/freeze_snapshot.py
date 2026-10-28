"""Freeze the research inputs into one archived snapshot, so every rerun reads the same data vintage.

python scripts/freeze_snapshot.py build     # fetch every universe company's facts, filings and FRED series, then pack
python scripts/freeze_snapshot.py pack      # re-pack engine/.cache after a FINTWIN_FILL_ONLY=1 top-up
python scripts/freeze_snapshot.py verify    # check engine/.cache against snapshot/manifest.json
python scripts/freeze_snapshot.py restore F # unpack snapshot tarball F into engine/.cache and verify it

Runs read the snapshot with FINTWIN_FROZEN=1: nothing is fetched, and a file the snapshot lacks is an error.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import tarfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
CACHE = ENGINE / ".cache"
OUT = ENGINE / "snapshot"
PARTS = ("edgar", "fred")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _files() -> list[Path]:
    # Committed inputs (fintwin/data/*.csv) are versioned by git; the snapshot holds what git does not.
    return sorted(p for part in PARTS for p in (CACHE / part).rglob("*") if p.is_file())


def manifest() -> dict:
    files = {p.relative_to(ENGINE).as_posix(): _sha(p) for p in _files()}
    digest = hashlib.sha256("".join(f"{k} {v}\n" for k, v in files.items()).encode()).hexdigest()
    return {"files": files, "n_files": len(files), "digest": digest}


def build() -> None:
    from fintwin.data.fred import SERIES, fred_series
    from fintwin.research.__main__ import prefetch

    started = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    prefetch()
    for series_id in SERIES.values():
        fred_series(series_id, max_age_hours=0)
    pack({"started": started, "finished": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")})


def pack(extracted: dict | None = None) -> None:
    """Pack engine/.cache as it is (after a FINTWIN_FILL_ONLY top-up, the earlier extraction dates are kept)."""
    old = OUT / "manifest.json"
    if extracted is None:
        prev = json.loads(old.read_text(encoding="utf-8")) if old.exists() else {}
        extracted = {**prev.get("extracted", {}), "topped_up": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    started = extracted.get("started", dt.datetime.now(dt.UTC).isoformat())
    m = manifest()
    m["extracted"] = extracted
    OUT.mkdir(exist_ok=True)
    tar = OUT / f"fintwin_snapshot_{started[:10]}.tar"
    with tarfile.open(tar, "w") as tf:  # members are already gzip-compressed
        for p in _files():
            tf.add(p, arcname=p.relative_to(ENGINE).as_posix())
    m["tarball"] = {"name": tar.name, "sha256": _sha(tar)}
    (OUT / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    print(f"{m['n_files']} files, digest {m['digest'][:16]}, {tar.name} {tar.stat().st_size / 1e6:.0f} MB")


def verify() -> None:
    want = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    have = manifest()
    missing = sorted(set(want["files"]) - set(have["files"]))
    changed = sorted(k for k in want["files"] if k in have["files"] and have["files"][k] != want["files"][k])
    extra = sorted(set(have["files"]) - set(want["files"]))
    for label, keys in (("missing", missing), ("changed", changed), ("extra", extra)):
        if keys:
            print(f"{label}: {len(keys)} (e.g. {keys[:3]})")
    if missing or changed:
        raise SystemExit("snapshot does not match manifest")
    print(f"ok: {want['n_files']} files, digest {want['digest'][:16]}" + (f", {len(extra)} extra" if extra else ""))


def restore(tar: str) -> None:
    with tarfile.open(tar) as tf:
        tf.extractall(ENGINE, filter="data")
    verify()


if __name__ == "__main__":
    if sys.argv[1] == "restore":
        restore(sys.argv[2])
    else:
        {"build": build, "verify": verify, "pack": pack}[sys.argv[1]]()
