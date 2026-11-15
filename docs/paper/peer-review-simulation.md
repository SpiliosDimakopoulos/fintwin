# Mock peer review: "Does Simulation Add Information Beyond Persistence?"

Date: 2026-10-23 · Manuscript: `docs/paper/fintwin.pdf` (24 pages, revision branch) · Reviewer persona: referee for an
empirical finance / forecasting journal (e.g. International Journal of Forecasting, Journal of Banking & Finance).

**Package status.** Only the manuscript exists. There is no paper-finalizer package (no target journal, cover letter,
title page, declarations or checklist) and no manuscript-dev-log. This review therefore covers the manuscript only;
submission compliance could not be reviewed.

## Step 1: Referee report (Persona A)

**Overall: Major Revision.** A fresh search found no close published competitor (originality holds). The weaknesses
are in the central result.

### Fatal issues
None.

### Major issues
1. **§6.2 / Table 3: the encompassing regression is restricted.** The dependent variable and every regressor are
   departures from N1, so N1's noise enters all of them with the same sign, and N1's weight is restricted to 1 − Σb.
   This is Lekakos's objection in regression form. The standard unconstrained Fair–Shiller regression in levels was
   missing.
2. **§6.3 / Table 4: the hybrid lacked combination-puzzle controls.** Any second, noisier forecast blended with a
   small weight lowers the error (Bates & Granger 1969; Smith & Wallis 2009). N3+N6 was the only control; N3+N1,
   N3+N2 and N3+N5 were missing, and so was the literature.
3. **Abstract / §6.3: the headline "3.5%" was chosen after the results.** It came from a hybrid built on N3, chosen
   after N3 turned out to be the best rule; the pre-specified hybrid was built on N1. The manuscript did not disclose
   this.
4. **Framework §2.4 and §5.1 overclaimed pre-registration.** "For each hypothesis the decision rule was fixed..."
   is true only for H2. The "earlier draft" of the rule was never committed, so it cannot be verified.
5. **The title overclaimed.** "Every Non-Financial SEC Filer" is false: the sample is US-GAAP filers with $50M+
   revenue and 16 quarters of history.
6. **§3.3: the bankruptcy census was not validated.** Item 1.03 was described inaccurately: it is also filed at plan
   confirmation. There was no recall check and no discussion of measurement error.
7. **The outcomes of H1–H3 were never stated explicitly.**

### Minor issues
- `references.bib`: Lyytinen et al. is 2024, vol. 13(3), not 2023 (checked on IDEAS/RePEc).
- Framework: the IMF WP/20/238 description "static or one-period cash-flow rules" is not supported. The paper
  projects net income, funding availability and debt service.
- Conclusion and Discussion said "a sixth", but λ is 0.10–0.15.
- Ford/GM example: "reported operating cash flow rose" was inaccurate; it exceeded the rule's prediction.
- §10: the 75-day reporting lag for conformal was not explained.
- §5.3: clustering is by firm only; cross-sectional dependence within a year was not discussed.
- Leftovers: `SUBMISSION.md`, `abstract.txt`, `.zenodo.json`, README, `findings.png`, the evidence page and the CV kit
  carried the old title or the uncaveated "3.5%" claim. The data-audit sentence is missing because the audit has not
  finished.

### Citations re-verified (fresh searches)
Kritzinger et al. 2018 (model/shadow/twin taxonomy) ✓ · Fair & Shiller 1990 AER 80(3):375–389 ✓ (the
regression-on-two-forecasts method is as attributed) · Gibbs & Candès 2021 NeurIPS ✓ · Fama & French 2000 (mean
reversion ≈38%/yr) ✓ · Dechow–Kothari–Watts 1998 JAE 25(2):133–168 ✓ · IMF WP/20/238 ✓ (characterization corrected)
· Lyytinen et al. ✓ (year corrected) · Smith & Wallis 2009 OBES 71(3):331–355 ✓ (Crossref) · 8-K Item 1.03 usage ✓
(also plan confirmations).

