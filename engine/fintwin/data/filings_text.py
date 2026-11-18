"""Filing text for T1 and T2 (revision plan 5, "T1 and T2: filing text"): the sections of the 10-K / 10-Q filed by a
cutoff.

For a company and a cutoff date d, the documents are the latest 10-K filed on or before d and the 10-Qs filed after
it, also on or before d. From the primary document of each, three sections are kept as plain text:
- MD&A (10-K Item 7; 10-Q Part I, Item 2),
- Risk Factors (10-K Item 1A; 10-Q Part II, Item 1A),
- the "Liquidity and Capital Resources" subsection of the MD&A.

Non-negotiable rule: no document filed after the cutoff. `check_filed_by` enforces it when a firm-year record is
written and again when it is read; it raises (it is not an `assert`, which `python -O` would remove).

Everything goes through `edgar.py` (`submission_pages`, `fetch` with its shared throttle under 10 requests/s and the
403 stop). Raw documents are not stored: only the three sections, in `engine/.cache/text` (a sibling of
`.cache/edgar`, so `freeze_snapshot.py`'s snapshot is unchanged). `freeze_text_snapshot` writes its own manifest.

Where the plan is silent nothing is guessed: amendments (10-K/A, 10-Q/A) are not used, a filing without a primary
document, a non-parseable document or a missing section is recorded with a reason in `failures`, and an MD&A
incorporated by reference (for example to the annual report exhibit) is recorded as missing.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from . import edgar as E

TEXT_DIR = E.CACHE_DIR.parent / "text"
SNAPSHOT_DIR = E.CACHE_DIR.parents[1] / "snapshot" / "text"  # beside freeze_snapshot.py's manifest, git-ignored

ANNUAL_FORMS = ("10-K", "10-K405", "10-KT")
QUARTERLY_FORMS = ("10-Q",)
SECTIONS = ("mda", "risk_factors", "liquidity")
SCHEMA = 1


class LookAheadError(ValueError):
    """A document filed after the cutoff reached the text features."""


def _date(x: str | dt.date) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def check_filed_by(docs: list[dict], cutoff: str | dt.date) -> None:
    """Raise LookAheadError unless every document's filingDate is on or before the cutoff (the one guard, used at
    write time and at read time)."""
    c = _date(cutoff)
    late = [(d.get("accession"), d.get("filingDate")) for d in docs if _date(d["filingDate"]) > c]
    if late:
        raise LookAheadError(f"documents filed after the cutoff {c}: {late}")


# ---------------------------------------------------------------------------------------------- choosing documents


def periodic_documents(pages: list[dict]) -> list[dict]:
    """Original 10-K / 10-Q filings of a company from its `submissions` pages (amendments are not used)."""
    out = []
    for p in pages:
        forms = p.get("form", [])
        n = len(forms)
        primary = p.get("primaryDocument", [""] * n)
        report = p.get("reportDate", [""] * n)
        for i, form in enumerate(forms):
            if form in ANNUAL_FORMS or form in QUARTERLY_FORMS:
                out.append(
                    {
                        "accession": p["accessionNumber"][i],
                        "form": form,
                        "filingDate": p["filingDate"][i],
                        "period": report[i] or "",
                        "primary": primary[i] or "",
                    }
                )
    return out


def select_documents(docs: list[dict], cutoff: str | dt.date) -> list[dict]:
    """The latest 10-K filed on or before the cutoff and the 10-Qs filed after it (and on or before the cutoff),
    oldest first. No 10-K by the cutoff: an empty list (the firm-year has no text)."""
    c = _date(cutoff)
    usable = [d for d in docs if _date(d["filingDate"]) <= c]
    annual = [d for d in usable if d["form"] in ANNUAL_FORMS]
    if not annual:
        return []
    k = max(annual, key=lambda d: (d["filingDate"], d["accession"]))
    qs = [d for d in usable if d["form"] in QUARTERLY_FORMS and d["filingDate"] > k["filingDate"]]
    out = [k, *sorted(qs, key=lambda d: (d["filingDate"], d["accession"]))]
    check_filed_by(out, c)
    return out


def document_url(cik: int, accession: str, primary: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{primary}"


# ---------------------------------------------------------------------------------------------- HTML to text

_BLOCK = {
    "p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "title", "center",
    "section", "article", "header", "footer", "blockquote", "pre", "hr", "dt", "dd", "page",
}  # fmt: skip
_SKIP = {"script", "style", "head", "ix:header", "xbrli:context", "noscript"}
_CELL = {"td", "th"}


_NL = "\n"
_VOID = {"br", "hr", "img", "input", "meta", "link", "col", "area", "base", "wbr"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0  # inside script/style/head/ix:header
        self.hide_tag: str | None = None  # an element styled display:none (inline XBRL hides its header this way)
        self.hide_depth = 0
        self.pre = 0  # inside <pre>: the source's line breaks are the text's

    def handle_starttag(self, tag, attrs):
        self.pre += tag == "pre"
        if self.hide_tag:
            self.hide_depth += tag == self.hide_tag
            return
        if tag in _SKIP:
            self.skip += 1
            return
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if "display:none" in style and tag not in _VOID:
            self.hide_tag, self.hide_depth = tag, 1
            return
        if tag in _BLOCK:
            self.parts.append(_NL)
        elif tag in _CELL:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
        if self.hide_tag:
            if tag == self.hide_tag:
                self.hide_depth -= 1
                if not self.hide_depth:
                    self.hide_tag = None
            return
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in _BLOCK:
            self.parts.append(_NL)
        elif tag in _CELL:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr") and not (self.skip or self.hide_tag):
            self.parts.append(_NL)

    def handle_data(self, data):
        if not (self.skip or self.hide_tag):
            # HTML whitespace: a line break in the source is a space (filings hard-wrap text inside paragraphs);
            # only block elements start a line
            self.parts.append(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_text(raw: str) -> str:
    """Plain text with one line per block element; runs of spaces collapsed, non-breaking spaces made plain."""
    if not re.search(r"<\s*(html|body|div|p|table|font)\b", raw[:20000], re.I):
        text = raw  # a plain-text filing (older EDGAR documents)
    else:
        parser = _TextParser()
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    text = text.replace("\xa0", " ").replace("​", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# ---------------------------------------------------------------------------------------------- sections

_SEP = r"[\s.:\-–—]*"
_ITEM = r"^\s*item\s*"
_TITLE = {
    "mda": r"management[’']?s\s+discussion\s+and\s+analysis",
    "risk": r"risk\s+factors",
    "qqd": r"quantitative\s+and\s+qualitative\s+disclosures?",
    "fs": r"(?:consolidated\s+)?financial\s+statements",
    "controls": r"controls\s+and\s+procedures",
    "unresolved": r"unresolved\s+staff\s+comments",
    "properties": r"properties",
    "cyber": r"cybersecurity",
    "legal": r"legal\s+proceedings",
    "sales": r"unregistered\s+sales",
    "defaults": r"defaults\s+upon\s+senior\s+securities",
    "other": r"other\s+information",
    "exhibits": r"exhibits",
}


def _heading(item: str, title: str | None = None) -> re.Pattern:
    """An `Item N.` heading at the start of a line (title text optional), e.g. `ITEM 7. MANAGEMENT'S DISCUSSION`."""
    t = rf"{_SEP}{_TITLE[title]}" if title else r"(?:\b|[\s.:\-–—])"
    return re.compile(rf"{_ITEM}{item}{t}", re.I | re.M)


SECTION_RULES = {
    "10-K": {
        "mda": ([_heading("7", "mda")], [_heading("7a"), _heading("8")]),
        "risk_factors": ([_heading("1a", "risk")], [_heading("1b"), _heading("1c"), _heading("2", "properties"),
                                                     _heading("2")]),
    },
    "10-Q": {
        "mda": ([_heading("2", "mda")], [_heading("3", "qqd"), _heading("4", "controls"), _heading("3"),
                                         _heading("4")]),
        "risk_factors": ([_heading("1a", "risk")], [_heading("2", "sales"), _heading("2"), _heading("3"),
                                                    _heading("5"), _heading("6")]),
    },
}  # fmt: skip

_LIQ_START = re.compile(r"^\s*(?:[A-Z]?[\d.]*\s*)?liquidity\s+and\s+capital\s+resources\s*:?\s*$", re.I | re.M)
_LIQ_END = re.compile(
    r"^\s*(?:critical\s+accounting|off[\s-]balance\s+sheet|recent(?:ly)?\s+(?:issued\s+|adopted\s+)?accounting"
    r"|new\s+accounting|recently\s+issued|forward[\s-]looking|cautionary|quantitative\s+and\s+qualitative"
    r"|inflation\b|seasonality\b|market\s+risk\b|results\s+of\s+operations\b|non-gaap|outlook\b)[^\n]{0,80}$",
    re.I | re.M,
)
MIN_SECTION_WORDS = 50


def _span(text: str, starts: list[re.Pattern], ends: list[re.Pattern]) -> str:
    """The longest span from a start heading to the next end or start heading: a table-of-contents entry runs only
    to the next entry or to the body's own heading, the body's heading to the next item. A start without anything
    after it runs to the end of the document."""
    best = ""
    found = [m for pat in starts for m in pat.finditer(text)]
    bounds = sorted({m.start() for pat in ends for m in pat.finditer(text)} | {m.start() for m in found})
    for m in found:
        nxt = next((e for e in bounds if e > m.start()), len(text))
        seg = text[m.start() : nxt]
        if len(seg) > len(best):
            best = seg
    return best.strip()


def _first_line_dropped(seg: str) -> str:
    return seg.split("\n", 1)[1].strip() if "\n" in seg else ""


def _incorporated_by_reference(seg: str) -> bool:
    return len(seg.split()) < 300 and bool(re.search(r"incorporated\s+(?:herein\s+)?by\s+reference", seg, re.I))


def _part_one_or_two(text: str, form: str) -> tuple[str, str]:
    """10-Q: (Part I, Part II), split at the last `PART II` line followed by an Item 1 / 1A heading (page headers
    that repeat "Part II" later in the part are not); 10-K: (text, text)."""
    if form != "10-Q":
        return text, text
    marks = [m.start() for m in re.finditer(r"^\s*part\s+ii\b(?!i)", text, re.I | re.M)]
    for pos in reversed(marks):
        if re.search(rf"{_ITEM}1a?\b", text[pos:], re.I | re.M):
            return text[:pos], text[pos:]
    return text, ""


def extract_sections(text: str, form: str) -> tuple[dict[str, str], dict[str, str]]:
    """({section: text}, {section: failure reason}) for the plain text of a 10-K or 10-Q."""
    kind = "10-K" if form in ANNUAL_FORMS else "10-Q"
    part1, part2 = _part_one_or_two(text, kind)
    rules = SECTION_RULES[kind]
    out, fail = {}, {}
    for name, (starts, ends) in rules.items():
        src = part2 if (kind == "10-Q" and name == "risk_factors") else part1
        seg = _span(src, starts, ends)
        body = _first_line_dropped(seg)
        if not seg:
            fail[name] = "heading not found"
        elif _incorporated_by_reference(body):
            fail[name] = "incorporated by reference"
        elif len(body.split()) < MIN_SECTION_WORDS:
            fail[name] = f"fewer than {MIN_SECTION_WORDS} words"
        else:
            out[name] = body
    if "mda" in out:
        liq = _first_line_dropped(_span(out["mda"], [_LIQ_START], [_LIQ_END]))
        if len(liq.split()) >= MIN_SECTION_WORDS:
            out["liquidity"] = liq
        else:
            fail["liquidity"] = "subsection not found"
    else:
        fail["liquidity"] = "no MD&A"
    return out, fail


_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|[^\sA-Za-z0-9]")


def token_count(text: str) -> int:
    """Word-and-punctuation tokens (a model-independent size; the subword count is measured at embedding time)."""
    return len(_TOKEN.findall(text))


# ---------------------------------------------------------------------------------------------- download and store


def _doc_record(cik: int, doc: dict) -> dict:
    rec = {k: doc[k] for k in ("accession", "form", "filingDate", "period")}
    rec.update(sections={}, tokens={}, failures={}, url=document_url(cik, doc["accession"], doc["primary"]))
    if not doc["primary"]:
        rec["failures"]["document"] = "no primary document in submissions"
        return rec
    try:
        resp = E.fetch(rec["url"])
    except E.requests.HTTPError as e:  # a missing document is recorded; a 403 block or any other error stops the run
        if e.response is None or e.response.status_code != 404:
            raise
        rec["failures"]["document"] = "404 for the primary document"
        return rec
    raw = resp.content.decode(resp.encoding or "utf-8", errors="replace")
    text = html_to_text(raw)
    if len(text.split()) < MIN_SECTION_WORDS:
        rec["failures"]["document"] = "no text in primary document"
        return rec
    sections, failures = extract_sections(text, doc["form"])
    rec["sections"] = sections
    rec["tokens"] = {k: token_count(v) for k, v in sections.items()}
    rec["failures"] = failures
    return rec


def firm_year_path(cik: int, cutoff: str | dt.date, root: Path | None = None) -> Path:
    return (root or TEXT_DIR) / f"{cik:010d}" / f"{_date(cutoff).isoformat()}.json.gz"


def write_firm_year(cik: int, cutoff: str | dt.date, docs: list[dict], root: Path | None = None) -> Path:
    check_filed_by(docs, cutoff)  # rule 1, at write time
    path = firm_year_path(cik, cutoff, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"schema": SCHEMA, "cik": cik, "cutoff": _date(cutoff).isoformat(), "documents": docs}
    E.write_atomic(path, gzip.compress(json.dumps(rec, sort_keys=True).encode("utf-8"), mtime=0))
    return path


def load_firm_year(cik: int, cutoff: str | dt.date, root: Path | None = None) -> dict:
    """The stored record; raises LookAheadError if any document was filed after the cutoff (rule 1, at read time)."""
    path = firm_year_path(cik, cutoff, root)
    if not path.exists():
        raise E.FrozenMiss(f"no text record: {path}") if E.frozen() else FileNotFoundError(path)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rec = json.load(fh)
    if rec["cik"] != cik or rec["cutoff"] != _date(cutoff).isoformat():
        raise ValueError(f"{path} holds cik {rec['cik']} cutoff {rec['cutoff']}")
    check_filed_by(rec["documents"], cutoff)
    return rec


def filing_text(cik: int, cutoff: str | dt.date, root: Path | None = None, max_age_hours: float = 24 * 30) -> dict:
    """The firm-year record for (cik, cutoff): read from the text cache, else built from SEC and written. In frozen
    mode (FINTWIN_FROZEN=1) a missing record is an error, never a fetch."""
    path = firm_year_path(cik, cutoff, root)
    if path.exists() or E.frozen():
        return load_firm_year(cik, cutoff, root)
    _, pages = E.submission_pages(cik, max_age_hours)
    docs = [_doc_record(cik, d) for d in select_documents(periodic_documents(pages), cutoff)]
    write_firm_year(cik, cutoff, docs, root)
    return load_firm_year(cik, cutoff, root)


# ---------------------------------------------------------------------------------------------- snapshot


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def text_manifest(root: Path | None = None) -> dict:
    root = root or TEXT_DIR
    files = {p.relative_to(root).as_posix(): _sha(p) for p in sorted(root.rglob("*.json.gz")) if p.is_file()}
    digest = hashlib.sha256("".join(f"{k} {v}\n" for k, v in files.items()).encode()).hexdigest()
    return {"files": files, "n_files": len(files), "digest": digest}


def freeze_text_snapshot(root: Path | None = None, out: Path | None = None, extra: dict | None = None) -> dict:
    """Write `manifest.json` (sha256 per file and one digest over all, as in scripts/freeze_snapshot.py) after
    re-reading every record through the cutoff guard, so a snapshot can never hold a late document."""
    root, out = root or TEXT_DIR, out or SNAPSHOT_DIR
    n_docs = 0
    for p in sorted(root.rglob("*.json.gz")):
        rec = load_firm_year(int(p.parent.name), p.name.removesuffix(".json.gz"), root)
        n_docs += len(rec["documents"])
    m = text_manifest(root)
    m.update(
        schema=SCHEMA,
        n_documents=n_docs,
        frozen_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        **(extra or {}),
    )
    out.mkdir(parents=True, exist_ok=True)
    E.write_atomic(out / "manifest.json", json.dumps(m, indent=1).encode("utf-8"))
    return m


def verify_text_snapshot(root: Path | None = None, out: Path | None = None) -> None:
    want = json.loads(((out or SNAPSHOT_DIR) / "manifest.json").read_text(encoding="utf-8"))
    have = text_manifest(root)
    if have["digest"] != want["digest"]:
        missing = sorted(set(want["files"]) - set(have["files"]))
        changed = sorted(k for k in want["files"] if k in have["files"] and have["files"][k] != want["files"][k])
        raise ValueError(f"text snapshot does not match its manifest: missing {missing[:3]}, changed {changed[:3]}")
