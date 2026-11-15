"""Turn raw XBRL company facts into a clean quarterly panel.

Three problems this module solves:
1. Tag drift - companies switch tags over time (SalesRevenueNet -> RevenueFromContract...), so each
   field has an ordered list of fallback tags, merged period by period (with a level check at each switch, D7).
2. Year-to-date reporting - 10-Q cash-flow facts are cumulative and Q4 only exists inside the 10-K
   annual total. Discrete quarters are recovered by differencing facts that share a start date, both legs taken
   from the same vintage (D6).
3. Look-ahead bias - restatements overwrite history. `asof` keeps only facts filed on or before a
   date, giving the point-in-time vintage an analyst would actually have seen.

The quarterly spine is a full fiscal calendar (D1): a quarter the company never reported is a row of NaN with
`gap=True`, not a silently skipped row, so windows of "the last n quarters" must be checked with `contiguous`.
FINTWIN_DATA_LEGACY=1 restores the revision-2 loader exactly (`_v2_*` functions at the end of this file).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache, partial
from typing import Any

import numpy as np
import pandas as pd

from .edgar import PERIODIC_FORMS, data_legacy, ticker_to_cik
from .edgar import company_facts as _company_facts


@lru_cache(maxsize=2)
def company_facts(cik: int) -> dict:
    """XBRL company facts, completed from each filing's own XBRL where the SEC API lacks a periodic filing."""
    from .xbrl_fallback import augment

    tags = {t for tags in (*DURATION.values(), *INSTANT.values()) for t in tags}
    tags |= set(MATURITY_TAGS) | {t for tags in DA_PARTS.values() for t in tags}
    tags |= {t for tags in _V2_TAGS.values() for t in tags}
    return augment(cik, _company_facts(cik), tags)


FORMS = PERIODIC_FORMS | {"20-F", "40-F"}
# A fiscal quarter is 12-14 weeks, but 52/53-week retailers run one 16- or 17-week quarter a year (Kroger's first,
# Costco's and AutoZone's fourth): anything from 11 to 18 weeks is one quarter.
QUARTER_DAYS = (75, 126)
ALIGN_TOLERANCE_DAYS = 12
DAYS_PER_QUARTER = 365.25 / 4
# Two spine quarters may share at most this many days; more means a recast or duplicate definition (D9).
OVERLAP_TOLERANCE_DAYS = 15
# Balances are carried forward across at most this many missing quarters (D2); flows never are.
BALANCE_FFILL_LIMIT = 2
# A fallback tag whose values differ from the higher-priority tags by more than this on shared periods is a level
# break (D7): median |a - b| / median |a| over the overlap.
SPLICE_TOLERANCE = 0.10
# A fiscal year is 52 or 53 weeks (364 or 371 days); the band also takes calendar years and a few days of slack.
FISCAL_YEAR_DAYS = (350, 380)
# Total debt above total liabilities means a debt tag is double counted or mis-tagged; 5% leaves room for rounding.
DEBT_OVER_LIABILITIES = 1.05

