# FinTwin growth plan: review by an empirical corporate-finance / accounting user

Reviewer stance: I use Compustat, CRSP and Compustat Snapshot. Reviewed: GROWTH_PLAN.md (sections 0-8), METHODOLOGY.md section 1, and greps of engine/fintwin/data (facts.py, edgar.py, xbrl_fallback.py). "Verified" = checked against a source or the repo; "unverified" = from my own knowledge, to be confirmed before the plan relies on it.

Overall: the plan targets ML/quant/HN audiences. Almost nothing addresses what an accounting or finance referee needs to cite the data: a variable dictionary, identifiers, validation against Compustat, a stated sample window and exclusions, and a restatement policy. These are cheap to add and decide whether academics adopt it.

## 1. Blocking problems

**FR-1 (Blocking). No identifier layer, so data cannot be merged with CRSP, IBES or Compustat.**
The planned universe has cik, ticker, sic, status, entry, exit (L2, H1). Empirical work merges on PERMNO or gvkey. Tickers are recycled, so ticker joins silently mismatch. ticker_to_cik uses SEC company_tickers.json, which lists current tickers only (verified, edgar.py:115). The repo uses synthetic keys like HTZ~2020 that must not leak into a public schema.
Fix:
- CIK is the primary key. Add a cik_ticker_history table (ticker, exchange, valid_from, valid_to, source) built from the SEC submissions API (tickers / formerNames fields) and from the cover-page dei:TradingSymbol and dei:SecurityExchangeName of each filing. Feasible from public data.
- Do NOT promise a shipped PERMNO or gvkey crosswalk. CRSP/Compustat identifiers are licensed, and WRDS linking tables (CRSP/Compustat Merged, SEC Analytics) are WRDS-only (unverified). Instead publish a documented recipe plus script: users join on Compustat company.cik (Compustat carries a CIK field; unverified) or on CUSIP/name+date matching, and a match_quality column. I did not verify any public CIK-PERMNO link; if one is adopted its licence must be checked.
- Add cik_history for CIK reuse, mergers, successor filers.

