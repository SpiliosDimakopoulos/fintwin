# OSS growth review of GROWTH_PLAN.md (2026-10-28)

Reviewer stance: open-source maintainer / DevRel. Evidence read: GROWTH_PLAN.md, README.md, ROADMAP.md, CONTRIBUTING.md, and read-only `gh` output (repo view, issues, labels, PRs, community profile).

Not verified (marked "verify"): competitor star counts and HN-study figures quoted in the plan; whether HF `super_squash_history` breaks commit/tag pins; JOSS eligibility rules; whether another project already uses the name "FinTwin"; awesome-list acceptance rules.

Repo facts seen: 4 stars, 8 forks, 20 topics (including `hacktoberfest`), community health 100% (CoC, CONTRIBUTING, PR template; only bug and feature issue templates). 12 of the 14 most recent merged PRs are Hacktoberfest-style tests/docstrings from one-off contributors, all merged 25-26 Oct; nothing since. Open issues #33-#44 were created by the maintainer within about 2 minutes (research ideas); only 2 issues carry `good first issue` (#15 unit tests, #24 glossary).

Diagnosis: the PIT dataset is the real asset, but the plan sequences six products behind a library refactor into one big-bang launch, relies on a hook (look-ahead bias) not yet shown to be large, and the first-run surfaces (README, install weight, name) currently sell the weakest part of the work (the twin).

---

## 1. Blocking problems

### OG-1 (Blocker) Six deliverables, one maintainer, one launch date
Library + HF dataset + benchmark with CI leaderboard + 5,300-page SEO dashboard + MCP server + docs site + 6 notebooks + JOSS/pyOpenSci, all gated into one G5 launch on a roughly 6-8 week estimate. Agents remove typing time, not review time: every merge, schema decision, data audit and ADR approval is the one human's, and the same human must be online 8-12 hours for HN/Reddit replies. The G4 "3 fresh reviewers" are agents reviewing agent output, which is not independent. Likely outcome: a slipped launch, or six half-polished surfaces, any of which can be the top HN comment.
Fix: define a minimum lovable product and gate the launch on that only (OG-2).

### OG-2 (Blocker) No minimum lovable product; the dataset is the MLP, not the library
A visitor must be able to do this in 60 seconds: get PIT fundamentals for a company and date and see how they differ from "latest" data. That needs (a) the public HF dataset with a good card and viewer, (b) a tiny read-only loader (or just documented `pd.read_parquet("hf://datasets/...")` snippets), (c) one notebook (the look-ahead study). Defer everything else: MCP, SEO pages, Kaggle mirror, leaderboard CI, prospective scoring pages, mkdocs site, pyOpenSci/JOSS, CLI, `twin().stress()` in the new API.

### OG-3 (Blocker) The hook is unproven and there is no go/no-go on it
"Look-ahead bias in naive backtests" is a known idea (every Compustat PIT user knows it). It lands only if the numbers are surprising and concrete: share of firm-quarters revised, median revision size, AUC inflation, number of firms lost to survivorship. If AUC inflation is 0.005 the post is flat and a quant-heavy HN audience says "known". The plan pre-specs study R (good) but schedules it in G2, after the library. Run a cheap version first (one day on the burst server, frozen snapshot) as the go/no-go that decides the headline. If the effect is small, the hook becomes "free, as-first-reported, includes delisted and bankrupt filers, fully reproducible" and the title changes. Is it the right hook? Probably a good second sentence, not a first one; the first is "free and PIT".

### OG-4 (High) First 60 seconds cannot work as specified (L1/L4/L6/A3)
- Core deps include statsmodels, scipy, requests: data users pay install and import cost for model code. Core should be pandas, pyarrow, huggingface_hub (or plain HTTP) and platformdirs; the twin goes in a `[model]` extra.
- First PyPI release `3.1.0a1` is a pre-release: `pip install fintwin` ignores pre-releases, so the README quickstart and the L6 test fail until a final release exists. 3.x on a first release also signals a mature API. Use `0.1.0` on PyPI and keep `v3.0.0`/`paper-*` as the paper tag only.
- Hub mode: dataset size and the per-call download are not stated. Needs partition or per-CIK files with filter pushdown so the first call is a few MB and a few seconds, plus a bundled tiny sample (about 20 companies) that works offline.

