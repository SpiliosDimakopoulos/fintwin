# Data engineering and data-compliance review of GROWTH_PLAN.md (workstream H, A4-A7, sections 7-8)

Reviewer: data engineer + data-compliance. Date: 2026-10-28. Not legal advice.
Verified against primary sources: HF storage-limits doc, SEC "accessing EDGAR data" page, DuckDB/HF docs (hf:// with @revision and globs), and the repo (LICENSE-DATA, engine/fintwin/data/edgar.py, .github/workflows/*).
Not verified: Kaggle terms (fetch returned no text), FASB taxonomy terms, HF Xet dedup behaviour for Parquet, SEC bulk-archive URLs, exact data sizes (my estimates).

## 1. Blocking problems

**DE-1 (Blocker) H5 super_squash_history contradicts H6 revision pinning and A7 snapshots.**
HF docs: squash is non-revertible, permanently deletes commit history and LFS file history. Any user who pinned a commit SHA (H6), or a paper reproducing from a revision, loses it. It is also unnecessary: HF says degradation starts "after a few thousand commits"; 1-2 commits/week is about 100/year.
Fix: never squash main. One atomic commit per weekly build. Immutable quarterly snapshots = git tag on the HF repo (2026Q4, v1.0.0) plus the Zenodo archive as the permanent copy. Library default revision = a tag recorded in the library release (DE-9). Squash only if commits pass ~2,000, after announcing it and re-tagging.

**DE-2 (Blocker) LICENSE-DATA contradicts A5; one repo-wide licence tag would mislabel third-party data.**
Today LICENSE-DATA says derived data keeps the terms of its source and that MIT covers code only. A5 says data is CC-BY-4.0. HF license YAML is per repo, so every file (macro, S&P membership, Damodaran-derived values) would be labelled CC-BY.
Traps:
- `universe` built from universe_sp500.csv / sp500_*.csv derives from Wikipedia revisions (CC BY-SA 4.0 per LICENSE-DATA item 5). ShareAlike material cannot be relicensed CC-BY, and S&P membership adds a list-ownership/trademark question. Build the ~5,300 universe from SEC data only (company_tickers, submissions, SIC, XBRL filers). No sp500_member column in published data.
- `macro` mixes NBER (attribution only), BEA, Fed H.15: not CC-BY. Ship as a separate config/repo with its own licence, or omit it and ship a fetch script. Philly Fed vintages and BAA10Y stay excluded (section 8).
- Damodaran-derived rating tables: not republished (keep).
Fix: rewrite LICENSE-DATA before G2 with a scope table (path/config, licence, origin); add THIRD_PARTY.md (planned); same table in the dataset card. State: "CC-BY-4.0 applies to FinTwin-created compilation, derived and normalised fields, to the extent any rights exist; underlying SEC facts are public information."

**DE-3 (Blocker) The vintage model cannot answer "as of D" correctly with a date-only filed, and quarterly_first/latest are not enough.**
- Known time must be the SEC acceptance timestamp (acceptanceDateTime in submissions). Filings accepted after 17:30 ET are disseminated next business day; with date-only filed an as-of query can look ahead by up to a day. Store filed (date32) and accepted_at (timestamp UTC) and state the PIT rule explicitly.
- Derived rows (de-cumulated Q4 = FY - 9M, YTD to quarter) are known only when their latest component is: filed/accepted_at of a derived row = max over components, plus derived_from accessions and pipeline_version. The plan has only a boolean derived.
- Do not store a mutable known_to/superseded column in the immutable base table (it changes when a new filing arrives, forcing rewrites of old files). Keep base append-only; compute supersession at query time or in a separately rebuilt derived table.
- quarterly_first and quarterly_latest are two points on the revision axis; users need arbitrary D. Keep them as convenience tables and make the as-of query the documented primitive (DE-19).
- Add a transaction-time dimension: ingested_build (first data release containing the row). Without it a parser fix silently rewrites history; with it users can say "as I knew it in release 2026.43".

**DE-4 (Blocker for CI) SEC fair-access plan for weekly CI is unspecified and current code handles it incompletely.**
SEC page (verified): 10 req/s max, declare User-Agent with contact, automated crawling managed, no stated penalty. Shared GitHub runner IPs are commonly throttled together (unverified for SEC). edgar.py (verified): _MIN_INTERVAL = 0.15 (about 6.7/s, good); retries 429 and 5xx at 5, 10, 20 s; does NOT retry/halt on 403, max wait 35 s. An IP block typically shows as 403 and lasts minutes.
Fix:
- Do not pull 5,300 companyfacts one by one weekly. Use SEC nightly bulk archives (companyfacts.zip, submissions.zip; I know them from experience, the fetched page did not list them, confirm URLs) = 2 downloads. Then fetch filings only for accessions new vs last manifest: hundreds of requests per week instead of thousands.
- 403 = circuit breaker: stop all workers, sleep 10-15 min, retry once, then fail the build (publish nothing). Honour Retry-After, add jitter.
- One global limiter across parallel shards (W1 plans 32 shards; 32 x 6.7/s would exceed 10/s if they all hit the SEC; check that shards read only cache).
- UA must carry a real contact (secret OK; edgar.py already raises when unset, good, so forks fail loudly).

**DE-5 (Blocker for publishing) No publish gate and no rollback procedure.** Section 7 says "corrections in the next weekly build". For a citable dataset a bad build must be reversible in minutes. See DE-12/DE-13; needed before the first public push (G4).

## 2. Important problems

**DE-6 (High) "Partition per year" is ambiguous; by period_end year it hurts as-of queries and weekly updates.**
Recommended for facts_vintages (estimated 50-200M rows including all vintages; my estimate, uncertain):
- Layout facts_vintages/filed_year=YYYY/part-NNNN.parquet (partition by filed year). Past years are immutable; the weekly build writes only the current year (or a delta file, DE-10). As-of D prunes years > year(D).
- Sort within files by (concept, cik, period_end, accepted_at) so row-group min/max stats prune on concept and cik (cross-section). If single-company queries dominate, sort by (cik, concept, ...). Decide with benchmark queries in ADR-002.
- Row groups 256k-1M rows, zstd level 3, dictionary encoding on concept/unit/form/source, page index and statistics on, optional bloom filter on cik. Files 100-500 MB. Never one file per company (HF: <100k files per repo, <10k per folder; breaks viewer and download speed). Keep W5 consistent: thousands of company JSON on HF would violate this; use shards or one Parquet.

**DE-7 (High) dtypes and long vs wide.**
- Long facts_vintages is the source of truth (concepts evolve, custom tags exist; wide would be thousands of sparse columns). Wide tables only for curated documented fields (quarterly_* with ~30-60 canonical fields), generated from long and labelled derived.
- Types: cik int64 (zero-pad only for display; "0000320193" vs "320193" is a classic join bug); period_start/end and filed date32; accepted_at timestamp[us, UTC]; value float64 plus decimals int16 (values up to ~1e13 are exact in float64, limit 2^53 ~ 9e15); concept dictionary string with taxonomy prefix (us-gaap:, dei:, custom); unit dictionary (USD, shares, USD/shares, pure); form/source dictionary; accession fixed 18-char string; fiscal_year/quarter int16/int8. Note SEC fy/fp in companyfacts describe the filing, not the period: keep raw sec_fy/sec_fp and name yours fiscal_*_derived (52/53-week logic).
- No sentinel values; nullable integer types (pandas Int64 or ArrowDtype) to avoid float-NaN corruption of ints. Ship schema.json (column, type, nullability, unit, description, since-version) feeding the data dictionary. Embed Parquet key-value metadata: schema_version, data_release, pipeline_version, source_snapshot_sha256.

**DE-8 (High) HF dataset card configs and viewer.**
Tables have different schemas: each needs its own configs entry with explicit data_files globs, otherwise load_dataset errors on mixed schemas and the viewer breaks. Avoid custom loading scripts (HF doc: such datasets get limited reuse; Parquet keeps the viewer working). Hive-style folders are fine for DuckDB/polars/pyarrow, but do not rely on load_dataset inferring partition columns: keep filed_year also as a real column. HF requires a dataset card and Parquet-friendly formats for large datasets (verified).

**DE-9 (High) H6 hub mode reproducibility defaults.**
Pinning is only reproducible if the default is pinned. Library ships DATA_REVISION = "<tag>" per release; ft.data.update() or mode="hub-latest" is opt-in; every result object records data_release. Use snapshot_download(allow_patterns=..., revision=TAG) per config, verify against manifest.json (DE-11), support HF_HUB_OFFLINE, do not pull all of facts_vintages for one company (use quarterly_* or filtered Parquet reads). Document anonymous download rate limits and optional token.

**DE-10 (High) Weekly incremental vs full rewrite.**
A full weekly rewrite of a few-GB dataset is feasible but every build can silently change history, and whether Xet chunk dedup keeps storage/transfer small for rewritten sorted Parquet is unverified (test with two builds on a private repo in G2 and measure stored bytes).
Recommended: append-only deltas. Weekly job writes facts_vintages/filed_year=2026/delta-<release>.parquet with only new/changed accessions and never touches earlier files; quarterly job compacts the year's deltas (new commit; history kept by tags). Small derived tables (quarterly_*, universe, events) may be rewritten weekly. A parser fix that changes history: bump pipeline_version and schema MAJOR/MINOR (DE-14), rewrite affected years in one commit.

**DE-11 (High) Checksums and manifests.**
H2 has SHA256 manifest only for v1. Make it standard: manifest.json = {data_release, schema_version, pipeline_version, built_at, source archive date + sha256, files:[path, bytes, sha256, rows, min/max filed], row counts per table}; CHECKSUMS.sha256; publish the manifest hash in the GitHub release and Zenodo record. Write manifest.json last in the commit; library verifies after download.

**DE-12 (High) Quality gates before publishing (extend H3).**
H3 lists accounting identity, key uniqueness, vintage monotonicity, 10-Q sample. Add hard gates (fail build, nothing published):
- Schema equals declared schema; no dtype drift; no nulls in non-nullable columns.
- Key uniqueness on (cik, concept, unit, period_start, period_end, accession).
- Row counts never decrease vs previous release per filed_year unless an explicit allow flag; weekly growth within bounds; company count within +-1%.
- Immutability: every row with ingested_build < current is hash-identical to the previous release unless pipeline_version changed (strongest PIT guard).
- accepted_at <= build time; period_end <= accepted_at; no future dates; vintage monotonic per (cik, concept, period).
- Events: only allowed Item codes; string columns on allow-list only (DE-17).
Soft gates (report, human review): identity-violation share, top-N largest weekly value changes, ~50-accession live re-check against SEC. Publish an auto-generated quality report in the dataset card.

**DE-13 (High) Staging and rollback on HF.**
1. Build and validate in CI with no token (artifact).
2. Upload to HF as a PR (create_pr=True) or staging branch; re-download and verify checksums.
3. Merge to main as one atomic commit; guard with parent_commit and the existing Actions concurrency group (data.yml already has concurrency: data, good). Delete merged PR refs (HF doc: refs keep storage).
4. Tag weekly (2026.43) and quarterly (2026Q4).
5. Rollback = new commit restoring the previous tag's files, plus data_notice entry. Never rewrite history. Zenodo: never delete; publish a new version and flag the bad one.
6. main must always be valid; consumers pin tags. Add an incident template and a 24 h target.

**DE-14 (High) Schema evolution and versioning.**
Two identifiers: schema_version (semver: MAJOR = column removed/renamed/retyped, meaning or PIT rule change, restated history; MINOR = new column/table/coverage; PATCH = fixes not changing released rows) and data_release (calendar id per build 2026.43; quarterly 2026Q4). A3 versions only library and paper. Add an auto-generated dataset CHANGELOG (rows added / changed with counts and reasons / removed, parser changes), a data_notice table for corrections, >= 1 minor-release deprecation window for renames, library declares a compatible schema_version range and errors clearly on mismatch. Never reuse a tag.

**DE-15 (High) HF_TOKEN and Actions security.**
Existing workflows are well hardened (actions SHA-pinned, permissions: contents: read default, write only in publishing jobs; verified by grep). For HF:
- Fine-grained token with write access to this one dataset repo only, owned by a dedicated bot/org account with 2FA; rotate every 90 days.
- Environment secret (hf-publish) restricted to main/tags by deployment-branch rules, not a repo-level secret. Required reviewers do not suit a weekly cron, so separate the jobs: build+validate has no token; publish job downloads the artifact and only uploads.
- Guard the publish job with a repository-name check and event_name != pull_request. Fork PRs do not get secrets under pull_request; workflow_dispatch can be run by anyone with write access, so restrict write access.
- welcome.yml uses pull_request_target (verified): safe only while it never checks out PR code. Record this rule in SECURITY.md.
- Pin huggingface_hub via uv lock; never pass the token on a command line; Dependabot for action SHAs.
- A token leak lets someone rewrite HF history: keep Zenodo plus GitHub release manifest hashes as an independent copy.
- Same for Zenodo/Kaggle tokens; test Zenodo on sandbox first.

**DE-16 (High) A7 hosting details.**
- Zenodo: concept DOI plus a version DOI per quarter; the paper cites the version DOI of the v1 snapshot; licence field must match the scope table (DE-2). Check the current per-record size limit (50 GB default as I recall; unverified).
- Kaggle: Kaggle terms could not be fetched; read them yourself (uploader must hold the rights to what is uploaded). Kaggle has a CC-BY-4.0 option but the mixed-licence caveat applies (no macro/S&P). Mirror a curated subset (quarterly_first/latest, universe, events), not the 100M-row long table, and label HF/Zenodo as canonical. Three hosts triple the "which copy is canonical" surface: start with HF + Zenodo, add Kaggle after launch.

**DE-17 (High, privacy) 8-K events must be numeric/categorical only.**
8-K text names individuals (Item 5.02 officers and directors, signatures, exhibits). The planned items (1.03, 2.04, 3.01, 2.01, 5.01) are fine as codes. Enforce by schema, not habit: events(cik, accession, form, item_codes[], filed, accepted_at, period_of_report); no free text, exhibit content, signer or filer-agent names. universe.exit_reason is a controlled vocabulary (acquired|delisted|bankrupt|merged|unknown). status=bankrupt is a derived label, not an SEC statement: document the inference rule and error rate ("algorithmic label, not a statement of fact about any company"). CI test fails on any string column in events not on the allow-list. Put a contact for removal/correction requests in the card. Company names: use only the legal-entity name from SEC registry data (sole-proprietor names can be personal data, rare).

**DE-18 (Medium) CC-BY on facts, EU database rights, attribution, trademarks.**
- Public-domain facts: CC-BY adds nothing enforceable on the facts themselves; CC-BY-4.0 does license sui generis database rights "where they apply" (EU), which covers the compilation. CC0 would be simpler for merging/ML; BY is acceptable and supports the citation goal. Say plainly that downstream users need not attribute the SEC facts as such, only FinTwin compilation.
- Suggested attribution: "Contains data derived from U.S. SEC EDGAR filings (public information), compiled and normalised by FinTwin (Author, Year), DOI, CC-BY-4.0. Not endorsed by or affiliated with the SEC." Provide BibTeX. Add a no-warranty / not-investment-advice disclaimer.
- 8-K-derived labels: fine as facts plus dates; publish the rules; no text.
- FASB US-GAAP taxonomy: concept names fine; do not republish taxonomy labels/definitions without checking FASB terms (unverified).
- Trademarks: A1 avoids "SEC"/"EDGAR" in names; extend to HF repo name, config names and the PyPI headline. Descriptive use ("derived from SEC EDGAR filings") is fine; S&P 500, Compustat, Moody's only descriptively and not in column names.

## 3. Missing opportunities

**DE-19 (Medium) Query recipe.** Put the as-of recipe at the top of the card and docs. DuckDB with a pinned tag (hf:// with @revision and globs is documented, verified):

```sql
INSTALL httpfs; LOAD httpfs;
WITH f AS (
  SELECT * FROM read_parquet('hf://datasets/ORG/fintwin-pit@2026Q4/facts_vintages/*/*.parquet')
  WHERE filed <= DATE '2020-02-15'
    AND concept IN ('us-gaap:Revenues', 'us-gaap:NetCashProvidedByUsedInOperatingActivities')
    AND cik = 815097
)
SELECT * FROM f
QUALIFY row_number() OVER (
  PARTITION BY cik, concept, unit, period_start, period_end
  ORDER BY accepted_at DESC) = 1;
```
Polars: pl.scan_parquet(same hf:// path).filter((pl.col("filed") <= date(2020,2,15)) & pl.col("cik").is_in(ids)).sort("accepted_at").group_by(["cik","concept","unit","period_start","period_end"]).last().collect(). Drop the cik filter for the cross-section. Benchmark single-company and full cross-section on a laptop in G2 and record timings in the card. The date-only filter is a simplification; the real rule uses accepted_at per DE-3.

**DE-20 (Medium) Costs and storage.** HF free public storage is "best-effort"; beyond the first few GB use responsibly; free private 100 GB (usable for the G2 private review); storage grants exist for high-impact open source (all verified). A few-GB dataset with small weekly deltas is fine; avoid weekly multi-GB rewrites and thousands of files. Section 5 "no recurring cost" holds if HF stays at a few GB; add the contingency (PRO or storage grant, Zenodo as fallback). W1 75-80 min/week is the dashboard; budget the dataset build separately and check concurrent-job limits on the free plan (unverified).

**DE-21 (Low) Lineage.** Add source_file_date and a per-row row_hash for cheap release diffs (feeds changelog and immutability gate).

**DE-22 (Low) Sample config.** Publish a small config (e.g. 50 firms) so CI notebooks and first-run tests do not download the full dataset.

**DE-23 (Low) Card sections.** Limitations (survivorship, XBRL era from 2009, small filers phased in 2011), known issues, intended/out-of-scope use, quality report, changelog link, citation.

## 4. Concrete plan edits (section/item -> change)

- A4 -> hub default pins a dataset tag shipped with the library release; latest is opt-in; live mode requires set_identity and obeys the shared limiter and 403 circuit breaker.
- A5 -> "Code MIT. FinTwin-created dataset tables CC-BY-4.0 (to the extent rights exist). Underlying SEC facts remain public information. Third-party series are not in the CC-BY repo (THIRD_PARTY.md)." Add the attribution text (DE-18).
- A6 / section 8 table -> also remove Wikipedia/S&P-derived membership from the published universe (build from SEC data); NBER/BEA/Fed macro in a separate config/repo with its own licence, or a script.
- A7 -> HF (weekly source of truth), Zenodo (permanent quarterly DOIs), Kaggle only after launch as a curated subset. Delete super_squash_history.
- H1 -> replace the year partition with filed_year partitioning, sort order, row-group/file sizes, dtypes (DE-6, DE-7); add accepted_at, derived_from, pipeline_version, ingested_build, row_hash, raw sec_fy/sec_fp; events allow-list (DE-17); quarterly_first/latest become derived convenience tables, the as-of query is the primitive.
- H2 -> manifest in every release, written last; SEC bulk-file date and sha recorded.
- H3 -> adopt DE-12 hard/soft gates incl. immutability; publish quality report.
- H4 -> configs per table with explicit data_files; limitations, privacy, licence-scope table, attribution, citation, versioning policy.
- H5 -> rewrite: weekly incremental delta build, validate (no token), HF PR, verify, merge, tag; quarterly compaction + Zenodo version; no squash; token in environment with separate publish job (DE-13, DE-15); SEC bulk archives + 403 breaker (DE-4); rollback runbook and 24 h target.
- H6 -> pinned default tag, per-config allow_patterns, checksum verification, offline mode, results record data_release.
- New H7 -> dataset changelog and semver policy (DE-14), data_notice table.
- Section 7 -> add risks: bad weekly build (staging + rollback); HF token compromise; SEC IP block from CI; squash breaking pins; licence contamination (CC BY-SA, NBER); personal data in 8-K; HF storage policy change (Zenodo copy). Replace "corrections in the next weekly build" with "rollback within 24 h plus notice, then corrected build".
- Section 8 -> add rows for Wikipedia (CC BY-SA 4.0, excluded), Damodaran (not republished), FASB taxonomy (names only).
- LICENSE-DATA -> rewrite per DE-2; fix item 1 (the 0.15 s interval is right, but 403 handling is missing).
- G2 gate -> add Xet dedup experiment, as-of query benchmark, rollback drill, token scope audit.

Sources: https://huggingface.co/docs/hub/storage-limits ; https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data ; https://duckdb.org/docs/lts/core_extensions/httpfs/hugging_face ; https://huggingface.co/docs/hub/en/datasets-duckdb
