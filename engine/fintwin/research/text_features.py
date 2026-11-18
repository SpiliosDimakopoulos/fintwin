"""Text features T1 and T2 (revision plan 5, "T1 and T2: filing text"; test P5-4), from `data/filings_text.py`.

T1, facts stated in the filing: a rule-based extractor whose patterns are published in `text_patterns.json`. It is
scored on 200 filings labelled by the author (`write_validation_sheet`, `score_validation`) and frozen before any
outcome is read (`freeze_extractor`, `assert_extractor_frozen`; the fingerprint covers the patterns and the extractor
source). The plan's five units are the labelled and scored units; the dividend unit is the union of two extracted
features, suspension and initiation.

T2, judgement: ChronoBERT embeddings (He, Lv, Manela and Wu 2025, arXiv:2502.21206), one vintage per cutoff.
Non-negotiable rule: the vintage's training data end strictly before the cutoff (`vintage_for`, `check_vintage`).
Training filings for test year Y are re-embedded with Y's vintage (`plan_embeddings`). The P5-4 control 3 (the 2024
vintage for every year) is the separately named `plan_vintage_difference_control`, whose rows are labelled as a
look-ahead control. transformers and torch are imported only inside `embed` (optional extra `fintwin[text]`).

P5-4 controls 2 and 4: `mask_identity` (masked-identity placebo) and `lm_counts` (Loughran-McDonald word counts).

This module imports nothing that reads outcomes.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import inspect
import json
import random
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import numpy as np

PATTERNS_PATH = Path(__file__).with_name("text_patterns.json")
T1_SECTIONS = ("mda", "risk_factors")  # the liquidity subsection lies inside the MD&A: not counted twice
SNIPPET_CHARS = 400


def _date(x: str | dt.date) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


# ============================================================================================== T1: extractor


def load_patterns(path: Path | None = None) -> dict:
    spec = json.loads(Path(path or PATTERNS_PATH).read_text(encoding="utf-8"))
    for f in spec["features"].values():
        f["_re"] = [re.compile(p, re.I) for p in f["patterns"]]
        f["_ex"] = [re.compile(p, re.I) for p in f.get("exclude", [])]
    return spec


_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9\"'(“])")


def split_sentences(text: str) -> list[str]:
    """Sentences: lines (one per HTML block) split after . ! ? ; before a capital, digit or quote."""
    return [s.strip() for line in text.split("\n") for s in _SENT.split(line) if len(s.strip()) > 3]


_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(million|billion|thousand|mn|bn|m\b|b\b)?", re.I)
_SCALE = {"thousand": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9}
_COST_WORD = re.compile(r"\b(?:costs?|charges?|expenses?)\b", re.I)


def dollar_amounts(sentence: str) -> list[float]:
    """Dollar amounts stated in a sentence, in dollars (`$12.5 million` -> 12.5e6)."""
    out = []
    for m in _AMOUNT.finditer(sentence):
        value = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        out.append(value * _SCALE.get((m.group(3) or "").lower(), 1.0))
    return out


def extract_t1(text: str, spec: dict | None = None) -> dict:
    """{feature: {"count": matching sentences, "snippets": [...]}} (+ "amount_usd" for restructuring: the largest
    dollar amount in a matching sentence that names a cost, charge or expense; None if none is stated)."""
    spec = spec or load_patterns()
    out: dict[str, dict] = {name: {"count": 0, "snippets": []} for name in spec["features"]}
    for name, f in spec["features"].items():
        if f.get("amount"):
            out[name]["amount_usd"] = None
    for sent in split_sentences(text):
        for name, f in spec["features"].items():
            if any(r.search(sent) for r in f["_re"]) and not any(r.search(sent) for r in f["_ex"]):
                rec = out[name]
                rec["count"] += 1
                rec["snippets"].append(sent[:SNIPPET_CHARS])
                if f.get("amount") and _COST_WORD.search(sent):
                    amounts = dollar_amounts(sent)
                    if amounts:
                        rec["amount_usd"] = max(amounts + [rec["amount_usd"] or 0.0])
    return out


def merge_t1(results: Iterable[dict]) -> dict:
    """Sum counts, keep snippets, take the largest amount over several texts (sections or documents)."""
    out: dict = {}
    for res in results:
        for name, r in res.items():
            o = out.setdefault(
                name, {"count": 0, "snippets": [], **({"amount_usd": None} if "amount_usd" in r else {})}
            )
            o["count"] += r["count"]
            o["snippets"] += r["snippets"]
            if r.get("amount_usd") is not None:
                o["amount_usd"] = max(o["amount_usd"] or 0.0, r["amount_usd"])
    return out


def t1_document(sections: dict[str, str], spec: dict | None = None) -> dict:
    """T1 on one filing: the MD&A and the Risk Factors (the liquidity subsection is inside the MD&A)."""
    spec = spec or load_patterns()
    return merge_t1(extract_t1(sections[s], spec) for s in T1_SECTIONS if sections.get(s))


def t1_units(res: dict, spec: dict | None = None) -> dict[str, int]:
    """The plan's five units as counts (a unit's count is the sum of its features' counts)."""
    spec = spec or load_patterns()
    units = dict.fromkeys(spec["units"], 0)
    for name, f in spec["features"].items():
        units[f["unit"]] += res.get(name, {}).get("count", 0)
    return units


