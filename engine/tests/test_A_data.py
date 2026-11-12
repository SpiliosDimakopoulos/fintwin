"""Revision-3 data-layer fixes (workstream A): D1-D3, D5-D7, D9, D11-D13, MM-F4 data side, plus D15 coverage."""

import numpy as np
import pandas as pd
import pytest

from fintwin.data import facts as F
from fintwin.data import xbrl_fallback as X
from fintwin.data.edgar_universe import ff12, is_financial

QE = ["03-31", "06-30", "09-30", "12-31"]
QS = ["01-01", "04-01", "07-01", "10-01"]


def quarters(first=2018, n=12):
    """(start, end) of n calendar quarters."""
    out = []
    for i in range(n):
        y, k = first + i // 4, i % 4
        out.append((f"{y}-{QS[k]}", f"{y}-{QE[k]}"))
    return out


def fact(start, end, val, filed=None, accn=None, form="10-Q"):
    filed = filed or str((pd.Timestamp(end) + pd.Timedelta(days=40)).date())
    row = {"end": end, "val": val, "filed": filed, "accn": accn or f"a-{end}", "form": form}
    if start:
        row["start"] = start
    return row


class Co:
    """A synthetic company: add tagged facts, then load it through `load_company` without any network."""

    def __init__(self, n=12, skip=(), revenue=100.0):
        self.gaap: dict = {}
        self.q = quarters(n=n)
        for i, (s, e) in enumerate(self.q):
            if i in skip:
                continue
            self.add("Revenues", s, e, revenue)
            self.add("NetCashProvidedByUsedInOperatingActivities", s, e, 10.0)
            self.add_i("Assets", e, 1000.0)
            self.add_i("StockholdersEquity", e, 400.0)
            self.add_i("CashAndCashEquivalentsAtCarryingValue", e, 50.0)

    def add(self, tag, start, end, val, **kw):
        self.gaap.setdefault(tag, {"units": {"USD": []}})["units"]["USD"].append(fact(start, end, val, **kw))
        return self

    def add_i(self, tag, end, val, **kw):
        return self.add(tag, None, end, val, **kw)

    def each(self, tag, val, skip=(), instant=False):
        for i, (s, e) in enumerate(self.q):
            if i not in skip:
                self.add_i(tag, e, val) if instant else self.add(tag, s, e, val)
        return self

    def load(self, monkeypatch, asof=None, legacy=False):
        monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1" if legacy else "0")
        monkeypatch.setattr(F, "company_facts", lambda cik: {"facts": {"us-gaap": self.gaap}})
        monkeypatch.setattr(F, "ticker_to_cik", lambda t: (1, "Test Co"))
        return F.load_company("TEST", asof=asof)


@pytest.fixture(autouse=True)
def _new_layer(monkeypatch):
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "0")


# ---- D1: full quarterly calendar ----


def test_D1_missing_quarter_is_a_gap_row_not_dropped(monkeypatch):
    c = Co(skip={5})
    q = c.load(monkeypatch).quarters
    assert len(q) == 12
    gap = pd.Timestamp(c.q[5][1])
    assert q.loc[gap, "gap"] and np.isnan(q.loc[gap, "revenue"])
    assert q.loc[gap, "cash"] == 50.0  # the balance sheet of that quarter is still read
    assert q["gap"].sum() == 1
    legacy = c.load(monkeypatch, legacy=True).quarters
    assert len(legacy) == 11 and gap not in legacy.index


def test_D1_contiguous_rejects_windows_across_a_gap(monkeypatch):
    q = Co(skip={8}).load(monkeypatch).quarters
    assert F.contiguous(q, 3)  # rows 9..11
    assert not F.contiguous(q, 4)  # would include the gap row
    assert F.contiguous(q.head(8), 8)
    assert not F.contiguous(q, 13)
    m = F.contiguous_mask(q, 4)
    assert m.tolist() == [False] * 3 + [True] * 5 + [False] * 4
    # a legacy frame (no gap rows) is judged by the spacing of its dates
    legacy = Co(skip={8}).load(monkeypatch, legacy=True).quarters
    assert F.contiguous(legacy, 3) and not F.contiguous(legacy, 4)


