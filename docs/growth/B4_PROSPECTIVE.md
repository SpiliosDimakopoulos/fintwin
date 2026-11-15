# B4: prospective track (design, 1 page)

Status: enabled on main (workflows predictions-archive.yml and ots-upgrade.yml); the chain starts with the first manual run (first_week=true). Plan item B4 (GROWTH_PLAN section 3-B), related ADR-003 sections 3 and 7.

## Why
Every historical benchmark can be accused of look-ahead. A score committed *before* the outcome cannot. Each week we
do not archive is lost for good, so the mechanism is small: one script, one release per week.

## What is archived (weekly)
Release `predictions-YYYY-WW` with four assets:
- `predictions_<week>.parquet`: one row per company with a CIK (~392 today), sorted by cik, fixed schema
  (`SCHEMA_VERSION` in `engine/scripts/archive_predictions.py`). Columns: identity and provenance (cik, ticker, `asof`
  = data cut-off, `last_quarter`, `built_at_utc`, git SHA, engine version, `data_release` YYYY.WW); model scores
  (`p_breach_4q/8q/12q`, `health_score`, `p_icr_below_1_5`, `p_downgrade_below_ig`); committed baselines
  (`base_rate_4q/8q`, `bl_runway_risk`, `bl_icr_risk`, `bl_leverage_risk`). `p_breach_12q` is null if the build lacks
  12 quarters; there is no fallback. Altman Z'' is not archived (no total assets in the dashboard files); adding it
  is a schema bump, never an edit of past weeks.
- `manifest_<week>.json`: SHA256 of the parquet, rows, git SHA, data_release, per-column target declaration, the frozen
  base rates, the tree hash of all input files, the SHA256 of the input zip, `prev_week` / `prev_sha256`.
- `inputs_<week>.zip`: the exact input files (the Actions artifact expires after 90 days).
- `manifest_<week>.json.ots`: OpenTimestamps proof of the manifest hash.

**Targets.** `p_breach` is a *liquidity-floor breach* probability, not bankruptcy. It is scored rank-only (PR-AUC,
ROC AUC) against distress labels; no Brier or log score unless a separately declared mapped probability is added.
**Base rates (T1 only).** `base_rate_t1_4q/8q` is the historical 8-K Item 1.03 rate per firm-origin within h quarters,
computed from `engine/fintwin/data/universe_edgar.csv` (5,309 firms, `bankruptcy_8k` = 1.03 dates). Stratum: the firms
whose CIK is in the current dashboard index (390 of them in the file); the all-universe rate is stored beside it.
Unit: (firm, quarter-end origin 2012-03-31..2024-12-31) with the firm active, 91*h-day window, origins with a 1.03 in the
previous 730 days excluded, origins whose window ends after the 2026-10-31 data cut dropped. Today: stratum 4q 0.080%
(15 / 18,809), 8q 0.174% (32 / 18,419); all-universe 4q 0.82%, 8q 1.78%. Caveat: the stratum is today's survivors by
selection, so it likely understates a live roster's rate; the manifest keeps numerator, denominator, period, the
definition text and the CSV's SHA256. The file has no 2.04/3.01 dates, so **T2a has no committed reference yet**. The
earlier ICR-implied rating-D rate (~10x too high: transient negative-EBIT quarters, survivor-only histories) is kept
only as `diagnostics.icr_d_proxy_rate` in the manifest and is not a baseline. The empirical 8-K rate is printed beside
the committed one at scoring.

## What proves the timing (and what does not)
Not evidence: `built_at_utc` (self-declared), the release `created_at` (the tagged commit's author-settable date), the
lightweight tag. Evidence: (1) release `published_at` (server-side); (2) the OpenTimestamps (Bitcoin-anchored) proof, which
does not depend on GitHub, needs no identity token and no extra permission, so it was chosen over Sigstore/Rekor
(`ots stamp` in the release job; the proof is pending at first and `ots upgrade` completes it later); (3) the hash
chain: each manifest holds the SHA256 of the previous week's manifest, so a deleted or back-filled week is detectable
(`verify_chain`; the first week has `prev_sha256 = null` and says so). The workflow refuses to start a new chain unless
told `first_week=true`, and refuses an existing tag.

If the stamp fails the release is still created, its notes say "published_at only", the job emits a warning and a
separate job opens an issue labelled `ots-missing`. Manual stamping: download `manifest_<week>.json`, run
`ots stamp` on it, upload the `.ots` to the `ots-upgrades` release (a late stamp proves only the later date). Upgraded
proofs (`ots upgrade`, once Bitcoin has confirmed) also go to that separate append-only `ots-upgrades` release; the
draft `ots-upgrade.yml` does this monthly and never replaces an uploaded proof. `ots` is installed pinned
(`opentimestamps-client==0.7.2` via `uvx`); replacing this by a hash-pinned requirements file is a maintainer TODO.

Repository settings (maintainer): Settings > Rules > Rulesets > New **tag** ruleset "predictions tags", Active, target
`predictions-*`, rules Restrict deletions, Restrict updates, Block force pushes; Restrict creations OFF (the
workflow creates tags); empty bypass list. Also enable "Immutable releases".

## Calendar and frozen rounds
Weekly after the Monday 06:00 UTC `data` run, labelled by ISO week of `asof`. A missed week stays missing; it is never
back-filled. A **round** is a calendar quarter. **Expected-week rule:** the official archive of a round is the earliest
archive whose `asof` falls in the first 14 days of the quarter (any 14 days hold two Mondays, so there are two chances).
If there is none the round is **VOID**: no fallback to a later week, because that would let the origin be chosen by
omission. Its companies are the frozen universe. `--round` requires `--exits` (otherwise acquired firms count as
survivors). Every other week is scored only with `--week` and labelled DIAGNOSTIC.

## Scoring (`engine/scripts/score_predictions.py`, skeleton)
Verifies the SHA256 and the chain, then follows ADR-003 section 3: per-row status event / survived /
exited_non_distress / exited_unknown; primary set = event + survived; firms acquired, merged or deregistered in the
window are not negatives; rows with a 1.03 in the 730 days before `asof` are excluded; counts per status are
printed. T1 = Item 1.03; T2a = 1.03, or 2.04/3.01 not accompanied by 2.01/5.01 in the same 8-K (labels carry
accession and items). Horizons 4 and 8 quarters, window not elapsed means refused.

## What we will and will not claim
Will: "these scores were committed before the outcomes, with this hash and this external timestamp".
Will not, in year one: any ranking, "beats a baseline", or calibration claim. About 392 large caps give roughly 0-2
8-K 1.03 events a year (the 5,300-firm universe gives ~25-30), so year-one metrics are often undefined and always
come with event counts. Never edit, re-fit or delete an archived week.

## Needs the maintainer
1. Merge to `main`; enable the workflow (draft); first run via `workflow_dispatch` with `first_week=true`.
2. Create the tag ruleset and enable Immutable releases (above); verify one release by hand (`ots verify`, sha256).
3. Archive the dashboard universe only, or also the full ~5,300 universe from the server pipeline (needed for a
   meaningful event count)?
4. pyarrow policy: pinned `--with pyarrow==26.0.1` now, or an optional dependency group at v3.0.0.
5. ADR-003 amendment before the first scoring: round freezing and the 14-day rule, the label rules, the T1 base-rate
   stratum (dashboard firms; or a size stratum instead), and that T2a has no reference yet.
6. Create the `ots-upgrades` release once; review and enable `ots-upgrade.yml`; hash-pin `ots`.