## Step 2: Fixes (Persona B)

| # | Fix | Status |
|---|---|---|
| M1 | Added the unconstrained levels encompassing regression to the code (`transmission.encompassing`), the GitHub run, Table 3 and the text. Twin coefficient 0.23, t = 9.5 (FCF: 10.7). | **Resolved.** The result holds. |
| M2 | Added combinations N3+N1, N3+N2, N3+N5 and N3+T0 with paired CIs (Table 4), plus the Smith–Wallis citation. **The finding changed:** for operating cash flow, N3+N5 reaches 12.49 vs 12.45 for N3+T1 (p = 0.30). Only for FCF does the twin beat every simple combination (0.21 pp, CI 0.05–0.37). The abstract, introduction, §6.3, discussion, conclusion, README, site, CV kit and response letter were rewritten to match. | **Resolved.** The claim is weaker and now correct. |
| M3 | Disclosed in §5.1 ("Specifications added after the run"). | **Resolved.** |
| M4 | Framework now says the rule applies to H2 only; §5.1 says the earlier draft was never committed. | **Resolved.** |
| M5 | New title: "...Tested on a Survivorship-Free Panel of SEC Filers" (paper, abstract, Zenodo, SUBMISSION). | **Resolved.** |
| M6 | §3.3 now describes Item 1.03 correctly. Census recall: 33/35 of the known 2020 filers; 63% of firms have several 1.03 filings; measurement error is acknowledged. | **Resolved.** |
| M7 | New paragraph "The hypotheses": H1 rejected, H2 accepted with small magnitude, H3 partly supported. | **Resolved.** |
| minor | Lyytinen year, IMF wording, λ wording, Ford/GM, conformal lag, clustering caveat, stale metadata, findings figure (now shows the regression combination) | **Resolved.** |

## Step 3: Re-check of the changes
- The abstract, §6.3, the discussion and the conclusion now say the same thing (checked in the compiled PDF).
- Table 4 and the text agree: FCF −0.21 [−0.37, −0.05]; CFO vs regression −0.05 [−0.14, 0.04].
- Three new problems introduced by the fixes were found and corrected:
  - a duplicated sentence in §5.3;
  - an opaque label "N5 + change in revenue" in Table 2;
  - the negative 4-quarter weight in the levels regression, now explained as mean reversion.
- The compile is clean: 24 pages, no errors, no overfull boxes.
- The claim "presumably because the twin models capital expenditure" is labelled as conjecture. It remains untested
  and is a candidate for a future check (decompose the FCF gain into CFO and capex).

## Genuine blockers (need something external)
1. **No submission package.** Run paper-finalizer once a target journal is chosen: cover letter, declarations
   (COI, funding, data availability, CRediT), the journal's format and length.
2. ~~Data-audit numbers~~: added to §3.1 after workflow run 39849497834 finished (1,043 → 748 gaps; 87% of
   panels end at the last filed quarter; the mismatches come from SEC companyfacts lag and untagged revenue,
   verified by hand on HCA, Coca-Cola, Semtech and Garmin). **Still open:** a fallback parser for filings
   missing from companyfacts.
3. **Acknowledging the commenting researchers by name** needs their permission.
4. **SSRN posting** is the author's decision.

---

# Round 2 (referee round on the revised paper)

## Step 1: Referee report (Persona A, independent subagent)
**Overall: Major Revision.** Findings: F1 the H1/H3 decision rules were written after results; F2 H3 "accepted"
against a comparator (twin without loops) that never produces cash depletion (AUC 0.50); F3 the 0.22 incremental
statistic needs CIs against the shrunk margin and the timing regression; F4 the FCF claim fails a Holm correction;
F5 the exposure regressions need industry clustering, a no-simulation control and decomposition language. Major:
walk-forward look-ahead (logits trained up to Y−1); the transmission test conditions on survival; "petitions"
counted every Item 1.03 filing; numbers from different samples looked inconsistent; the data-audit macros were 0 and
the 98% data target was not met; 75-day conformal lag; the revised specification was informed by the sensitivity
analysis; the 2020 outcome was a worst-point drawdown; firm-only clustering; many overstatements; current SIC/GICS
and restatements; literature gaps. Minor: thousands separators, citation contexts (Smith–Wallis cited for combination
gains; Fama–French 2000 cited for "margins"; Fama–French 1997 for the FF12 definitions), referee mentions in the text.