def t1_features(record: dict, spec: dict | None = None) -> dict:
    """Flat T1 features of a firm-year record from `filings_text.load_firm_year`: counts and binaries per feature
    and per unit, and the restructuring amount, over all its documents."""
    spec = spec or load_patterns()
    res = merge_t1(t1_document(d["sections"], spec) for d in record["documents"])
    if not res:
        res = {name: {"count": 0, "snippets": []} for name in spec["features"]}
    out: dict = {}
    for name, r in res.items():
        out[f"t1_{name}_n"] = r["count"]
        out[f"t1_{name}"] = int(r["count"] > 0)
    for unit, n in t1_units(res, spec).items():
        out[f"t1u_{unit}"] = int(n > 0)
    out["t1_restructuring_cost_usd"] = res.get("restructuring", {}).get("amount_usd")
    return out


# ---------------------------------------------------------------------------------------------- freeze


def extractor_fingerprint(path: Path | None = None) -> str:
    """sha256 over the patterns file and the source of the extraction functions."""
    canonical = json.dumps(json.loads(Path(path or PATTERNS_PATH).read_text(encoding="utf-8")), sort_keys=True)
    h = hashlib.sha256(canonical.encode("utf-8"))  # independent of line endings and layout
    for fn in (load_patterns, split_sentences, dollar_amounts, extract_t1, merge_t1, t1_document, t1_units):
        h.update(inspect.getsource(fn).encode("utf-8"))
    h.update(_SENT.pattern.encode() + _AMOUNT.pattern.encode() + _COST_WORD.pattern.encode())
    h.update(repr(T1_SECTIONS).encode())
    return h.hexdigest()


