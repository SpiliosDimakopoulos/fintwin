"""Filing text (T1/T2, revision plan 5): section extraction, the cutoff and vintage rules, T1 patterns, the placebo,
the validation sheet and the embedding code path. Offline: SEC calls and transformers/torch are faked."""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from fintwin.data import edgar as E
from fintwin.data import filings_text as F
from fintwin.research import text_features as T

FILL = " ".join(["The company describes its operations in plain words for the reader."] * 12)


def tenk_html(mda_extra: str = "", rf_extra: str = "") -> str:
    toc = (
        "<table><tr><td>Item 1A.</td><td>Risk Factors</td><td>12</td></tr>"
        "<tr><td>Item 1B.</td><td>Unresolved Staff Comments</td><td>20</td></tr>"
        "<tr><td>Item 7.</td><td>Management&#8217;s Discussion and Analysis of Financial Condition</td><td>30</td></tr>"
        "<tr><td>Item 7A.</td><td>Quantitative and Qualitative Disclosures About Market Risk</td><td>40</td></tr>"
        "<tr><td>Item 8.</td><td>Financial Statements</td><td>41</td></tr></table>"
    )
    return (
        "<html><head><style>p {color: red}</style></head><body>"
        '<div style="display:none"><ix:header><ix:hidden>dei:EntityName HIDDEN XBRL</ix:hidden></ix:header>'
        "<div>nested hidden</div></div>"
        f"<p>ANNUAL REPORT</p>{toc}"
        "<p>PART I</p><p><b>Item 1A. Risk Factors</b></p>"
        f"<p>RISKBODY {FILL} {rf_extra}</p>"
        "<p>Item 1B. Unresolved Staff Comments</p><p>None.</p>"
        "<p>Item 2. Properties</p><p>We lease offices.</p>"
        "<p>PART II</p><p>ITEM 7. MANAGEMENT&#8217;S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS</p>"
        f"<p>MDABODY {FILL}</p><p>Results of Operations</p><p>{FILL}</p>"
        f"<p>Liquidity and Capital Resources</p><p>LIQBODY {FILL} {mda_extra}</p>"
        f"<p>Critical Accounting Policies</p><p>CRITBODY {FILL}</p>"
        "<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p><p>QQDBODY rates.</p>"
        "<p>Item 8. Financial Statements</p><p>FSBODY</p>"
        "<script>var x = 'Item 7. Management's Discussion';</script></body></html>"
    )


def tenq_html() -> str:
    return (
        "<html><body><p>PART I. FINANCIAL INFORMATION</p><p>Item 1. Financial Statements</p><p>Item 2. "
        "Management's Discussion and Analysis</p><p>PART II. OTHER INFORMATION</p><p>Item 1A. Risk Factors</p>"
        "<p>PART I &#8212; FINANCIAL INFORMATION</p><p>Item 1. Financial Statements</p><p>FSQ</p>"
        "<p>Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>"
        f"<p>QMDA {FILL}</p><p>Item 3. Quantitative and Qualitative Disclosures About Market Risk</p><p>QQD</p>"
        "<p>Item 4. Controls and Procedures</p><p>CTRL</p>"
        "<p>PART II &#8212; OTHER INFORMATION</p><p>Item 1. Legal Proceedings</p><p>None.</p>"
        f"<p>Item 1A. Risk Factors</p><p>QRISK {FILL}</p>"
        "<p>Item 2. Unregistered Sales of Equity Securities and Use of Proceeds</p><p>SALESBODY none</p>"
        "<p>Item 6. Exhibits</p></body></html>"
    )


# ---------------------------------------------------------------------------------------------- extraction


def test_html_to_text_drops_hidden_xbrl_scripts_and_styles():
    text = F.html_to_text(tenk_html())
    assert "HIDDEN XBRL" not in text and "nested hidden" not in text
    assert "color: red" not in text and "var x" not in text
    assert "MANAGEMENT’S DISCUSSION" in text and "ANNUAL REPORT" in text