### OG-5 (High) Reproducibility mechanics contradict each other (H5 vs H6)
H6 pins HF revisions for reproducibility; H5 pushes weekly and runs `super_squash_history` quarterly, which rewrites history (verify whether commit-hash pins and tags survive; likely not). Weekly overwrites also mean the same call returns different results next month. Fix: immutable versioned snapshots (branch/config per quarter, e.g. `2026Q4`), `latest` as a moving alias, library default pinned to a version recorded in the package, Zenodo DOI per snapshot (already planned). Never squash a ref someone can pin.

---

## 2. Important problems

### OG-6 (High) Launch shape: one big bang is the wrong unit
Recommended sequence of smaller launches, each one story with its own shot at HN/Reddit/newsletters:
1. Private beta, 2-3 weeks before launch (missing from the plan): private HF link and notebook to 8-10 humans (the researchers who replied, 2-3 quant/finance-ML people, 1 data engineer). Each spot-checks 20 filings.
2. Launch 1 (mid-Jan 2027): dataset + study + `pip install fintwin` read-only.
3. Launch 2, 4-6 weeks later: benchmark (static baselines table, submissions by PR), with the data already trusted.
4. Launch 3: dashboard-for-all and MCP, once the library has users.

Order answer: dataset first, library as a thin loader at the same time, benchmark second, dashboard and MCP last. Dashboard and twin are the least validated parts (the paper says simulation adds nothing for ranking) and must not be the face of launch 1.

### OG-7 (High) "Show HN with a finding as title" is a category error (G4)
Show HN is for something people can run; a finding is a normal link submission. Doing both on day 0 splits attention and can look like self-promotion. Do: Show HN for the dataset/loader, with the study as the first link in the first comment; submit the blog post separately only if it stands alone, on another day. Prepare a first comment (what it is, what it is not, known gaps, how to report data errors). Post Tue-Thu about 8-10am US Eastern. Never ask for upvotes (ring detection). If it sinks, email the HN moderators (hn at ycombinator.com) for the second-chance pool rather than reposting.

Title candidates:
- "Show HN: Free point-in-time SEC fundamentals for ~5,000 companies, including bankrupt ones"
- "Show HN: As-first-reported SEC financials (filed-date vintages), CC-BY, on Hugging Face"

Avoid "digital twin", "AI", "stress-testing" in the title, and any title promising "naive backtests are wrong" before the numbers exist.

### OG-8 (High) "What does this add over companyfacts / SEC Financial Statement Data Sets / edgartools?" will be the top comment
SEC companyfacts already carries a filed date per fact, and the SEC publishes Financial Statement Data Sets with filing dates. Section 0 of the plan does not confront this. README and dataset card need a short comparison table: what raw companyfacts gives, what it lacks (YTD de-cumulation, 52/53-week calendars, XBRL fallback for missing facts, delisted/bankrupt universe, first vs latest panels, events, validation report), with one worked example where the naive route gives a wrong number. Verify each claim on a concrete company before writing it.

### OG-9 (High) Negative-results risk is mostly framing and naming
The honesty is an asset (rare and credible) but the repo identity is "digital twin that stress-tests companies", while the paper says the twin does not beat a random walk for cash or its own formula for bankruptcy. HN will read "digital twin + MCP + LLM analyst + 5,300 health scores" as hype, then find the paper's own verdict. Mitigations:
- Lead launch 1 with data, whose quality evidence is independent of the twin; the twin is "also included, with honest results".
- Do not publish bankruptcy-style health scores on 5,300 indexable pages (OG-10).
- One sentence in the first comment: the model built on this data mostly did not beat simple baselines, which is why the data and benchmark are the contribution.
- The sharper critique will be data errors, not the paper: do the audit and beta first (OG-6, H3).