# field -> ordered tag fallbacks. Duration concepts are flows over a period, instants are balances.
DURATION = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueServicesGross",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",
        # industry-specific totals, used only for periods that none of the tags above covers (found in the audit of
        # the remaining gaps: services firms, utilities, oil and gas producers, real estate, contractors)
        "SalesRevenueServicesNet",
        "RegulatedAndUnregulatedOperatingRevenue",
        "ElectricUtilityRevenue",
        "OilAndGasRevenue",
        "OilAndGasSalesRevenue",
        "RealEstateRevenueNet",
        "ContractsRevenue",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
    ],
    # Totals only. Depreciation alone (without amortization) is a component, combined in DA_PARTS (MM-F4).
    "da": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "CostDepreciationAmortizationAndDepletion",
        "UtilitiesOperatingExpenseDepreciationAndAmortization",
    ],
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestAndDebtExpense",
        "InterestExpenseDebt",
    ],
    "tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "cfo": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    # non-cash impairments, added back to operating income (credit analysts' "adjusted EBIT")
    "imp_total": ["AssetImpairmentCharges"],
    "imp_gw_intang": ["GoodwillAndIntangibleAssetImpairment"],
    "imp_goodwill": ["GoodwillImpairmentLoss"],
    "imp_intangible": [
        "ImpairmentOfIntangibleAssetsExcludingGoodwill",
        "ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill",
    ],
    "imp_longlived": ["ImpairmentOfLongLivedAssetsHeldForUse"],
}
# D&A from its parts, for quarters no total tag covers: depreciation plus whatever amortization is tagged.
DA_PARTS = {
    "depreciation": ["Depreciation"],
    "amortization": ["AmortizationOfIntangibleAssets", "FinanceLeaseRightOfUseAssetAmortization"],
}
INSTANT = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "short_investments": [
        "MarketableSecuritiesCurrent",
        "ShortTermInvestments",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "inventory": ["InventoryNet", "InventoryNetOfAllowancesCustomerAdvancesAndProgressBillings"],
    "payables": [
        "AccountsPayableCurrent",
        "AccountsPayableTradeCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ],
    "deferred_revenue": [
        "ContractWithCustomerLiabilityCurrent",
        "CustomerDepositsCurrent",
        "DeferredRevenueCurrent",
        "CustomerAdvancesCurrent",
    ],
    "ppe": [
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    ],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    # debt building blocks, combined in _total_debt
    "debt_current": ["DebtCurrent"],
    "ltd_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "short_borrowings": ["ShortTermBorrowings", "ShortTermBankLoansAndNotesPayable"],
    "commercial_paper": ["CommercialPaper"],
    "ltd_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "debt_combined": [
        "DebtLongtermAndShorttermCombinedAmount",
        "DebtInstrumentCarryingAmount",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "DebtAndCapitalLeaseObligations",
    ],
    "ltd_total": ["LongTermDebt"],
    # last-resort debt evidence (D3): instrument-level totals and finance leases, used only when no tag above exists
    "debt_notes": ["SeniorNotes", "NotesPayable", "ConvertibleNotesPayable", "LongTermNotesPayable"],
    "finance_lease": ["FinanceLeaseLiability"],
    "revolver_capacity": ["LineOfCreditFacilityMaximumBorrowingCapacity"],
}
DEBT_FIELDS = [
    "debt_current",
    "ltd_current",
    "short_borrowings",
    "commercial_paper",
    "ltd_noncurrent",
    "debt_combined",
    "ltd_total",
    "debt_notes",
    "finance_lease",
]
MATURITY_TAGS = [
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive",
]
# Fields whose level break at a tag switch, or Q4 vintage conflict, flags the quarter.
CORE_FLOWS = ["revenue", "operating_income", "net_income", "cfo", "capex", "da"]
SPLICE_FIELDS = [*CORE_FLOWS, "cash"]
# Outflows reported as positive payments (D13); a filer that tags them negative is normalised.
SIGNED_OUTFLOWS = ["capex", "dividends", "buybacks", "interest_expense"]
# Zero only if never tagged in the whole vintage (D2); otherwise a missing quarter stays NaN.
ZERO_IF_NEVER_TAGGED = [
    "dividends",
    "buybacks",
    "sbc",
    "short_investments",
    "receivables",
    "inventory",
    "deferred_revenue",
    "payables",
]
BALANCES = [
    "cash",
    "ppe",
    "assets",
    "current_assets",
    "current_liabilities",
    "equity",
    "retained_earnings",
    "payables",
    "revolver_capacity",
    "short_investments",
    "receivables",
    "inventory",
    "deferred_revenue",
]
# Flag columns added to `quarters` (all bool except da_annual); see docs/review_2026-10/interfaces/A.md.
FLAG_COLUMNS = ["gap", "fye_break", "vintage_mixed", "splice_break", "da_missing"]


@dataclass
class CompanyData:
    ticker: str
    cik: int
    name: str
    asof: str | None
    quarters: pd.DataFrame  # index = quarter end (Timestamp)
    provenance: dict[str, dict[str, str]]  # field -> {period end iso: accession}
    maturities: list[float]  # principal due in years 1..5 and after year 5
    maturities_date: str | None
    notes: list[str] = field(default_factory=list)
    # True where a value in `quarters` was not reported for that quarter but carried forward or zero-filled (D2)
    imputed: pd.DataFrame | None = None
    # data-quality diagnostics: tag splices, Q4 vintage fixes, sign flips, gap counts (empty in legacy mode)
    flags: dict = field(default_factory=dict)


def contiguous(q: pd.DataFrame, n: int, col: str = "revenue") -> bool:
    """True if the last `n` rows of `q` are `n` consecutive fiscal quarters, all with `col` reported.

    Pass `q.head(n)` / `q.loc[a:b]` to test another window. A window fails if it is short, holds a calendar gap
    row (D1), crosses a fiscal-year-end change that left days uncovered (D9), or (legacy frames without gap rows)
    has two rows further apart than one quarter.
    """
    if n <= 0 or len(q) < n:
        return False
    return bool(contiguous_mask(q.tail(n), n, col).iloc[-1])


def contiguous_mask(q: pd.DataFrame, n: int, col: str = "revenue") -> pd.Series:
    """Per row: does the window of the `n` rows ending here pass `contiguous`? Use it to mask `.rolling(n)` sums."""
    ok = q[col].notna()
    if n <= 1:
        return ok
    steps = pd.Series(q.index, index=q.index).diff().dt.days
    link = steps.between(*QUARTER_DAYS)  # row i follows row i-1 by one quarter (False on the first row)
    if "fye_break" in q:
        link &= ~q["fye_break"].astype(bool)
    run = ok.astype(int).rolling(n, min_periods=n).sum().eq(n)  # rows i-n+1..i reported
    links = link.astype(int).rolling(n - 1, min_periods=n - 1).sum().eq(n - 1)  # links into rows i-n+2..i
    return (run & links).astype(bool)


