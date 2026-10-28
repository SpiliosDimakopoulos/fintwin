# FinTwin: πλάνο για να γίνει χρήσιμο open-source project

28-10-2026. Βάση: έρευνα αγοράς (GitHub API, SEC/FRED/HF/Pages docs, μελέτες για HN) και χάρτης του κώδικα στο `rev3`.
Συμπληρώνει το `IMPROVEMENT_PLAN.md` (rev3/paper), δεν το αντικαθιστά.

## 0. Θέση: τι είναι το FinTwin για τον κόσμο

Σήμερα: 4 αστέρια, 79 μοναδικοί επισκέπτες σε 2 εβδομάδες, κανένα `pip install`, dashboard 390 εταιρειών.
Ο επισκέπτης μπορεί να *κοιτάξει*, όχι να *χρησιμοποιήσει*.

**Το κενό που επιβεβαίωσε η έρευνα:** δεν υπάρχει ανοιχτό, αναπαραγώγιμο, point-in-time panel θεμελιωδών για όλο
το universe των SEC filers. edgartools (2.8k★) διαβάζει μία κατάθεση· FinanceToolkit (5.5k★) / OpenBB (75k★) δίνουν
δεδομένα providers χωρίς vintages· secfsdstools (86★) έχει filed date αλλά όχι panel· οι PIT βάσεις (Compustat PIT,
Sharadar, tradevodata) είναι επί πληρωμή. Τα bankruptcy datasets (Polish UCI, Taiwan, Kaggle "American") είναι μικρά,
ετήσια, ανωνυμοποιημένα, χωρίς ημερομηνίες κατάθεσης.

**Άρα η αξία, με σειρά:**
1. **Δεδομένα**: δωρεάν PIT panel ~5.200 εταιρειών 2009–σήμερα, vintages κατά filed date, YTD de-cumulation, 52/53
   εβδομάδες, XBRL fallback, χωρίς survivorship, με γεγονότα (8-K 1.03/2.04/3.01, συγχωνεύσεις). Χρήστες: ερευνητές
   finance, quants/φοιτητές (backtests χωρίς look-ahead), ML.
2. **Benchmark**: χρεοκοπία, έλλειψη ρευστότητας, πρόβλεψη ταμειακών ροών, με σταθερά χρονικά splits, baselines και
   leaderboard, συν **prospective track** (προβλέψεις που δεσμεύονται με hash πριν συμβούν τα γεγονότα). Το τελευταίο
   δεν το βρήκαμε πουθενά και ταιριάζει με την προκαθορισμένη φιλοσοφία του paper.
3. **Μηχανή stress test** ως βιβλιοθήκη (`twin("CCL").stress("covid")`) και dashboard για όλες τις εταιρείες.
4. **MCP server** ώστε LLM agents να ζητούν PIT δεδομένα και stress tests (edgartools το πρόσθεσε πρόσφατα).

Το μήνυμα προς τα έξω αλλάζει από «το μοντέλο χάνει από έναν κανόνα» σε **«δωρεάν point-in-time δεδομένα SEC και
ένα αυστηρό benchmark· εδώ φαίνεται πόσο look-ahead έχουν οι αφελείς backtests»**. Τα ειλικρινή αποτελέσματα μένουν,
ως απόδειξη αυστηρότητας.

**Δεν υποσχόμαστε αστέρια.** Μετρήσιμοι στόχοι 3 μηνών μετά το launch: pip downloads/μήνα (pepy), HF downloads,
εξωτερικά issues/PRs, υποβολές στο leaderboard, citations. Τα αστέρια ακολουθούν αν αυτά κινηθούν.

## 1. Αποφάσεις (προτείνω· αλλάζουν μόνο με λόγο)

