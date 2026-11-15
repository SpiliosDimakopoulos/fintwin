# Rerun 5: πλάνο μέχρι ένα σωστό, τελικό run (12-11-2026)

Στόχος: ένα full rerun (probe → dry → universe → sample → select → stats → cross-spec → sobol) που δεν χρειάζεται
επανάληψη. Τα ευρήματα με κωδικούς (S*, P*, D*) είναι στο `RERUN5_FIXPLAN.md`. Η δουλειά γίνεται στο worktree
`.claude/worktrees/nonfinite` (branch `fix/nonfinite-guards`), όπου ήδη υπάρχουν: guards για NaN, το τεστ v3 vs
v2-pre (S1, `fintwin/research/cross_spec.py`), 12 tests, και τα scripts του auditor (`engine/scripts/audit_draft/`).

## 0. Κανόνες
- **Καραντίνα:** τα νούμερα του run της 11/12-11 (`engine/out/`) δεν μπαίνουν στο paper και κανένας κανόνας απόφασης
  δεν αλλάζει εξαιτίας τους. Ό,τι επιλέγεται εδώ (π.χ. το primary cell του B2) επιλέγεται από το κείμενο του pre-spec.
- **Κάθε εύρημα R (μόνο από reviewer) αναπαράγεται πρώτα με test που αποτυγχάνει.** Αν δεν αναπαράγεται:
  «not reproduced» στο fixplan και καμία αλλαγή.
- **Κάθε αλλαγή κατατάσσεται** ως «διόρθωση bug» ή «επιλογή ανάλυσης μετά το pre-spec» στο συμπλήρωμα (WP8).
- **Βαρύ μόνο στον server** (x86 cpx42, όλα τα στάδια ίδια πλατφόρμα). Στο PC μόνο tests των αρχείων που αλλάζουν.

## 1. Αποφάσεις του owner (WP0, πριν από τον κώδικα που εξαρτάται από αυτές)
| # | Ερώτημα | Πρόταση |
|---|---|---|
| A1 | D4: ουρές Student-t (df=3 δίνει paths 1000× το median) | κόψιμο των τυποποιημένων draws στο ±10 σε κάθε spec (διόρθωση αριθμητικής, όχι μοντέλου)· οι medians δεν αλλάζουν |
| A2 | D5: health ανεβαίνει με βαθύτερο shock (12% των rows v3) | διερεύνηση 1 ώρα (μηχανισμός)· αν είναι συμπεριφορά του μοντέλου, αναφέρεται ως έχει, όχι διόρθωση |
| A3 | S2: ποιο cell του B2 είναι το primary | ο κανόνας του pre-spec: realized shock, 8 τρίμηνα, liquidity shortfall· τα άλλα 7 περιγραφικά |
| A4 | a reader | όμιλοι = robustness (τα αποτελέσματα ανά ticker μένουν primary)· age / base rate / filing = exploratory |
| A5 | MINOR (S7, P8, D7) | μόνο όσα αλλάζουν αριθμό ή κρύβουν σφάλμα· τα υπόλοιπα στο fixplan ως «γνωστά» |
| A6 | Commits | ένα commit ανά WP στο branch, με έγκρισή σου (ταυτότητα HANDOFF, χωρίς Co-Authored-By) |

**Απόφαση 12-11-2026:** ο owner ανέθεσε τις A1–A6 στην κύρια συνεδρία· ισχύουν οι προτάσεις του πίνακα, εκτός από
την A1: το κόψιμο των draws θα άλλαζε το v2-pre, που κατά το pre-spec είναι το μοντέλο του paper 2.0.0. Έτσι μπαίνει
μόνο αριθμητικό φράγμα (`G_LOG_MAX` = 50 στο log growth του τριμήνου, που αποτρέπει overflow → NaN και δεν δεσμεύει
κανένα ρεαλιστικό draw) και οι ουρές αναφέρονται ως ιδιότητα του μοντέλου (επηρεάζουν mean/CRPS, όχι medians). Τα commits
γίνονται τοπικά στο branch (κανένα push).

