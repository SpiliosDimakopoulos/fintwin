"""Fill gaps in the SEC `companyfacts` API from the XBRL of each filing.

`companyfacts` is the convenient source, but it is not complete: in October 2026 the second-quarter 10-Qs of HCA
Healthcare and Coca-Cola, filed in July with XBRL, were still absent from it. This module lists a company's periodic
filings from the `submissions` API, finds the XBRL-tagged ones whose accession number never appears in
`companyfacts`, reads the XBRL instance of each (the `*_htm.xml` extracted from inline XBRL, or the stand-alone
instance of older filings), and appends its US-GAAP facts in the same row format, with the filing's own accession
number, form and filing date. Point-in-time loading therefore treats them exactly like facts from the API.

Only entity-wide facts (contexts without dimensions) in USD are kept, which is what `companyfacts` reports as well.
A candidate file is used only if its root element is an XBRL instance, and a fact repeated in one instance keeps its
most precise `decimals` (D11). Filings that `companyfacts` holds only in part are not completed.
"""

from __future__ import annotations

import gzip
import io
import logging
import os
import re
import xml.etree.ElementTree as ET

import numpy as np

from . import edgar as E

log = logging.getLogger(__name__)

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "http://xbrl.org/2006/xbrldi"
GAAP_PREFIX = "http://fasb.org/us-gaap/"


def enabled() -> bool:
    return os.environ.get("FINTWIN_XBRL_FALLBACK", "1") != "0"


def periodic_filings(cik: int) -> list[dict]:
    """Every XBRL-tagged 10-K / 10-Q (and amendments) in the company's complete filing history."""
    _, pages = E.submission_pages(cik, 24)
    out = []
    for p in pages:
        forms = p.get("form", [])
        xbrl, primary = p.get("isXBRL", [0] * len(forms)), p.get("primaryDocument", [""] * len(forms))
        for i, form in enumerate(forms):
            if form in E.PERIODIC_FORMS and xbrl[i]:
                out.append(
                    {"accn": p["accessionNumber"][i], "form": form, "filed": p["filingDate"][i], "primary": primary[i]}
                )
    return out


LINKBASE_SUFFIXES = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "_ref.xml")
NOT_INSTANCE = re.compile(r"^(FilingSummary|MetaLinks|defnref|R\d+)\.xml$", re.I)
MAX_CANDIDATES = 3


def _instance_name(cik: int, accn: str, primary: str) -> str | None:
    """Revision-2 choice: first inline instance, else the first .xml that is not a linkbase (may be a non-instance)."""
    names = _index_names(cik, accn)
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


def _index_names(cik: int, accn: str) -> list[str]:
    idx = E._get_json(
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/index.json",
        f"index_{accn}.json",
        24 * 365,
    )
    return [x["name"] for x in idx["directory"]["item"]]


def instance_candidates(names: list[str], primary: str) -> list[str]:
    """Possible XBRL instances of a filing, most likely first (D11): the inline-extracted `*_htm.xml`, then .xml files
    that are neither linkbases nor viewer/reference files (FilingSummary, MetaLinks, defnref, R*.xml), those named
    after the primary document first. The caller confirms each by its root element."""
    inline = [n for n in names if n.endswith("_htm.xml")]
    stem = primary.rsplit(".", 1)[0] if primary else ""
    xml = [n for n in names if n.endswith(".xml") and n not in inline]
    xml = [n for n in xml if not n.endswith(LINKBASE_SUFFIXES) and not NOT_INSTANCE.match(n)]
    xml.sort(key=lambda n: (not (stem and n.startswith(stem)), not re.search(r"\d{8}\.xml$", n)))
    return (inline + xml)[:MAX_CANDIDATES]


def is_instance(content: bytes) -> bool:
    """An XBRL instance has an `xbrli:xbrl` root element."""
    try:
        for _, el in ET.iterparse(io.BytesIO(content), events=("start",)):
            return el.tag == f"{XBRLI}xbrl"
    except ET.ParseError:
        return False
    return False


