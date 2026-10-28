"""Model specification switches for the revision-3 ladder (docs/REVISION_PLAN_3.md §0.2).

FINTWIN_SPEC selects a specification:
- ``v2-pre``: the pre-specified model of paper 2.0.0 (35% fixed-cost prior), no revision-3 fixes;
- ``v2-rev``: the revised model of revision 2 (5% prior), no revision-3 fixes. The default: it is today's product;
- ``v3``: every model fix of REVISION_PLAN_3 §1.

FINTWIN_FIXES overrides the fix set. ``F5,F4`` replaces it; ``+F9`` / ``-F3`` add to or remove from the spec's
defaults; ``none`` empties it. IDs may carry the ``MM-`` prefix. The research pipeline can also switch in-process with
``using(...)``, which takes precedence over the environment.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

SPECS = ("v2-pre", "v2-rev", "v3")
DEFAULT_SPEC = "v2-rev"

# Every switchable fix owned by the calibration workstream (B1). Others may register their own IDs: `active` accepts
# any ID and simply reports whether it is in the active set.
ALL_FIXES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F12", "F13", "F14", "M2", "M3")
# MM-F9 (parameter uncertainty) and M2 (floating by sector) are §2 extensions: off in v3, so H2 is unaffected.
# MM-F11 (debt-free loss-makers are not rated D) lives in model/sd_model.py (B2) and is part of v3; M1, M4, M5 are §2
# extensions, off in every spec.
V3_FIXES = (frozenset(ALL_FIXES) - {"F9", "M2"}) | {"F11"}
DEFAULT_FIXES = {"v2-pre": frozenset(), "v2-rev": frozenset(), "v3": V3_FIXES}

# The cumulative ladder of REVISION_PLAN_3 §0.2, as FINTWIN_FIXES values on top of FINTWIN_SPEC=v2-pre.
LADDER = (
    ("v2-pre", ""),
    ("+F5", "F5"),
    ("+F4", "F5,F4"),
    ("+F1", "F5,F4,F1"),
    ("+F2", "F5,F4,F1,F2"),
    ("+F3", "F5,F4,F1,F2,F3"),
)

# Fixed-cost prior mean per specification. v3 keeps the pre-specified 35%: the 5% of v2-rev was selected under the
# broken weighting (MM-F1), where choosing the prior meant choosing the estimate.
FIXED_SHARE_PRIOR_BY_SPEC = {"v2-pre": 0.35, "v2-rev": 0.05, "v3": 0.35}

_override: ContextVar[tuple[str | None, str | None] | None] = ContextVar("fintwin_spec_override", default=None)


def _norm(fix_id: str) -> str:
    f = fix_id.strip().upper()
    return f[3:] if f.startswith("MM-") else f


def spec() -> str:
    o = _override.get()
    name = (o[0] if o and o[0] else None) or os.environ.get("FINTWIN_SPEC") or DEFAULT_SPEC
    name = name.strip().lower()
    if name not in SPECS:
        raise ValueError(f"FINTWIN_SPEC={name!r}: expected one of {SPECS}")
    return name


def fixes() -> frozenset[str]:
    """The active fix IDs (normalised, without the MM- prefix)."""
    o = _override.get()
    raw = o[1] if o and o[1] is not None else os.environ.get("FINTWIN_FIXES")
    base = DEFAULT_FIXES[spec()]
    if raw is None:
        return base
    items = [s.strip() for s in raw.split(",") if s.strip()]
    if not items or [s.lower() for s in items] == ["none"]:
        return frozenset() if items else base
    if all(s[0] in "+-" for s in items):
        out = set(base)
        for s in items:
            (out.add if s[0] == "+" else out.discard)(_norm(s[1:]))
        return frozenset(out)
    return frozenset(_norm(s) for s in items)


def active(fix_id: str) -> bool:
    return _norm(fix_id) in fixes()


def fixed_share_prior() -> float:
    return FIXED_SHARE_PRIOR_BY_SPEC[spec()]


def label() -> str:
    """Human-readable stamp for shard files and _sources, e.g. ``v2-pre+F5,F4``."""
    f = fixes()
    if f == DEFAULT_FIXES[spec()]:
        return spec()
    return f"{spec()}[{','.join(sorted(f, key=lambda s: (s[0], int(s[1:]) if s[1:].isdigit() else 0)))}]"


@contextmanager
def using(spec_name: str | None = None, fix_list: str | None = None):
    """Switch specification in-process (overrides the environment). ``fix_list`` uses the FINTWIN_FIXES syntax."""
    token = _override.set((spec_name, fix_list))
    try:
        spec()  # validate early
        yield
    finally:
        _override.reset(token)