## 2. Πακέτα εργασίας (με αυτή τη σειρά)
| WP | Ευρήματα | Αρχεία | Test πρώτα | Done όταν |
|---|---|---|---|---|
| 1 Δεδομένα | D1, D2, D3, D7 (μηδενικά άλλων tags: διαγνωστικό) | `data/facts.py` (`_merge_tags`, `_duration_table`), `backtest/batch.py:227,245,350` | Alaska 766421, Dentsply 818479 (0 → μη μηδενικό tag), HP 47217 (αρνητικό τρίμηνο), Baxter 10456 (cash row), **και μια εταιρεία με πραγματικά μηδενικά έσοδα** (δεν πρέπει να «διορθωθεί») | μετρητής overrides στο `diag`· σάρωση όλου του snapshot στον server: πόσες εταιρείες πριν/μετά |
| 2 Engine | D1 guard (έσοδα ≤ 0 στο 32-τρίμηνο παράθυρο, `rev_ttm > 0` στο `usable()`), D4 (A1), D5 (A2), D6 (spec ρητά παντού, error αν λείπει), Sobol finite check | `stochastic/calibrate.py`, `shocks.py`, `research/experiments.py`, `assumption_sobol.py`, `stochastic/spec.py` | μονάδα με ένα μηδενικό τρίμηνο → error σε όλα τα specs· draws ≤ ±10· κλήση χωρίς FINTWIN_SPEC → σφάλμα | όλα τα specs απορρίπτουν τις ίδιες μονάδες |
| 3 Pipeline | P1, P2, P3, P5, P6, P8 (mkdir, set -e ανά ομάδα, logs ανά στάδιο, SOURCE.json καθαρό, versions στο run_meta) | `scripts/rev3_server.sh`, `research/__main__.py`, `assumption_sobol.py` | packer `.part` κάθε 20'· digest drift → άρνηση· άλλο `machine` → άρνηση· stats χωρίς wf πίνακα → FAIL | δοκιμή στο probe |
| 4 Stamp split | P9 | νέο `fintwin/clean.py` (`_clean`), `SHARD_FILES` + `analysis_digest` στο `__main__.py`, stats glue έξω από το shard path | εκτέλεση `company()` και `_one()` → `sys.modules ⊆ SHARD_MODULES`· shards γράφουν `_modules` | αλλαγή στο `stats.py` δεν ακυρώνει shards (test) |
| 5 Στατιστική | S2 (A3, + firm-block CI, block count), S3 (D8 στα B2/B3, `bk_2020` spans), S4 (`hybrid_train`), S5 (κοινά masks, αποτελέσματα και στην τομή v2-pre/v2-rev/v3-wf), P4 (Sobol attrition) | `research/stats.py`, `distress.py`, `transmission.py`, `experiments.py:276`, `assumption_sobol.py` | ένα test ανά εύρημα σε συνθετικά δεδομένα | S1 υπάρχει ήδη |
| 6 a reader | όμιλοι (κοινά accession σε 10-K/10-Q/8-K και amendments, union-find, ένα event ανά όμιλο-origin, cluster switch και στο `boot_losses`), rivals (age, base rate με Y−3 / `known_by`, 10-K/A, 4.02, NT) | νέο `research/families.py`, `research/rivals.py`, `stats.py` | δύο CIK με κοινή κατάθεση 10-Q → ίδιος όμιλος· Form 4 δεν ενώνει· base rate δεν βλέπει outcome μετά το origin | robustness και exploratory στο research.json, χωριστά από τα επιβεβαιωτικά |
| 7 Audit shards | το δομικό μέτρο: κάθε στάδιο ελέγχεται πριν πάει στο επόμενο | νέο `scripts/audit_shards.py` (από `scripts/audit_draft/`), κλήση στο τέλος κάθε σταδίου | κατώφλια: 0 None/NaN σε health, q, y· 0 log_rev ≤ 0· 0 y < 0· διαφορά μονάδων ανάμεσα σε specs = μόνο οι καταγεγραμμένες· όριο errors ανά τύπο | κόκκινο → το στάδιο αποτυγχάνει με exit ≠ 0 |
| 8 Τεκμηρίωση | καθάρισμα και συμπλήρωμα | σβήσιμο `scripts/stats_finite.py` και των γραμμών wrapper στο rev3· `REV3_LIGHT_PLAN.md` §8 → «αντικαταστάθηκε»· νέο §9: συμπλήρωμα με ημερομηνία (κάθε αλλαγή, κατηγορία, πόσες μονάδες αλλάζει)· header του `rev3_server.sh` (x86) | — | commit, hash στο συμπλήρωμα, πριν από το rerun |

## 3. Πύλες (καμία δεν παρακάμπτεται)
| Πύλη | Κριτήριο περάσματος |
|---|---|
| G1 | τα tests κάθε WP περνούν τοπικά· ruff καθαρό |
| G2 | δεύτερος γύρος 4 reviewers Fable στο τελικό diff, στο runbook και στα κατώφλια του audit: για κάθε εύρημα «fixed / not reproduced», και κανένα νέο BLOCKER ή MAJOR |
| G3 | probe στον server: όλο το test suite περνά, χρόνοι ανά στάδιο, σάρωση snapshot του WP1 |
| G4 | dry run 300 εταιρειών που **περιέχει υποχρεωτικά** 766421, 818479, 47217, 10456, 20212, 1320461 και τρεις με ομίλους: ladder → select → stats → cross-spec → μικρό Sobol → audit πράσινο· και πρόβα του lost-server resume (σβήσιμο server στη μέση, resume από τα pulled shards) |
| G5 | full rerun, audit πράσινο μετά από κάθε στάδιο |
| G6 | `down`, `status` χωρίς χρέωση, τύπος server + EUR στην αναφορά |