| # | Απόφαση | Γιατί |
|---|---|---|
| A1 | Όνομα `fintwin` σε PyPI (ελεύθερο, ελέγχθηκε 28-10) και conda-forge αργότερα | Ίδιο με το repo/DOI. Δεν χρησιμοποιούμε «SEC»/«EDGAR» σε όνομα/domain (trademarks). |
| A2 | Monorepo όπως είναι (`engine/` = πακέτο Python, `web/` = dashboard) | Μία πηγή αλήθειας, ήδη parity tests. |
| A3 | Εκδόσεις: `v3.0.0` = tag του paper (rev3). Βιβλιοθήκη από `3.1.0a1`. | Το paper παραπέμπει σε σταθερό tag· η βιβλιοθήκη κινείται. |
| A4 | Δύο τρόποι δεδομένων: **hub** (προεπιλογή: Parquet από Hugging Face, χωρίς κλήσεις SEC) και **live** (από SEC με το User-Agent του χρήστη) | Ο νέος χρήστης παίρνει αποτέλεσμα σε δευτερόλεπτα· δεν φορτώνουμε την SEC με χιλιάδες χρήστες. |
| A5 | Dataset: κώδικας MIT, δεδομένα **CC-BY-4.0** | Τα γεγονότα είναι public domain· CC-BY ζητά αναφορά (citations), είναι αποδεκτό για ML. Η SEC ζητά να αναφέρεται ως πηγή. |
| A6 | **Κανένα FRED series της Moody's/ICE στο dataset** (`BAA10Y` είναι της Moody's). Μόνο κυβερνητικές σειρές (DGS3MO, DGS10, USREC, GDP· Philly Fed RTDSM) μετά από έλεγχο ανά σειρά. Το credit spread το κατεβάζει ο χρήστης τοπικά. | Όροι FRED: σειρές με copyright θέλουν άδεια του ιδιοκτήτη. |
| A7 | Φιλοξενία: HF Datasets (κύρια, viewer, `load_dataset`), Zenodo DOI ανά τρίμηνο snapshot, Kaggle mirror μηνιαία | HF για ML, Zenodo για citation, Kaggle για practitioners. |
| A8 | Docs: mkdocs + mkdocstrings στο `/docs/` του ίδιου Pages site· notebooks εκτελούνται σε CI με μικρό δείγμα, με κουμπί Colab | Το Material for MkDocs ίσως είναι σε maintenance (να επιβεβαιωθεί, εναλλακτικά Zensical). |
| A9 | Dashboard: από hash routes σε path routes (`/c/CCL/`) με prerender στατικού HTML ανά ticker και sitemap | SEO· 5.200 × ~45 KB ≈ 250 MB < 1 GB όριο Pages. |
| A10 | Benchmark labels δημόσια (ιστορικά γεγονότα)· το leaderboard δέχεται μόνο υποβολές με κώδικα που αναπαράγεται σε CI. Το prospective track βαθμολογείται κάθε τρίμηνο. | Τίμιο: δεν κρύβουμε test set που ήδη υπάρχει στο EDGAR. |

## 2. Ροές εργασίας (workstreams)

### L. Βιβλιοθήκη και packaging
Ευρήματα κώδικα: `fintwin/__init__.py` εκθέτει μόνο `__version__`· cache hard-coded σε 3 διαφορετικά σημεία
(`data/edgar.py:20`, `data/fred.py:16`, `pipeline.py:28`, `backtest/batch.py:35`)· User-Agent υποχρεωτικό από env·
κανένα entry point.

- **L1** `fintwin/config.py`: ένα cache dir (`FINTWIN_CACHE` ή `platformdirs.user_cache_dir("fintwin")`, το repo
  `.cache` μένει για development), `set_identity("Name email")` όπως στο edgartools, mode `hub|live|frozen`.
  Όλα τα modules περνούν από εδώ. Τεστ ότι εγκατάσταση σε site-packages δεν γράφει μέσα στο πακέτο.
- **L2** Δημόσιο API (σχέδιο στο ADR-001, πριν από κώδικα):
  ```python
  import fintwin as ft
  ft.set_identity("Jane Doe jane@uni.edu")          # μόνο για live mode
  ft.universe(asof="2020-02-15")                    # DataFrame: cik, ticker, sic, status, entry, exit
  ft.facts("CCL", asof="2020-02-15")                # PIT τριμηνιαίο panel μίας εταιρείας
  ft.panel(fields=["revenue","fcf","cash"], asof="2020-02-15")   # cross-section, όλο το universe
  ft.events(kind="bankruptcy")                      # 8-K 1.03 κ.λπ.
  tw = ft.twin("CCL", asof="2020-02-15")            # calibrated twin
  tw.stress("covid").summary(); tw.reverse_stress(); tw.health()
  ft.bench.load("bankruptcy-8q"); ft.bench.evaluate(task, preds)
  ```
  Wrappers πάνω στα υπάρχοντα (`data/facts.load_company`, `stochastic/calibrate.calibrate`, `stochastic/mc.run`,
  `scenarios/presets.build_scenario`). Εσωτερικά modules μένουν όπως είναι· τα δημόσια ονόματα σταθερά από 3.1.