**FR-2 (Blocking). Sample window is overstated ("2009-today") and there is no coverage-by-year table.**
XBRL phase-in (verified: https://www.sec.gov/info/smallbus/secg/interactivedata-secg.htm): large accelerated filers (float over 5B USD) from periods after June 15 2009; other large accelerated June 2010; all others including smaller reporting companies for periods ending on or after June 15 2011; detailed footnote tagging a year later. So:
- Before mid-2011 the panel is a small, size-selected, survival-selected set. Regressions on 2009-2010 are not comparable with Compustat.
- "Survivorship-free" is true only from 2011. A firm that failed in 2009-2011 and was never tagged is absent. The 475 bankruptcy labels therefore have a selection problem: report how many have at least N quarters of XBRL history before the event.
- FY2009+ filings repeat prior-year comparatives with later filed dates. These are usable as restated vintages but are NOT first-reported; flag them (first_reported_flag).
Fix: publish n firms, share of core variables available, by year and size bucket; state "full universe from 2011Q2; large-filer subset 2009-2010"; recommend studies start 2011Q3 or later.

**FR-3 (Blocking). No validation against Compustat is planned.**
H3 checks A = L + E and compares to 10-Qs (same source), which shows internal consistency, not agreement with the data referees trust. Fix:
- Stratified random sample (about 500 firm-quarters by size, year, SIC, 52/53-week status). Compare AT, LT, CEQ, SALEQ, NIQ, OIADPQ, OANCFY (de-cumulated), DLCQ+DLTTQ, CHEQ. Report exact-match share, within-1% share, distribution of absolute log ratios, systematic breaks.
- Publish code and aggregate comparison only (Compustat values cannot be redistributed). Ship validate_against_compustat.py for licensed users.
- If no WRDS access, say so openly; never claim agreement that was not tested.
- Also compare first-reported values to Compustat Snapshot on a sample; Snapshot uses its own vintage dates, which differ from the SEC filing date (FR-8).
- Replication of published results (FR-15) is a second validation vector.

**FR-4 (Blocking). No variable dictionary mapped to Compustat items.**
The plan uses fields like revenue, fcf, cash and promises a data dictionary auto-generated from the schema. A schema dump does not define fields. METHODOLOGY section 1 shows choices that change values: ordered fallback tags merged period by period, debt assembled from components, operating income rebuilt as pretax income + interest, and an impairment addback to EBIT (item 3, motivated by Kraft Heinz). The last is a non-GAAP adjustment baked into a field; a researcher using operating_income will assume OIADP.
Fix: VARIABLES.md / variable_map.csv with per field: definition, XBRL tags in priority order, nearest Compustat quarterly item (SALEQ, ATQ, CHEQ, DLCQ, DLTTQ, OIADPQ, OANCFY, CAPXY...), known differences (Compustat standardizes and nets; XBRL is as reported), fill share per tag, and a tag_used column in the panel. Ship adjusted_ebit and unadjusted operating_income as separate fields. Flag derived and imputed values (the plan has derived; add imputed, which exists in CompanyData).

## 2. Important problems

**FR-5 (High). Amendment and restatement policy is unspecified.**
facts.py:40 includes 10-K/A, 10-Q/A, 10-KT in FORMS (verified); METHODOLOGY says the latest filing wins. H1 quarterly_first vs quarterly_latest needs definitions: first = earliest filed per (cik, concept, period)? A 10-K/A that only adds Part III has no financials; one with full restated financials is a vintage. Specify: which forms create vintages; that 10-K405/10-KSB are out of scope; that comparatives restated in the next-year filing are a vintage (often the real restatement channel); restated_flag and restatement_lag columns; link to 8-K Item 4.02 non-reliance (add to events; the plan lists only 1.03/2.04/3.01/2.01/5.01). Keep acceptance datetime, not just filed date. Confirm that per-fact filed/accn are used, not frames (a legacy frames path is mentioned in facts.py:241).

**FR-6 (High). Financials excluded without a stated rule.**
Define the filter (SIC 6000-6999? REITs 6798, SPACs 6770, holding companies?). Keep excluded firms in universe with exclusion_reason rather than dropping them; consider a second minimal table for banks/insurers. EDGAR SIC is a current assignment, not point-in-time, and differs from Compustat historical SIC; document the source (sic_source).

**FR-7 (High). Units, scale and dei checks are not listed.**
Known XBRL problems: x1000 / x1e6 scale errors, sign errors, wrong decimals, custom tags, dimensional (segment) contexts mistaken for consolidated totals, non-USD units. H3 lists only A = L + E. Add: USD-only filter with flags, QoQ jump tests (over 100x with reversal), shares outstanding from dei:EntityCommonStockSharesOutstanding (cover-page date differs from period end), DocumentFiscalPeriodFocus / DocumentPeriodEndDate vs derived quarter (companyfacts fy/fp describe the filing, not the fact period; the fallback sets them to None). Publish error rates before and after cleaning and a corrections log with accessions, so referees see where cleaning ends and winsorizing begins.

**FR-8 (High). PIT availability dates.**
Filed date is the right information-set date, but keep acceptance timestamp and add known_date (next trading day after acceptance if after close). Compustat rdq is a different object that researchers use; document the mapping. Restated comparatives carry later filed dates.

**FR-9 (High). Fiscal-quarter alignment and Q4 construction need disclosed error.**
Q4 = FY - 9M (verified, METHODOLOGY). Flows are fine; EPS, share counts and quarterly tax cannot be derived by subtraction (EPS differences are wrong when share counts change); a restated 9M propagates into Q4. Snapping 52/53-week years within +/-12 days onto a spine relabels periods: keep original period_end and add company fiscal_year/fiscal_quarter (Compustat FYEARQ/FQTR style) and calendar_quarter. Flag q4_derived, fiscal-year-end changes and 10-KT transition periods, annual-only filers; leave gaps as NaN.

**FR-10 (High). Licence statement.**
CC-BY is fine for SEC facts, but A5 asserts "public domain" without checking the SEC site notice (unverified). Say that derived labels are project work under CC-BY and that users must not redistribute merged Compustat/CRSP files.

**FR-11 (High). Survivorship-free claim and bankruptcy-label recall must be defined and tested.**
Define universe construction (EDGAR index by form and SIC? minimum quarters?). Cross-check yearly counts against the SEC Financial Statement Data Sets (exists; counts unchecked). The 8-K 1.03 label misses firms that stopped filing, pre-2005 events (Item 1.03 begins 2005), prepacks reported otherwise, subsidiary-CIK filers. Measure recall on a hand-checked sample and against LoPucki BRD. T1 labels are also confounded with going-concern opinions and NT 10-K filings; expose a going-concern flag. Delisting returns are out of scope without CRSP; say so.

**FR-12 (Medium). Benchmark design points a referee will raise.**
- Test 2019-2024 includes COVID; report by year and give events per split (train is up to 2016 with a small share of the 475 events, clustered in 2015-16 energy).
- Report base rates per split, top-decile lift, not just PR-AUC.
- Add hazard-model baselines (Shumway 2001), CHS 2008 fundamentals-only variant; note Ohlson 1980 and Altman Z-double-prime are not re-estimated. The benchmark is fundamentals-only (no market data); say it and add a bring-your-own-CRSP hook.
- Justify the CRPS cash-flow task against the earnings-forecast literature (Hou, van Dijk, Zhang 2012; seasonal random walk baseline).

**FR-13 (Medium). Study R framing.**
Report share of firm-quarters whose key fields differ between first and latest, by field, with magnitude distribution, before the AUC effect. Cite Compustat backfill / Snapshot literature. A modest result is still publishable; do not pre-commit to a dramatic headline.

**FR-14 (Medium). Citation and versioning.**
Weekly rebuilds change data under users. Add: dataset_version and build_date in a manifest; Zenodo concept DOI + version DOI; immutable tagged snapshots (weekly builds never alter them); CITATION.cff and dataset BibTeX; data-correction changelog with accessions (the risk table mentions it, H1-H5 do not); separate build date from SEC filed. State the limitation that facts downloaded today are not guaranteed identical to what EDGAR showed then (SEC corrections). Consider a data-descriptor paper in addition to JOSS.

## 3. Missing opportunities

**FR-15 (Opportunity). Replication notebooks for classic research.** Add or substitute for the HN-style list: (1) Sloan 1996 accruals and modified-Jones discretionary accruals, with quarterly cash-flow accruals enabled by de-cumulation (a real edge over annual work); (2) distress: Altman, Ohlson, Shumway, CHS-lite; (3) earnings/cash-flow forecasting in the Hou-van Dijk-Zhang style; (4) restatements and Item 4.02; (5) Fama-French RMW/CMA and gross profitability built PIT to measure look-ahead; (6) filing-lag / NT 10-K analysis. Each reproduces a published estimate.

**FR-16 (Opportunity). compustat_like view.** Wide quarterly table with Compustat-style names (atq, ltq, saleq, niq, oancfy, capxy) and datafqtr-like keys plus known_date, so existing code swaps sources.

**FR-17 (Opportunity). Filer metadata from dei.** Filer category, shell flag, auditor name (dei:AuditorName, recent years only), ICFR attestation, going concern. Standard controls in accounting research.

**FR-18 (Opportunity). Academic-facing positioning.** The stress engine is for risk managers; in academic materials lead with data, validation, bench, and give the model a short assumptions section.

## 4. Concrete plan edits

- Section 0 item 1 (2009-σήμερα) → "full universe from 2011Q2; large filers from 2009"; add coverage-by-year table to dataset card (FR-2).
- Section 0 (χωρίς survivorship) → "survivorship-free for the XBRL era, with documented construction and recall check" (FR-11).
- A5 → add SEC attribution wording checked at source; derived labels under CC-BY; no redistribution of merged Compustat/CRSP files (FR-10).
- H1 universe → cik primary; add cik_ticker_history, cik_history, sic_source, exclusion_reason, filer_category; drop synthetic tilde keys from public schema (FR-1, FR-6).
- H1 facts_vintages → add acceptance_datetime, known_date, company fiscal_year/quarter, calendar_quarter, tag_used, imputed, q4_derived, restated_flag, first_reported_flag, dataset_version (FR-5, 7, 8, 9, 14).
- H1 events → add 8-K 4.02, 4.01, NT 10-K/10-Q, going-concern flag (FR-5, FR-11).
- New H7 → VARIABLES.md + variable_map.csv (Compustat mapping, tags, fill shares); D data dictionary must embed it (FR-4).
- H3 → split: H3a internal checks incl. unit/scale error rates; H3b Compustat validation protocol (500 firm-quarters, match-rate table, script for licensed users) (FR-3, FR-7).
- New H8 → ID recipe/script link_to_crsp_compustat.py, match rate on sample, no redistribution (FR-1).
- H2 → document quarterly_first rule (earliest filed), amendments and comparative-restatement handling (FR-5).
- B1 → events per split, results by year, base rates, Shumway/CHS-lite/Z-double-prime baselines, fundamentals-only statement, BYO-market-data hook (FR-12).
- B0 → also assess label recall vs LoPucki BRD (FR-11).
- R → pre-spec shares of revised firm-quarters by field and magnitude first; cite Snapshot literature; accept a small effect (FR-13).
- D notebooks → replace #5 sector screen with accruals + distress replication; add restatement and PEAD/SUE notebooks reproducing published numbers (FR-15).
- H4/G5 → CITATION.cff, concept+version DOIs, immutable snapshots, correction log, data-descriptor paper alongside JOSS (FR-14).
- Section 3 gates → G2 gate adds "Compustat validation table (or explicit statement it was not done)" and "coverage-by-year published" (FR-2, FR-3).
- Section 7 risks → add "systematic mismatch with Compustat" and "pre-2011 selection bias misused" (FR-2, FR-3).

## Verification status
- Verified: XBRL phase-in dates (SEC small-business guide, Marcum); FORMS includes 10-K/A, 10-Q/A, 10-KT (facts.py:40, xbrl_fallback.py:28); ticker lookup uses current SEC company_tickers.json (edgar.py:115); Q4 by differencing; latest-filing-wins rule (METHODOLOGY section 1).
- Not verified: any public CIK-PERMNO link or its licence; Compustat company table carrying CIK; WRDS-only status of SEC Analytics links; historic ticker/SIC in the submissions API; 8-K 1.03 recall; SEC public-domain wording; literature citations (Sloan 1996, Shumway 2001, CHS 2008, Hou-van Dijk-Zhang 2012, Ohlson 1980) are from memory.