def test_10k_sections_skip_table_of_contents_and_stop_at_next_item():
    sec, fail = F.extract_sections(F.html_to_text(tenk_html()), "10-K")
    assert set(sec) == {"mda", "risk_factors", "liquidity"} and not fail
    assert sec["mda"].startswith("MDABODY") and "QQDBODY" not in sec["mda"] and "LIQBODY" in sec["mda"]
    assert sec["risk_factors"].startswith("RISKBODY") and "None." not in sec["risk_factors"]
    assert sec["liquidity"].startswith("LIQBODY") and "CRITBODY" not in sec["liquidity"]
    assert "Item 7A" not in sec["mda"]


def test_10q_mda_from_part_one_and_risk_factors_from_part_two():
    sec, fail = F.extract_sections(F.html_to_text(tenq_html()), "10-Q")
    assert sec["mda"].startswith("QMDA") and "QQD" not in sec["mda"]
    assert sec["risk_factors"].startswith("QRISK") and "SALESBODY" not in sec["risk_factors"]
    assert "SALESBODY" not in sec["mda"]
    assert fail == {"liquidity": "subsection not found"}


def test_missing_and_incorporated_sections_are_failures_not_guesses():
    html = (
        "<p>Item 7. Management's Discussion and Analysis</p><p>The information required by this item is "
        "incorporated herein by reference to the Annual Report to Shareholders.</p><p>Item 8. Financial Statements</p>"
    )
    sec, fail = F.extract_sections(F.html_to_text("<html><body>" + html + "</body></html>"), "10-K")
    assert sec == {} and fail["mda"] == "incorporated by reference"
    assert fail["risk_factors"] == "heading not found" and fail["liquidity"] == "no MD&A"


def test_token_count():
    assert F.token_count("Net sales rose 5%, to $1.2 million.") == 13


# ---------------------------------------------------------------------------------------------- cutoff rule


def _page(rows):
    keys = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


PAGES = [
    _page(
        [
            ("0001-25-000003", "10-K", "2025-02-20", "2024-12-31", "k2024.htm"),  # after the cutoff
            ("0001-24-000009", "10-Q", "2024-11-01", "2024-09-30", "q3.htm"),
            ("0001-24-000007", "10-K/A", "2024-08-01", "2023-12-31", "ka.htm"),  # amendment: not used
            ("0001-24-000006", "10-Q", "2024-08-01", "2024-06-30", "q2.htm"),
            ("0001-24-000005", "8-K", "2024-06-01", "", "e.htm"),
            ("0001-24-000004", "10-Q", "2024-05-01", "2024-03-31", "q1.htm"),
            ("0001-24-000002", "10-K", "2024-02-15", "2023-12-31", "k2023.htm"),
            ("0001-23-000008", "10-Q", "2023-11-01", "2023-09-30", "old.htm"),
        ]
    )
]


def test_select_documents_latest_10k_and_later_10qs_by_cutoff():
    docs = F.select_documents(F.periodic_documents(PAGES), "2025-02-15")
    assert [d["accession"] for d in docs] == ["0001-24-000002", "0001-24-000004", "0001-24-000006", "0001-24-000009"]
    same_day = F.select_documents(F.periodic_documents(PAGES), "2024-02-15")
    assert [d["accession"] for d in same_day] == ["0001-24-000002"]  # filed on the cutoff date counts
    assert F.select_documents(F.periodic_documents(PAGES), "2023-12-31") == []  # no 10-K by then


