"""Run the known-bad firms (12-11-2026 findings) under the current spec into .cache/research/_known_bad_<spec>/.

  python scripts/known_bad.py SPEC CIK...      (spec and selection from the environment, as a shard)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fintwin.clean import _clean  # noqa: E402
from fintwin.research.experiments import company  # noqa: E402

d = Path(".cache/research") / f"_known_bad_{sys.argv[1]}"
d.mkdir(parents=True, exist_ok=True)
for c in sys.argv[2:]:
    t = f"CIK{int(c):010d}"
    try:
        r = company(t, with_forecasts=True)
    except Exception as e:  # recorded like a shard
        r = {"ticker": t, "errors": {"company": f"{type(e).__name__}: {e}"}}
    (d / f"{t}.json").write_text(json.dumps(_clean(r)), encoding="utf-8")
    print(t, len(r.get("panel", [])), "panel rows", len(r.get("errors") or {}), "errors", flush=True)