- **L3** CLI `fintwin` (`[project.scripts]`, argparse ώστε να μη μπει εξάρτηση): `fintwin facts CCL --asof …`,
  `fintwin stress CCL covid`, `fintwin bench eval …`, `fintwin data pull`.
- **L4** Εξαρτήσεις: core = numpy, pandas, scipy, requests, statsmodels, pyarrow, platformdirs·
  `python-dotenv` σε extra· extras `[api]`, `[ai]`, `[mcp]`, `[ml]` (lightgbm για baselines), `[docs]`.
  Wheel χωρίς δεδομένα (μόνο τα μικρά CSV αναφοράς).
- **L5** Release: PyPI Trusted Publishing από Actions (environment `pypi` με required reviewer = εσύ), TestPyPI πρώτα,
  `CHANGELOG.md`, type hints (`py.typed`), mypy ήδη υπάρχει.
- **L6** First-run test: σε καθαρό container στον burst server, `pip install fintwin` → README quickstart → πρέπει να
  τρέξει σε < 60 s. Γίνεται και CI job (πάνω σε TestPyPI).

### H. Dataset (FinTwin-PIT)
- **H1** Σχήμα (ADR-002): πίνακες Parquet
  - `facts_vintages`: cik, concept, period_start/end, fiscal_year/quarter, value, unit, **filed**, accession, form,
    source (`companyfacts|xbrl_fallback`), derived (αν προέκυψε από de-cumulation). Ο πίνακας-καρδιά.
  - `quarterly_first`: panel εταιρείας-τριμήνου όπως **πρωτοδημοσιεύτηκε** · `quarterly_latest`: με τελευταίες αναθεωρήσεις.
  - `universe`: είσοδος/έξοδος, SIC, κατάσταση (active/acquired/delisted/bankrupt), λόγος εξόδου.
  - `events`: 8-K 1.03/2.04/3.01, 2.01/5.01, με ημερομηνία κατάθεσης.
  - `macro`: μόνο οι επιτρεπτές σειρές (A6).
  Κάθε γραμμή με provenance (accession → link στο EDGAR). Partition ανά έτος.
- **H2** Exporter `fintwin/data/export_parquet.py` από τη frozen cache. **Το dataset v1 βγαίνει από το ίδιο snapshot με
  το paper** (`manifest.json` SHA256), ώστε paper και dataset να είναι ταυτόσημα.
- **H3** Validation suite: ταυτότητες λογιστικής (A = L + E εντός ανοχής), μοναδικότητα κλειδιών, μονοτονία vintages,
  σύγκριση δείγματος με τα 10-Q· αναφορά ποιότητας στο dataset card. Issue template «data error».
- **H4** Dataset card (YAML: license, task_categories, configs), citation, όροι πηγών.
- **H5** Εβδομαδιαίο push από το `data.yml` με `HF_TOKEN` secret· `super_squash_history` κάθε τρίμηνο· Zenodo DOI
  στα τριμηνιαία tags· Kaggle mirror μηνιαία.
- **H6** Hub mode στη βιβλιοθήκη: `hf_hub_download` με pinned revision, ώστε τα αποτελέσματα να αναπαράγονται.

### B. Benchmark (FinTwin-Bench)
- **B0** Πρώτα βιβλιογραφικός έλεγχος (V4FinBench 2026 και survey arXiv 2411.01928, Papers with Code, HF): τι
  υπάρχει, τι ακριβώς είναι καινούριο. Καμία δήλωση «πρώτο» χωρίς αυτό.