def test_D1_gap_rows_follow_52_53_week_balance_sheet_dates(monkeypatch):
    # retailer ends on Saturdays; the unreported quarter's end is taken from its balance-sheet date
    ends = ["2023-04-01", "2023-07-01", "2023-09-30", "2023-12-30", "2024-03-30", "2024-06-29", "2024-09-28"]
    c = Co(n=0)
    prev = pd.Timestamp("2022-12-31")
    for i, e in enumerate(ends):
        s = str((prev + pd.Timedelta(days=1)).date())
        if i != 3:
            c.add("Revenues", s, e, 100.0)
        c.add_i("Assets", e, 10.0)
        prev = pd.Timestamp(e)
    q = c.load(monkeypatch).quarters
    assert list(q.index.strftime("%Y-%m-%d")) == ends
    assert q["gap"].tolist() == [False, False, False, True, False, False, False]


# ---- D2: no per-quarter zero fill ----


def test_D2_balances_carry_forward_flows_stay_missing(monkeypatch):
    c = Co().each("AccountsReceivableNetCurrent", 30.0, skip={4, 9, 10, 11}, instant=True)
    c.each("PaymentsOfDividends", 5.0, skip={6})
    d = c.load(monkeypatch)
    q = d.quarters
    assert q["receivables"].iloc[4] == 30.0 and d.imputed["receivables"].iloc[4]  # carried, and marked
    assert q["receivables"].iloc[10] == 30.0 and np.isnan(q["receivables"].iloc[11])  # limit of 2 quarters
    assert np.isnan(q["dividends"].iloc[6])
    assert (q["buybacks"] == 0).all() and "buybacks: no data, assumed 0" in d.notes  # never tagged
    legacy = c.load(monkeypatch, legacy=True).quarters
    assert legacy["receivables"].iloc[4] == 0.0 and legacy["dividends"].iloc[6] == 0.0


# ---- D3: total debt ----


def test_D3_untagged_quarter_is_missing_not_zero(monkeypatch):
    c = Co().each("LongTermDebtNoncurrent", 200.0, skip={2, 3, 4}, instant=True)
    q = c.load(monkeypatch).quarters
    assert q["total_debt"].iloc[3] == 200.0  # carried forward within the limit
    assert np.isnan(q["total_debt"].iloc[4])  # beyond the limit: unknown
    assert c.load(monkeypatch, legacy=True).quarters["total_debt"].iloc[4] == 0.0


def test_D3_never_tagged_debt_is_zero_with_note(monkeypatch):
    d = Co().load(monkeypatch)
    assert (d.quarters["total_debt"] == 0).all()
    assert "total_debt: no debt tag in any filing, assumed 0" in d.notes and d.flags["debt_untagged"]


def test_D3_short_term_only_and_instrument_tags(monkeypatch):
    q = Co().each("CommercialPaper", 70.0, instant=True).load(monkeypatch).quarters
    assert (q["total_debt"] == 70.0).all()  # legacy: 0 (no long-term line)
    c = Co().each("SeniorNotes", 300.0, instant=True).each("FinanceLeaseLiability", 20.0, instant=True)
    assert (c.load(monkeypatch).quarters["total_debt"] == 320.0).all()
    assert (c.load(monkeypatch, legacy=True).quarters["total_debt"] == 0.0).all()


def test_D3_debt_current_is_carried_like_noncurrent(monkeypatch):
    c = Co().each("LongTermDebtNoncurrent", 200.0, instant=True).each("DebtCurrent", 50.0, skip={7}, instant=True)
    q = c.load(monkeypatch).quarters
    assert q["total_debt"].iloc[7] == 250.0
    assert c.load(monkeypatch, legacy=True).quarters["total_debt"].iloc[7] == 200.0