## Step 2: Fixes (Persona B)
- Code, rerun on GitHub (research 39967917290, Sobol 39967924725, audit 39957502187): logits trained on cutoffs up
  to Y−3; first Item 1.03 filing per case (420 firm-years at 238 companies); cumulative 2020 FCF; 90-day lag;
  two-way clustered encompassing and Harvey–Leybourne–Newbold tests; industry-clustered exposure and episode
  regressions with the health formula as control; attrition and inverse-probability weighting; 4-quarter bankruptcy
  horizon; Sobol reference point at the specified values; CIs for the twin against N4 and N6.
- Text: abstract, introduction, discussion and conclusion now say "information in sample, no reliable gain out of
  sample"; H1/H3 declared descriptive; H3 verdict qualified as mechanical; FCF result "suggestive, not established";
  exposure and episodes called a decomposition; sample of each differing number stated (revised spec on 2018–2024,
  AUC on the transmission sample); attrition paragraph; audit numbers and the unmet 98% target; current SIC/GICS and
  restatements; February cutoffs; 403 non-financial S&P members; 18 new verified references (forecast combination
  and encompassing, cash-flow prediction, ML distress models, OECD stress test, DT-in-finance work flagged as
  practitioner or preprint); citation contexts corrected; referee mentions removed; thousands separators.
- README, site summary, CV kit, response letter and message drafts updated to the new numbers.

## Step 3: Re-check of the changes (independent subagent)
Nine problems found in the revised text and all fixed: a `\ref` destroyed by a Python escape; the introduction
attributed cash depletion to two loops (only R2 produces it; B1 produces payout and capex cuts); the 4-quarter
margin's levels weight is near zero, not negative; the Holm sentence was not scoped to FCF; λ range for FCF is
0.10–0.20; the "boundary of the grid" wording; 35 vs 27 legacy filers; the 2020 numbers in Table exposure and
Table episodes differ by design (now explained); a t-statistic range mixed clustered and unclustered values.
Compile clean, 31 pages.