def _download(cik: int, accn: str, name: str) -> bytes:
    path = E.CACHE_DIR / f"xbrl_{accn}_{name}.gz"
    if path.exists():
        return gzip.decompress(path.read_bytes())
    if E.frozen():
        raise E.FrozenMiss(f"not in the frozen snapshot: {path.name}")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{name}"
    content = E.fetch(url).content
    if content[:64].lstrip().lower().startswith((b"<!doctype html", b"<html")):  # SEC's block page, never cache it
        raise RuntimeError(f"HTML page instead of XBRL from {url}; check SEC_USER_AGENT and the request rate")
    E.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    E.write_atomic(path, gzip.compress(content))
    return content


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
    seen: dict[tuple, tuple[float, dict]] = {}  # (tag, start, end) -> (precision, row)
    legacy = E.data_legacy()
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
        prec = _precision(el.get("decimals"))
        if key in seen:  # the same fact repeated in several statements
            # D11: keep the most precise version (a summary table may repeat a value rounded to millions)
            if legacy or prec <= seen[key][0]:
                continue
            seen[key][1]["val"] = val
            seen[key] = (prec, seen[key][1])
            continue
        row = {**ctx, "val": val, "accn": accn, "form": form, "filed": filed, "fy": None, "fp": None}
        seen[key] = (prec, row)
        out.setdefault(tag, []).append(row)
    return out


def _precision(decimals: str | None) -> float:
    """XBRL `decimals` as a sortable precision: INF is exact, a missing attribute is the least precise."""
    if decimals is None:
        return -np.inf
    if decimals.strip().upper() == "INF":
        return np.inf
    try:
        return float(decimals)
    except ValueError:
        return -np.inf


def _filing_facts(cik: int, f: dict, tags: set[str]) -> dict | None:
    """Facts of one filing from its XBRL instance, trying candidate files until one is an instance (D11)."""
    name = _instance_name(cik, f["accn"], f["primary"])
    # EDGAR's own extraction of an inline-XBRL filing is always an instance; anything else is checked (D11)
    if E.data_legacy() or (name and name.endswith("_htm.xml")):
        return parse_instance(_download(cik, f["accn"], name), tags, f["accn"], f["form"], f["filed"]) if name else None
    for name in instance_candidates(_index_names(cik, f["accn"]), f["primary"]):
        try:
            content = _download(cik, f["accn"], name)
        except Exception as e:
            log.warning("xbrl fallback: CIK %s %s/%s skipped: %s: %s", cik, f["accn"], name, type(e).__name__, e)
            continue
        if is_instance(content):
            return parse_instance(content, tags, f["accn"], f["form"], f["filed"])
    return None


def augment(cik: int, raw: dict, tags: set[str]) -> dict:
    """Append facts from periodic filings that `companyfacts` lacks. Never fails: on any error it returns `raw` with
    what was added so far, logs the error and lists it in `raw["_fallback_errors"]`."""
    if not enabled():
        return raw
    errors: list[str] = []
    try:
        gaap = raw.setdefault("facts", {}).setdefault("us-gaap", {})
        known = {r["accn"] for t in gaap.values() for rows in t.get("units", {}).values() for r in rows}
        missing = [f for f in periodic_filings(cik) if f["accn"] not in known and f["filed"] >= "2009-06-01"]
        added = []
        for f in missing:
            try:
                facts = _filing_facts(cik, f, tags)
            except Exception as e:  # one unreadable filing must not drop the others
                errors.append(f"{f['accn']}: {type(e).__name__}: {e}")
                log.warning("xbrl fallback: CIK %s filing skipped: %s", cik, errors[-1])
                continue
            if facts is None:
                continue
            for tag, rows in facts.items():
                gaap.setdefault(tag, {"units": {}})["units"].setdefault("USD", []).extend(rows)
            if facts:
                added.append(f["accn"])
        raw.setdefault("_fallback", []).extend(added)
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
        log.warning("xbrl fallback: CIK %s abandoned: %s", cik, errors[-1])
    if errors:
        raw["_fallback_errors"] = errors
    return raw
