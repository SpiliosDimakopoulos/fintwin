"""Corporate families of the universe (a reader, 12-11-2026 reply): registrants of one group are linked when they
appear on the same filing.

A joint filing lists every co-registrant under one accession number, so two universe CIKs that share an accession
number on a 10-K, 10-Q or 8-K (or an amendment) belong to one group: a parent and the subsidiaries with their own
public debt, or the captive finance arm of a manufacturer. Ownership filings (Forms 3/4/5, SC 13D/G) list issuer and
holder under one accession too, and would join investors to their holdings, so they are not used. Links are taken
from the whole snapshot (a clustering unit, not a predictor, so no point-in-time issue); a merger 8-K filed jointly
by acquirer and target joins them, which only makes the clusters larger (conservative).

Used as a robustness check declared after the pre-specification (docs/review_2026-10/RERUN5_PLAN.md, WP6): the
bootstrap resamples families instead of firms, and a group's bankruptcy counts once per family and cutoff.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

LINK_FORMS = frozenset({"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "8-K/A", "10-KT", "10-KT/A"})


def links(filings: dict[int, pd.DataFrame], counts: dict | None = None) -> list[tuple[int, int]]:
    """Pairs of CIKs that share an accession number on a periodic or current report (`counts`, when given, receives
    the number of shared filings per pair)."""
    owners: dict[str, set[int]] = {}
    for cik, f in filings.items():
        if f is None or f.empty:
            continue
        sel = f[f["form"].isin(LINK_FORMS)]
        for acc in sel["accessionNumber"].unique():
            owners.setdefault(acc, set()).add(int(cik))
    out = set()
    for ciks in owners.values():
        if len(ciks) > 1:
            first, *rest = sorted(ciks)
            out |= {(first, c) for c in rest}
            if counts is not None:
                for c in rest:
                    counts[(first, c)] = counts.get((first, c), 0) + 1
    return sorted(out)


def families(ciks: Iterable[int], pairs: Iterable[tuple[int, int]]) -> dict[int, int]:
    """CIK -> family id (the smallest CIK of its group), by union-find; a CIK without a link is its own family."""
    parent = {int(c): int(c) for c in ciks}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    return {c: find(c) for c in parent}


def build(ciks: list[int], out: Path | None = None) -> dict[int, int]:
    """Families of `ciks` from the snapshot's submissions; written to `out` (JSON) when given."""
    from ..data.edgar_universe import submissions

    filings = {}
    missing = 0
    for c in ciks:
        try:
            filings[c] = submissions(c)["filings"][["accessionNumber", "form"]]
        except Exception:  # noqa: BLE001 - a CIK without submissions is its own family, and counted
            filings[c] = None
            missing += 1
    if ciks and missing > len(ciks) / 2:  # no snapshot submissions: every family would be a singleton, silently
        raise SystemExit(f"families: no submissions for {missing} of {len(ciks)} CIKs")
    print(f"families: submissions missing for {missing} of {len(ciks)} CIKs (each its own family)")
    counts: dict = {}
    fam = families(ciks, links(filings, counts))
    thin = sum(1 for v in counts.values() if v <= 2)  # links resting on one or two joint filings (a merger 8-K)
    print(f"families: {len(counts)} links, {thin} of them on <= 2 shared filings")
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({str(k): v for k, v in fam.items()}), encoding="utf-8")
    return fam


def summary(fam: dict[int, int]) -> dict:
    sizes = pd.Series(list(fam.values())).value_counts()
    return {"ciks": len(fam), "families": int(len(sizes)), "multi_member": int((sizes > 1).sum()),
            "ciks_in_multi": int(sizes[sizes > 1].sum()), "largest": int(sizes.max()) if len(sizes) else 0}  # fmt: skip
