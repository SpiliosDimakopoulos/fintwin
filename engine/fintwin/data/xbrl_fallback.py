"""Fill gaps in the SEC `companyfacts` API from the XBRL of each filing.

`companyfacts` is the convenient source, but it is not complete: in October 2026 the second-quarter 10-Qs of HCA
Healthcare and Coca-Cola, filed in July with XBRL, were still absent from it. This module lists a company's periodic
filings from the `submissions` API, finds the XBRL-tagged ones whose accession number never appears in
`companyfacts`, reads the XBRL instance of each (the `*_htm.xml` extracted from inline XBRL, or the stand-alone
instance of older filings), and appends its US-GAAP facts in the same row format, with the filing's own accession
number, form and filing date. Point-in-time loading therefore treats them exactly like facts from the API.

Only entity-wide facts (contexts without dimensions) in USD are kept, which is what `companyfacts` reports as well.
"""

from __future__ import annotations

import gzip
import os
import xml.etree.ElementTree as ET

import requests

from . import edgar as E

PERIODIC = {"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT"}
XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "http://xbrl.org/2006/xbrldi"
GAAP_PREFIX = "http://fasb.org/us-gaap/"


def enabled() -> bool:
    return os.environ.get("FINTWIN_XBRL_FALLBACK", "1") != "0"


def periodic_filings(cik: int) -> list[dict]:
    """Every XBRL-tagged 10-K / 10-Q (and amendments) in the company's complete filing history."""
    d = E._get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"submissions_{cik:010d}.json", 24)
    pages = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        pages.append(E._get_json(f"https://data.sec.gov/submissions/{f['name']}", f["name"], 24 * 365))
    out = []
    for p in pages:
        for i, form in enumerate(p.get("form", [])):
            if form in PERIODIC and p.get("isXBRL", [0] * (i + 1))[i]:
                out.append(
                    {
                        "accn": p["accessionNumber"][i],
                        "form": form,
                        "filed": p["filingDate"][i],
                        "primary": p.get("primaryDocument", [""] * (i + 1))[i],
                    }
                )
    return out


def _instance_name(cik: int, accn: str, primary: str) -> str | None:
    idx = E._get_json(
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/index.json",
        f"index_{accn}.json",
        24 * 365,
    )
    names = [x["name"] for x in idx["directory"]["item"]]
    inline = [n for n in names if n.endswith("_htm.xml")]
    if inline:
        return inline[0]
    stem = primary.rsplit(".", 1)[0] if primary else ""
    xml = [
        n
        for n in names
        if n.endswith(".xml")
        and n not in ("FilingSummary.xml",)
        and not n.endswith(("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml"))
    ]
    exact = [n for n in xml if n.startswith(stem)] if stem else []
    return (exact or xml or [None])[0]


def _download(cik: int, accn: str, name: str) -> bytes:
    path = E.CACHE_DIR / f"xbrl_{accn}_{name}.gz"
    if path.exists():
        return gzip.decompress(path.read_bytes())
    if E.frozen():
        raise E.FrozenMiss(f"not in the frozen snapshot: {path.name}")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{name}"
    last = None
    for _ in range(3):
        try:
            import time

            wait = E._MIN_INTERVAL - (time.time() - E._last_request)
            if wait > 0:
                time.sleep(wait)
            r = requests.get(url, headers={"User-Agent": E._user_agent()}, timeout=60)
            E._last_request = time.time()
            r.raise_for_status()
            E.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(r.content))
            return r.content
        except requests.RequestException as e:
            last = e
    raise RuntimeError(f"could not download {url}: {last}")


def parse_instance(content: bytes, tags: set[str], accn: str, form: str, filed: str) -> dict[str, list[dict]]:
    """US-GAAP USD facts of one XBRL instance, entity-wide contexts only, in `companyfacts` row format."""
    root = ET.fromstring(content)
    contexts: dict[str, dict] = {}
    for c in root.iter(f"{XBRLI}context"):
        if c.find(f"{XBRLI}entity/{XBRLI}segment") is not None or c.find(f"{XBRLI}scenario") is not None:
            continue
        p = c.find(f"{XBRLI}period")
        if p is None:
            continue
        inst = p.find(f"{XBRLI}instant")
        if inst is not None:
            contexts[c.get("id") or ""] = {"end": (inst.text or "").strip()[:10]}
        else:
            s, e = p.find(f"{XBRLI}startDate"), p.find(f"{XBRLI}endDate")
            if s is not None and e is not None:
                contexts[c.get("id") or ""] = {"start": (s.text or "").strip()[:10], "end": (e.text or "").strip()[:10]}
    usd = set()
    for u in root.iter(f"{XBRLI}unit"):
        m = u.find(f"{XBRLI}measure")
        if m is not None and m.text and m.text.strip().split(":")[-1] == "USD":
            usd.add(u.get("id"))
    out: dict[str, list[dict]] = {}
    seen: set[tuple] = set()
    for el in root:
        if not el.tag.startswith("{" + GAAP_PREFIX):
            continue
        tag = el.tag.split("}", 1)[1]
        if tag not in tags or el.get("unitRef") not in usd or el.get("contextRef") not in contexts:
            continue
        if el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true" or not (el.text or "").strip():
            continue
        try:
            val = float((el.text or "").strip())
        except ValueError:
            continue
        ctx = contexts[el.get("contextRef") or ""]
        key = (tag, ctx.get("start"), ctx["end"])
        if key in seen:  # the same fact repeated in several statements
            continue
        seen.add(key)
        out.setdefault(tag, []).append(
            {**ctx, "val": val, "accn": accn, "form": form, "filed": filed, "fy": None, "fp": None}
        )
    return out


def augment(cik: int, raw: dict, tags: set[str]) -> dict:
    """Append facts from periodic filings that `companyfacts` lacks. Never fails: on any error, returns `raw`."""
    if not enabled():
        return raw
    try:
        gaap = raw.setdefault("facts", {}).setdefault("us-gaap", {})
        known = {r["accn"] for t in gaap.values() for rows in t.get("units", {}).values() for r in rows}
        missing = [f for f in periodic_filings(cik) if f["accn"] not in known and f["filed"] >= "2009-06-01"]
        added = []
        for f in missing:
            try:
                name = _instance_name(cik, f["accn"], f["primary"])
                if not name:
                    continue
                facts = parse_instance(_download(cik, f["accn"], name), tags, f["accn"], f["form"], f["filed"])
            except Exception:  # one unreadable filing must not drop the others
                continue
            for tag, rows in facts.items():
                gaap.setdefault(tag, {"units": {}})["units"].setdefault("USD", []).extend(rows)
            if facts:
                added.append(f["accn"])
        raw.setdefault("_fallback", []).extend(added)
    except Exception:
        return raw
    return raw