def test_cutoff_guard_at_write_and_at_read(tmp_path):
    late = [{"accession": "x", "form": "10-K", "filingDate": "2025-02-16", "period": "", "sections": {}}]
    with pytest.raises(F.LookAheadError):
        F.write_firm_year(1, "2025-02-15", late, tmp_path)
    ok = [{**late[0], "filingDate": "2025-02-15"}]
    path = F.write_firm_year(1, "2025-02-15", ok, tmp_path)
    assert F.load_firm_year(1, "2025-02-15", tmp_path)["documents"][0]["accession"] == "x"
    rec = json.loads(gzip.decompress(path.read_bytes()))
    rec["documents"][0]["filingDate"] = "2025-03-01"  # a record altered after it was written
    path.write_bytes(gzip.compress(json.dumps(rec).encode()))
    with pytest.raises(F.LookAheadError):
        F.load_firm_year(1, "2025-02-15", tmp_path)


class _Resp:
    def __init__(self, text):
        self.content, self.encoding = text.encode("utf-8"), "utf-8"


def test_filing_text_end_to_end_offline(tmp_path, monkeypatch):
    fetched = []

    def fake_fetch(url, sec=True):
        fetched.append(url)
        return _Resp(tenq_html() if "q" in url.rsplit("/", 1)[1] else tenk_html())

    monkeypatch.setattr(E, "submission_pages", lambda cik, age: ({}, PAGES))
    monkeypatch.setattr(E, "fetch", fake_fetch)
    monkeypatch.setattr(E.requests, "get", lambda *a, **k: pytest.fail("no direct HTTP"))
    rec = F.filing_text(320193, "2024-06-01", tmp_path)
    assert [d["accession"] for d in rec["documents"]] == ["0001-24-000002", "0001-24-000004"]
    assert all(u.startswith("https://www.sec.gov/Archives/edgar/data/320193/") for u in fetched)
    assert not any("k2024" in u or "q2.htm" in u for u in fetched)
    k = rec["documents"][0]
    assert k["tokens"]["mda"] == F.token_count(k["sections"]["mda"]) and k["period"] == "2023-12-31"
    n = len(fetched)
    F.filing_text(320193, "2024-06-01", tmp_path)  # second call reads the cache
    assert len(fetched) == n


def test_frozen_mode_never_fetches(tmp_path, monkeypatch):
    monkeypatch.setenv("FINTWIN_FROZEN", "1")
    monkeypatch.setattr(E, "submission_pages", lambda *a: pytest.fail("frozen mode must not fetch"))
    with pytest.raises(E.FrozenMiss):
        F.filing_text(5, "2020-02-15", tmp_path)


def test_text_snapshot_manifest_and_verify(tmp_path):
    root, out = tmp_path / "text", tmp_path / "snap"
    doc = {"accession": "a", "form": "10-K", "filingDate": "2020-01-10", "period": "", "sections": {"mda": "x"}}
    F.write_firm_year(7, "2020-02-15", [doc], root)
    m = F.freeze_text_snapshot(root, out)
    assert m["n_files"] == 1 and m["n_documents"] == 1 and len(m["digest"]) == 64
    F.verify_text_snapshot(root, out)
    F.write_firm_year(7, "2020-02-15", [{**doc, "sections": {"mda": "y"}}], root)
    with pytest.raises(ValueError, match="does not match"):
        F.verify_text_snapshot(root, out)


def test_text_modules_use_only_the_edgar_client():
    for mod in (F, T):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import requests" not in src and "urllib" not in src


# ---------------------------------------------------------------------------------------------- vintages


@pytest.mark.parametrize(
    "cutoff, year",
    [("2015-02-15", 2014), ("2024-12-31", 2023), ("2025-01-01", 2024), ("2030-02-15", 2024), ("2000-01-01", 1999)],
)
def test_vintage_for_ends_strictly_before_cutoff(cutoff, year):
    v = T.vintage_for(cutoff)
    assert v == f"manelalab/chrono-bert-v1-{year}1231" and T.vintage_end(v) < dt.date.fromisoformat(cutoff)
    T.check_vintage(v, cutoff)


def test_vintage_rule_violations():
    assert T.vintage_for("1999-12-31") is None
    with pytest.raises(ValueError, match="look-ahead"):
        T.check_vintage("manelalab/chrono-bert-v1-20141231", "2014-12-31")
    with pytest.raises(ValueError):
        T.vintage_end("bert-base-uncased")