## Genuine blockers (round 2)
1. No submission package (no target journal yet; SSRN only, by the author's decision).
2. Data target: the last panel quarter matches the last filing for 90% of companies, not 98%; disclosed, not fixed.
3. Naming the commenting researchers needs their permission.
4. The OECD reference (Roulet 2020) is the closest match found, not confirmed as the intended source.

---

# Round 3 (IJF two-pillar version, v3.0.0; 15-11-2026)

Package reviewed: `fintwin.pdf` (rev3, 39 pages before this round), `fintwin.tex` + sections + tables, `highlights.txt`,
`abstract.txt`, `SUBMISSION.md`, the Elsevier declarations inside the manuscript, `docs/REVISION_PLAN_3.md` and the git
history. **There is still no paper-finalizer package:** no cover letter, no separate title page, no submission checklist,
no manuscript-dev-log. Compliance was therefore checked only against what the manuscript itself contains. The
official IJF Guide for Authors could not be fetched (HTTP 403), so the abstract and keyword limits are unverified.

Method: a self-review alone is not enough, so this round used three checks. (1) An independent referee subagent read
the compiled text and the repository with no access to my conclusions. (2) A separate subagent re-verified the
citations against Crossref and RePEc. (3) I checked the git history by hand. Every claim from the referee subagent
that is kept below was checked against the files.

## Step 1: Referee report (Persona A)

**Overall: Reject in its current form at IJF.** The reason is structural (A4, A5), not a matter of wording.

### Fatal
- **A1. The pre-specification could not be verified.** §5.1 cited commits 70c4b17, 6d5ea9c, 6ca96b7, c1f3d1e, ab47c5d
  and 5ca86d2. None of them is in the published history; after git-filter-repo they exist only in the local
  `backup/rev3-before-scrub`. The abstract said "committed to a **public** repository before the runs", but `rev3` was
  first pushed on 15-11 at 13:59, after the full run of 13–14 November. Git dates are set by the committer, and there
  is no third-party timestamp. The rewrite also changed two words of the plan (a commenter's name became
  "a referee").
- **A2. A third, undisclosed supplement.** `RERUN5_SUPPLEMENT.md` (da78dd5, 12-11) contains analysis choices: the
  decisive B2 cell, the one-sided B1 test, common firm-years for walk-forward, and the W6a/W6b passes. They came after
  the dry-run statistics, which breaks the plan's own rule. The supplement admits that the year-block CI covers only
  about 85–88% and promises a firm-block CI, which the paper does not report. The paper said "two supplements".
- **A3. Undisclosed data changes made after the dry run.** The zero-revenue tag fallback, Q4 from the same vintage
  (CFO in 289 and capex in 205 of 899 companies), missing short investments set to 0 (about 23% of cash forecasts),
  and a bound on log growth. All of them change the realized outcomes.
- **A4. Almost no genuine ex-ante forecast.** Pillar A and the density test receive the realized revenue. The
  decisive B2 cell scores a Recession-conditional probability against unconditional outcomes. The only ex-ante
  forecasts are the AUCs, where simulation adds about 0.003.
- **A5. The contribution is too small for IJF.** It is a negative result about one in-house simulator, which is
  expected given Fama–French (2000), and there is no second model to make the paper about the protocol.

### Major
B1 "pre-specified" overstates what was fixed in advance (§5.1, title) · B2 "earlier attempts … produced no
statistics", whereas the supplement speaks of a quarantined run of 11/12-11 (§5.1) · B3 the limitation on
winsorization looks like a contradiction with supplement S4 (§9) · B4 the v3 components differ between the plan and
the paper (F9, M1–M4; M3 undefined) (§4.3) · B5 the H2 rule has no discriminating power: it also passes for v2-pre
(§6.3) · B6 two two-way t-statistics (8.4 against 7.3, the latter non-PSD), so which one is pre-specified? (§6.3) ·
B7 the advice "shrink with weight 0.2" is unsafe given forecasts of 1.95M pp (§9) · B8 the abstract rested on the
median-loss MCS, where there is no gain; the mean-loss MCS is not reported · B9 inference with 8–11 year clusters
(wild-cluster or randomization inference is missing) · B10 scaling by trailing revenue plus the F3 misfire make the
means and the CRPS hard to interpret, and "revenue close to zero" sits oddly with the $50M screen · B11 the density
rivals are weak by construction (pooled, homoskedastic) · B12 the shortfall label is weak (Item 3.01 dominates; a
15% base rate); recalibration and a cleaner label are missing; the 1,295/1,539 counts come from another sample ·
B13 survival conditioning: only 15% of firm-years before a petition qualify; the IPW model is not specified · B14
look-ahead not quantified (NBER, scenario design, current SIC, restatements, the small-firm sample selected on the
future) · B15 which years each test uses is unclear · B16 "the corrections were bug fixes", yet F1 and F3 are
re-specifications · B17 legacy appendix material (S&P 500 sample, "prior weight 0.5/8", AUC 0.81 against 0.87) ·
B18 the earlier evaluation is used throughout but never cited, and 460cdda came after v1 results · B19 the competing
interest is undeclared (the author develops FinTwin).

### Minor
C1 "improves … by only 0.017" (that number is a skill score) · C3 the type of p-value is not labelled · C4 5,219
against 5,309 unexplained · C5 the 98% target is not in REVISION_PLAN_3 · C7 Union Carbide 2019 has v2-pre = 8 ·
C8 counts from different samples (403/341, 1,651/1,766, 21,075/19,266) · C9 Z against Z'' · C10 "within 20–25%",
"overshot" · C11 the elasticity has no CI · C12 t = 2.0 against the "above 2" rule; verdicts given to descriptive
hypotheses · C13 an ambiguous "it" (70% threshold) · C14 the co-registrant pass is "unchanged" with no numbers ·
C15 "weekly, automatic" against quarterly inputs · C16 S1 continuity line and Sobol N 311 against 320 · C17 the
4-quarter base is not reported first · D1 artifacts: "Appendix Appendix" (x4), ".." in 10 headings, "p =<0.001",
"sSRN", "Kenneth r. french" · D2 repository jargon (v2-pre, F1–F14, digests) · D3 B1/B2 label clash · D4 notation
(base revenue B, pi, lambda against w, the scale of tau) · D7 Table 1 rates FinTwin favourably before any evidence ·
D8 Wikipedia as a source · E1 the abstract was 257 words · E3 SUBMISSION.md had a different title and keywords · E4
no postal address · E6 the concept DOI was cited instead of the version DOI · E7 Appendix B should be a separate
supplementary file.

### Citations (fresh verification, Crossref/RePEc)
No wrong entries were found. Confirmed: romano2005, hansen2011, hansen2005, clark2001 (nested models; the theory
assumes quadratic loss), fair1990, cameron2011, murphy1973, gneiting2007b, diebold1995, harvey1998, chong1986,
bates1969, clemen1989, timmermann2006, claeskens2016, fama2000, kritzinger2018, grieves2017, tao2019, altman1968,
ohlson1980, zmijewski1984, shumway2001, campbell2008, roulet2020, imf2020, hou2012 and others. Notes:
- Missing: Diebold–Gunther–Tay 1998 (PIT).
- 23 bib entries are uncited; BibTeX ignores them.
- altman1995 is marked "from memory" and is uncited.
- bhatia2026 exists as an SSRN entry and was not read.

Originality: openfundex (HF, v0.7.0) is a dataset of scores and targets, and its own card puts missing bankruptcies
at about 21%. It has no simulator and no persistence benchmark. Nothing closer was found, which is a negative result
of a search, not proof.

## Step 2: Fixes (Persona B)

| # | Fix | Status |
|---|---|---|
| A1 | §5.1: new paragraph "How far the record can be verified" (private repo until 15-11, no external timestamp, rewrite of the history, two words changed); the published hashes b7d8c8e, ba2f629, e3c399b, cfadfba, 86da9e3, 333079c; abstract "public repository" → "project repository … and list every later deviation"; intro and data availability updated | **Partly.** The hashes and the disclosure are fixed. Verifiability cannot be fixed retroactively (blocker 1) |
| A2 | §5.1: three supplements; the third (da78dd5) with its analysis choices; states that the plan's rule was broken; CI undercoverage; the firm-block CI not reported | **Resolved** as disclosure. The firm-block CI is still not computed |
| A3 | §5.1: the four data changes, with their size | **Resolved** |
| A4, A5 | Not fixable by text | **Open, structural** |
| B2 | Run of 11–12-11: outputs set aside, only integrity checks read | **Resolved** |
| B3 | §9: S4 moved the combinations to training-year limits, not these p-values | **Resolved** |
| B5 | §6.3: the rule passes for v2-pre as well and has little power | **Resolved** (text) |
| B7 | §9: the weight-0.2 advice holds only after explosive forecasts are bounded | **Resolved** |
| B8 | Abstract: MCS removed ("not significant under median loss, reverses on raw loss"); §9 says the mean-loss MCS is not reported | **Partly.** The mean-loss MCS still needs a run |
| B16 | §9: "most were bug fixes; F1 and F3 re-specified the cost model" | **Resolved** |
| B18 | New entry `dimakopoulos2026` (Zenodo v2.0.0, 10.5281/zenodo.23603030), cited in the intro, the framework and §5.1; 460cdda came after the S&P 500 transmission results of v1 | **Resolved** |
| B19 | Competing interest: the author develops and maintains FinTwin and its site | **Resolved** |
| E6 | Version DOI 10.5281/zenodo.24249768 (v3.0.0) plus the concept DOI, explaining that later versions change numbers | **Resolved** |
| E1 | Abstract 257 → 242 words | **Partly.** The IJF limit is unverified |
| E3 | SUBMISSION.md: title, keywords and JEL match the manuscript | **Resolved** |
| C1, C3, C4, C7, C10, C12, C13, C14 | Brier skill wording; Romano–Wolf p labelled; "companies whose filings the audit loaded"; Caleres/Union Carbide by year; "0.8 and 1.25 times"; "overcorrected"; H1 "not supported … descriptive", H3 "rule written after its first results"; episode t-statistics to two decimals (2.04, 4.04, 4.60, via `research_assets.py`); 70% threshold unambiguous; co-registrant pass "not reported" | **Resolved** (C14 as disclosure) |
| D1 | `\ref` instead of "Appendix~\ref"; trailing periods removed from 10 headings; new macro `GainDmPrel` in `rev3_assets.py` (fixes "p =<0.001"); {SSRN}, {Kenneth R. French} in the bib | **Resolved** |
| — | Diebold–Gunther–Tay 1998 added (verified on Crossref) and cited with the PIT | **Resolved** |
| — | Overfull boxes (tails table, OECD URL) | **Resolved**: 0 overfull, 0 undefined, 40 pages |

## Step 3: Re-check
- The compiled §5.1 was read again. The new text does not contradict the tables: the 4q Recession cell has 9 blocks
  against 8, and the supplement figures (289/205/899, 23%) match the source.
- One new problem was found and fixed: data availability cited §5.1 twice. The "Exploratory additions" bullet
  repeated the supplement bullet and now refers to it.
- The regenerated numbers files differ only in the intended macros (EpiTRobust x3, GainDmPrel). The figures were
  restored to the committed version. The paper-related tests pass (10 passed, 1 skipped).
- Not re-checked: whether all 19 MCS forecasters are listed anywhere (B8), and the Table 1 hyphenation (D1). Both
  remain on the list.

## Still open
**Genuine blockers:**
1. **An external timestamp of the plan cannot be created retroactively.** If the plan was sent to the commenting
   researchers before 13-11, that is a third-party witness, and only the author knows. For v3.1, timestamp the plan
   (OpenTimestamps or Zenodo/OSF) before the run.
2. **Author's postal address and country** (Elsevier). The TODO remains at `fintwin.tex:31`.
3. **IJF limits for the abstract and keywords** must be checked on the official guide; it could not be fetched.
4. **The paper-finalizer package** is missing: cover letter (covering duplicate publication, given Zenodo v2), title
   page, checklist, and Appendix B as a separate supplementary file.

**Structural (new analysis, so paper-execution-planner first):** A4 genuine unconditional forecasts (revenue forecast
too) and a prospective hold-out from the weekly archive; A5 a second model under the same protocol, or a reframing
as a protocol/data paper; B10 a scale-robust outcome; B12 recalibrated shortfall probabilities and a cleaner label;
B9 wild-cluster/randomization inference; B8 the mean-loss MCS in the text; B14 quantifying the NBER look-ahead; B11
stronger density rivals. Each of these counts as a new, post-hoc specification and has to be declared as one.

**Other open items, deliberately left:**
- B4, B6, B13, B15, B17.
- C5, C8, C9, C11, C15–C17.
- D2–D4, D7, D8.
- The title word "Pre-Specified" is the author's decision. After the new disclosure, "with committed decision rules"
  is the safer wording.