def test_D3_total_debt_parts():
    nan = np.nan
    q = pd.DataFrame(
        {
            "debt_current": [nan, nan, nan, nan],
            "ltd_current": [10.0, nan, nan, nan],
            "short_borrowings": [5.0, nan, nan, nan],
            "commercial_paper": [nan, 7.0, nan, nan],
            "ltd_noncurrent": [100.0, nan, nan, nan],
            "debt_combined": [nan, nan, 90.0, nan],
            "ltd_total": [nan, nan, nan, nan],
            "debt_notes": [nan, nan, nan, nan],
            "finance_lease": [nan, nan, nan, nan],
        }
    )
    assert F._total_debt(q).tolist()[:3] == [115.0, 7.0, 90.0] and np.isnan(F._total_debt(q).iloc[3])


# ---- D5: deterministic same-day ties ----


def test_D5_same_day_amendment_tie_is_deterministic_and_row_consistent():
    rows = [
        fact("2024-01-01", "2024-12-31", 500, "2025-02-15", "0001-25-000002", "10-K/A"),
        fact("2024-01-01", "2024-12-31", 480, "2025-02-15", "0001-25-000001", "10-K"),
    ]
    for order in (rows, rows[::-1]):
        df = F._usd_facts({"X": {"units": {"USD": order}}}, "X", None)
        r = F._latest(df, ["start", "end"]).iloc[0]
        assert (r["val"], r["accn"]) == (500, "0001-25-000002")
    # one whole row per period: a later fact with a missing column must not borrow it from an earlier one
    df = pd.DataFrame(
        {
            "end": pd.to_datetime(["2024-03-31"] * 2),
            "filed": pd.to_datetime(["2024-04-30", "2024-05-30"]),
            "accn": ["old", "new"],
            "val": [1.0, 2.0],
            "frame": ["CY2024Q1I", None],
        }
    )
    r = F._latest(df, ["end"]).iloc[0]
    assert r["accn"] == "new" and pd.isna(r["frame"])


# ---- D6: Q4 from one vintage ----


def test_D6_q4_uses_the_ytd_leg_as_known_when_the_annual_was_filed():
    rows = [
        fact("2024-01-01", "2024-09-30", 300, "2024-10-30", "q3"),
        fact("2024-01-01", "2024-12-31", 420, "2025-02-15", "k", "10-K"),
        # next year's Q3 10-Q restates the prior-year 9-month comparative; the 10-K annual total is not restated
        fact("2024-01-01", "2024-09-30", 270, "2025-10-30", "q3next"),
    ]
    diag: dict = {}
    q = F._duration_table({"X": {"units": {"USD": rows}}}, "X", None, diag)
    assert q[pd.Timestamp("2024-12-31")][0] == 120  # 420 - 300, not 420 - 270
    assert diag["vintage_fixed"] == [("X", pd.Timestamp("2024-12-31"))]
    # legacy differenced across vintages
    with pytest.MonkeyPatch.context() as m:
        m.setenv("FINTWIN_DATA_LEGACY", "1")
        assert F.duration_quarters({"X": {"units": {"USD": rows}}}, "X")[pd.Timestamp("2024-12-31")][0] == 150


def test_D6_q4_without_a_consistent_vintage_is_dropped_and_flagged():
    rows = [
        fact("2024-01-01", "2024-12-31", 420, "2025-02-15", "k", "10-K"),
        fact("2024-01-01", "2024-09-30", 270, "2025-10-30", "q3next"),  # the only 9M version came later
    ]
    diag: dict = {}
    q = F._duration_table({"X": {"units": {"USD": rows}}}, "X", None, diag)
    assert pd.Timestamp("2024-12-31") not in q and diag["vintage_mixed"]


# ---- D7: level check at a tag switch ----


def test_D7_tag_switch_with_a_level_break_is_flagged(monkeypatch):
    c = Co(n=0)
    for i, (s, e) in enumerate(quarters(n=12)):
        if i < 8:
            c.add("Revenues", s, e, 100.0)
        if i >= 6:  # the new tag overlaps two quarters, 30% lower
            c.add("RevenueFromContractWithCustomerExcludingAssessedTax", s, e, 70.0)
        c.add_i("Assets", e, 1.0)
    d = c.load(monkeypatch)
    splice = d.flags["splice"]
    assert splice[0]["field"] == "revenue" and splice[0]["rel_diff"] == pytest.approx(30 / 70, abs=1e-3)
    assert d.quarters["splice_break"].sum() == 6 and not d.quarters["splice_break"].iloc[6:].any()