def test_planner_reembeds_training_filings_with_the_test_vintage():
    filings = [
        {"id": f"a{y}", "cutoff": f"{y}-02-15", "sections": 3, "tokens": 1000} for y in range(2010, 2017)
    ]  # fmt: skip
    plan = T.plan_embeddings(filings, {2015: "2015-02-15", 2016: "2016-02-15"})
    by = plan["by_year"]
    assert by[2015]["vintage"].endswith("20141231") and by[2016]["vintage"].endswith("20151231")
    assert (by[2015]["train"], by[2015]["test"]) == (3, 1)  # 2010-2012 and 2015
    assert (by[2016]["train"], by[2016]["test"]) == (4, 1)
    assert plan["total"]["sections"] == 27 and plan["total"]["new_sections"] == 27  # different vintages: no reuse
    ctrl = T.plan_vintage_difference_control(filings, {2015: "2015-02-15", 2016: "2016-02-15"})
    assert {r["vintage"] for r in ctrl["rows"]} == {"manelalab/chrono-bert-v1-20241231"}
    assert ctrl["total"]["new_sections"] == 6 * 3  # one pass per filing (2010-2013, 2015, 2016) under one vintage
    with pytest.raises(ValueError):
        T.check_plan(ctrl["rows"])


# ---------------------------------------------------------------------------------------------- T1


@pytest.mark.parametrize(
    "feature, sentence",
    [
        ("going_concern", "These conditions raise substantial doubt about our ability to continue as a going concern."),
        ("going_concern", "Our auditors included a going concern explanatory paragraph in their report."),
        ("covenant", "In March 2020 we obtained a waiver from our lenders of the leverage covenant."),
        ("covenant", "As of December 31, 2019, we were not in compliance with the fixed charge coverage covenant."),
        ("acquisition_divestiture", "On July 1, 2019, we completed the acquisition of Acme Corp for $40 million."),
        ("acquisition_divestiture", "In May we entered into a definitive agreement to sell our European division."),
        ("restructuring", "In 2019 the Board approved a restructuring plan to close two plants."),
        ("restructuring", "We recorded restructuring charges of $12.5 million in the fourth quarter."),
        ("dividend_suspension", "In April 2020 the Board suspended the quarterly cash dividend."),
        ("dividend_initiation", "In 2018 the Board declared our first quarterly dividend."),
    ],
)
def test_t1_positive(feature, sentence):
    res = T.extract_t1(sentence)
    assert res[feature]["count"] == 1 and res[feature]["snippets"] == [sentence]


@pytest.mark.parametrize(
    "feature, sentence",
    [
        ("going_concern", "Management concluded that there is no substantial doubt about our ability to continue as a going concern."),
        ("going_concern", "Management is required to evaluate whether there is substantial doubt about the ability to continue as a going concern."),
        ("going_concern", "A failure to refinance could raise substantial doubt about our ability to continue as a going concern."),
        ("covenant", "If we breach the covenants in our credit agreement, the lenders could accelerate the debt."),
        ("covenant", "We were in compliance with all covenants under the credit facility."),
        ("acquisition_divestiture", "We may pursue acquisitions that could disrupt our business."),
        ("acquisition_divestiture", "We completed the sale of products to new customers."),
        ("restructuring", "Any future restructuring could result in significant charges."),
        ("dividend_suspension", "The Board may suspend the dividend at any time."),
        ("dividend_initiation", "We have never paid cash dividends and do not anticipate paying dividends."),
    ],
)  # fmt: skip
def test_t1_negative(feature, sentence):
    assert T.extract_t1(sentence)[feature]["count"] == 0