- **B1** Pre-spec (ADR-003, γραμμένο *πριν* τρέξει οτιδήποτε, όπως το REVISION_PLAN_3):
  - T1 χρεοκοπία σε 4 και 8 τρίμηνα (AUC, PR-AUC, Brier, log loss)·
  - T2 έλλειψη ρευστότητας (το label του άξονα B του paper)·
  - T3 ταμειακές ροές/FCF ένα έτος μπροστά (CRPS, MAE), με και χωρίς realized revenue (transmission)·
  - splits: train ≤ 2016, val 2017–2018, test 2019–2024 (ή ακριβώς τα cutoffs του paper), μόνο PIT features·
  - baselines: Altman Z″, Ohlson O, logit, 16q margin, LightGBM, FinTwin.
- **B2** `fintwin.bench`: `load`, `evaluate`, `baselines`, μορφή υποβολής (Parquet προβλέψεων + script + `env.lock`).
- **B3** Leaderboard: φάκελος `bench/submissions/`, CI ξανατρέχει τον κώδικα και βαθμολογεί, πίνακας στο site.
- **B4** Prospective track: κάθε τρίμηνο οι προβλέψεις (baselines + υποβολές) κλειδώνουν με SHA256 σε GitHub
  release/Zenodo· βαθμολογούνται όταν βγουν τα 8-K. Σελίδα «προβλέψεις που κάναμε πριν συμβούν».
- **B5** Baselines τρέχουν στον burst server (cax21, λίγα λεπτά).

### R. Το «άγκιστρο»: πόσο look-ahead έχουν οι αφελείς backtests
Μελέτη που κάνει τον κόσμο να καταλάβει γιατί χρειάζεται το dataset:
- ποσοστό εταιρειών-τριμήνων που αναθεωρήθηκαν μετά την πρώτη δημοσίευση, και κατά πόσο·
- πόσο φουσκώνει το AUC χρεοκοπίας και ένα απλό factor backtest με `quarterly_latest` αντί για `quarterly_first`·
- πόσες εταιρείες λείπουν αν το universe ληφθεί από τους σημερινούς tickers (survivorship).
Pre-spec πριν τρέξει, compute στον burst server, γίνεται notebook #1, blog post και το κεντρικό post στο HN.

### W. Dashboard για όλους
- **W1** Μέτρηση (28-10, 3 τελευταία runs): norms ~14', shards 5,5–6' median για ~392 εταιρείες/16 ≈ 13,5 s ανά εταιρεία, σύνολο ~23'. Για 5.200: ~19,5 ώρες runner, με 20 ταυτόχρονα jobs ≈ 60' + norms ≈ 75–80' την εβδομάδα. Χωράει δωρεάν (32 shards × ~37', κάτω από το timeout 120'). Αρχικά έλεγχος αν
  στα δωρεάν runners (public repo) με περισσότερα shards, ή αν το πλήρες universe χτίζεται ανά μήνα και οι 390 ανά εβδομάδα.
- **W2** Universe: από S&P 500 (`universe_sp500.csv`, 394) στο universe του dataset με φίλτρο κάλυψης· gate
  `MIN_COMPANIES` προσαρμόζεται.
- **W3** Path routing + prerender (React `renderToString` σε build script) για `/c/<TICKER>/`: τίτλος, meta,
  σύντομη περίληψη κειμένου (όχι μόνο αριθμοί, αλλιώς η Google δεν τα κάνει index), sitemap, canonical. SPA fallback
  με `404.html`· τα παλιά `#…` links ανακατευθύνονται.
- **W4** Σελίδες τομέα, screener όλου του universe, εβδομαδιαία λίστα «μεγαλύτερες αλλαγές υγείας» (υπάρχει ήδη RSS),
  export CSV, κουμπί «άνοιξε σε notebook».
- **W5** Μέγεθος: αν το JSON περάσει ~600 MB, τα company JSON πάνε στο HF και το site τα φορτώνει από εκεί.

### M. MCP server και integrations
- **M1** `fintwin-mcp` (extra `[mcp]`, επίσημο Python SDK): tools `facts`, `panel`, `events`, `stress`, `health`,
  `reverse_stress`, μόνο hub mode, όλα read-only. Οδηγίες για Claude Desktop / Cursor.
