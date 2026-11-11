# engine-data review (engine/fintwin/data/, engine/fintwin/export.py)

Read-only review. Paths relative to engine/fintwin/.

### D1 USREC recession regime is not point in time (look-ahead)
- where: data/fred.py:68-94 (recession_regime), 77-80
- severity: bug
- changes numbers: yes (needs owner decision)
- issue: With `asof`, `rec` is today's NBER-dated USREC cut at `asof`. NBER announces peaks and troughs 6-21 months late, so at a past cutoff the series already "knows" a recession ended or began before NBER said so; `in_recession_now`, `exit` and `hazard` all use that. Before 2010 (no Philadelphia Fed vintage) `gdp` also falls back to today's revised GDP. This input is not covered by the "look-ahead-safe" claim.
- fix: lag USREC by the NBER announcement dates (about 12 dates, flag a regime only from its announcement), or state in the docstring and the paper's limitations that the regime is ex post. Do not change silently while the paper run is in flight.
- effort: M

### D2 Rate-limit handling: 403 and Retry-After ignored, `_download` retries with no backoff
- where: data/edgar.py:74-89; data/xbrl_fallback.py:121-131
- severity: risk
- changes numbers: no
- issue: SEC answers an over-limit client with 403 (and sometimes 429 with Retry-After). `_get_json` retries only 429/5xx, ignores `Retry-After`, and `raise_for_status()` on a 403 aborts at once. `_download` catches every `RequestException` (404 and 403 included) and retries three times back to back with only the 0.15 s throttle, the pattern that prolongs an SEC block.
- fix: one shared `_fetch(url)` in edgar.py used by both: retry 429/403/5xx and connection errors with `max(Retry-After, 5*2**attempt)`, fail fast on other 4xx; `_download` calls it.
- effort: S

### D3 `frame()` swallows every HTTPError, so a rate limit silently shrinks the universe
- where: data/edgar_universe.py:112-119
- severity: bug
- changes numbers: no (only a rebuild of universe_edgar.csv)
- issue: `except requests.HTTPError: return []` is meant for "tag not used that year" (404), but after the retries a 429/403/5xx lands there too and the (tag, year) counts as empty (and is not cached). `candidates()` then drops companies with no warning; the CSV feeds the research universe.
- fix: `except requests.HTTPError as e: if e.response.status_code != 404: raise; return []`.
- effort: S

### D4 Cache files are written non-atomically; a truncated file breaks every later run
- where: data/edgar.py:91-92; data/xbrl_fallback.py:127; data/fred.py:35; export.py:165-168
- severity: risk
- changes numbers: no
- issue: A kill or full disk mid-write leaves a truncated gzip/CSV with a fresh mtime. The reader (edgar.py:69-70) then raises on every run until the file is deleted; in frozen/fill-only mode it counts as present and is never refetched. Two threads fetching the same name can interleave. `_write` in export.py can leave a half-written company JSON for the web app.
- fix: write to a `.tmp` sibling and `os.replace`; put it in one small helper.
- effort: S

### D5 `augment()` hides all failures and can mix vintages into a "frozen" data set
- where: data/xbrl_fallback.py:215-238, 40
- severity: risk
- changes numbers: only in the failure or mix case
- issue: (a) `except Exception: return raw` and the inner `except Exception: continue` drop the fallback on any error, including FrozenMiss for a missing submissions file, so two runs can load different data with no log line or note. (b) companyfacts honours FINTWIN_FACTS_MAX_AGE but `periodic_filings` reads submissions with a fixed 24 h age, so an old, frozen companyfacts is topped up with filings it never held (frozen/fill_only mask this, a plain max-age run does not).
- fix: catch narrowly (`requests.RequestException`, `FrozenMiss`, `ET.ParseError`), keep the failures in `raw["_fallback_errors"]` and surface them as a `CompanyData` note; pass the same max age to `periodic_filings`.
- effort: M

### D6 Submissions paging duplicated, two max ages on one cache file
- where: data/xbrl_fallback.py:38-56 vs data/edgar_universe.py:122-129
- severity: slop
- changes numbers: no
- issue: Both read `submissions_{cik}.json` and its older pages; one with a 24 h limit, the other 30 days. Whichever runs first decides freshness for the other.
- fix: one `edgar.submission_pages(cik, max_age_hours)`; both callers use it.
- effort: S

### D7 `_instance_name` is a revision-2 relic that now only detects inline files
- where: data/xbrl_fallback.py:64-79, 199-212
- severity: slop
- changes numbers: no
- issue: In non-legacy mode `_instance_name` is called only to see whether an `_htm.xml` exists, then `_index_names` is called again and `instance_candidates` repeats the same inline check. The legacy chooser hand-lists suffixes instead of using `LINKBASE_SUFFIXES`; `(exact or xml or [None])[0]` is hard to read.
- fix: fetch `names` once; non-legacy loops over `instance_candidates(names, primary)` (inline file is already first and `is_instance` is cheap); keep `_instance_name` only for the legacy path.
- effort: S