def test_t1_restructuring_amount_and_firm_year_features():
    text = "The Board approved a restructuring plan in 2019. We expect to incur restructuring costs of $1.2 billion."
    assert T.extract_t1(text)["restructuring"]["amount_usd"] == pytest.approx(1.2e9)
    assert T.dollar_amounts("$3,500 and $2.5 million") == [3500.0, 2.5e6]
    doc = {"sections": {"mda": text, "liquidity": text, "risk_factors": "Nothing here."}}
    feats = T.t1_features({"documents": [doc, {"sections": {}}]})
    assert feats["t1_restructuring_n"] == 2  # the liquidity copy is not counted again
    assert feats["t1u_restructuring"] == 1 and feats["t1u_going_concern"] == 0
    assert feats["t1_restructuring_cost_usd"] == pytest.approx(1.2e9)


def test_extractor_freeze(tmp_path):
    lock = tmp_path / "t1.lock"
    with pytest.raises(RuntimeError, match="not frozen"):
        T.assert_extractor_frozen(lock)
    T.freeze_extractor(lock)
    T.assert_extractor_frozen(lock)
    changed = tmp_path / "p.json"
    spec = json.loads(T.PATTERNS_PATH.read_text(encoding="utf-8"))
    spec["features"]["going_concern"]["patterns"].append("doubt")
    changed.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed"):
        T.assert_extractor_frozen(lock, changed)
    with pytest.raises(FileExistsError):
        T.freeze_extractor(lock)


# ---------------------------------------------------------------------------------------------- validation sheet


def _items():
    fired = T.extract_t1("These conditions raise substantial doubt about our ability to continue as a going concern.")
    quiet = T.extract_t1("Sales rose.")
    return [
        {"id": f"{y}-{i}", "cik": i, "cutoff": f"{y}-02-15", "form": "10-K", "t1": fired if i < 3 else quiet}
        for y in (2015, 2016)
        for i in range(10)
    ]


def test_validation_sheet_stratified_and_scored(tmp_path):
    path = tmp_path / "sheet.csv"
    rows = T.write_validation_sheet(_items(), path, n=12)
    strata = {}
    for r in rows:
        strata[(r["year"], r["any_fired"])] = strata.get((r["year"], r["any_fired"]), 0) + 1
    assert strata == {(2015, 1): 3, (2015, 0): 3, (2016, 1): 3, (2016, 0): 3}
    assert {r["stratum_weight"] for r in rows} == {1.0, round(7 / 3, 6)}
    with open(path, newline="", encoding="utf-8") as fh:
        sheet = list(csv.DictReader(fh))
    assert {
        "id",
        "cik",
        "cutoff",
        "form",
        "snippet_going_concern",
        "label_going_concern",
        "label_dividend_change",
    } <= set(sheet[0])
    assert all(r["label_covenant"] == "" for r in sheet)
    for r in sheet:  # the author's labels: one fired filing is a false positive, one quiet one a miss
        r["label_going_concern"] = "1" if r["pred_going_concern"] == "1" else "0"
    sheet[0]["label_going_concern"] = "0" if sheet[0]["pred_going_concern"] == "1" else "1"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sheet[0]))
        w.writeheader()
        w.writerows(sheet)
    s = T.score_validation(path)["going_concern"]
    assert s["n_labelled"] == 12 and s["tp"] + s["fp"] == 6
    assert (s["precision"], s["recall"]) in ((5 / 6, 1.0), (1.0, 6 / 7))
    assert T.score_validation(path)["covenant"]["n_labelled"] == 0
    sheet[1]["fingerprint"] = "0" * 64
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sheet[0]))
        w.writeheader()
        w.writerows(sheet)
    with pytest.raises(RuntimeError, match="fingerprint"):
        T.score_validation(path)


# ---------------------------------------------------------------------------------------------- P5-4 controls