- **M2** Παράδειγμα «LLM credit analyst» που χρησιμοποιεί μόνο αριθμούς από τα tools (συνδέεται με το υπάρχον module σημειωμάτων).

### D. Τεκμηρίωση και παραδείγματα
- Site docs: Getting started (60 s), Concepts (PIT, vintages, survivorship), Data dictionary (από το schema, αυτόματα),
  API reference (mkdocstrings), Benchmark, Model (από METHODOLOGY), Paper, FAQ, Data terms.
- Notebooks (Colab badge, εκτελούνται σε CI): (1) πόσο look-ahead έχει ο αφελής backtest, (2) μοντέλο χρεοκοπίας σε 20
  γραμμές και υποβολή στο bench, (3) Carnival 2020 stress test, (4) δικό σου σενάριο και reverse stress, (5) screen
  τομέα, (6) MCP με LLM.

### G. Παρουσίαση, launch, κοινότητα
- **G1** README από την αρχή: μία φράση αξίας, GIF, `pip install` + 3 γραμμές, «γιατί PIT», σύνδεσμοι dataset/bench/
  dashboard/paper, citation. Τα αποτελέσματα του paper σε δική τους ενότητα.
- **G2** Καθαρισμός root (`grep.exe.stackdump`, `klein_list.txt` τοπικά), issue templates (bug, data error, bench
  submission, feature), labels, Discussions κατηγορίες, `GOVERNANCE.md` (σύντομο).
- **G3** Pipeline good-first-issues που φέρνουν πραγματική αξία: XBRL tag mappings, νέα σενάρια, νέα baselines στο
  bench, έλεγχοι ποιότητας δεδομένων, μεταφράσεις dashboard.
- **G4** Launch (τα posts τα κάνεις εσύ από τους λογαριασμούς σου· εγώ ετοιμάζω κείμενα):
  - Ημέρα 0: blog post (R) + Show HN με τίτλο που λέει το εύρημα, όχι το όνομα του project. Οι μελέτες δείχνουν
    +100–300 αστέρια την πρώτη εβδομάδα από HN έκθεση σε AI projects· σε niche finance λογικά λιγότερα.
  - Ημέρα 1–3: r/algotrading, r/quant, r/datascience, r/Python· HF dataset/Kaggle με notebook.
  - Εβδομάδα 1–2: PRs σε awesome-quant (30k★), awesome-public-datasets (80k★), financial-machine-learning (8.8k★),
    awesome-ai-in-finance· PyCoder's Weekly / Python Weekly.
  - Μην γίνει launch μεταξύ 20/12 και 6/1 (χαμηλή κίνηση).
- **G5** Ακαδημαϊκά: pyOpenSci review (πιστοποίηση ποιότητας), JOSS paper (έλεγχος προϋποθέσεων ιστορικού),
  Zenodo, email στους researchers που απάντησαν, με link στο dataset.
- **G6** Συνέχεια: εβδομαδιαία δεδομένα (ήδη), μηνιαίο minor release με changelog, τριμηνιαία βαθμολόγηση του
  prospective track (ξανά αφορμή για post), απάντηση σε issues < 48 ώρες μέσω `fintwin-maintainer`.

## 3. Σειρά και gates

Ο κανόνας: **ο κώδικας του rev3 παγώνει όταν ξεκινήσει το full run.** Η βιβλιοθήκη γίνεται σε branch `lib` από εκείνο
το commit, ώστε τα νούμερα του paper να μην εξαρτώνται από τον refactor.