### D8 `fred.py`: `__import__("math")`, no retry, vintage CSV re-read per call
- where: data/fred.py:84 (also 33, 57)
- severity: slop
- changes numbers: no
- issue: `gdp.apply(lambda x: __import__("math").log(x))` is `np.log(gdp)` written the long way. `fred_series` has no retry or User-Agent, unlike edgar, so one transient 5xx kills a long run. `gdp_vintage` re-reads and parses the vintage CSV on every call (once per cutoff x company).
- fix: `yoy = np.log(gdp).diff(4).dropna()`; use the shared fetch helper from D2; `lru_cache` a `_vintages()` reader.
- effort: S

### D9 `build_backtests` has an `if True:` scaffold and an unused unpack
- where: export.py:363-394
- severity: slop
- changes numbers: n/a
- issue: The body sits under `if True:` (left from deleted code). `rows` is built with `for ck in [r["cutoff"]]` just to rename a variable and then unpacked as `for _, _, v, s in rows`; only `v, s` are used.
- fix: dedent; build the frame directly from `for r in bt["forecast"].values() for v, s in r["scores"].items()`.
- effort: S

### D10 `golden_cases` rewrites the TS parity goldens from live, network-refreshed data
- where: export.py:273-315, 354-355, 321
- severity: risk
- changes numbers: n/a (web test fixtures)
- issue: `load_company(ticker)` uses the 24 h cache, so every multi-ticker `export` run rewrites the six `__golden__` files from whatever EDGAR serves that day; goldens drift for reasons unrelated to the engine and the diff is noisy. `meta_block()["generated"]` is `date.today()`, so index.json also changes daily with no data change.
- fix: regenerate goldens only on the explicit `GOLDEN` argument (drop the `len(tickers) > 1` trigger) or from a frozen snapshot.
- effort: S

### D11 `SECTORS` (90 entries) is a dead-weight fallback; `classify` called twice
- where: export.py:44-139, 259-260
- severity: slop
- changes numbers: no
- issue: SECTORS is consulted only when `classify()` returns "", and its labels ("Cruise", "Mobility") do not match the GICS labels the index otherwise carries. `classify(c.ticker)` runs twice on adjacent lines.
- fix: check whether any ticker in SHOWCASE/UNIVERSE/UNIVERSE_XL hits the fallback; if none, delete SECTORS; call `gics, sector = classify(...)` once.
- effort: S

### D12 `quality_report` crashes on an empty panel; misnamed variable
- where: data/quality.py:7-14, 17, 29
- severity: risk
- changes numbers: no
- issue: `q.index[-1]` and `q.index[0]` raise IndexError for a company with no reported revenue quarters (e.g. no USD facts: `_usd_facts` reads only the `USD` unit, `_spine` then returns an empty frame and `load_company` does not complain). `implied_nwc_cash = q["cash"].diff()` is used only for a count and has nothing to do with working capital.
- fix: raise a clear `ValueError("no reported quarters")` in `load_company` when the spine is empty; rename to `cash_change`.
- effort: S

### D13 `load_company` is ~120 lines with a duplicated notes loop and a verbatim legacy twin
- where: data/facts.py:525-642 (loops at 571-573 and 591-593), 657-791
- severity: slop
- changes numbers: no
- issue: "no data, assumed 0" notes come from two loops over overlapping field lists (payables and deferred_revenue split off for no reason), then ZERO_IF_NEVER_TAGGED zero-fills a third list. The legacy loader repeats the operating-income rebuild and impairment block line for line, to be kept in sync by hand.
- fix: one loop over `ZERO_IF_NEVER_TAGGED` emitting the note before zero-filling (note order changes, values do not; check no test asserts on order); extract `_adjust_operating_income(q, notes)` for both loaders; split load_company into extract / normalise / derive.
- effort: M

### D14 `imputed` never flags a zero-filled `total_debt`
- where: data/facts.py:548, 603-608, 632
- severity: risk
- changes numbers: no (metadata)
- issue: `reported = q.notna()` is taken before `total_debt` exists, so it falls under `fill_value=True` and is never marked imputed, although the field comment says "carried forward or zero-filled" (D3 assumes 0 for a company that never tags debt). Rebuilt operating income is flagged imputed, so the mask mixes "filled" and "derived".
- fix: compute `total_debt`'s mask from the ffilled debt parts (or set it explicitly when `debt_untagged`), and state in the comment what `imputed` covers.
- effort: S

### D15 `ticker_to_cik`: any ticker starting with "CIK" is parsed as a key; inline imports
- where: data/edgar.py:99-114
- severity: risk
- changes numbers: no
- issue: `ticker.upper().startswith("CIK")` then `int(ticker[3:])` raises ValueError for a real ticker such as CIK; api.py:64 maps only "Unknown ticker" to a 404, so it becomes a 500. `import csv` is done inline twice and both CSVs are re-read on each call.
- fix: `re.fullmatch(r"CIK\d{10}", t.upper())`; module-level `import csv`; small `lru_cache` readers.
- effort: S