def test_masked_identity_placebo():
    sub = {
        "name": "TARGET CORP",
        "formerNames": [{"name": "DAYTON HUDSON CORP"}],
        "tickers": ["TGT"],
        "addresses": {"business": {"city": "MINNEAPOLIS"}, "mailing": {"city": "Minneapolis"}},
    }
    terms = T.identity_terms(sub, auditors=["Smith & Jones LLP"])
    text = (
        "Target Corp (NYSE: TGT), formerly Dayton Hudson Corp, is based in Minneapolis. Our target leverage is 2x. "
        "Ernst & Young LLP and Smith & Jones LLP audited TARGET."
    )
    masked = T.mask_identity(text, terms)
    assert "Target" not in masked and "TGT" not in masked and "Dayton" not in masked and "Minneapolis" not in masked
    assert "Ernst" not in masked and "Smith" not in masked
    assert "our target leverage" in masked.lower()  # the common word stays
    assert masked.count("[COMPANY]") == 3 and "[TICKER]" in masked and "[CITY]" in masked


def test_loughran_mcdonald_counts(tmp_path):
    p = tmp_path / "lm.csv"
    p.write_text("Word,Negative,Positive,Uncertainty\nLOSS,2009,0,0\nGAIN,0,2009,0\nMAY,0,0,2009\nOLD,-2020,0,0\n")
    lm = T.load_lm_dictionary(p)
    assert lm["Negative"] == {"LOSS"} and lm["Positive"] == {"GAIN"}
    c = T.lm_counts("The loss may offset the gain; old loss.", lm)
    assert (c["n_words"], c["Negative"], c["Positive"], c["Uncertainty"]) == (8, 2, 1, 1)
    assert c["Negative_share"] == pytest.approx(0.25)
    j = tmp_path / "lm.json"
    j.write_text(json.dumps({"Negative": ["loss"]}))
    assert T.lm_counts("Loss", T.load_lm_dictionary(j))["Negative"] == 1


# ---------------------------------------------------------------------------------------------- embedding (faked)