def test_D7_consistent_tag_switch_is_not_flagged(monkeypatch):
    c = Co(n=0)
    for i, (s, e) in enumerate(quarters(n=12)):
        if i < 8:
            c.add("Revenues", s, e, 100.0)
        if i >= 6:
            c.add("RevenueFromContractWithCustomerExcludingAssessedTax", s, e, 98.0)
        c.add_i("Assets", e, 1.0)
    d = c.load(monkeypatch)
    assert "splice" not in d.flags and not d.quarters["splice_break"].any()


# ---- D9: fiscal-year-end changes ----


def test_D9_recast_quarters_overlapping_by_two_months_are_dropped(monkeypatch):
    # fiscal year moves from December to February: the recast Mar-May quarter overlaps Jan-Mar by a month
    c = Co(n=0)
    for s, e in [("2023-01-01", "2023-03-31"), ("2023-04-01", "2023-06-30"), ("2023-07-01", "2023-09-30")]:
        c.add("Revenues", s, e, 100.0)
    c.add("Revenues", "2023-03-01", "2023-05-31", 100.0, filed="2024-07-10")  # recast comparative, 61 days later
    c.add("Revenues", "2023-10-01", "2023-12-31", 100.0)
    c.add("Revenues", "2024-03-01", "2024-05-31", 100.0)  # first new-calendar quarter after a 2-month 10-KT stub
    c.add("Revenues", "2024-06-01", "2024-08-31", 100.0)
    q = c.load(monkeypatch).quarters
    assert pd.Timestamp("2023-05-31") not in q.index  # revision 2 kept it (61 days >= 60)
    assert q.loc["2024-05-31", "fye_break"] and q["fye_break"].sum() == 1
    assert not q["gap"].any()
    assert not F.contiguous(q, 3) and F.contiguous(q, 2) and F.contiguous(q.head(4), 4)
    assert pd.Timestamp("2023-05-31") in c.load(monkeypatch, legacy=True).quarters.index


# ---- D13: signs ----


def test_D13_negative_outflows(monkeypatch):
    c = Co().each("PaymentsToAcquirePropertyPlantAndEquipment", -8.0)  # filer tags payments negative
    c.each("PaymentsOfDividends", 5.0, skip={3}).add("PaymentsOfDividends", *c.q[3], -2.0)
    d = c.load(monkeypatch)
    assert (d.quarters["capex"] == 8.0).all() and "capex: reported with a negative sign, flipped" in d.notes
    assert np.isnan(d.quarters["dividends"].iloc[3]) and d.flags["sign_negative"] == {"dividends": 1}
    assert (c.load(monkeypatch, legacy=True).quarters["capex"] == -8.0).all()


# ---- MM-F4 (data side): D&A ----


def test_MMF4_da_from_parts_and_missing_flag(monkeypatch):
    c = Co().each("Depreciation", 6.0, skip={0, 1}).each("AmortizationOfIntangibleAssets", 2.0)
    q = c.load(monkeypatch).quarters
    assert (q["da"].iloc[2:] == 8.0).all()  # depreciation + amortization (legacy: depreciation alone)
    assert q["da_missing"].tolist()[:3] == [True, True, False]
    assert (c.load(monkeypatch, legacy=True).quarters["da"].iloc[2:] == 6.0).all()


def test_MMF4_annual_only_da_gives_an_estimate_and_a_note(monkeypatch):
    c = Co()
    for y in (2018, 2019, 2020):
        c.add("DepreciationDepletionAndAmortization", f"{y}-01-01", f"{y}-12-31", 40.0, form="10-K")
    d = c.load(monkeypatch)
    q = d.quarters
    assert q["da"].isna().all() and q["da_missing"].all()
    assert (q["da_annual"] == 10.0).all()
    assert any("da: not reported in the last 8 quarters" in n for n in d.notes)
    # point in time: before the first 10-K is filed there is no estimate for 2018
    early = c.load(monkeypatch, asof="2018-12-31").quarters
    assert early["da_annual"].isna().all()