### OG-10 (Medium-High) 5,300 prerendered SEO pages (W3/A9): wrong priority, real risks
- Near-duplicate templated pages with numbers are thin content; indexing is uncertain and can drag down the whole site. Payoff takes months, if ever.
- Health scores for every small filer, indexed, conflict with the paper's finding that they do not rank risk better than baselines; reputational and disclaimer burden.
- Costs: 75-80 minute weekly build, 250 MB per deploy, a JSON-to-HF workaround (W5), path routing and 404 fallback maintenance.

Defer to launch 3; if kept, index a curated subset with real text and noindex the rest.

### OG-11 (Medium-High) L2 API design
- A ticker is not a PIT key: tickers are reassigned, changed and retired. `facts("CCL", asof=...)` must resolve ticker to CIK as of the date, accept `cik=` directly, and raise clearly on ambiguity.
- Define `asof` in one sentence (facts with filed <= asof; date vs datetime; same-day filings) in README, docstring and dataset card.
- Choose names once: `asof` vs `as_of`; namespace as `ft.pit.facts/panel/universe/events` rather than generic top-level `panel`/`universe`. Keep `ft.twin` and `ft.bench` out of the first stable surface (mark experimental).
- Return plain `pandas.DataFrame` with documented dtypes (`filed`, `period_end` as datetime64; float64 values; explicit unit column). No custom data classes. Polars/Arrow later.
- A short documented standard concept list (`revenue`, `fcf`, ...) mapped to us-gaap tags, with a raw-tag escape hatch.
- Lazy: `import fintwin` does no network and no heavy imports (submodules via `__getattr__`); first data call prints one line saying what it downloads and where it caches; `ft.cache_info()`. `set_identity` only for live mode; hub mode needs zero configuration.
- ADR-001 needs a deprecation policy; the plan promises stable names from 3.1 while the package is an alpha.

### OG-12 (Medium) README converts developers poorly today
Current README: 9 badges (including a Lighthouse score), a ~250-word "30-second pitch" paragraph, a dense results table above the fold, and a "Run it" section that starts with copying .env.example and running uv sync (contributor setup, not user install). It also says "390+ companies" and "5,220 filers" on the same screen. Pattern that converts:
1. One line of value ("Free point-in-time SEC fundamentals: what the market could have known on any date").
2. pip install + 3 lines of code + real printed output as text.
3. One chart: first-reported vs latest gap.
4. "Why PIT" in four lines and the OG-8 comparison table.
5. Links: dataset, Colab notebook, dashboard, paper.
6. Move the results table, feature table and screenshots below the fold or to docs.

Cut badges to CI, PyPI, HF, licence, DOI.

### OG-13 (Medium) Community mechanics are not real yet
- The Hacktoberfest crowd will not return. Remove the `hacktoberfest` topic after the event; add a short low-value-PR policy.
- Good first issues must be bounded, non-trivial and valuable (G3 is right in spirit), each with file pointers, a failing test to make green and a time estimate: XBRL tag mapping for a sector, reconcile 10 companies against their filings and file a data-error report, add a baseline to the benchmark. Currently 2 exist and are trivial.
- The data-error template exists only in the plan; add it now as a form (accession number, concept, expected vs actual). It will be the highest-traffic template.
- Recognition: all-contributors or a CONTRIBUTORS block, credit in the dataset changelog for data fixes, named thanks in release notes, authorship on the dataset paper for substantial data work.
- Governance: a short GOVERNANCE.md is right; state "single maintainer, best-effort support".
- Drop the "under 48 h response" promise (G6): a burnout trap and a trust risk when missed. Promise weekly triage.
- Sponsors: not before users exist. After launch 1, enable GitHub Sponsors with a small stated purpose (compute, domain). For a data project, sustainability is mostly the pipeline staying free and automated; grants and academic routes are more realistic than donations. Fiscal sponsorship only after real adoption.