def _fake_stack(monkeypatch):
    class Tensor:
        def __init__(self, a):
            self.a = np.asarray(a, dtype=float)

        def float(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.a

    class NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    torch = types.ModuleType("torch")
    torch.no_grad, torch.tensor, torch.__version__ = NoGrad, np.asarray, "fake"

    class Tok:
        pad_token_id, model_max_length = 0, int(1e30)

        def __call__(self, text, add_special_tokens=False):
            return {"input_ids": [int(w) for w in text.split()]}

        def num_special_tokens_to_add(self, pair=False):
            return 2

        def build_inputs_with_special_tokens(self, ids):
            return [100, *ids, 100]

    class Model:
        config = types.SimpleNamespace(max_position_embeddings=6, hidden_size=2)

        def eval(self):
            return self

        def __call__(self, input_ids, attention_mask):
            h = np.repeat(np.asarray(input_ids, dtype=float)[..., None], 2, axis=2)
            return types.SimpleNamespace(last_hidden_state=Tensor(h))

    def load_model(name, attn_implementation):
        if attn_implementation == "sdpa":
            raise ValueError("sdpa not supported")
        return Model()

    tr = types.ModuleType("transformers")
    tr.__version__ = "fake"
    tr.AutoTokenizer = types.SimpleNamespace(from_pretrained=lambda name: Tok())
    tr.AutoModel = types.SimpleNamespace(from_pretrained=load_model)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", tr)
    monkeypatch.setattr(T, "_MODELS", {})
    monkeypatch.setattr(T, "LOAD_INFO", {})


def test_embed_chunks_pools_and_records_attention_fallback(monkeypatch):
    _fake_stack(monkeypatch)
    v = "manelalab/chrono-bert-v1-20141231"
    out = T.embed(["1 2", "1 2 3 4 5 6", ""], v, batch_size=2)
    info = T.LOAD_INFO[v]
    assert info["attn_implementation"] == "eager" and "sdpa" in info["failed"] and info["max_length"] == 6
    assert out.dtype == np.float16 and out.shape == (3, 2)
    assert out[0, 0] == pytest.approx((100 + 1 + 2 + 100) / 4)
    # 6 tokens in chunks of 4 (max length 6 minus 2 special): [1..4] and [5, 6], weighted 4 and 2
    first, second = (100 + 10 + 100) / 6, (100 + 11 + 100) / 4
    assert float(out[1, 0]) == pytest.approx((4 * first + 2 * second) / 6, rel=1e-3)
    assert np.isnan(out[2]).all()


def test_chunk_ids_and_missing_dependency(monkeypatch):
    assert T.chunk_ids(list(range(5)), 2) == [[0, 1], [2, 3], [4]]
    with pytest.raises(ValueError):
        T.chunk_ids([1], 0)
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setattr(T, "_MODELS", {})
    with pytest.raises(RuntimeError, match="fintwin\\[text\\]"):
        T.embed(["1"], "manelalab/chrono-bert-v1-20141231")


def test_text_probe_help_runs_without_torch():
    script = Path(__file__).resolve().parents[1] / "scripts" / "text_probe.py"
    res = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0 and "--sections" in res.stdout


def test_patterns_file_is_shipped_with_the_package():
    assert T.PATTERNS_PATH.parent == Path(T.__file__).parent  # data file beside the module
    spec = T.load_patterns()
    assert set(spec["units"]) == {f["unit"] for f in spec["features"].values()} and len(spec["units"]) == 5


# ---------------------------------------------------------------------------------------------- review additions


def test_hard_wrapped_source_lines_do_not_split_sentences_or_make_headings():
    wrapped = (
        "<html><body><p>Item 7. Management's Discussion and Analysis</p><p>"
        + FILL
        + " These conditions raise substantial doubt\nabout our ability to continue\nas a going concern. For the "
        "statements see\nItem 8. Financial Statements and Supplementary Data, which follow.</p>"
        "<p>Item 8. Financial Statements</p><p>FS</p></body></html>"
    )
    sec, _ = F.extract_sections(F.html_to_text(wrapped), "10-K")
    assert "which follow." in sec["mda"]  # the wrapped in-paragraph "Item 8" reference is no heading
    assert T.extract_t1(sec["mda"])["going_concern"]["count"] == 1


def test_fingerprint_ignores_line_endings_and_layout(tmp_path):
    crlf = tmp_path / "p.json"
    crlf.write_bytes(T.PATTERNS_PATH.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    compact = tmp_path / "c.json"
    compact.write_text(json.dumps(json.loads(T.PATTERNS_PATH.read_text(encoding="utf-8"))), encoding="utf-8")
    assert T.extractor_fingerprint(crlf) == T.extractor_fingerprint(compact) == T.extractor_fingerprint()


def test_placebo_leaves_ordinary_words_and_short_tickers_without_context():
    terms = {"company": [], "ticker": ["A", "IT"], "auditor": [], "city": ["MOBILE"]}
    text = "A mobile app in Mobile. IT spending rose (IT). Listed on the NYSE: IT and NYSE: A."
    masked = T.mask_identity(text, terms)
    assert masked == "A mobile app in [CITY]. IT spending rose (IT). Listed on the NYSE: [TICKER] and NYSE: [TICKER]."


def test_missing_document_is_a_failure_but_a_block_stops(tmp_path, monkeypatch):
    def raise_status(code):
        def fetch(url, sec=True):
            raise E.requests.HTTPError(f"{code}", response=types.SimpleNamespace(status_code=code))

        return fetch

    monkeypatch.setattr(E, "submission_pages", lambda cik, age: ({}, PAGES))
    monkeypatch.setattr(E, "fetch", raise_status(404))
    rec = F.filing_text(9, "2024-03-01", tmp_path)
    assert rec["documents"][0]["failures"] == {"document": "404 for the primary document"}
    monkeypatch.setattr(E, "fetch", raise_status(403))
    with pytest.raises(E.requests.HTTPError):
        F.filing_text(9, "2024-06-01", tmp_path)
    assert not F.firm_year_path(9, "2024-06-01", tmp_path).exists()