# ---- D11: XBRL fallback instance choice and precision ----


def test_D11_instance_candidates_skip_reference_files():
    names = ["defnref.xml", "FilingSummary.xml", "R1.xml", "abc-20121231_lab.xml", "abc-20121231.xml", "other.xml"]
    assert X.instance_candidates(names, "abc10k.htm")[:2] == ["abc-20121231.xml", "other.xml"]
    assert X.instance_candidates(["x_htm.xml", "abc-20121231.xml"], "x.htm")[0] == "x_htm.xml"
    assert X.is_instance(b'<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>')
    assert not X.is_instance(b'<?xml version="1.0"?><definitions/>') and not X.is_instance(b"not xml")


def test_D11_duplicate_facts_keep_the_most_precise():
    doc = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2025">
 <xbrli:context id="i"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
 <us-gaap:Assets contextRef="i" unitRef="usd" decimals="-6">7000000</us-gaap:Assets>
 <us-gaap:Assets contextRef="i" unitRef="usd" decimals="-3">7012000</us-gaap:Assets>
</xbrli:xbrl>"""
    out = X.parse_instance(doc, {"Assets"}, "a", "10-Q", "2026-07-29")
    assert [r["val"] for r in out["Assets"]] == [7012000.0]


def test_D11_augment_tries_the_next_candidate(monkeypatch):
    inst = b'<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>'
    files = {"abc.xml": b"<definitions/>", "abc-2012.xml": inst}  # both plausible by name
    monkeypatch.setattr(
        X, "periodic_filings", lambda cik: [{"accn": "n", "form": "10-K", "filed": "2013-02-01", "primary": "abc.htm"}]
    )
    monkeypatch.setattr(X, "_index_names", lambda cik, accn: list(files))
    monkeypatch.setattr(X, "_download", lambda cik, accn, name: files[name])
    seen = []
    monkeypatch.setattr(X, "parse_instance", lambda content, *a: seen.append(content) or {"Assets": [{"accn": "n"}]})
    raw = X.augment(1, {"facts": {"us-gaap": {}}}, {"Assets"})
    assert seen == [inst] and raw["_fallback"] == ["n"]
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")  # revision 2 parsed the first name-matching file blindly
    seen.clear()
    X.augment(1, {"facts": {"us-gaap": {}}}, {"Assets"})
    assert seen == [b"<definitions/>"]


# ---- D12: universe financial filter ----


def test_D12_financial_filter_matches_ff12_and_keeps_shells(monkeypatch):
    assert is_financial(6020) and is_financial(6798) and is_financial(6900)
    assert not is_financial(6770) and not is_financial(3711) and not is_financial(None)
    assert ff12(6770) == "Other" and ff12(6900) == "Money"
    monkeypatch.setenv("FINTWIN_DATA_LEGACY", "1")
    assert is_financial(6770) and not is_financial(6900)


# ---- D15: remaining coverage ----


def test_D15_align_tolerance():
    s = {pd.Timestamp("2024-03-30"): (1.0, "a"), pd.Timestamp("2024-07-20"): (2.0, "b")}
    vals, prov = F._align(s, [pd.Timestamp("2024-03-31"), pd.Timestamp("2024-06-30")])
    assert vals[0] == 1.0 and np.isnan(vals[1]) and prov == {"2024-03-31": "a"}  # 20 days > 12-day tolerance


def test_legacy_frame_has_revision_2_columns_only(monkeypatch):
    c = Co(skip={5}).each("AccountsReceivableNetCurrent", 3.0, skip={2}, instant=True)
    d = c.load(monkeypatch, legacy=True)
    assert not set(F.FLAG_COLUMNS + ["da_annual", "debt_notes", "finance_lease"]) & set(d.quarters.columns)
    assert d.imputed is None and d.flags == {} and d.quarters["receivables"].iloc[2] == 0.0


# ---- rerun 5 (12-11-2026): restated annuals, zero-valued revenue tags ----


def test_D6_restated_annual_in_a_later_10k_is_not_differenced_against_the_original_ytd():
    # HP 2014: the 2016 10-K restates FY2014 (spin-off) as a comparative; the 9-month YTD is never restated, so
    # latest annual minus 9-month gave a negative Q4. The pair must come from one vintage: the 9-month as last filed
    # and the first annual filed after it.
    rows = [
        fact("2013-11-01", "2014-07-31", 83.0, "2014-09-10", "q3"),
        fact("2013-11-01", "2014-10-31", 111.0, "2014-12-18", "k14", "10-K"),
        fact("2013-11-01", "2014-10-31", 56.0, "2016-12-15", "k16", "10-K"),
    ]
    diag: dict = {}
    q = F._duration_table({"X": {"units": {"USD": rows}}}, "X", None, diag)
    assert q[pd.Timestamp("2014-10-31")][0] == 28.0
    assert diag["vintage_fixed"] == [("X", pd.Timestamp("2014-10-31"))]


def test_D6_restated_ytd_pairs_with_the_annual_filed_after_it():
    rows = [
        fact("2024-01-01", "2024-09-30", 300, "2024-10-30", "q3"),
        fact("2024-01-01", "2024-12-31", 420, "2025-02-15", "k", "10-K"),
        fact("2024-01-01", "2024-09-30", 270, "2025-10-30", "q3next"),  # restated 9-month comparative
        fact("2024-01-01", "2024-12-31", 380, "2026-02-15", "knext", "10-K"),  # and the annual restated with it
    ]
    q = F._duration_table({"X": {"units": {"USD": rows}}}, "X", None, {})
    assert q[pd.Timestamp("2024-12-31")][0] == 110  # 380 - 270, one vintage


def test_zero_in_the_first_revenue_tag_yields_to_a_non_zero_lower_tag(monkeypatch):
    # Alaska Air 2012-13: `Revenues` = 0 beside `SalesRevenueNet` with the real figures
    c = Co(n=0)
    for i, (s, e) in enumerate(quarters(n=12)):
        c.add("Revenues", s, e, 0.0 if i % 4 else 100.0)
        c.add("SalesRevenueNet", s, e, 100.0)
        c.add_i("Assets", e, 1.0)
    d = c.load(monkeypatch)
    assert (d.quarters["revenue"] == 100.0).all()
    assert d.flags["zero_override"] == [{"field": "revenue", "tag": "SalesRevenueNet", "n": 9}]


def test_a_genuine_zero_revenue_without_another_tag_is_kept(monkeypatch):
    c = Co(n=0)
    for i, (s, e) in enumerate(quarters(n=8)):
        c.add("Revenues", s, e, 0.0 if i == 3 else 100.0)
        c.add_i("Assets", e, 1.0)
    d = c.load(monkeypatch)
    assert d.quarters["revenue"].iloc[3] == 0.0 and "zero_override" not in d.flags


def test_D6_annual_leg_comes_from_an_annual_report_not_a_10q():
    # Church & Dwight 2023: 10-Qs carry an FY2022 fact of another context (179) filed after the 9-month comparative;
    # pairing it with the YTD gave Q4 2022 = -3,760.6M (round-2 review)
    rows = [
        fact("2022-01-01", "2022-09-30", 4000.0, "2022-10-28", "q3-22"),
        fact("2022-01-01", "2022-12-31", 5375.0, "2023-02-15", "k-22", "10-K"),
        fact("2022-01-01", "2022-09-30", 3940.0, "2023-10-27", "q3-23"),  # 9-month comparative, restated
        fact("2022-01-01", "2022-12-31", 179.0, "2023-10-27", "q3-23b"),  # a 10-Q's annual fact of another context
        fact("2022-01-01", "2022-12-31", 5376.0, "2024-02-14", "k-23", "10-K"),  # annual comparative, restated
    ]
    q = F._duration_table({"X": {"units": {"USD": rows}}}, "X", None, {})
    assert q[pd.Timestamp("2022-12-31")][0] == 5376.0 - 3940.0