### OG-14 (Medium) Leaderboard CI is a security and emptiness problem (B3)
CI that re-runs submitted code is arbitrary code execution in Actions: needs sandboxing, no secrets, fork-PR constraints and resource limits. With no users the board shows only your baselines, which reads as dead. Ship a static baselines table first, "submit predictions by PR, scored by the maintainer" second, automated re-execution only after about three external submitters.

---

## 3. Missing opportunities

### OG-15 (High value) Start the prospective registry now
Issue #41 exists. A hash-committed weekly prediction archive only gains value with elapsed time; each month of delay is a month less of verifiable history at launch. A cron that writes a hashed prediction file to a release or Zenodo costs hours and gives a non-copyable asset by mid-2027. Do it before the library.

### OG-16 (Medium) Reserve names early, with something real
Cheap: HF organisation and dataset slug, PyPI project, conda-forge later. The plan rejects a placeholder; a real 0.1.0 with the read-only loader, published early, does the same honestly and exercises Trusted Publishing before launch day. Check that "fintwin" is not already a visible project or company (verify).

### OG-17 (Medium) Instrumentation, ethically (the plan lists metrics, not mechanics)
- No telemetry or phone-home in the library.
- PyPI: pepy.tech / pypistats; mirrors and CI inflate counts, so use trends and the "without mirrors" series.
- HF: download counts come from specific file fetches and include your own CI; watch likes, "used in" notebooks/Spaces, discussions.
- GitHub traffic API keeps 14 days only: add a weekly Action appending views, uniques, clones, referrers and top paths to a CSV on a data branch.
- GitHub Pages has no analytics: use a cookieless counter (GoatCounter, Plausible or Cloudflare Web Analytics) and disclose it in the footer.
- Citations: Google Scholar alerts, Zenodo/DataCite counts, GitHub dependents, code search for "import fintwin".
- Pre-register thresholds now, as in the paper. Example for 90 days after launch 1: 500 PyPI downloads/month without mirrors, 300 HF downloads, 5 external issues (at least 2 data errors), 1 non-docstring external PR, 2 citations. Without thresholds a flop gets rationalised.

### OG-18 (Medium) Channels that suit a dataset
Quantocracy; r/algotrading (data flair), r/datasets; Kaggle with a notebook; arXiv q-fin and SSRN (endorsement takes lead time); HF community posts; direct emails to 15-20 named academics who use PIT data; a meetup talk offer. Awesome-list PRs only after a stable release and a few weeks of repo activity; check each list's rules (verify).

### OG-19 (Medium) If the launch flops
Pre-agree the protocol. Days 1-3: read referrers and README bounce. Do not repost the same link; wait 3-4 weeks and relaunch with a new angle (benchmark, or a concrete finding). Keep the weekly pipeline running: compounding comes from releases and citations, not spikes. Ask 3 beta users to critique the README. Pre-set a scope-reduction trigger (e.g. no external issue by day 60: freeze dashboard and benchmark expansion, keep only the weekly dataset).

### OG-20 (Low-Medium) Naming
"FinTwin" says digital twin / fintech, not point-in-time data; the audience searches "point-in-time", "SEC XBRL", "bankruptcy dataset", "look-ahead bias". Keep fintwin as the umbrella package (switching cost is high: paper, DOI), but give the dataset a descriptive slug and card title (e.g. "SEC Point-in-Time Fundamentals", slug like sec-pit-fundamentals), and make the repo description and topics lead with PIT. Add topics point-in-time, fundamentals, look-ahead-bias, huggingface-datasets. The A1 rule of avoiding "SEC"/"EDGAR" in names is over-cautious for descriptive use (edgartools, secfsdstools do it); avoid logos and any implication of endorsement. If the umbrella name is to change, decide before PyPI 0.1.0.

