# FinTwin: πλάνο για να γίνει χρήσιμο open-source project (v2)

v1 28-10-2026 · **v2 28-10-2026, μετά από 6 reviews** (`growth_review/`: finance_researcher FR, benchmark BM, oss_growth OG,
architecture AR, data_engineering DE, product_ux PX — 123 ευρήματα). Κάθε αλλαγή σημειώνει το ID που την προκάλεσε.
Συμπληρώνει το `IMPROVEMENT_PLAN.md` (rev3/paper), δεν το αντικαθιστά.

## 0. Θέση

Σήμερα: 4★, 79 μοναδικοί επισκέπτες σε 2 εβδομάδες, χωρίς `pip install`, dashboard 390 εταιρειών. Ο επισκέπτης
μπορεί να *κοιτάξει*, όχι να *χρησιμοποιήσει*.

**Τι δίνει ήδη η SEC, και τι λείπει (OG-8).** Το `companyfacts` έχει filed date ανά fact και τα Financial Statement
Data Sets έχουν ημερομηνίες κατάθεσης. Δεν δίνουν: τριμηνιαίο panel (YTD de-cumulation, Q4 = FY − 9M), 52/53
εβδομάδες, τα facts που λείπουν από το API (XBRL fallback), universe με όσες εταιρείες εξαφανίστηκαν, ερώτημα «όπως
ήταν γνωστό στις D» για όλο το universe, γεγονότα (8-K) ευθυγραμμισμένα με τα δεδομένα, αναφορά ποιότητας. Αυτό το
κενό δεν το καλύπτει κανένα ανοιχτό εργαλείο (edgartools 2.8k★ = μία κατάθεση· FinanceToolkit/OpenBB χωρίς vintages·
Compustat PIT/Sharadar επί πληρωμή· το μόνο ανοιχτό PIT στο HF είναι CC BY-NC με το ιστορικό επί πληρωμή).

**Χρήστες και η δουλειά που τους κάνουμε (PX-1):**
1. Ερευνητής finance/λογιστικής: αναπαραγώγιμο PIT panel χωρίς WRDS, που ενώνεται με το Compustat/CRSP που ήδη έχει.
2. Quant/φοιτητής: backtests χωρίς look-ahead και survivorship, σε 3 γραμμές.
3. ML ερευνητής: benchmark με πραγματικά γεγονότα και τίμια splits.
4. (Δευτερεύον) αναλυτής/φοιτητής: stress lab για μία εταιρεία. Το dashboard είναι **επιφάνεια απόκτησης**, το MCP
   **κανάλι διανομής**.

**Ο twin είναι δευτερεύων στην παρουσίαση (OG-9).** Πρώτα τα δεδομένα, που η ποιότητά τους δεν εξαρτάται από τα
αποτελέσματα του twin· ο twin «περιλαμβάνεται, με τίμια αποτελέσματα».

**Ακρίβεια στις δηλώσεις (FR-2, FR-11):** πλήρες universe από 2011Q2 (XBRL phase-in: μεγάλοι filers από 2009)· μόνο
μη χρηματοοικονομικές εταιρείες· «χωρίς survivorship» για την εποχή XBRL, με τεκμηριωμένη κατασκευή και μέτρηση recall
των labels. Πίνακας κάλυψης ανά έτος στο dataset card.

## 1. Αποφάσεις