| Φάση | Τι | Εξάρτηση | Gate για να προχωρήσουμε |
|---|---|---|---|
| **G0** τώρα, παράλληλα με rev3 | ADR-001 API, ADR-002 schema, ADR-003 bench pre-spec, pre-spec της μελέτης R· B0 βιβλιογραφία· έλεγχος όρων ανά FRED/Philly Fed σειρά· W1 μέτρηση χρόνων· τα 3 κείμενα που δεν αγγίζουν κώδικα | καμία | ADRs εγκεκριμένα από σένα |
| **rev3** | dry run → full run → paper (ήδη στο IMPROVEMENT_PLAN) | snapshot | tag `v3.0.0` |
| **G1** βιβλιοθήκη alpha | L1–L5, H2 exporter, H6 hub mode | κώδικας rev3 παγωμένος | tests πράσινα, first-run test < 60 s, `3.1.0a1` στο TestPyPI |
| **G2** δεδομένα + bench | H1–H5, B1–B3, B5, μελέτη R στον server | G1, snapshot rev3 | validation suite πράσινη, dataset ιδιωτικό στο HF για έλεγχο |
| **G3** επιφάνεια | W2–W5, D (docs + notebooks), M1–M2, G1–G3 | G2 | site docs live, notebooks περνούν σε CI |
| **G4** πριν το launch | 3 φρέσκοι reviewers (κώδικας, δεδομένα, «νέος χρήστης»), security review, διορθώσεις, `3.1.0` στο PyPI, dataset δημόσιο | G3 | καμία ανοιχτή κρίσιμη παρατήρηση |
| **G5** launch | G4 της ενότητας 2 | G4 + δική σου έγκριση | — |
| **G6** συνέχεια | G5, G6 της ενότητας 2, B4 πρώτο τρίμηνο | — | — |

Εκτίμηση: G0 1–2 μέρες· rev3 ~1–2 εβδομάδες· G1 ~1 εβδομάδα· G2 1–2 εβδομάδες· G3 ~2 εβδομάδες· G4 λίγες μέρες.
Launch ρεαλιστικά **αρχές-μέσα Δεκεμβρίου ή μέσα Ιανουαρίου** (όχι στις γιορτές).

## 4. Ποιος κάνει τι (agents και μοντέλα)

Ίδιο σύστημα με το rev3: κάθε workstream σε δικό του git worktree και branch, με τους κανόνες του `AGENT_BRIEF.md`
(identity, χωρίς push, interface notes στο `interfaces/`, αιτήματα στο `requests/`), merge από την κύρια συνεδρία.

| Εργασία | Ποιος | Γιατί |
|---|---|---|
| ADR-001/002/003, pre-spec R, όλες οι αποφάσεις, merges, τελικά κείμενα README/HN | **κύρια συνεδρία (Opus)** | σχεδιασμός και κρίση |
| L1–L3 (config, δημόσιο API, CLI) | **Opus subagent** σε worktree | αγγίζει όλα τα modules, λεπτός refactor |
| L4–L5 packaging, Trusted Publishing, CHANGELOG | Sonnet | τυποποιημένο |
| H2 exporter, H3 validation, H6 hub mode | Sonnet· σχήμα και review από Opus | μεσαία δυσκολία |
| H4 dataset card, H5 workflows | Sonnet | |
| B0 βιβλιογραφία, έλεγχοι όρων FRED | `researcher` (Sonnet) | κρίση πάνω σε πηγές |
| B2–B3 bench κώδικας και leaderboard CI | Sonnet | |
| W1 μέτρηση από logs Actions | Haiku (`bulk-reader`) | μηχανικό |
| W2–W5 dashboard, prerender, routing | Sonnet (frontend) | |
| M1–M2 MCP | Sonnet | |
| D docs και notebooks | Sonnet συγγραφή· Haiku για link check και τυπογραφικά | |
| G2 templates/labels, awesome-list PR κείμενα | Haiku | μηχανικό |
| Reviewers G4 | 3 φρέσκοι agents: code review (Opus), data audit (Sonnet), «νέος χρήστης» σε καθαρό server (Sonnet) | ανεξάρτητη ματιά |

Παράλληλα στο G1: L (Opus) και H2 (Sonnet), με το interface «ο exporter διαβάζει μέσω `fintwin.config`» να ορίζεται
στο ADR-001 πριν ξεκινήσουν. Στο G3: W, D, M τρέχουν ταυτόχρονα (διαφορετικά αρχεία).

## 5. Compute και κόστος

- Όλα τα βαριά στο burst server (cax21/cax31): export dataset από το snapshot, μελέτη R, baselines του bench,
  first-run tests. Εκτίμηση < 1 EUR συνολικά για G1–G4.