def freeze_extractor(lock: Path, path: Path | None = None) -> dict:
    """Record the extractor's fingerprint; the code that reads outcomes calls `assert_extractor_frozen` first."""
    if lock.exists():
        raise FileExistsError(f"{lock} exists: the extractor is already frozen")
    rec = {
        "fingerprint": extractor_fingerprint(path),
        "frozen_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def assert_extractor_frozen(lock: Path, path: Path | None = None) -> None:
    if not lock.exists():
        raise RuntimeError(f"T1 extractor not frozen ({lock} missing): no outcome may be read before it is")
    want = json.loads(lock.read_text(encoding="utf-8"))["fingerprint"]
    if extractor_fingerprint(path) != want:
        raise RuntimeError("T1 extractor changed after it was frozen (patterns or extractor source differ)")


# ---------------------------------------------------------------------------------------------- validation sheet


def _allocate(sizes: dict, n: int) -> dict:
    """Equal allocation over strata, capped by stratum size, the remainder passed on to strata with room."""
    alloc = dict.fromkeys(sizes, 0)
    left = min(n, sum(sizes.values()))
    while left:
        room = sorted(k for k in sizes if alloc[k] < sizes[k])
        share, extra = divmod(left, len(room))
        for i, k in enumerate(room):
            add = min(share + (i < extra), sizes[k] - alloc[k])
            alloc[k] += add
            left -= add
    return alloc


def write_validation_sheet(
    items: list[dict], path: Path, n: int = 200, seed: int = 20261118, spec: dict | None = None
) -> list[dict]:
    """The labelling sheet: n filings stratified by cutoff year and by whether any T1 feature fired, with equal
    allocation over the strata. `items` hold id, cik, cutoff, form, url (optional) and `t1` (from `t1_document`).
    Every row carries its stratum weight (stratum size / stratum sample), so the scorer can also give population
    estimates, and the extractor fingerprint, so a sheet scored against a changed extractor is refused."""  # fmt: skip
    spec = spec or load_patterns()
    fp = extractor_fingerprint()
    strata: dict = defaultdict(list)
    for it in items:
        units = t1_units(it["t1"], spec)
        strata[(_date(it["cutoff"]).year, any(units.values()))].append(it)
    alloc = _allocate({k: len(v) for k, v in strata.items()}, n)
    rng = random.Random(seed)
    rows = []
    for key in sorted(strata):
        members = sorted(strata[key], key=lambda it: str(it["id"]))
        for it in rng.sample(members, alloc[key]):
            res = it["t1"]
            row = {"id": it["id"], "cik": it["cik"], "cutoff": _date(it["cutoff"]).isoformat(), "form": it["form"],
                   "year": key[0], "url": it.get("url", ""), "any_fired": int(key[1]),
                   "stratum_weight": round(len(members) / alloc[key], 6), "fingerprint": fp}  # fmt: skip
            units = t1_units(res, spec)
            for unit in spec["units"]:
                feats = [name for name, f in spec["features"].items() if f["unit"] == unit]
                row[f"pred_{unit}"] = int(units[unit] > 0)
                row[f"snippet_{unit}"] = " || ".join(
                    (f"[{name}] " if len(feats) > 1 else "") + s
                    for name in feats
                    for s in res.get(name, {}).get("snippets", [])[:3]
                )
                row[f"label_{unit}"] = ""
            rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    return rows


_YES, _NO = {"1", "y", "yes", "true", "t"}, {"0", "n", "no", "false", "f"}


def score_validation(path: Path, spec: dict | None = None) -> dict:
    """Precision and recall per unit from the labelled sheet (blank labels are skipped), unweighted and weighted by
    the stratum weights. Refuses a sheet made with a different extractor."""
    spec = spec or load_patterns()
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    fp = extractor_fingerprint()
    if any(r["fingerprint"] != fp for r in rows):
        raise RuntimeError("the sheet was made with a different T1 extractor (fingerprint mismatch)")
    out = {}
    for unit in spec["units"]:
        c = dict.fromkeys(("tp", "fp", "fn", "tn"), 0)
        cw = dict.fromkeys(("tp", "fp", "fn", "tn"), 0.0)
        for r in rows:
            lab = r[f"label_{unit}"].strip().lower()
            if not lab:
                continue
            if lab not in _YES | _NO:
                raise ValueError(f"row {r['id']}: label_{unit} = {lab!r} is not a yes/no value")
            y, p = lab in _YES, r[f"pred_{unit}"] == "1"
            k = ("tp" if p else "fn") if y else ("fp" if p else "tn")
            c[k] += 1
            cw[k] += float(r["stratum_weight"])

        def ratio(a, b):
            return a / (a + b) if a + b else None

        out[unit] = {**c, "n_labelled": sum(c.values()),
                     "precision": ratio(c["tp"], c["fp"]), "recall": ratio(c["tp"], c["fn"]),
                     "precision_weighted": ratio(cw["tp"], cw["fp"]), "recall_weighted": ratio(cw["tp"], cw["fn"])}  # fmt: skip
    return out


# ============================================================================================== T2: vintages

VINTAGE_REPO = "manelalab/chrono-bert-v1-{year}1231"
VINTAGE_YEARS = range(1999, 2025)  # 1999-12-31 ... 2024-12-31 (verified on the HF hub 2026-11-18, DESIGN.md)


def vintage_end(vintage: str) -> dt.date:
    m = re.fullmatch(r"manelalab/chrono-bert-v1-(\d{4})1231", vintage)
    if not m:
        raise ValueError(f"not a ChronoBERT vintage: {vintage}")
    return dt.date(int(m.group(1)), 12, 31)


def vintage_for(cutoff: str | dt.date) -> str | None:
    """The latest vintage whose training data end strictly before the cutoff date; None if there is none."""
    c = _date(cutoff)
    years = [y for y in VINTAGE_YEARS if dt.date(y, 12, 31) < c]
    return VINTAGE_REPO.format(year=max(years)) if years else None


def check_vintage(vintage: str, cutoff: str | dt.date) -> None:
    """Raise unless the vintage's training ends strictly before the cutoff (the non-negotiable rule)."""
    if not vintage_end(vintage) < _date(cutoff):
        raise ValueError(f"look-ahead: {vintage} ends {vintage_end(vintage)}, not before the cutoff {_date(cutoff)}")


def _plan(filings: list[dict], test_cutoffs: dict[int, str | dt.date], train_lag: int, vintage_of) -> dict:
    rows, seen = [], set()
    for year in sorted(test_cutoffs):
        tc = _date(test_cutoffs[year])
        vintage = vintage_of(tc)
        if vintage is None:
            continue
        for f in filings:
            fy = _date(f["cutoff"]).year
            role = "test" if fy == year else ("train" if fy <= year - train_lag else None)
            if role is None:
                continue
            key = (f["id"], vintage)
            rows.append({"test_year": year, "test_cutoff": tc.isoformat(), "vintage": vintage, "id": f["id"],
                         "filing_cutoff": _date(f["cutoff"]).isoformat(), "role": role,
                         "sections": f.get("sections", 0), "tokens": f.get("tokens", 0),
                         "new_pass": key not in seen})  # fmt: skip
            seen.add(key)
    by_year: dict = {}
    for r in rows:
        b = by_year.setdefault(r["test_year"], {"vintage": r["vintage"], "train": 0, "test": 0, "sections": 0,
                                                "tokens": 0, "new_sections": 0, "new_tokens": 0})  # fmt: skip
        b[r["role"]] += 1
        b["sections"] += r["sections"]
        b["tokens"] += r["tokens"]
        if r["new_pass"]:
            b["new_sections"] += r["sections"]
            b["new_tokens"] += r["tokens"]
    total = {k: sum(b[k] for b in by_year.values()) for k in ("sections", "tokens", "new_sections", "new_tokens")}
    return {"rows": rows, "by_year": by_year, "total": total}


def plan_embeddings(filings: list[dict], test_cutoffs: dict[int, str | dt.date], train_lag: int = 3) -> dict:
    """(filing, vintage) pairs per test year Y: Y's own filings and the training filings (cutoff year <= Y - lag),
    all embedded with Y's vintage. `filings` hold id (accession), cutoff, sections and tokens (counts, for sizing).
    Totals count every pair; `new_*` counts each (filing, vintage) once (the compute to size). Every row is checked
    against the vintage rule."""
    plan = _plan(filings, test_cutoffs, train_lag, vintage_for)
    check_plan(plan["rows"])
    return plan


def plan_vintage_difference_control(
    filings: list[dict], test_cutoffs: dict[int, str | dt.date], train_lag: int = 3, year: int = 2024
) -> dict:
    """P5-4 control 3 only: every year embedded with the `year` vintage. This deliberately breaks the vintage rule
    (it measures look-ahead); its rows are labelled `control = "vintage_difference"` and never pass `check_plan`."""
    fixed = VINTAGE_REPO.format(year=year)
    plan = _plan(filings, test_cutoffs, train_lag, lambda _c: fixed)
    for r in plan["rows"]:
        r["control"] = "vintage_difference"
    plan["control"] = "vintage_difference"
    return plan


def check_plan(rows: list[dict]) -> None:
    """Raise if any row is a look-ahead control or uses a vintage not strictly before its test cutoff."""
    for r in rows:
        if r.get("control"):
            raise ValueError(f"control row in a main plan: {r}")
        check_vintage(r["vintage"], r["test_cutoff"])


# ---------------------------------------------------------------------------------------------- T2: embedding

LOAD_INFO: dict[str, dict] = {}  # per vintage: attention implementation that loaded, failures, max length, versions
_MODELS: dict[str, tuple] = {}
_SANE_MAX = 1_000_000  # tokenizers report a huge sentinel when no limit is set


def _max_length(config, tokenizer) -> int:
    raw = [getattr(config, "max_position_embeddings", None), getattr(tokenizer, "model_max_length", None)]
    cands = [int(c) for c in raw if isinstance(c, int | float) and 0 < c < _SANE_MAX]
    if not cands:
        raise RuntimeError("no maximum sequence length in the model config or tokenizer")
    return min(cands)


def _load(vintage: str):
    if vintage in _MODELS:
        return _MODELS[vintage]
    try:
        import torch
        import transformers
        from transformers import AutoModel, AutoTokenizer
    except ImportError as e:
        raise RuntimeError("T2 needs the optional dependencies: pip install 'fintwin[text]'") from e
    tokenizer = AutoTokenizer.from_pretrained(vintage)
    failed, model, impl = {}, None, None
    for impl in ("sdpa", "eager"):
        try:
            model = AutoModel.from_pretrained(vintage, attn_implementation=impl)
            break
        except (ImportError, ValueError, RuntimeError) as e:
            failed[impl] = f"{type(e).__name__}: {e}"[:300]
    if model is None:
        raise RuntimeError(f"{vintage} loads with neither sdpa nor eager attention: {failed}")
    model.eval()
    LOAD_INFO[vintage] = {
        "attn_implementation": impl,
        "failed": failed,
        "max_length": _max_length(model.config, tokenizer),
        "config_class": type(model.config).__name__,
        "hidden_size": int(model.config.hidden_size),
        "torch": getattr(torch, "__version__", "?"),
        "transformers": getattr(transformers, "__version__", "?"),
    }
    _MODELS[vintage] = (torch, model, tokenizer)
    return _MODELS[vintage]


def chunk_ids(ids: list[int], size: int) -> list[list[int]]:
    """Consecutive chunks of at most `size` token ids (the last one shorter)."""
    if size < 1:
        raise ValueError("chunk size must be positive")
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def embed(texts: list[str], vintage: str, batch_size: int = 8, max_length: int | None = None) -> np.ndarray:
    """One float16 vector per text: each text is tokenized, cut into chunks of the model's maximum length (read from
    its config at runtime, or `max_length` if smaller), each chunk mean-pooled over its attention mask, and the
    chunks averaged with weights equal to their token counts. An empty text gives a row of NaN. The model is loaded
    with attn_implementation="sdpa", else "eager"; the one that worked is in LOAD_INFO[vintage]."""
    torch, model, tok = _load(vintage)
    info = LOAD_INFO[vintage]
    length = min(max_length or info["max_length"], info["max_length"])
    n_special = tok.num_special_tokens_to_add(pair=False)
    chunks, owner = [], []
    for i, text in enumerate(texts):
        ids = tok(text, add_special_tokens=False)["input_ids"] if text and text.strip() else []
        for c in chunk_ids(ids, length - n_special):
            chunks.append(tok.build_inputs_with_special_tokens(c))
            owner.append(i)
    hidden = info["hidden_size"]
    sums = np.zeros((len(texts), hidden), dtype=np.float64)
    weights = np.zeros(len(texts))
    pad = tok.pad_token_id if tok.pad_token_id is not None else 0
    order = sorted(range(len(chunks)), key=lambda k: len(chunks[k]))  # similar lengths per batch: less padding
    for b in range(0, len(order), batch_size):
        idx = order[b : b + batch_size]
        width = max(len(chunks[k]) for k in idx)
        ids = [chunks[k] + [pad] * (width - len(chunks[k])) for k in idx]
        mask = [[1] * len(chunks[k]) + [0] * (width - len(chunks[k])) for k in idx]
        with torch.no_grad():
            out = model(input_ids=torch.tensor(ids), attention_mask=torch.tensor(mask))
        h = np.asarray(out.last_hidden_state.float().cpu().numpy(), dtype=np.float64)
        m = np.asarray(mask, dtype=np.float64)[..., None]
        pooled = (h * m).sum(axis=1) / m.sum(axis=1)
        for row, k in enumerate(idx):
            w = len(chunks[k]) - n_special
            sums[owner[k]] += pooled[row] * w
            weights[owner[k]] += w
    with np.errstate(invalid="ignore", divide="ignore"):
        return (sums / weights[:, None]).astype(np.float16)


# ============================================================================================== P5-4 controls

AUDITORS = (
    "Ernst & Young", "Deloitte & Touche", "Deloitte", "PricewaterhouseCoopers", "KPMG", "Grant Thornton", "BDO USA",
    "RSM US", "Crowe", "Moss Adams", "Marcum", "Baker Tilly", "Arthur Andersen", "CohnReznick", "Mazars", "EisnerAmper",
)  # fmt: skip  # submissions metadata has no auditor: these and any names passed in are masked
_SUFFIX = re.compile(
    r"(?:[\s,]+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|l\.?p|n\.?v|s\.?a|holdings?|group"
    r"|the)\.?|\s*/[a-z]{2,3}/?)\s*$",
    re.I,
)


def _name_variants(name: str) -> list[str]:
    out, cur = [name.strip()], name.strip()
    while True:
        nxt = _SUFFIX.sub("", cur).strip(" ,.")
        if nxt == cur or not nxt:
            break
        out.append(nxt)
        cur = nxt
    return [v for v in dict.fromkeys(out) if len(v) >= 3]


def identity_terms(submissions: dict, auditors: Iterable[str] = ()) -> dict[str, list[str]]:
    """Identity strings from a company's `submissions` record: names (current and former, with and without legal
    suffixes), tickers, business and mailing cities; auditors from the argument plus the AUDITORS list."""
    names = [submissions.get("name", "")] + [f.get("name", "") for f in submissions.get("formerNames", [])]
    cities = [(submissions.get("addresses", {}).get(k) or {}).get("city") or "" for k in ("business", "mailing")]
    return {
        "company": [v for n in names if n for v in _name_variants(n)],
        "ticker": [t for t in submissions.get("tickers", []) if t],
        "auditor": list(dict.fromkeys([*auditors, *AUDITORS])),
        "city": [c.strip() for c in dict.fromkeys(cities) if c.strip()],
    }


MASK_TOKENS = {"company": "[COMPANY]", "ticker": "[TICKER]", "auditor": "[AUDITOR]", "city": "[CITY]"}


def mask_identity(text: str, terms: dict[str, list[str]]) -> str:
    """Replace identity strings with neutral tokens (longest first), so that ordinary words stay:
    - one-word names and cities only in upper or title case ("Target", "Mobile", not "target", "mobile");
    - tickers in upper case, and those of one to three letters (A, IT, ALL) only right after an exchange name,
      "symbol" or "ticker";
    - longer names and auditors in any case."""
    pairs = sorted(((t, k) for k, ts in terms.items() for t in ts), key=lambda p: -len(p[0]))
    for term, kind in pairs:
        token = MASK_TOKENS[kind]
        if kind == "ticker":
            t = re.escape(term.upper())
            if len(term) <= 3:
                text = re.sub(rf"{_TICKER_CONTEXT}{t}(?=[)\"”\s,.;]|$)", token, text)
            else:
                text = re.sub(rf"(?<![\w$]){t}(?!\w)", token, text)
        elif kind in ("company", "city") and (len(term.split()) == 1 or kind == "city"):
            for form in {term.upper(), term.title()}:
                body = r"\s+".join(re.escape(w) for w in form.split())
                text = re.sub(rf"(?<!\w){body}(?!\w)", token, text)
        else:
            body = r"\s+".join(re.escape(w) for w in term.split())
            text = re.sub(rf"(?<!\w){body}(?!\w)", token, text, flags=re.I)
    return text


_TICKER_CONTEXT = "(?:" + "|".join(
    rf"(?<={re.escape(p)})"
    for p in ("NYSE: ", "NYSE:", "NYSE ", "NASDAQ: ", "Nasdaq: ", "NASDAQ ", "Nasdaq ", "symbol ", 'symbol "',
              "symbol “", "ticker ", 'ticker "', "ticker “")
) + ")"  # fmt: skip


# Loughran-McDonald Master Dictionary: https://sraf.nd.edu/loughranmcdonald-master-dictionary/ (CSV, one row per word,
# a category column holds the year the word was added, 0 if not in the category, a negative year if removed).
LM_CATEGORIES = ("Negative", "Positive", "Uncertainty", "Litigious", "Strong_Modal", "Weak_Modal", "Constraining")


def load_lm_dictionary(path: Path) -> dict[str, frozenset[str]]:
    """{category: upper-case words} from the Master Dictionary CSV, or from a JSON {category: [words]}."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k: frozenset(w.upper() for w in v) for k, v in raw.items()}
    out: dict[str, set] = {c: set() for c in LM_CATEGORIES}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            for c in LM_CATEGORIES:
                v = (r.get(c) or "0").strip()
                if v and float(v) > 0:
                    out[c].add(r["Word"].strip().upper())
    return {k: frozenset(v) for k, v in out.items()}


_WORD = re.compile(r"[A-Za-z]+")


def lm_counts(text: str, dictionary: dict[str, frozenset[str]]) -> dict:
    """Word counts per category and their shares of all words."""
    words = [w.upper() for w in _WORD.findall(text)]
    n = len(words)
    out: dict = {"n_words": n}
    for c, vocab in dictionary.items():
        k = sum(w in vocab for w in words)
        out[c] = k
        out[f"{c}_share"] = k / n if n else None
    return out
