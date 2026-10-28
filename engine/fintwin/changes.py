"""Weekly "what changed" feed: compare this week's twins with last week's and explain the material moves.

Every Monday the data workflow rebuilds all twins from the latest filings. Before the new index replaces the old
one, this module diffs the two: which companies filed new quarters, whose baseline health moved materially, and
which component of the score (liquidity runway, interest coverage, leverage, solvency) drove the move. The result is
kept as a rolling history in data/changes.json and published as an RSS feed (data/feed.xml).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape

THRESHOLD = 5.0  # health points on the 0-100 scale
HISTORY_WEEKS = 26
SITE = "https://spiliosdimakopoulos.github.io/fintwin/"
# weights of the health score's components (model.sd_model): runway, coverage rating, leverage, Altman Z''
WEIGHTS = {"liq": 0.3, "cov": 0.3, "lev": 0.2, "solv": 0.2}
LABELS = {"liq": "liquidity runway", "cov": "interest coverage", "lev": "leverage", "solv": "solvency (Altman Z'')"}


def _round(x, nd: int):
    return None if x is None else round(x, nd)


def _drivers(before: dict | None, after: dict | None) -> list[dict]:
    """Contribution of each component to the change in the score, largest first."""
    if not before or not after:
        return []
    out = [
        {"component": k, "label": LABELS[k], "points": round(WEIGHTS[k] * (after[k] - before[k]), 1)}
        for k in WEIGHTS
        if before.get(k) is not None and after.get(k) is not None
    ]
    return sorted((d for d in out if abs(d["points"]) >= 0.5), key=lambda d: -abs(d["points"]))


def diff(prev: dict, new: dict, today: str | None = None) -> dict:
    """One week's changes between two index.json payloads."""
    pc, nc = prev.get("companies", {}), new.get("companies", {})
    movers, filings = [], []
    for t in sorted(set(pc) & set(nc)):
        a, b = pc[t], nc[t]
        filed = a.get("last_quarter") != b.get("last_quarter")
        if filed:
            filings.append({"ticker": t, "name": b["name"], "quarter": b.get("last_quarter")})
        ba, bb = a["matrix"]["base"], b["matrix"]["base"]
        h0, h1 = ba.get("health"), bb.get("health")
        if h0 is None or h1 is None:  # a null score (NaN in the build) must not crash the weekly aggregate
            continue
        if abs(h1 - h0) < THRESHOLD:
            continue
        s0, s1 = a["matrix"].get("pandemic", {}).get("health"), b["matrix"].get("pandemic", {}).get("health")
        movers.append(
            {
                "ticker": t,
                "name": b["name"],
                "sector": b.get("sector", ""),
                "health_before": round(h0, 1),
                "health_after": round(h1, 1),
                "delta": round(h1 - h0, 1),
                "stress_before": None if s0 is None else round(s0, 1),
                "stress_after": None if s1 is None else round(s1, 1),
                "p_breach_before": _round(ba.get("p_breach"), 3),
                "p_breach_after": _round(bb.get("p_breach"), 3),
                "new_filing": filed,
                "quarter": b.get("last_quarter"),
                "drivers": _drivers(a.get("components"), b.get("components")),
            }
        )
    movers.sort(key=lambda m: m["delta"])
    return {
        "date": today or date.today().isoformat(),
        "previous": prev.get("meta", {}).get("generated"),
        "n_companies": len(set(pc) & set(nc)),
        "n_new_filings": len(filings),
        "n_weaker": sum(m["delta"] < 0 for m in movers),
        "n_stronger": sum(m["delta"] > 0 for m in movers),
        "movers": movers,
        "new_filings": filings,
        "added": sorted(set(nc) - set(pc)),
        "removed": sorted(set(pc) - set(nc)),
    }


def update_history(history: dict | None, week: dict) -> dict:
    """Prepend this week, replacing an entry with the same date (re-runs), keep the last HISTORY_WEEKS weeks."""
    weeks = [w for w in (history or {}).get("weeks", []) if w.get("date") != week["date"]]
    return {"threshold": THRESHOLD, "weeks": [week, *weeks][:HISTORY_WEEKS]}


def _title(w: dict) -> str:
    if not w["n_weaker"] and not w["n_stronger"]:
        return f"FinTwin weekly, {w['date']}: no material changes ({w['n_new_filings']} new filings)"
    return f"FinTwin weekly, {w['date']}: {w['n_weaker']} weaker, {w['n_stronger']} stronger"


def _line(m: dict) -> str:
    why = ", ".join(f"{d['label']} {d['points']:+.1f}" for d in m["drivers"][:2])
    filing = f"; new quarter {m['quarter']}" if m["new_filing"] else ""
    return f"{m['ticker']} ({m['name']}): health {m['health_before']:.0f} to {m['health_after']:.0f}{filing}" + (
        f"; driven by {why}" if why else ""
    )


def rss(history: dict) -> str:
    """RSS 2.0 feed, one item per weekly rebuild."""
    items = []
    for w in history["weeks"]:
        lines = [_line(m) for m in w["movers"][:12]] or ["No company's baseline health moved by 5 points or more."]
        pub = format_datetime(datetime.fromisoformat(w["date"]).replace(hour=8, tzinfo=UTC))
        items.append(
            "<item>"
            f"<title>{escape(_title(w))}</title>"
            f"<link>{SITE}#changes</link>"
            f'<guid isPermaLink="false">fintwin-week-{w["date"]}</guid>'
            f"<pubDate>{pub}</pubDate>"
            f"<description>{escape('<br>'.join(escape(x) for x in lines))}</description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        "<title>FinTwin: what changed this week</title>"
        f"<link>{SITE}#changes</link>"
        "<description>Weekly rebuild of financial digital twins of S&amp;P 500 companies from SEC filings: "
        "which companies' health moved, and why.</description>"
        "<language>en</language>" + "".join(items) + "</channel></rss>\n"
    )