- Εβδομαδιαίο build/push στα δωρεάν GitHub Actions (public repo). HF/Zenodo δωρεάν.
- Κανένα νέο πάγιο κόστος.

## 6. Τι χρειάζεται από σένα (εξωτερικές ενέργειες)

1. Έγκριση των ADRs του G0.
2. Λογαριασμός PyPI (και TestPyPI) και ρύθμιση pending trusted publisher για το `fintwin`.
3. Λογαριασμός/organisation στο Hugging Face και `HF_TOKEN` ως GitHub secret (εγώ δεν βλέπω το token).
4. Έγκριση πριν από κάθε δημόσια δημοσίευση: push, PyPI release, HF dataset δημόσιο, Kaggle, Zenodo, awesome-list PRs.
5. Τα posts του launch (HN, Reddit) από τους λογαριασμούς σου.

## 7. Κίνδυνοι

| Κίνδυνος | Αντιμετώπιση |
|---|---|
| Λάθη στα δεδομένα γίνονται δημόσια | validation suite, data-error template, διορθώσεις στο επόμενο εβδομαδιαίο build, changelog δεδομένων |
| Άδειες τρίτων (FRED Moody's/ICE) | A6· έλεγχος ανά σειρά πριν το G2 |
| Κάποιος πάρει το όνομα στο PyPI | alpha στο PyPI στο τέλος του G1 (όχι placeholder) |
| Ένας maintainer, burnout | αυτοματοποίηση (weekly build, CI leaderboard, maintainer skill), σαφή good-first-issues |
| Το bench δεν είναι καινούριο | B0 πριν από κάθε δήλωση· το prospective track και τα PIT labels είναι η διαφορά |
| Μέγεθος Pages | W5 (company JSON στο HF) |
| Rate limits SEC από χρήστες | hub mode προεπιλογή· live mode με το throttle που ήδη υπάρχει |

## 8. Ευρήματα G0 (28-10)

**Πόσο καινούριο είναι το benchmark.** Κοντινότερα: V4FinBench (2026, 1M+ firm-years Visegrad, label κανόνας από λογιστικά, χωρίς PIT, χωρίς live track),
EDGAR-CORPUS/ECL (labels LoPucki, αριθμοί Compustat, ετήσιο), arXiv 2606.05623 (10-K κείμενο, ετήσιο).
Live/prospective: ForecastBench, Foresight Arena, TS-Arena (commit-reveal), κανένα σε credit/θεμελιώδη.
Ένα ανοιχτό PIT dataset βρέθηκε μόνο ως CC BY-NC με το ιστορικό αναθεωρήσεων επί πληρωμή (StockAlloy FiledFact-100K).
**Μπορούμε να πούμε** (ως «δεν βρήκαμε προηγούμενο»): ανοιχτό CC-BY PIT/as-first-reported panel XBRL· labels από
ημερομηνίες 8-K 1.03 σε 4 και 8 τρίμηνα· task έλλειψης ρευστότητας· CRPS για ταμειακές ροές με/χωρίς revenue·
prospective track σε credit. **Δεν λέμε**: «πρώτο bankruptcy benchmark», «πρώτο σε SEC», «πρώτο live», «πρώτο PIT».

**Άδειες ανά σειρά (αντικαθιστά το A6).**

| Σειρά | Στο CC-BY dataset; |
|---|---|
| BAA10Y (Moody's) | Όχι. Script που την κατεβάζει τοπικά. |
| Philly Fed RTDSM (GDP vintages) | Όχι χωρίς γραπτή άδεια. Script + παραπομπή Croushore & Stark (2001). Προαιρετικά email στη Philly Fed. |
| DGS3MO, DGS10 | Ναι, από την πηγή (Fed H.15 ή Treasury yield curve), όχι από FRED. |
| GDP | Ναι, από BEA, με αναφορά. |
| USREC | Ναι, χτισμένο από τις ημερομηνίες NBER («Permission to copy is granted, provided attribution»). |

Νέο αρχείο `THIRD_PARTY.md` με πηγή και όρους κάθε σειράς· οι σειρές NBER/BEA/Fed εξαιρούνται ρητά από τη CC-BY.