### D16 `edgar_universe.build` drops companies on any exception
- where: data/edgar_universe.py:163-168
- severity: risk
- changes numbers: no (universe build only)
- issue: `except Exception` + `continue` removes a company from the committed universe CSV after a transient failure; the only trace is one printed line and the final summary does not count them.
- fix: catch `requests.RequestException`, collect failed CIKs, print the count and exit non-zero so a partial build is not committed by accident.
- effort: S

### D17 `sp500_on` wikitext parsing is positional and fails opaquely
- where: data/edgar_universe.py:213-239
- severity: risk
- changes numbers: no
- issue: `cells[2]` and `cells[3]` index by position after a regex split, so a row with other columns raises IndexError with no ticker context; `["revisions"][0]` is a KeyError if the date precedes the first revision; rows without a known ticker template are skipped silently, so a short list is the only symptom.
- fix: assert the parsed count is about 495-510, print skipped rows, check `"revisions" in rev`.
- effort: S

### D18 A 200 response with an HTML body gives a bare JSONDecodeError
- where: data/edgar.py:89-90
- severity: risk
- changes numbers: no
- issue: SEC's "undeclared automated tool" page can arrive as HTTP 200 text/html; `resp.json()` raises JSONDecodeError (nothing cached, good) but with no hint, so in a loop over thousands of CIKs it looks like data corruption instead of a block.
- fix: catch `ValueError` and raise `RuntimeError(f"non-JSON response from {url} (status {resp.status_code}); check SEC_USER_AGENT and rate limit")`.
- effort: S

### D19 Periodic-form set differs between fallback and loader; awkward defaults
- where: data/xbrl_fallback.py:28, 47, 53 vs data/facts.py:40
- severity: slop
- changes numbers: no
- issue: facts accepts 20-F and 40-F, the fallback completes only 10-K/10-Q/10-KT variants; the two lists are kept in sync by hand. `p.get("isXBRL", [0] * (i + 1))[i]` and the `primaryDocument` equivalent are a roundabout `p["isXBRL"][i]`.
- fix: define the form sets once (edgar.py) and index the page dict directly.
- effort: S

### D20 No tests for fred.py, quality.py, `history_block`, `build_backtests`
- where: tests (none cover data/fred.py, data/quality.py, export.history_block)
- severity: test
- changes numbers: n/a
- issue: The recession regime (hazard, exit, shortfall) and `history_block` (TTM via `ok4`, ICR only for interest > 0, provenance links) have no unit test. `history_block` is exactly the series the web app plots. Export tests cover only `_clean`, `dumps`, `index_entry`.
- fix: a synthetic-quarters test for `history_block` (a gap row makes TTM null, interest <= 0 gives null ICR) and a short USREC fixture for `recession_regime`.
- effort: M

### D21 Fetch retry/failure paths are untested; one test asserts a vacuous bound
- where: tests/test_edgar_rate_limit.py, tests/test_frozen.py:30-45
- severity: test
- changes numbers: n/a
- issue: `_get_json` is tested only with a 200 response. The 429/5xx backoff, final-attempt raise, 403, FrozenMiss, and a truncated cache file are never exercised. `test_frozen` asserts `all(s <= _MIN_INTERVAL for s in slept)`, which also holds when nothing sleeps.
- fix: fake `requests.get` returning [429, 200], [500]*4, [403], plus a truncated cache file; assert call counts and raised types.
- effort: S

### D22 `interest_expense` shares the "payments are positive" rule with capex
- where: data/facts.py:189, 82-96
- severity: risk
- changes numbers: yes (needs owner decision)
- issue: A quarter where `InterestExpense` is negative (credit, reversal, or net interest income) is set to missing and the operating-income rebuild then adds 0; if most quarters are negative the whole series is flipped. Likely rare; the only trace is a note.
- fix: leave for the pre-registered run and list in limitations; next revision restrict the rule to capex, dividends, buybacks.
- effort: S

### D23 Magic numbers without a named constant
- where: data/facts.py:110 (350-380), 119 (380), 618 (1.05); data/quality.py:17 (tail 20), 29 (450)
- severity: slop
- changes numbers: no
- issue: These thresholds are inline while sibling thresholds (QUARTER_DAYS, SPLICE_TOLERANCE, BALANCE_FFILL_LIMIT) are named and explained.
- fix: `FISCAL_YEAR_DAYS = (350, 380)`, `DEBT_OVER_LIABILITIES = 1.05`, `LADDER_STALE_DAYS = 450`, each with a one-line reason.
- effort: S

### D24 `export.build` keeps stale entries and still stamps the index as fresh
- where: export.py:334-360
- severity: risk
- changes numbers: no
- issue: A ticker that fails keeps its old index entry and company JSON while `meta.generated` is set to today, so the app shows old data as fresh. SystemExit comes only after the index is written.
- fix: drop or mark (`stale: true`) the failed ticker's entry, or write the index only when `failed` is empty.
- effort: S
