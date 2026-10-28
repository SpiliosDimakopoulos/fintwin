"""A survivorship-free research universe and a census of Chapter 11 filings, both built from EDGAR itself.

    uv run python -m fintwin.data.edgar_universe            # -> data/universe_edgar.csv
    uv run python -m fintwin.data.edgar_universe sp500 2020-02-20   # -> data/sp500_2020-02-20.csv

Universe. The XBRL `frames` API returns, for each calendar year, one revenue fact per company that reported it,
including companies that were later acquired, delisted or liquidated. A company enters the universe if it reported
at least $50M of revenue in any year 2012-2024 under any of the revenue tags the loader uses, is not a financial
company or REIT (SIC 6000-6799) and reports in US GAAP. Membership on a given cutoff is decided later, point in
time, by whether the company's filings on that date give at least 16 quarters of history.

Bankruptcy. Item 1.03 of Form 8-K ("Bankruptcy or Receivership") must be filed within four business days of a
Chapter 11 or Chapter 7 petition, so every 8-K carrying it is an event. The census reads each company's complete
filing history from the `submissions` API.

S&P 500 on a past date. The Wikipedia constituents table as it stood on that date (it lists CIKs), checked against
the independent membership history of github.com/fja05680/sp500.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import requests

from .edgar import _get_json, data_legacy
from .facts import DURATION

HERE = Path(__file__).resolve().parent
UNIVERSE_CSV = HERE / "universe_edgar.csv"
YEARS = range(2012, 2025)
MIN_REVENUE = 50e6

# Fama-French 12 industries from 4-digit SIC codes (Kenneth French's definitions; 11 = Money is excluded upstream)
FF12 = [
    ("Consumer NonDurables", [(100, 999), (2000, 2399), (2700, 2749), (2770, 2799), (3100, 3199), (3940, 3989)]),
    (
        "Consumer Durables",
        [
            (2500, 2519),
            (2590, 2599),
            (3630, 3659),
            (3710, 3711),
            (3714, 3714),
            (3716, 3716),
            (3750, 3751),
            (3792, 3792),
            (3900, 3939),
            (3990, 3999),
        ],
    ),
    (
        "Manufacturing",
        [
            (2520, 2589),
            (2600, 2699),
            (2750, 2769),
            (3000, 3099),
            (3200, 3569),
            (3580, 3629),
            (3700, 3709),
            (3712, 3713),
            (3715, 3715),
            (3717, 3749),
            (3752, 3791),
            (3793, 3799),
            (3830, 3839),
            (3860, 3899),
        ],
    ),
    ("Energy", [(1200, 1399), (2900, 2999)]),
    ("Chemicals", [(2800, 2829), (2840, 2899)]),
    ("Business Equipment", [(3570, 3579), (3660, 3692), (3694, 3699), (3810, 3829), (7370, 7379)]),
    ("Telecom", [(4800, 4899)]),
    ("Utilities", [(4900, 4949)]),
    ("Shops", [(5000, 5999), (7200, 7299), (7600, 7699)]),
    ("Health", [(2830, 2839), (3693, 3693), (3840, 3859), (8000, 8099)]),
    ("Money", [(6000, 6999)]),
]


def ff12(sic: int | None) -> str:
    if sic is None or (sic == SHELL_SIC and not data_legacy()):  # a recoded shell's industry is unknown
        return "Other"
    for name, ranges in FF12:
        if any(lo <= sic <= hi for lo, hi in ranges):
            return name
    return "Other"


# SIC 6770 is "blank checks". EDGAR keeps only a company's current SIC, and the shell left after a Chapter 11 sale or
# liquidation is often recoded to 6770; a company in this universe reported >= $50M of revenue, so a 6770 code here
# is such a shell, not a financial firm (D12).
SHELL_SIC = 6770


def is_financial(sic: int | None) -> bool:
    """Financials and REITs, excluded from the universe: the FF12 "Money" range 6000-6999 (D12), except shells.

    Revision 2 excluded 6000-6799 only, so 6800-6999 firms entered the universe while `ff12` labelled them Money.
    """
    if sic is None:
        return False
    if data_legacy():
        return 6000 <= sic <= 6799
    return 6000 <= sic <= 6999 and sic != SHELL_SIC


def frame(tag: str, year: int) -> list[dict]:
    try:
        d = _get_json(
            f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY{year}.json", f"frames_{tag}_CY{year}.json", 1e6
        )
    except requests.HTTPError:  # tag not used in that year
        return []
    return d.get("data", [])


def submissions(cik: int) -> dict:
    """Company metadata plus every filing (the API pages older filings into separate files)."""
    d = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"submissions_{cik:010d}.json", 24 * 30)
    pages = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        pages.append(_get_json(f"https://data.sec.gov/submissions/{f['name']}", f["name"], 24 * 365))
    filings = pd.concat([pd.DataFrame(p) for p in pages if p], ignore_index=True)
    return {"meta": d, "filings": filings}


def candidates() -> pd.DataFrame:
    rows = []
    for year in YEARS:
        for tag in DURATION["revenue"]:
            for r in frame(tag, year):
                rows.append({"cik": int(r["cik"]), "name": r["entityName"], "year": year, "revenue": float(r["val"])})
    df = pd.DataFrame(rows)
    best = df.groupby(["cik", "year"])["revenue"].max().reset_index()
    big = best[best["revenue"] >= MIN_REVENUE].groupby("cik")["year"].agg(["min", "max"])
    names = df.sort_values("year").groupby("cik")["name"].last()
    return big.join(names).rename(columns={"min": "first_year", "max": "last_year"}).reset_index()


def sp500_ciks() -> set[int]:
    """Non-financial S&P 500 members (today's and those of 20 Feb 2020) are always included: GICS puts managed-care
    insurers (SIC 6324) in Health Care, and a few large filers are missing from some revenue frames."""
    out: set[int] = set()
    for f in ("universe_sp500.csv", "sp500_2020-02-20.csv"):
        d = pd.read_csv(HERE / f)
        d = d[~d["sector"].isin(["Financials", "Real Estate"])].dropna(subset=["cik"])
        out |= set(d["cik"].astype(int))
    return out


def build() -> pd.DataFrame:
    cand = candidates()
    forced = sp500_ciks()
    extra = sorted(forced - set(cand["cik"]))
    cand = pd.concat([cand, pd.DataFrame({"cik": extra, "first_year": None, "last_year": None, "name": ""})])
    print(f"{len(cand)} companies with >= $50M revenue in some year {YEARS.start}-{YEARS.stop - 1}", flush=True)
    out = []
    for i, r in enumerate(cand.itertuples()):
        try:
            s = submissions(r.cik)
        except Exception as e:  # keep going; the company is reported as missing
            print(f"  {r.cik}: {type(e).__name__}: {e}", flush=True)
            continue
        meta, f = s["meta"], s["filings"]
        sic = int(meta["sic"]) if str(meta.get("sic") or "").isdigit() else None
        if is_financial(sic) and r.cik not in forced:
            continue
        items = f["items"].fillna("") if "items" in f else pd.Series("", index=f.index)
        is_8k = f["form"].isin(["8-K", "8-K/A"])
        bk = sorted(set(f.loc[is_8k & items.str.contains(r"\b1\.03\b"), "filingDate"]))
        periodic = f.loc[f["form"].isin(["10-K", "10-Q", "10-KT"]), "filingDate"]
        out.append(
            {
                "key": f"CIK{r.cik:010d}",
                "cik": r.cik,
                "name": meta.get("name") or r.name,
                "ticker": (meta.get("tickers") or [""])[0],
                "sic": sic,
                "industry": ff12(sic),
                "fy_end": meta.get("fiscalYearEnd"),
                "first_year": r.first_year,
                "last_year": r.last_year,
                "last_periodic": periodic.max() if len(periodic) else None,
                "bankruptcy_8k": ";".join(bk),
            }
        )
        if i % 250 == 0:
            print(f"  {i}/{len(cand)}", flush=True)
    u = pd.DataFrame(out).sort_values("key")
    u.to_csv(UNIVERSE_CSV, index=False)
    return u


def sp500_on(date: str) -> pd.DataFrame:
    """S&P 500 constituents on `date` (ticker, name, GICS sector and sub-industry, CIK)."""
    api = "https://en.wikipedia.org/w/api.php"
    ua = {"User-Agent": "fintwin-research (github.com/SpiliosDimakopoulos/fintwin)"}
    q: dict[str, str | int] = {
        "action": "query",
        "prop": "revisions",
        "titles": "List of S&P 500 companies",
        "rvlimit": 1,
        "rvstart": f"{date}T23:59:59Z",
        "rvdir": "older",
        "rvprop": "ids|timestamp",
        "format": "json",
    }
    rev = next(iter(requests.get(api, params=q, headers=ua, timeout=60).json()["query"]["pages"].values()))
    rev = rev["revisions"][0]
    text = requests.get(
        "https://en.wikipedia.org/w/index.php", params={"oldid": rev["revid"], "action": "raw"}, headers=ua, timeout=60
    ).text
    table = text[text.index('id="constituents"') :]
    table = table[: table.index("|}")]
    rows = []
    for block in table.split("\n|-")[1:]:
        tick = re.search(
            r"\{\{\s*(?:NyseSymbol|NasdaqSymbol|nyse|nasdaq|BZX link|NYSE American)\s*\|\s*([A-Z.]+)", block, re.I
        )
        body = block.split("\n", 2)[-1].replace("\n|", "||")  # some rows put a cell on its own line
        cells = [c.strip() for c in re.split(r"\|\|", body)]
        cik = re.search(r"\b(\d{10})\b", block)
        if not tick or not cik:
            continue
        name = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", cells[0].lstrip("|")).strip()
        rows.append(
            {
                "ticker": tick.group(1).upper().replace(".", "-"),
                "name": name,
                "sector": cells[2],
                "industry": cells[3],
                "cik": int(cik.group(1)),
            }
        )
    df = pd.DataFrame(rows).drop_duplicates("ticker")
    df.attrs["revision"] = rev
    return df


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sp500":
        d = sys.argv[2]
        df = sp500_on(d)
        df.to_csv(HERE / f"sp500_{d}.csv", index=False)
        print(len(df), "constituents, Wikipedia revision", df.attrs["revision"])
    else:
        u = build()
        print(len(u), "non-financial companies;", int((u["bankruptcy_8k"] != "").sum()), "with an Item 1.03 8-K")