| # | Απόφαση | Λόγος / ID |
|---|---|---|
| A1 | `fintwin` στο PyPI (ελεύθερο). Το dataset με περιγραφικό τίτλο **«FinTwin PIT: point-in-time US SEC fundamentals»**. «SEC» μόνο περιγραφικά, ποτέ σε όνομα/domain/λογότυπο. | trademarks, OG-20 |
| A2 | Monorepo (`engine/`, `web/`). | |
| A3 | `v3.0.0` = tag του paper. **Πρώτο PyPI release `3.1.0` τελικό** (pre-releases μόνο στο TestPyPI, αλλιώς το `pip install` τα αγνοεί). | OG-4 |
| A4 | Hub mode προεπιλογή: Parquet από HF, **pinned στο tag του dataset που συνοδεύει κάθε έκδοση**, χωρίς env vars ή identity· `latest` προαιρετικό. Live mode μόνο με `set_identity`, κοινό rate limiter και διακόπτη για 403. Hub mode απενεργοποιεί το XBRL fallback· live χωρίς User-Agent → σφάλμα, όχι σιωπηλά άλλα δεδομένα. | DE-4, AR-4 |
| A5 | Κώδικας MIT. Πίνακες του FinTwin: CC-BY-4.0 (στον βαθμό που υπάρχουν δικαιώματα). Τα SEC facts μένουν δημόσια πληροφορία. Τρίτες σειρές **εκτός** του CC-BY repo (`THIRD_PARTY.md`). Νέο `LICENSE-DATA`. | DE-2, FR-10 |
| A6 | **Εκτός dataset και wheel:** BAA10Y (Moody's· το μοντέλο δεν το χρησιμοποιεί, αφαιρείται), Philly Fed RTDSM, Damodaran rating spreads, Wikipedia S&P/GICS (CC BY-SA). Universe και τομείς **μόνο από SEC** (SIC → FF12). Μακρο από πρωτογενή κυβερνητική πηγή (Treasury/H.15, BEA, NBER) σε ξεχωριστό config ή με script. Ό,τι χρειάζεται ο twin και δεν αναδιανέμεται (spreads, GDP vintages) κατεβαίνει στο μηχάνημα του χρήστη με cache. | AR-10, AR-11, DE-2 |
| A7 | HF = πηγή αλήθειας (εβδομαδιαία), Zenodo = μόνιμο DOI ανά τρίμηνο. Kaggle μετά το launch, ως επιμελημένο υποσύνολο. **Κανένα `super_squash_history`.** | DE-1, AR-17, OG-5 |
| A8 | Launch 1 χωρίς docs site: README + dataset card + notebooks + docstrings. mkdocs στο launch 2. | OG |
| A9 | Σελίδες ανά εταιρεία μόνο στο launch 3, σταδιακά και με κανόνα ποιότητας (`noindex` όπου λίγα δεδομένα). Πρώτα σελίδες τομέα, εβδομαδιαίων αλλαγών και εννοιών. Απόφαση για custom domain. | PX-3, PX-4 |
| A10 | Benchmark: dev labels δημόσια· ο ιστορικός πίνακας λέγεται ρητά «όχι leakage-proof», δείχνει αριθμό προσπαθειών και διαστήματα· **κύρια κατάταξη = prospective track**. | BM-1 |
| A11 | **Πολιτική διατύπωσης και νομικού κινδύνου** για scores επώνυμων εταιρειών: «δείκτης», όχι πρόβλεψη ή συμβουλή· ζώνες αντί για πιθανότητες στο dashboard· banner, μεθοδολογία και link πηγών σε κάθε σελίδα· πολιτική διορθώσεων· κατάσταση «ανεπαρκές ιστορικό»· λίστα απαγορευμένων φράσεων· νομικός έλεγχος πριν από >390 δημόσιες σελίδες. | PX-2, PX-9 |
| A12 | Κλειδί παντού το **CIK**· `resolve(ticker, asof)` από πίνακα tickers με ημερομηνίες ισχύος. | FR-1, AR-6 |
| A13 | Κανόνας PIT: γνωστό από το **SEC acceptance timestamp** (μετά τις 17:30 ET = επόμενη εργάσιμη). Παράγωγες γραμμές γνωστές όταν και το τελευταίο συστατικό τους. Base πίνακες append-only· «as of D» είναι η βασική λειτουργία, τα first/latest είναι όψεις. | DE-3 |
| A14 | Τρεις αριθμοί έκδοσης: βιβλιοθήκη (semver), `schema_version` (semver), `data_release` (π.χ. `2026.47`). Το benchmark έχει δικά του παγωμένα snapshots. | DE-14, BM-10 |

## 2. Τρία launches αντί για ένα (OG-1, OG-6)

Ένας maintainer δεν στηρίζει έξι προϊόντα σε ένα launch. Κάθε launch είναι μόνο του χρήσιμο:

| Launch | Περιέχει | Κοινό |
|---|---|---|
| **1. Δεδομένα** | dataset στο HF (+Zenodo DOI), λεπτός loader `pip install fintwin` (μόνο δεδομένα), 3 notebooks, μελέτη R, νέο README | ερευνητές, quants |
| **2. Benchmark + μοντέλο** | `fintwin.bench` με στατικό πίνακα baselines, prospective track, `ft.twin` (extra `[model]`), docs site, paper datasets & benchmarks | ML, ακαδημαϊκοί |
| **3. Επιφάνεια** | dashboard σε όλο το universe (σταδιακά), σελίδες τομέα/εβδομάδας, MCP server, badges/widgets, newsletter | ευρύ κοινό, LLM agents |

## 3. Ροές εργασίας

### L. Βιβλιοθήκη
- **L1** `fintwin/config.py`: ένα cache dir (`FINTWIN_CACHE` ή `platformdirs`), mode `hub|live|frozen`, `set_identity`.
  Αλλάζουν **≥ 15 σημεία** με hard-coded paths και παρενέργειες: εγγραφές μέσα στο πακέτο (`universe.py:98`),
  `load_dotenv(override=True)` στο import (`memo.py:31`), `lru_cache` που καθαρίζουν σε αλλαγή mode (`facts.py:29`,
  `universe.py:35,65,70`). Τεστ: εγκατάσταση σε read-only site-packages. (AR-5)
- **L2** API. Δεδομένα (launch 1): επίπεδα DataFrames, lazy imports, τεκμηριωμένο `asof`:
  ```python
  import fintwin as ft
  ft.sample()                                          # 50 εταιρείες, < 5 MB
  ft.universe(asof="2020-02-15")                       # cik, name, sic, ff12, status, eligible_asof
  ft.facts(ticker="CCL", asof="2020-02-15")            # ή cik=…; PIT τριμηνιαίο panel
  ft.panel(fields=["revenue", "fcf", "cash"], asof="2020-02-15")   # cross-section
  ft.events(kinds=["1.03", "2.04", "3.01", "4.02"])
  ft.resolve("CCL", asof="2020-02-15")                 # ticker -> cik
  ```
  Μοντέλο (launch 2, `[model]`): `ft.twin(…, asof, spec=…)` → `.stress()`, `.reverse_stress()`, `.health()`.
  **Ο PIT twin είναι η research εκδοχή του calibrate** (`research/experiments.py:350-363`), που εξάγεται στο
  `fintwin/twin.py` και τη χρησιμοποιούν και η έρευνα και το API: macro, spreads, GDP vintage όπως ήταν στο `asof`,
  `sector_tol=1` ή PIT norms, ρητό `spec`. Απλό wrapper πάνω στο `stochastic/calibrate` θα είχε look-ahead. Τεστ
  ισοδυναμίας με το research calibrate. (AR-1, AR-12)
  Μετρημένοι χρόνοι (CCL): φόρτωση ~3 s, calibrate 1,1 s, stress 0,12 s, reverse stress ~2 s· cold import 11 s →
  χρειάζεται lazy import για τα 60 s. (AR-18) Πολιτική deprecation στο ADR-001.
- **L3** CLI: αναβάλλεται στο launch 2. (OG)
- **L4** Εξαρτήσεις: core = pandas, pyarrow, huggingface_hub, platformdirs· `[model]` = numpy, scipy, statsmodels·
  `[live]` = requests· `[mcp]`, `[ml]`, `[docs]`. Το wheel χωρίς δεδομένα τρίτων (A6), με έλεγχο στο CI. (OG, AR-10)
- **L5** PyPI Trusted Publishing (environment `pypi`, required reviewer = εσύ), TestPyPI πρώτα, `CHANGELOG.md`, `py.typed`.
- **L6** First-run test σε CI: Linux/Windows/macOS × Python 3.11–3.13, χρόνοι install/import/πρώτης κλήσης ως
  νούμερα CI· και σε καθαρό burst server. (OG)

### H. Dataset «FinTwin PIT»
- **H1** Σχήμα (ADR-002, Opus review):
  - `facts_raw`: cik, tag, unit, start, end, val, accn, form, filed, **accepted_at**, filing_fy/fp, frame, decimals,
    source (companyfacts|xbrl_fallback), ingested_build, pipeline_version, row_hash. Τα 97 tags του loader +
    `DA_PARTS`/`MATURITY_TAGS`. **Ο loader τρέχει αμετάβλητος πάνω του** (το τριμηνιαίο panel δεν αρκεί για τον twin). (AR-2)
  - `panel_vintages`: cik, period_end, known_from, όλες οι στήλες του `quarters`, flags (q4_derived, imputed,
    restated, first_reported), tag_used και accession ανά πεδίο, derived_from. `quarterly_first`/`quarterly_latest` =
    όψεις. (AR-7, FR-4/5/9, DE-3)
  - `companies` (status, exit_reason από Forms 25/15 και 8-K 2.01/3.01/5.01, sic, ff12, filer_category,
    exclusion_reason, eligible_asof), `tickers` (με ημερομηνίες ισχύος), `events` (μόνο κωδικοί items και acceptance
    time, **χωρίς ελεύθερο κείμενο**: τα 8-K ονομάζουν πρόσωπα), `manifest` (SHA256 snapshot, git SHA loader, spec).
    (AR-8, FR-1, FR-6, DE-17)
  - Partition **`cik % 64`**, ταξινόμηση (cik, tag, end, accepted_at): μία εταιρεία = ένα μικρό αρχείο. Εβδομαδιαία
    deltas σε δικά τους αρχεία, συμπίεση ανά τρίμηνο. Cross-section «as of D» με DuckDB/polars, χρόνοι μετρημένοι στο
    card. (AR-3, DE-6/7/19)
  - `sample` config 50 εταιρειών. (DE-22)
- **H2** Exporter από τη frozen cache· **v1 από το ίδιο snapshot με το paper**. Το `panel_vintages` κοστίζει ~130
  CPU-ώρες μία φορά (2×cax31, ~8 h, < 1 EUR), μετά **μόνο incremental**. Τεκμηρίωση κανόνων first/latest, 10-K/A,
  10-Q/A, αναθεωρημένων comparatives. (AR-7, FR-5)
- **H3** Ποιότητα:
  - H3a αυτόματες πύλες (hard: κλειδιά, λογιστικές ταυτότητες, μονάδες/κλίμακα, dei, immutability μέσω row_hash·
    soft: αποκλίσεις, κάλυψη), αναφορά ποιότητας στο card. (DE-12, FR-7)
  - H3b ανεξάρτητος έλεγχος 200 τυχαίων εταιρειών-τριμήνων απέναντι στις ίδιες τις καταθέσεις, ποσοστό ταύτισης στο card. (OG)
  - H3c σύγκριση με Compustat σε ~500 εταιρείες-τρίμηνα **από beta χρήστη με WRDS**: μόνο συγκεντρωτικά ποσοστά, script
    για όποιον έχει άδεια· αλλιώς ρητή δήλωση ότι δεν έγινε. (FR-3)
  - Recall των labels χρεοκοπίας απέναντι σε δημόσιες λίστες (π.χ. LoPucki BRD). (FR-11)
- **H4** Dataset card: configs ανά πίνακα, περιορισμοί, κάλυψη ανά έτος, ιδιωτικότητα, πίνακας άδειας ανά πηγή,
  κείμενο αναφοράς, citation, πολιτική εκδόσεων, Croissant metadata. (DE, BM-15, FR-14)
- **H5** Εβδομαδιαία ροή: SEC **bulk archives** (`companyfacts.zip`, `submissions.zip`) + μόνο οι νέες καταθέσεις, σε
  ένα job· **τα shards δεν αγγίζουν ποτέ την SEC** (`FINTWIN_FILL_ONLY=1`), αλλιώς ~130 req/s με ένα User-Agent στα
  5.300· διακόπτης στο 403 → delta (χωρίς token) → πύλες → HF PR → επαλήθευση → merge → tag. Token μόνο σε environment
  ξεχωριστού publish job. Rollback με νέο commit σε < 24 h + ανακοίνωση. (DE-4/5/13/15, AR-14)
- **H6** Hub mode: pinned tag, `allow_patterns` ανά config, έλεγχος checksums, offline mode, κάθε αποτέλεσμα γράφει
  `data_release`. CI τεστ: hub == frozen. (DE, AR-22)
- **H7** `VARIABLES.md` + `variable_map.csv`: πεδίο → tags → Compustat item, ποσοστό συμπλήρωσης· προσαρμοσμένο και μη
  προσαρμοσμένο EBIT χωριστά. Changelog δεδομένων. (FR-4, DE-14)
- **H8** `link_to_crsp_compustat.py`: σύνδεση μέσω CIK με τα δεδομένα του ίδιου του χρήστη, ποσοστό ταύτισης σε δείγμα,
  καμία αναδιανομή. (FR-1)

### R. Μελέτη look-ahead (το «άγκιστρο»)
- **R0 go/no-go, φθηνά, στο G0:** από το snapshot (το `companyfacts` κρατά όλες τις τιμές ανά περίοδο): ποσοστό
  εταιρειών-τριμήνων και πεδίων που αναθεωρήθηκαν και κατά πόσο· AUC του Altman Z″ με πρώτες vs τελευταίες τιμές· πόσες
  εταιρείες λείπουν αν το universe βγει από τους σημερινούς tickers. Pre-spec πριν τρέξει, δεκτό και μικρό αποτέλεσμα,
  παραπομπή στη βιβλιογραφία Compustat Snapshot. cax21, ~1 ώρα. (OG-3, FR-13)
- **R1** αν περάσει: πλήρης έκδοση πάνω στο `panel_vintages`, notebook #1, blog post. Αν όχι: το άγκιστρο γίνεται «το
  ανοιχτό panel με τις χρεοκοπημένες μέσα» + η σύγκριση με companyfacts (OG-8).

### B. Benchmark «FinTwin-Bench» (launch 2)
- **B0** Έγινε (ενότητα 9). Μένει: recall labels vs LoPucki. (FR-11)
- **B1** Pre-spec (ADR-003, πριν τρέξει οτιδήποτε):
  - **T1** χρεοκοπία σε 4 (προεπιλογή) και 8 τρίμηνα. Κατάσταση γραμμής event / survived / exited-non-distress /
    exited-unknown, `time_to_event`, `exit_reason`, κανόνας right-censoring. Κύρια μέτρα **PR-AUC και Brier skill**,
    AUC δευτερεύον, cluster-bootstrap διαστήματα, ζώνες κατάταξης (~28 γεγονότα/έτος → ±0,03–0,05 στο AUC). (BM-3/4/5)
  - **T2a** μόνο πιστωτικό γεγονός (8-K 1.03/2.04/3.01)· **T2b** ο κανόνας ισολογισμού του `REVISION_PLAN_3` §4,
    δηλωμένος ως proxy. (BM-2)
  - **T3** ταμειακές ροές/FCF ένα έτος μπροστά, CRPS, με και χωρίς realized revenue.
  - Splits = **τα cutoffs του paper (2015/2020/2022)** walk-forward, purge κατά τον ορίζοντα, cutoff στο acceptance
    time, το 2020 χωριστά· έτσι το baseline FinTwin είναι η έξοδος του paper. (BM-6, AR-19)
  - Baselines: base rate, Altman Z″, Ohlson O, Shumway, CHS-lite, logit, 16q margin, LightGBM/CatBoost/XGBoost, RF,
    TabPFN, AutoGluon, FinTwin· για T3 χρονοσειρές. Δηλωμένο budget tuning. (BM-12, FR-12)
- **B2** `fintwin.bench`: `load`, `evaluate` σε μία γραμμή, έλεγχος `filed <= cutoff`, εντολή leakage audit, clipping
  πιθανοτήτων, hashed IDs, hash του snapshot στην υποβολή. (BM-7/14)
- **B3** Στο launch 2 **στατικός πίνακας baselines**. Αυτόματη επανεκτέλεση υποβολών αργότερα, μόνο με γραμμένους κανόνες
  sandbox: `pull_request` με `permissions: {}`, έγκριση για fork PRs, εξαρτήσεις πρώτα και μετά εκτέλεση με
  `--network none` μόνο πάνω στα features, βαθμολόγηση σε χωριστό job, εγγραφή μέσω `workflow_run`. Βαριές υποβολές
  χειροκίνητα, label «maintainer-rerun». (BM-8, AR-15, OG)
- **B4** Prospective track: **το αρχείο ξεκινά τώρα** (G0), ανεξάρτητα από το benchmark: κάθε εβδομάδα τα scores του
  twin και 2–3 baselines σε Parquet + SHA256 σε GitHub release. Σταθερό ημερολόγιο, παγωμένο universe ανά γύρο, tracks
  που κρίνονται γρήγορα (1 τρίμηνο, T3)· **καμία δήλωση κατάταξης τον πρώτο χρόνο** (~25–30 γεγονότα). Βαθμολόγηση σε
  σχέση με ένα δεσμευμένο baseline. (BM-9/17, OG-15)
- **B5** Baselines στον burst server· το baseline FinTwin από το run του paper (αλλιώς ~6–7 h cax31). (AR)
- **B6** Paper datasets & benchmarks (π.χ. NeurIPS D&B ή Scientific Data), datasheet, ablation first-reported vs
  restated. (BM-15/16)

### W. Dashboard (launch 3)
- **W1** Μετρήθηκε: ~13,5 s/εταιρεία, 5.300 ≈ 75–80′/εβδομάδα σε δωρεάν runners, **μόνο αν τα shards δεν καλούν την SEC** (H5).
- **W2** Universe από SEC (όχι Wikipedia), φίλτρο: τελευταία περιοδική κατάθεση < 6 μήνες + κανόνας για το ποιες
  εταιρείες παίρνουν σελίδα που γίνεται index. Τομείς SIC → FF12 (αλλάζει ο υπολογισμός sector norms). Το `index.json`
  σταματά να γίνεται commit στο main (`data.yml:113-118`). (AR-14, PX)
- **W3** Path routes + SSR-ready views με δεδομένα ως props + hydration (1–1,5 εβδ.)· μοναδικοί τίτλοι και περιεχόμενο,
  JSON-LD Dataset, `lastmod` από ημερομηνία κατάθεσης, μόνιμο JS redirect από τα `#…`, προσοχή στο status του `404.html`. (AR, PX-8)
- **W4** Σελίδες τομέα, εβδομαδιαίων αλλαγών και εννοιών πρώτα· feeds ανά ticker, watchlist, SVG badges/widgets ανά
  ticker (backlinks), πάνελ «Χρησιμοποίησε αυτά τα δεδομένα» → notebook/loader. (PX-4/6/12/13)
- **W5** Κλίμακα: `index.json` στρογγυλεμένο και σπασμένο (`index_min` + lazy), virtualised palette και πίνακες
  (`CommandPalette.tsx:15-31,61-64`, `CompareView.tsx:41`, `TwinView.tsx:86`, `VersusView.tsx:26`), LRU στο
  `data.ts:91-100`· μέγεθος site **370–530 MB**· κοντά στο 1 GB → company JSON στο HF. Lighthouse + axe-core στο CI. (AR-14, PX-7)
- **W6** Κριτήρια προσβασιμότητας και mobile. (PX-7)

### M. MCP (launch 3)
- **M1** Tools γύρω από δουλειές agent, περιορισμένο μέγεθος απάντησης, υποχρεωτικά πεδία provenance/caveat και μια
  έτοιμη πρόταση για παράθεση. Τοπικό stdio πρώτα. (PX-5)
- **M2** Επαλήθευση αριθμών + σουίτα τεστ παραποίησης· notebook που επαναλαμβάνει καταγεγραμμένες συνομιλίες. (PX, AR-16)
- **M3** MCP registries, έτοιμα config snippets, `llms.txt`, JSON ανά σελίδα. (PX-16)

### D. Notebooks και docs
- Launch 1: **#0** μία εταιρεία σε 60 s, χωρίς κλειδιά, με γράφημα· **#1** look-ahead (R)· **#2** μοντέλο χρεοκοπίας σε
  20 γραμμές. Τρέχουν σε CI πάνω στο `sample` με pinned revision, σε αλλαγές docs και κάθε νύχτα. (AR-16, PX)
- Launch 2: αναπαραγωγές δημοσιευμένων αποτελεσμάτων (accruals, distress, restatements, PEAD/SUE), Carnival stress test,
  δικό σου σενάριο· mkdocs site με Data dictionary από το H7. (FR-15)

### G. Παρουσίαση, κοινότητα, launches
- **G1 πρώτο και φθηνότερο:** νέο README: μία φράση αξίας, το μονοπάτι των 60 s, πίνακας «τι δίνει η SEC / τι
  προσθέτουμε» με ένα επαληθευμένο παράδειγμα όπου ο αφελής δρόμος δίνει λάθος νούμερο. (OG-8/12)
- **G2** Φόρμα «data error» τώρα, αφαίρεση του topic `hacktoberfest`, topics για PIT, πολιτική για χαμηλής αξίας PRs,
  `GOVERNANCE.md` με δήλωση single maintainer, καθαρισμός root. (OG)
- **G3** 8–10 πραγματικά good-first-issues με pointers σε αρχεία και failing tests· all-contributors. (OG)
- **G4 Launches:**
  - **Human beta πριν από κάθε launch**: οι ερευνητές που απάντησαν + 3–5 χρήστες· 5–8 συνεδρίες usability για το
    launch 3. Οι agent reviewers δεν αρκούν. (OG-2, PX)
  - Launch 1: **Show HN για το dataset/loader** (όχι για το εύρημα), Τρ–Πε 8–10 π.μ. ώρα Ν. Υόρκης, έτοιμο πρώτο σχόλιο
    (τι είναι, τι δεν είναι, γνωστά κενά, πώς αναφέρεις λάθος), ποτέ αίτημα για upvotes· αν βυθιστεί, email στους
    moderators για second chance. Τίτλοι: «Show HN: Free point-in-time SEC fundamentals for ~5,000 companies, including
    bankrupt ones» ή «Show HN: As-first-reported SEC financials (filed-date vintages), CC-BY». Χωρίς «digital twin», «AI»,
    «stress testing» στον τίτλο. Η μελέτη R ως link στο πρώτο σχόλιο, το blog post άλλη μέρα. (OG-7)
  - Μετά: r/algotrading, r/quant, r/datascience, r/Python, HF· PRs σε awesome-quant, awesome-public-datasets,
    financial-machine-learning· PyCoder's Weekly. Launch 3: MCP registries, Search Console.
  - Όχι launch 20/12–6/1. Καθαρό ημερολόγιο τη μέρα του launch.
- **G5** pyOpenSci, JOSS, data-descriptor paper μετά το launch 2. CITATION.cff, concept + version DOIs, log διορθώσεων. (FR-14)
- **G6** Εβδομαδιαίο triage (όχι υπόσχεση 48 h), release μόνο όταν υπάρχει κάτι, newsletter/auto-post από το feed
  αλλαγών (launch 3), σελίδα «φρεσκάδα δεδομένων». (OG, PX)

## 4. Σειρά και gates

**Κανόνας κλάδων (AR-13):** μέχρι το `v3.0.0` το `lib` δέχεται **μόνο νέα αρχεία**. Μετά το tag: merge του rev3 στο main,
νέο `lib` από το main, μία μηχανική αλλαγή paths, και τεστ ισοδυναμίας με το paper (30 εταιρείες × 1 cutoff, bit-for-bit
με τα shards του `v3.0.0`).

| Φάση | Τι | Gate |
|---|---|---|
| **G0** τώρα, παράλληλα με rev3 | ADR-001/002/003· pre-spec και **R0 go/no-go**· νέο README (G1) και G2· **αρχείο prospective (B4)** και **Action για την κίνηση του GitHub** (ενότητα 8)· νέο `LICENSE-DATA`/`THIRD_PARTY.md` | ADRs εγκεκριμένα, απόφαση R0 |
| **rev3** | dry → full run → paper | tag `v3.0.0` |
| **G1** loader + dataset | L1, L2-δεδομένα, L4–L6, H1–H8, R1 | hub == frozen· read-only site-packages· πύλες πράσινες· πίνακας κάλυψης· H3b· dataset ιδιωτικό στο HF |
| **Beta 1** | 3–5 άνθρωποι, H3c αν βρεθεί WRDS | ευρήματα ενσωματωμένα |
| **Launch 1** | `3.1.0` στο PyPI, dataset δημόσιο, Show HN | δική σου έγκριση |
| **G2** | L2-twin (PIT calibrate), B1–B6, docs site, notebooks launch 2 | twin == research calibrate· leakage audit πράσινο |
| **Beta 2 → Launch 2** | | |
| **G3** | W, M, A11 | νομικός έλεγχος διατύπωσης· Lighthouse/axe· κανόνας index σελίδων· usability |
| **Launch 3** | | |

**Χρονοδιάγραμμα (AR-21)**, μετά το `v3.0.0` (~μέσα Νοεμβρίου):

| Ροή | Εκτίμηση |
|---|---|
| L (χωρίς twin) | 1,5–2 εβδ. |
| H1–H8 | 3–4 εβδ. + ~8 h server |
| R1 | 1 εβδ. |
| L2-twin | ~1 εβδ. |
| B | 2–2,5 εβδ. |
| W | 3–4 εβδ. |
| M | 1 εβδ. |
| D | 1,5–2 εβδ. |

→ **Launch 1 μέσα–τέλη Ιανουαρίου 2027**, launch 2 ~Μάρτιο, launch 3 ~Απρίλιο–Μάιο.
Κρίσιμη διαδρομή: L1 → `facts_raw` + `panel_vintages` → hub mode → R1 → beta → launch 1.

## 5. Ποιος κάνει τι

Κάθε ροή σε δικό της worktree/branch με τους κανόνες του `AGENT_BRIEF.md` (identity, χωρίς push, `interfaces/`,
`requests/`). **Καμία ροή δεν ξεκινά πριν περάσει review η ροή από την οποία εξαρτάται.** (OG)

| Εργασία | Ποιος |
|---|---|
| ADRs, pre-specs (R0, bench), αποφάσεις, merges, README, κείμενα launch | κύρια συνεδρία (Opus) |
| L1 + L2 (config, API, **εξαγωγή PIT twin**) | ένας Opus agent, πριν ξεκινήσει το H2 (AR-22) |
| H1 σχήμα, H6 hub mode | Sonnet υλοποίηση, **Opus review** (κρίνουν αν η βιβλιοθήκη αναπαράγει το paper) |
| H2 exporter, H3a, H4, H5, H7, H8 | Sonnet |
| H3b έλεγχος απέναντι στις καταθέσεις | Sonnet (διαβάζει 10-Q)· δειγματοληψία από την κύρια |
| R0/R1 | compute στον burst server· γραφή Sonnet, τελικό κείμενο κύρια |
| B1 | κύρια· B2–B5 Sonnet |
| W | Sonnet (frontend)· W3 SSR review Opus |
| M | Sonnet |
| D notebooks | Sonnet· link check Haiku |
| G2/G3 templates, labels, κείμενα PRs σε awesome lists | Haiku |
| Review πριν από κάθε launch | 3 φρέσκοι agents (code Opus, data Sonnet, «νέος χρήστης» σε καθαρό server Sonnet) **+ human beta** |

**Budget ανθρώπινου review:** πόσες ώρες/εβδομάδα μπορείς· ορίζει πόσες ροές τρέχουν παράλληλα.

## 6. Compute και κόστος

Burst server για R0 (~1 h cax21), `panel_vintages` (~8 h 2×cax31), baselines, first-run tests: εκτίμηση < 3 EUR μέχρι το
launch 1. Εβδομαδιαίο build σε δωρεάν Actions (με bulk archives της SEC). HF δωρεάν όσο μένει σε λίγα GB (αλλιώς storage
grant, Zenodo ως εφεδρεία). (DE-20)

## 7. Τι χρειάζεται από σένα

1. Έγκριση των ADRs του G0 και των A1–A14.
2. Ώρες/εβδομάδα για review.
3. PyPI/TestPyPI + pending trusted publisher· λογαριασμός HF και `HF_TOKEN` σε GitHub environment.
4. Επαφή με τους ερευνητές για beta (και αν κάποιος έχει WRDS για το H3c).
5. Custom domain (launch 3) και νομικός έλεγχος διατύπωσης (A11).
6. Έγκριση πριν από κάθε δημόσια κίνηση· τα posts από τους λογαριασμούς σου.

## 8. Μετρικές, όρια, σχέδιο αποτυχίας (OG-17/19)

- Από τώρα: εβδομαδιαίο Action που αποθηκεύει την κίνηση του GitHub (το API κρατά 14 μέρες)· cookieless μετρητής στο
  Pages· **καμία telemetry στη βιβλιοθήκη**.
- Όρια για 90 μέρες μετά το launch 1, προκαθορισμένα: 500 PyPI downloads/μήνα χωρίς mirrors, 300 HF downloads,
  5 εξωτερικά issues (≥ 2 για λάθη δεδομένων), 1 εξωτερικό PR που δεν είναι docstring, 2 citations.
- Αν δεν πιαστούν: συνεντεύξεις με 5 χρήστες που ήρθαν και έφυγαν, αλλαγή αγκίστρου ή κοινού, όχι repost.

## 9. Ευρήματα έρευνας G0 (28-10)

**Benchmark, τι είναι καινούριο.** Κοντινότερα: V4FinBench (2026, Visegrad, label από λογιστικό κανόνα, χωρίς PIT),
EDGAR-CORPUS/ECL (LoPucki labels, Compustat, ετήσια), arXiv 2606.05623 (10-K κείμενο). Live/prospective: ForecastBench,
Foresight Arena, TS-Arena, κανένα σε credit. **Λέμε** «δεν βρήκαμε προηγούμενο» για: ανοιχτό CC-BY PIT panel XBRL· labels
από ημερομηνίες 8-K 1.03 σε 4/8 τρίμηνα· task ρευστότητας· CRPS για ταμειακές ροές· prospective track σε credit.
**Δεν λέμε** «πρώτο».

**Άδειες ανά σειρά.**

| Σειρά | Στο CC-BY dataset |
|---|---|
| BAA10Y (Moody's) | Όχι· αφαιρείται |
| Philly Fed RTDSM | Όχι· script, ή BEA/ALFRED vintages μετά από έλεγχο |
| Damodaran rating spreads | Όχι· κατεβαίνει τοπικά με αναφορά |
| Wikipedia S&P/GICS | Όχι (CC BY-SA)· universe/τομείς από SEC |
| DGS3MO, DGS10 | Ναι, από Treasury/H.15, ξεχωριστό config |
| GDP | Ναι, από BEA, ξεχωριστό config |
| USREC | Ναι, από ημερομηνίες NBER με αναφορά |
| FASB taxonomy | Μόνο ονόματα tags |

**Weekly build:** ~13,5 s/εταιρεία· 5.300 χωρούν στα δωρεάν runners (~75–80′) αν τα shards δεν καλούν την SEC.

## 10. Κίνδυνοι

| Κίνδυνος | Αντιμετώπιση |
|---|---|
| Αδύναμο άγκιστρο | R0 go/no-go πριν χτιστεί οτιδήποτε γύρω του |
| Κριτική για ποιότητα / «αυτό το δίνει ήδη η SEC» | H3a–c δημοσιευμένα, πίνακας σύγκρισης στο README |
| Κακό εβδομαδιαίο build | staging PR, πύλες, rollback < 24 h + ανακοίνωση |
| Αποκλεισμός IP από την SEC | bulk archives, κοινό limiter, διακόπτης 403, shards χωρίς SEC |
| Μόλυνση άδειας (CC BY-SA, Moody's, Philly Fed) | A6, `THIRD_PARTY.md`, έλεγχος wheel στο CI |
| Προσωπικά δεδομένα από 8-K | μόνο κωδικοί items |
| Διαρροή HF token | environment, ξεχωριστό publish job, ελάχιστο scope |
| Σπασμένα pins | κανένα squash, immutable tags |
| Υπερπροσαρμογή στο ιστορικό leaderboard / ξένος κώδικας στο CI | A10, B3 sandbox |
| Απόκλιση από Compustat / κατάχρηση pre-2011 δεδομένων | H3c, πίνακας κάλυψης |
| Ποινή SEO για thin content / παράπονο εταιρείας για «κίνδυνο χρεοκοπίας» | A9, A11, νομικός έλεγχος |
| Παραποίηση από LLM | M1/M2 |
| Burnout ενός maintainer | τρία launches, εβδομαδιαίο triage, αυτοματοποίηση |
| Κάποιος πάρει το όνομα | `3.1.0` στο τέλος του G1 |

## 11. Θέση v3 (10-11-2026): το ανοιχτό testbed δυσπραγίας χωρίς look-ahead

Ο στόχος του maintainer: λίγα αλλά άψογα δεδομένα, χωρίς βαρύ υπολογισμό, μοναδικό στον κόσμο. Συμπέρασμα από
έλεγχο ανταγωνιστών σε πρωτογενείς σελίδες (10-11):

| Πηγή | Ανοιχτό | PIT (acceptance time) | Χωρίς survivorship | Τριμηνιαίο, de-cumulated, 52/53 | Labels χρεοκοπίας | Prospective |
|---|---|---|---|---|---|---|
| **FinTwin** | ναι (MIT / CC-BY) | ναι | ναι (XBRL εποχή) | ναι | census 8-K 1.03, recall μετρημένο (FR-11) | ναι (B4) |
| HF `ttchopper/openfundex` | CC-BY | όχι (filing_date, FSDS) | εν μέρει (λείπει το 21% των χρεοκοπιών, δική τους δήλωση) | δεν αναφέρεται | 8-K 1.03 | slice 2024+, όχι προκαταχωρημένο |
| Valuein | όχι (ιδιόκτητη άδεια δεδομένων) | ναι | ναι | ναι (χωρίς 52/53) | όχι | όχι |
| Tradevo | όχι ($29/μήνα) | filing date | ; | όχι (ετήσιο) | όχι | όχι |
| LoPucki BRD | δωρεάν πίνακας | όχι | ; | όχι | ναι, μεγάλες εταιρείες, **σταμάτησε 12/2022** | όχι |
| Look-Ahead-Bench, OpenFinArena | ναι | ; | ; | όχι | όχι | live, αλλά όχι δυσπραγία |

**Η θέση:** *το ανοιχτό, αναπαραγώγιμο testbed για πρόβλεψη εταιρικής δυσπραγίας χωρίς look-ahead*. Τρία κομμάτια, με
αυτή τη σειρά προτεραιότητας:
1. **Prospective track (B4) πρώτο, γιατί η αξία του μεγαλώνει μόνο με τον χρόνο:** κάθε εβδομάδα που δεν αρχειοθετείται
   χάνεται για πάντα. Δεσμευμένες προβλέψεις (SHA256 + release timestamp) πριν από τα γεγονότα: εκεί το look-ahead
   είναι εξ ορισμού αδύνατο, και αυτό χρειάζονται τα papers του 2025-26 για το look-ahead bias των LLM.
2. **Λίγα, άψογα δεδομένα:** ~25 βασικά μεγέθη ανά τρίμηνο (όχι εκατομμύρια facts), κάθε τιμή με accession και
   acceptance time, αναφορά ποιότητας, recall των labels απέναντι στο BRD.
3. **Labels:** το census 8-K 1.03 (+2.04/3.01) εβδομαδιαία, εκεί που το BRD σταμάτησε.

Ο twin μένει τίμιο baseline και stress lab· το «η προσομοίωση δεν βελτιώνει την κατάταξη» είναι επιχείρημα
αξιοπιστίας. Απέναντι στο openfundex λέμε ρητά και μετρημένα: acceptance-time vintages, πληρότητα του census, σωστά
τρίμηνα, μόνο μη χρηματοοικονομικές, προκαταχωρημένο prospective track. Κόστος υπολογισμού: το weekly build ήδη
τρέχει δωρεάν στο GitHub Actions· το archive προσθέτει δευτερόλεπτα.