## 4. Runbook (από το `engine/`, με B=C:/Users/USER/claude_shared/burst/burst.py)
Πριν από κάθε server: `py scripts/source_stamp.py` (πρέπει `dirty: false`), hash του commit, `burst.py status`
(ελεύθερα ≥ 8 vCPU από τα 20), `freeze_snapshot.py verify` τοπικά.
```
python $B do . "bash scripts/rev3_server.sh probe"    --x86 --ram 16 --hours 3 --max-hours 6  --keep --exclude out --exclude .cache --pull "out/results_probe.tgz" "out/*.log" "out/run_meta_probe.json"
python $B do . "bash scripts/rev3_server.sh dry"      --x86 --ram 16 --hours 3 --max-hours 6  --keep --exclude out --exclude .cache --exclude snapshot --pull ... --partial-pull "out/results_dry.tgz"
python $B do . "bash scripts/rev3_server.sh universe" --x86 --ram 16 --hours 6 --max-hours 16 --keep (ίδια excludes) --pull ... --partial-pull "out/results_universe.tgz"
python $B do . "bash scripts/rev3_server.sh sample"   --x86 --ram 16 --hours 5 --max-hours 10 --keep ...
python $B do . "bash scripts/rev3_server.sh select"   --x86 --ram 16 --hours 5 --max-hours 10 --keep ...
python $B do . "bash scripts/rev3_server.sh stats"    --x86 --ram 16 --hours 5 --max-hours 10 --keep ...
python $B do . "bash scripts/rev3_server.sh sobol"    --x86 --ram 16 --hours 5 --max-hours 12 ...   (χωρίς --keep)
python $B down && python $B status
```
Μετά από κάθε στάδιο: exit 0, audit πράσινο, `run_meta` με το ίδιο code digest, `machine` x86_64, αρχείο pulled
(md5 ίδιο με τον server). Διακοπή αν: audit κόκκινο, digest διαφορετικό, errors > όριο, χρόνος > 1,5× του probe.
Pull κάθε σταδίου (`<s>` = όνομα σταδίου): `--pull "out/results_<s>.tgz" "out/*.log" "out/run_meta_<s>.json"`, και
**μόνο** στα probe, dry, universe, sample, select επιπλέον `"out/audit_*.json"` (στα stats/sobol το glob δεν βρίσκει τίποτα
και το pull αποτυγχάνει), με `--partial-pull "out/results_<s>.tgz" "out/*.log"`. Το audit γράφει
`out/audit_<s>_<run>.json`· κόκκινο σημαίνει exit 1 του σταδίου και το archive μένει για το pull. Χαμένος server:
βλ. header του `rev3_server.sh` (εξαγωγή σε άδειο κατάλογο, ποτέ στο `.cache`).

## 5. Ανάθεση
| Βήμα | Agent | Μοντέλο | Γιατί |
|---|---|---|---|
| WP0 αποφάσεις | κύρια συνεδρία + εσύ | Opus | επιλογές του owner |
| WP1, WP2, WP4, WP5, WP6 κώδικας και tests | κύρια συνεδρία | Opus | λεπτές αλλαγές σε αριθμούς του paper |
| WP3 pipeline | κύρια συνεδρία | Opus | κρίσιμο για την απώλεια shards |
| WP7 audit script | κύρια συνεδρία, από τα scripts του auditor | Opus | κατώφλια = απόφαση |
| Σάρωση snapshot (WP1), μετρήσεις, ανάγνωση logs | bulk-reader / Explore | Haiku | μηχανική δουλειά |
| G2 δεύτερος γύρος | 4 reviewers | Fable | ανεξάρτητη ματιά (ζήτησή σου) |
| G3–G5 runs | burst server | — | ποτέ στο PC |

## 6. Κόστος και χρόνος
- Δουλειά: WP1–WP8 περίπου 2–3 συνεδρίες· G2 ~1 ώρα.
- Server: probe + dry ≈ 3–4 ώρες ≈ 0,5 €· full rerun ≈ 18 ώρες ≈ 2,5 € (cpx42, 0,117 €/ώρα).