### OG-21 (Low) Schedule realism
The phase estimates omit the human review cycle and the rev3 dependency. Missing a date costs nothing; a rushed launch does. Target mid-Jan 2027 (Tue-Thu); early Dec only if the beta is finished by 1 Dec. JOSS typically expects public development history and evidence of research use (verify current rules): keep it out of the launch plan.

---

## 4. Concrete plan edits (section/item -> change)

- 0 (Thesis) -> add the "what companyfacts/FSDS already give" paragraph; state the MLP; say the twin is secondary.
- 1 / A1 -> keep fintwin on PyPI; allow descriptive "SEC" in dataset titles; add a naming gate before 0.1.0.
- 1 / A3 -> PyPI starts at 0.1.0 (final release, not alpha); paper tag v3.0.0/paper-* independent.
- 1 / A4 -> keep hub default; add bundled offline sample and "first call under about 5 MB".
- 1 / A7 -> drop the monthly Kaggle mirror from launch 1; keep HF + Zenodo.
- 1 / A8 -> no mkdocs site at launch 1: README + dataset card + notebook + docstrings.
- 1 / A9 -> defer to launch 3; curated indexable subset only.
- 2 / L1 -> hub mode requires no env vars or identity.
- 2 / L2 -> rewrite sketch: ft.pit.facts(ticker=None, cik=None, asof=...), ft.pit.panel, ft.pit.universe, ft.pit.events, ft.sample(); twin and bench experimental; document asof; resolve ticker as of date; plain DataFrames; lazy imports; deprecation policy in ADR-001.
- 2 / L3 (CLI) -> defer.
- 2 / L4 -> core = pandas, pyarrow, huggingface_hub, platformdirs; [model] = numpy/scipy/statsmodels; [live] = requests.
- 2 / L6 -> run on Linux, Windows, macOS and Python 3.10-3.13; record install, import and first-call times as CI numbers.
- 2 / H3 -> add an independent audit (random 200 company-quarters checked against the primary filings, match rate in the card) and the human beta.
- 2 / H5 -> replace weekly overwrite + squash with immutable versioned snapshots plus a moving alias; never squash pinned refs.
- 2 / B3 -> static baselines table at launch 2; automated re-execution later, sandbox rules written first.
- 2 / B4 -> start the weekly hashed prediction archive now, decoupled from the benchmark.
- 2 / R -> cheap go/no-go run first; headline chosen from the pre-registered analysis.
- 2 / W2-W5 and M1-M2 -> move to launch 3.
- 2 / G1 -> README rewrite (OG-12) first; cheapest step, affects all traffic.
- 2 / G2 -> add data-error form now; remove hacktoberfest topic; add PIT topics; low-value-PR policy; GOVERNANCE.md with single-maintainer notice.
- 2 / G3 -> write 8-10 real good-first-issues with file pointers and failing tests; all-contributors.
- 2 / G4 -> replace with the staged sequence (OG-6); Show HN for the dataset (OG-7 titles); first comment drafted; maintainer calendar cleared for launch day.
- 2 / G5 -> defer pyOpenSci and JOSS until after launch 2.
- 2 / G6 -> weekly triage instead of "under 48 h"; monthly release only if there is something to release.
- 3 (Order/gates) -> new order: G0 (ADRs, R go/no-go, registry cron, README rewrite) -> rev3 -> dataset + thin loader -> human beta -> launch 1 -> benchmark -> launch 2 -> dashboard/MCP -> launch 3. Add gates "hook go/no-go" and "beta feedback incorporated".
- 4 (Who does what) -> state the human review budget (hours/week) and a rule that no workstream starts before the previous one is reviewed; G4 reviewers must include humans.
- 7 (Risks) -> add: weak hook; HN critique of data quality; companyfacts overlap; pins broken by squash; leaderboard code execution; SEO thin content; burnout from response-time promises.
- New section 9 (Metrics) -> pre-registered thresholds, weekly traffic-snapshot Action, cookieless counter on Pages, no library telemetry, flop protocol (OG-17, OG-19).