def _usd_facts(gaap: dict, tag: str, asof: pd.Timestamp | None) -> pd.DataFrame:
    if tag not in gaap:
        return pd.DataFrame()
    rows = gaap[tag]["units"].get("USD", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["form"].isin(FORMS)].copy()
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    if "start" in df:
        df["start"] = pd.to_datetime(df["start"])
    if asof is not None:
        df = df[df["filed"] <= asof]
    return df


def _by_vintage(df: pd.DataFrame) -> pd.DataFrame:
    """Facts in filing order with a deterministic tie-break on same-day filings (accession number, D5)."""
    return df.sort_values(["filed", "accn"], kind="mergesort")


def _latest(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Keep the most recently filed fact per period (restatements win, within the vintage).

    One whole row per period (D5): `groupby().last()` takes the last non-null value of each column separately,
    which can splice the value of one filing to the accession number of another.
    """
    if data_legacy():
        return _v2_latest(df, keys)
    return _by_vintage(df).drop_duplicates(keys, keep="last").reset_index(drop=True)


def _duration_table(gaap: dict, tag: str, asof: pd.Timestamp | None = None, diag: dict | None = None) -> dict:
    """Discrete quarters {end: (value, accn, start)} for one tag, de-cumulating YTD facts within one vintage."""
    df = _usd_facts(gaap, tag, asof)
    if df.empty or "start" not in df:
        return {}
    df = _by_vintage(df.dropna(subset=["start"]))
    versions = {k: g for k, g in df.groupby(["start", "end"], sort=False)}
    df = df.drop_duplicates(["start", "end"], keep="last").copy()
    df["days"] = (df["end"] - df["start"]).dt.days

    out: dict[pd.Timestamp, tuple[float, str, pd.Timestamp]] = {}
    direct = df[df["days"].between(*QUARTER_DAYS)]
    for r in direct.itertuples():
        out[r.end] = (float(r.val), r.accn, r.start)

    # Pairs of cumulative facts sharing a start date: later minus earlier = the quarter in between. The earlier leg is
    # taken as it stood when the later leg was filed (D6): differencing a restated 9-month YTD against an original
    # annual total (or the reverse) mixes two vintages and books the whole restatement in Q4.
    for start, grp in df[df["days"] > QUARTER_DAYS[1]].groupby("start"):
        grp = pd.concat([grp, direct[direct["start"] == start]]).sort_values("end")
        rows = list(grp.itertuples())
        for i in range(1, len(rows)):
            late, early = rows[i], rows[i - 1]
            gap = (late.end - early.end).days
            if not (QUARTER_DAYS[0] <= gap <= QUARTER_DAYS[1]) or late.end in out:
                continue
            vers = versions[(early.start, early.end)]
            lvers = versions[(late.start, late.end)]
            if (late.end - late.start).days > 300:  # an annual later leg: from an annual report (10-K family) when
                annual = lvers[lvers["form"].astype(str).str.startswith(("10-K", "20-F", "40-F"))]  # one exists; a 10-Q
                lvers = annual if len(annual) else lvers  # may carry an annual fact of another context (round 2)
            # One vintage: the earlier leg as last filed and the first later leg filed after it. A later leg restated
            # in a later 10-K (e.g. a spin-off recast as a comparative) is otherwise differenced against a YTD that
            # was never restated (12-11-2026: HP FY2014 Q4 came out at -26bn).
            leg = vers.iloc[-1]
            after = lvers[lvers["filed"] >= leg["filed"]]
            if len(after):
                lv = after.iloc[0]
            else:  # the earlier leg was restated after every version of the later one: the YTD as known then
                lv = lvers.iloc[-1]
                same = vers[vers["accn"] == lv["accn"]]
                prior = vers[vers["filed"] <= lv["filed"]]
                leg = same.iloc[-1] if len(same) else prior.iloc[-1] if len(prior) else None
            if leg is None:  # the earlier leg only exists in filings after the later leg: no consistent vintage
                if diag is not None:
                    diag.setdefault("vintage_mixed", []).append((tag, late.end))
                continue
            if diag is not None and (float(leg["val"]) != float(early.val) or float(lv["val"]) != float(late.val)):
                diag.setdefault("vintage_fixed", []).append((tag, late.end))
            out[late.end] = (float(lv["val"] - leg["val"]), lv["accn"], early.end + pd.Timedelta(days=1))
    return out


def duration_quarters(gaap: dict, tag: str, asof: pd.Timestamp | None = None) -> dict:
    """Discrete-quarter values {end: (value, accn)} for one tag, de-cumulating YTD facts."""
    if data_legacy():
        return _v2_duration_quarters(gaap, tag, asof)
    return {e: v[:2] for e, v in _duration_table(gaap, tag, asof).items()}


def instant_values(gaap: dict, tag: str, asof: pd.Timestamp | None = None) -> dict:
    df = _usd_facts(gaap, tag, asof)
    if df.empty:
        return {}
    df = _latest(df, ["end"])
    return {r.end: (float(r.val), r.accn) for r in df.itertuples()}


def _merge_tags(gaap: dict, tags: list[str], extractor, asof, diag: dict | None = None, name: str = "") -> dict:
    """Merge tag fallbacks by priority, period by period. With `diag`, check each switch for a level break (D7)."""
    merged: dict = {}
    for tag in tags:
        s = extractor(gaap, tag, asof)
        new = [e for e in s if e not in merged]
        if diag is not None and merged and new:
            both = [e for e in s if e in merged]
            if both:
                a = np.array([merged[e][0] for e in both])
                b = np.array([s[e][0] for e in both])
                level = float(np.median(np.abs(a)))
                if level > 0:
                    rel = float(np.median(np.abs(a - b)) / level)
                else:  # a tag of zeros beside a non-zero one is a break, not a match
                    rel = float("inf") if float(np.median(np.abs(b))) > 0 else 0.0
                if rel > SPLICE_TOLERANCE:
                    diag.setdefault("splice", []).append(
                        {"field": name, "tag": tag, "rel_diff": round(rel, 4), "overlap": len(both), "periods": new}
                    )
            else:
                diag.setdefault("splice_unchecked", []).append({"field": name, "tag": tag, "periods": new})
        if name == "revenue":  # a revenue booked as exactly 0 yields to a non-zero lower tag (Alaska Air 2012-13)
            zero = [e for e in s if e in merged and merged[e][0] == 0 and s[e][0] != 0]
            for e in zero:
                merged[e] = s[e]
            if zero and diag is not None:
                diag.setdefault("zero_override", []).append({"field": name, "tag": tag, "n": len(zero)})
        for e in new:
            merged[e] = s[e]
    return merged


def _align(series: dict, spine: list[pd.Timestamp]) -> tuple[list[float], dict[str, str]]:
    """Snap {end: (val, accn)} onto the spine of quarter ends (52/53-week calendars drift a few days)."""
    if not series:
        return [np.nan] * len(spine), {}
    ends = np.array(sorted(series), dtype="datetime64[ns]")
    vals, prov = [], {}
    for q in spine:
        diffs = np.abs((ends - np.datetime64(q)).astype("timedelta64[D]").astype(int))
        i = int(np.argmin(diffs))
        if diffs[i] <= ALIGN_TOLERANCE_DAYS:
            v, accn = series[pd.Timestamp(ends[i])][:2]
            vals.append(v)
            prov[q.date().isoformat()] = accn
        else:
            vals.append(np.nan)
    return vals, prov


def _on_spine(dates, spine: list[pd.Timestamp]) -> np.ndarray:
    """Boolean per spine point: is one of `dates` within the alignment tolerance."""
    hit = np.zeros(len(spine), dtype=bool)
    for d in dates:
        diffs = [abs((d - s).days) for s in spine]
        if diffs and min(diffs) <= ALIGN_TOLERANCE_DAYS:
            hit[int(np.argmin(diffs))] = True
    return hit


def _spine(revenue: dict, min_year: int, anchors: list[pd.Timestamp], notes: list[str]) -> pd.DataFrame:
    """Full fiscal calendar: reported revenue quarters plus NaN rows for the quarters in between that were not (D1).

    Quarters that overlap the previous one by more than OVERLAP_TOLERANCE_DAYS are recast or duplicate definitions
    and are dropped; the first-ending one is kept (D9). Uncovered days shorter than a quarter between two quarters (the
    stub of a fiscal-year-end change, e.g. a two-month 10-KT) set `fye_break` on the next quarter. Inserted rows take
    the nearest balance-sheet date (`anchors`) within the alignment tolerance, so 52/53-week calendars stay aligned.
    """
    cands = sorted((e, v[2]) for e, v in revenue.items() if e.year >= min_year)
    kept: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    dropped = 0
    for e, s in cands:
        if kept and s < kept[-1][0] - pd.Timedelta(days=OVERLAP_TOLERANCE_DAYS):
            dropped += 1
            continue
        kept.append((e, s))
    anchor_arr = np.array(sorted(set(anchors)), dtype="datetime64[ns]")

    def snap(t: pd.Timestamp) -> pd.Timestamp:
        if len(anchor_arr):
            d = np.abs((anchor_arr - np.datetime64(t)).astype("timedelta64[D]").astype(int))
            i = int(np.argmin(d))
            if d[i] <= ALIGN_TOLERANCE_DAYS:
                return pd.Timestamp(anchor_arr[i])
        return t

    rows: list[dict[str, Any]] = []
    n_gap, n_break = 0, 0
    for i, (e, s) in enumerate(kept):
        brk = False
        if i:
            prev = kept[i - 1][0]
            uncovered = (s - prev).days - 1
            # whole quarters that fit in the uncovered days; less than one quarter is a stub, not a missing quarter
            k = 0 if uncovered < QUARTER_DAYS[0] else max(1, int(round(uncovered / DAYS_PER_QUARTER)))
            for j in range(1, k + 1):
                t = snap(prev + pd.Timedelta(days=round(j * uncovered / k)))
                if (rows and (t - rows[-1]["end"]).days < QUARTER_DAYS[0]) or (e - t).days < QUARTER_DAYS[0]:
                    continue  # snapping pulled it onto a neighbour
                rows.append({"end": t, "gap": True, "fye_break": False})
                n_gap += 1
            if k == 0 and uncovered > OVERLAP_TOLERANCE_DAYS:
                brk = True
                n_break += 1
        rows.append({"end": e, "gap": False, "fye_break": brk})
    if dropped:
        notes.append(f"spine: {dropped} overlapping (recast or duplicate) quarter definitions dropped")
    if n_gap:
        notes.append(f"spine: {n_gap} unreported quarters kept as gap rows (NaN)")
    if n_break:
        notes.append(f"spine: {n_break} fiscal-year-end change(s) leave days uncovered (fye_break)")
    if not rows:
        return pd.DataFrame({"gap": [], "fye_break": []}, index=pd.DatetimeIndex([], name="end"))
    return pd.DataFrame(rows).set_index("end")


def _total_debt(q: pd.DataFrame) -> pd.Series:
    """Combine heterogeneous debt tags into one total-debt series, preferring explicit splits.

    NaN where the quarter has no debt evidence at all (D3); the caller zero-fills only a company that never tags debt.
    """
    if data_legacy():
        return _v2_total_debt(q)
    parts = q[["ltd_current", "short_borrowings", "commercial_paper"]]
    current = q["debt_current"].fillna(parts.sum(axis=1, min_count=1))
    split = current.fillna(0.0) + q["ltd_noncurrent"]
    short = q[["short_borrowings", "commercial_paper"]].sum(axis=1)
    total = split.fillna(q["debt_combined"]).fillna(q["ltd_total"] + short)
    # only short-term debt tagged (no long-term line at all): the current part is the total
    total = total.fillna(current)
    notes_total = q["debt_notes"].fillna(0.0) + q["finance_lease"].fillna(0.0)
    has_notes = q[["debt_notes", "finance_lease"]].notna().any(axis=1)
    return total.fillna(notes_total.where(has_notes))


def season_of(end: pd.Timestamp) -> int:
    """Fiscal-calendar-agnostic season key 0..3 (shift back 10 days so 52/53-week ends land correctly)."""
    return ((end - pd.Timedelta(days=10)).month - 1) // 3


def _normalise_signs(q: pd.DataFrame, notes: list[str], flags: dict) -> None:
    """Payments are positive outflows (D13). A filer tagging most of them negative is flipped; isolated negative
    quarters (usually a YTD restatement de-cumulated into one quarter) become missing."""
    for k in SIGNED_OUTFLOWS:
        s = q[k]
        nz = s[s.notna() & (s != 0)]
        if len(nz) and float((nz < 0).mean()) > 0.5:
            q[k] = -s
            notes.append(f"{k}: reported with a negative sign, flipped")
            flags.setdefault("sign_flipped", []).append(k)
        neg = q[k] < 0
        if neg.any():
            q.loc[neg, k] = np.nan
            notes.append(f"{k}: {int(neg.sum())} negative quarter(s) set to missing")
            flags.setdefault("sign_negative", {})[k] = int(neg.sum())


def _annual_da(gaap: dict, cut, ends: list[pd.Timestamp]) -> dict:
    """A quarter-of-year D&A estimate (fiscal-year total / 4) for quarters without a quarterly D&A fact (MM-F4).

    Uses the fiscal year covering the quarter if its 10-K is in the vintage, else the latest earlier fiscal year.
    """
    years: dict[tuple, float] = {}
    for tag in [*DURATION["da"], *DA_PARTS["depreciation"]]:
        df = _usd_facts(gaap, tag, cut)
        if df.empty or "start" not in df:
            continue
        df = _latest(df.dropna(subset=["start"]), ["start", "end"])
        fy = df[((df["end"] - df["start"]).dt.days).between(*FISCAL_YEAR_DAYS)]
        for r in fy.itertuples():
            years.setdefault((r.start, r.end), float(r.val))
    out = {}
    for e in ends:
        cover = [v for (s, en), v in years.items() if s <= e <= en + pd.Timedelta(days=ALIGN_TOLERANCE_DAYS)]
        if cover:
            out[e] = cover[0] / 4
            continue
        before = [(en, v) for (s, en), v in years.items() if en < e and (e - en).days <= FISCAL_YEAR_DAYS[1]]
        if before:
            out[e] = max(before)[1] / 4
    return out


def load_company(ticker: str, asof: str | None = None, min_year: int = 2010) -> CompanyData:
    if data_legacy():
        return _v2_load_company(ticker, asof, min_year)
    cik, name = ticker_to_cik(ticker)
    raw = company_facts(cik)
    gaap = raw["facts"].get("us-gaap", {})
    cut = pd.Timestamp(asof) if asof else None
    diag: dict = {}
    notes: list[str] = []
    if raw.get("_fallback_errors"):
        notes.append(f"xbrl fallback incomplete, {len(raw['_fallback_errors'])} error(s): {raw['_fallback_errors'][0]}")

    dur = {}
    for k, tags in DURATION.items():
        sub: dict = {}
        dur[k] = _merge_tags(gaap, tags, partial(_duration_table, diag=sub), cut, diag, k)
        for kind in ("vintage_mixed", "vintage_fixed"):
            diag.setdefault(kind, []).extend((k, *x) for x in sub.get(kind, []))
    # D&A from depreciation + amortization where no total tag covers the quarter
    dep = _merge_tags(gaap, DA_PARTS["depreciation"], _duration_table, cut)
    amort = [_merge_tags(gaap, [t], _duration_table, cut) for t in DA_PARTS["amortization"]]
    n_parts = 0
    for e, (v, accn, s) in dep.items():
        if e not in dur["da"]:
            dur["da"][e] = (v + sum(a[e][0] for a in amort if e in a), accn, s)
            n_parts += 1
    inst = {k: _merge_tags(gaap, tags, instant_values, cut, diag, k) for k, tags in INSTANT.items()}

    anchors = [*inst["assets"], *inst["cash"]]
    cal = _spine(dur["revenue"], min_year, anchors, notes)
    spine = list(cal.index)

    data, provenance = {}, {}
    for k, s in {**dur, **inst}.items():
        data[k], provenance[k] = _align(s, spine)
    q = pd.DataFrame(data, index=pd.DatetimeIndex(spine, name="end"))
    q["gap"] = cal["gap"].astype(bool).values
    q["fye_break"] = cal["fye_break"].astype(bool).values
    mixed = [e for f, _, e in diag["vintage_mixed"] if f in CORE_FLOWS]
    q["vintage_mixed"] = _on_spine(mixed, spine)
    breaks = [e for s in diag.get("splice", []) if s["field"] in SPLICE_FIELDS for e in s["periods"]]
    q["splice_break"] = _on_spine(breaks, spine)
    if n_parts and q["da"].notna().any():
        notes.append(f"da: depreciation + amortization used for {n_parts} quarters without a D&A total")

    _normalise_signs(q, notes, diag)
    reported = q.notna()

    for k in ["dividends", "buybacks", "sbc", "short_investments", "receivables", "inventory", "revolver_capacity"]:
        if q[k].isna().all():
            notes.append(f"{k}: no data, assumed 0" if k != "revolver_capacity" else f"{k}: no data")
    # Some filers never tag operating income; rebuild it as pre-tax income plus interest expense.
    if q["operating_income"].isna().any():
        rebuilt = q["pretax_income"] + q["interest_expense"].fillna(0)
        if q["operating_income"].isna().all():
            notes.append("operating income rebuilt as pre-tax income + interest expense")
        q["operating_income"] = q["operating_income"].fillna(rebuilt)
    # Adjusted operating income: add back non-cash impairments. Tags overlap (a cash-flow total vs. its components),
    # so take the largest of the alternative measurements per quarter rather than summing them.
    parts = q[["imp_goodwill", "imp_intangible", "imp_longlived"]].fillna(0).sum(axis=1)
    impairment = (
        pd.concat([q["imp_total"].fillna(0), q["imp_gw_intang"].fillna(0), parts], axis=1).max(axis=1).clip(lower=0)
    )
    q["impairment"] = impairment
    q["operating_income_reported"] = q["operating_income"]
    q["operating_income"] = q["operating_income"] + impairment
    if impairment.gt(0).any():
        notes.append(f"operating income adjusted for impairments in {int(impairment.gt(0).sum())} quarters")
    for k in ("payables", "deferred_revenue"):
        if q[k].isna().all():
            notes.append(f"{k}: no data, assumed 0")
    # D2: a field the company never tags is zero; one it tags but skipped in a quarter is unknown, not zero.
    for k in ZERO_IF_NEVER_TAGGED:
        if q[k].isna().all():
            q[k] = 0.0
    # Balances are sticky: carry the last known value across a few missing quarters. Flows are never carried.
    q[BALANCES] = q[BALANCES].ffill(limit=BALANCE_FFILL_LIMIT)
    # Debt: every component carried forward the same way before the total is assembled (D3).
    if q[DEBT_FIELDS].isna().all().all():
        q["total_debt"] = 0.0
        notes.append("total_debt: no debt tag in any filing, assumed 0")
        diag["debt_untagged"] = True
    else:
        q[DEBT_FIELDS] = q[DEBT_FIELDS].ffill(limit=BALANCE_FFILL_LIMIT)
        q["total_debt"] = _total_debt(q)
        n_nan = int(q["total_debt"][~q["gap"]].isna().sum())
        if n_nan:
            notes.append(f"total_debt: no debt tag in {n_nan} reported quarters, left missing")
    debt_parts = ["debt_current", "ltd_current", "short_borrowings", "commercial_paper"]
    q[debt_parts] = q[debt_parts].fillna(0.0)
    if q["liabilities"].isna().any():
        derived = q["assets"] - q["equity"]
        if q["liabilities"].isna().all():
            notes.append("liabilities derived as assets - equity")
        q["liabilities"] = q["liabilities"].fillna(derived)
    over = q["total_debt"] > DEBT_OVER_LIABILITIES * q["liabilities"]
    if over.any():
        notes.append(f"total_debt exceeds total liabilities in {int(over.sum())} quarters (check the debt tags)")
        diag["debt_over_liabilities"] = int(over.sum())
    q["season"] = [season_of(e) for e in q.index]

    # MM-F4: D&A missing in a reported quarter. `da` stays NaN; `da_annual` offers the fiscal-year/4 estimate.
    q["da_missing"] = q["da"].isna() & ~q["gap"]
    est = _annual_da(gaap, cut, [e for e in q.index[q["da_missing"]]])
    q["da_annual"] = pd.Series(est, dtype=float).reindex(q.index)
    real = q[~q["gap"]]
    if len(real) and real["da_missing"].tail(8).all():
        notes.append("da: not reported in the last 8 quarters (D&A sits inside operating costs)")

    imputed = (~reported.reindex(columns=q.columns, fill_value=True)) & q.notna()
    imputed = imputed.drop(columns=[c for c in [*FLAG_COLUMNS, "season", "da_annual"] if c in imputed])
    diag.update(
        gaps=int(q["gap"].sum()),
        fye_breaks=int(q["fye_break"].sum()),
        da_missing=int(q["da_missing"].sum()),
        da_from_parts=n_parts,
    )
    maturities, mat_date = _maturity_ladder(gaap, cut)
    return CompanyData(ticker.upper(), cik, name, asof, q, provenance, maturities, mat_date, notes, imputed, diag)


def _maturity_ladder(gaap: dict, asof) -> tuple[list[float], str | None]:
    per_tag = [instant_values(gaap, t, asof) for t in MATURITY_TAGS]
    dates = set().union(*[set(d) for d in per_tag[:3]])
    if not dates:
        return [], None
    latest = max(dates)
    ladder = []
    for d in per_tag:
        near = [e for e in d if abs((e - latest).days) <= ALIGN_TOLERANCE_DAYS]
        ladder.append(d[near[0]][0] if near else 0.0)
    return ladder, latest.date().isoformat()


# ---- revision-2 data layer, kept verbatim for FINTWIN_DATA_LEGACY=1 ----

# tag lists as they stood in revision 2 (fields not listed here were unchanged)
_V2_TAGS = {
    "da": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "Depreciation",
    ],
    "short_borrowings": ["ShortTermBorrowings"],
    "debt_combined": ["DebtLongtermAndShorttermCombinedAmount", "DebtInstrumentCarryingAmount"],
}
_V2_NEW_FIELDS = {"debt_notes", "finance_lease"}


def _v2_latest(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return df.sort_values("filed").groupby(keys, as_index=False).last()


def _v2_duration_quarters(gaap: dict, tag: str, asof: pd.Timestamp | None = None) -> dict:
    df = _usd_facts(gaap, tag, asof)
    if df.empty or "start" not in df:
        return {}
    df = _v2_latest(df.dropna(subset=["start"]), ["start", "end"])
    df["days"] = (df["end"] - df["start"]).dt.days

    out: dict[pd.Timestamp, tuple[float, str]] = {}
    direct = df[df["days"].between(*QUARTER_DAYS)]
    for r in direct.itertuples():
        out[r.end] = (float(r.val), r.accn)

    for _, grp in df[df["days"] > QUARTER_DAYS[1]].groupby("start"):
        grp = pd.concat([grp, direct[direct["start"] == grp["start"].iloc[0]]]).sort_values("end")
        ends, vals, accns = grp["end"].tolist(), grp["val"].tolist(), grp["accn"].tolist()
        for i in range(1, len(ends)):
            gap = (ends[i] - ends[i - 1]).days
            if QUARTER_DAYS[0] <= gap <= QUARTER_DAYS[1] and ends[i] not in out:
                out[ends[i]] = (float(vals[i] - vals[i - 1]), accns[i])
    return out


def _v2_total_debt(q: pd.DataFrame) -> pd.Series:
    current = q["debt_current"].copy()
    parts = q[["ltd_current", "short_borrowings", "commercial_paper"]]
    current = current.fillna(parts.sum(axis=1, min_count=1)).fillna(0.0)
    split = current + q["ltd_noncurrent"]
    total = split.fillna(q["debt_combined"]).fillna(
        q["ltd_total"] + q[["short_borrowings", "commercial_paper"]].sum(axis=1)
    )
    return total.fillna(0.0)


def _v2_load_company(ticker: str, asof: str | None = None, min_year: int = 2010) -> CompanyData:
    cik, name = ticker_to_cik(ticker)
    raw = company_facts(cik)
    gaap = raw["facts"].get("us-gaap", {})
    cut = pd.Timestamp(asof) if asof else None
    duration = {k: _V2_TAGS.get(k, v) for k, v in DURATION.items()}
    instant = {k: _V2_TAGS.get(k, v) for k, v in INSTANT.items() if k not in _V2_NEW_FIELDS}

    dur = {k: _merge_tags(gaap, tags, _v2_duration_quarters, cut) for k, tags in duration.items()}
    inst = {k: _merge_tags(gaap, tags, instant_values, cut) for k, tags in instant.items()}

    spine = sorted(e for e in dur["revenue"] if e.year >= min_year)
    # Drop spine points closer than ~2 months to the previous one (duplicate quarter definitions).
    clean: list[pd.Timestamp] = []
    for e in spine:
        if not clean or (e - clean[-1]).days >= 60:
            clean.append(e)
    spine = clean

    data, provenance = {}, {}
    for k, s in {**dur, **inst}.items():
        data[k], provenance[k] = _align(s, spine)
    q = pd.DataFrame(data, index=pd.DatetimeIndex(spine, name="end"))

    notes = []
    for k in ["dividends", "buybacks", "sbc", "short_investments", "receivables", "inventory", "revolver_capacity"]:
        if q[k].isna().all():
            notes.append(f"{k}: no data, assumed 0")
    if q["operating_income"].isna().any():
        rebuilt = q["pretax_income"] + q["interest_expense"].fillna(0)
        if q["operating_income"].isna().all():
            notes.append("operating income rebuilt as pre-tax income + interest expense")
        q["operating_income"] = q["operating_income"].fillna(rebuilt)
    parts = q[["imp_goodwill", "imp_intangible", "imp_longlived"]].fillna(0).sum(axis=1)
    impairment = (
        pd.concat([q["imp_total"].fillna(0), q["imp_gw_intang"].fillna(0), parts], axis=1).max(axis=1).clip(lower=0)
    )
    q["impairment"] = impairment
    q["operating_income_reported"] = q["operating_income"]
    q["operating_income"] = q["operating_income"] + impairment
    if impairment.gt(0).any():
        notes.append(f"operating income adjusted for impairments in {int(impairment.gt(0).sum())} quarters")
    if q["payables"].isna().all():
        notes.append("payables: no data, assumed 0")
    zero_fill = [
        "dividends",
        "buybacks",
        "sbc",
        "short_investments",
        "receivables",
        "inventory",
        "deferred_revenue",
    ]
    q[zero_fill] = q[zero_fill].fillna(0.0)
    for k in [
        "cash",
        "ppe",
        "assets",
        "current_assets",
        "current_liabilities",
        "equity",
        "retained_earnings",
        "ltd_noncurrent",
        "debt_combined",
        "ltd_total",
        "payables",
        "revolver_capacity",
    ]:
        q[k] = q[k].ffill(limit=2)
    q["payables"] = q["payables"].fillna(0.0)
    q["total_debt"] = _v2_total_debt(q)
    debt_parts = ["debt_current", "ltd_current", "short_borrowings", "commercial_paper"]
    q[debt_parts] = q[debt_parts].fillna(0.0)
    if q["liabilities"].isna().any():
        derived = q["assets"] - q["equity"]
        if q["liabilities"].isna().all():
            notes.append("liabilities derived as assets - equity")
        q["liabilities"] = q["liabilities"].fillna(derived)
    q["season"] = [season_of(e) for e in q.index]

    maturities, mat_date = _maturity_ladder(gaap, cut)
    return CompanyData(ticker.upper(), cik, name, asof, q, provenance, maturities, mat_date, notes)
