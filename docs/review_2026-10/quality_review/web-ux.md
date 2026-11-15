# web-ux review (web/src/views, index.html, public, styles.css, plus App.tsx/ui.tsx/CommandPalette where views depend on them)

### W1 Failed data fetch leaves a skeleton forever (no error state)
- where: web/src/views/OverviewView.tsx:23, web/src/views/BacktestView.tsx:17-19, web/src/views/HeroSim.tsx:28
- severity: bug
- changes numbers: n/a
- issue: `loadCalibration().then(setCal)`, `loadResearch().then(setRes)` and `loadCompany("CCL").then(setC)` have no `.catch`. On a network error or 404 the promise rejects unhandled; Overview shows a 120px skeleton forever, Backtest shows `<Skeleton h={600}/>` forever (only `loadBacktest` is caught), the hero chart never leaves "…".
- fix: add `.catch` to each and render the same `callout` App uses; in BacktestView set `err` from all three loaders. A small `useLoad(fn)` hook returning `{data, error}` would replace the repeated effect pattern.
- effort: S

### W2 Index load failure shows a raw "TypeError: ..." above a permanent skeleton, with no retry
- where: web/src/App.tsx:55,120-121
- severity: bug
- changes numbers: n/a
- issue: if `loadIndex` fails, `error` is `String(e)` rendered above `<Skeleton h={420}/>` (since `!index`), so the page looks like it is still loading and tells the visitor nothing actionable.
- fix: when `error && !index` render only a plain message ("Could not load the data. Reload the page.") with a reload button; keep the raw message for the console.
- effort: S

### W3 No canonical link, structured data, noscript, or sitemap: the page is an empty shell to crawlers and no-JS readers
- where: web/index.html:1-29, web/public/robots.txt
- severity: risk
- changes numbers: n/a
- issue: body is only `<div id="root"></div>`; no `<noscript>`, no `<link rel="canonical">`, no JSON-LD, robots.txt has no `Sitemap:` and there is no sitemap.xml. Hash routes are not indexable, so the single real URL carries all SEO weight. `twitter:title` and `twitter:description` are missing (only card and image).
- fix: add canonical `https://spiliosdimakopoulos.github.io/fintwin/`, a `<noscript>` with the h1, description and links to paper/GitHub/data feed, JSON-LD `WebApplication` (name, description, url, applicationCategory FinanceApplication, author, isAccessibleForFree), twitter title/description, minimal sitemap.xml and `Sitemap:` line. Optionally prerender the hero h1 and lede into `#root`.
- effort: S

### W4 Static `<title>FinTwin</title>`; per-view titles and focus not handled
- where: web/index.html:25, web/src/App.tsx:83-86
- severity: risk
- changes numbers: n/a
- issue: the title is a bare brand name with no statement of what it is; per-view titles are not set (only the ticker prefix on company views), so Evidence, Method, Compare all read "FinTwin" in tabs and history. On route change only `scrollTo(0)` runs, so keyboard and screen-reader users get no focus move or announcement.
- fix: `<title>FinTwin: cash and debt stress tests for S&P 500 companies</title>`; set `document.title` to `${NAV label} · ${name}FinTwin`; move focus to the view's `<h1>` (or `main` with tabIndex=-1) in the effect next to `scrollTo`.
- effort: S

### W5 InfoTip definitions are unreachable for screen readers and touch users
- where: web/src/ui.tsx:64-70, web/src/styles.css:222-228
- severity: risk
- changes numbers: n/a
- issue: the button has `aria-label="More information"`, which replaces its content, and the `role="tooltip"` text has no `aria-describedby` link, so the definitions of Spearman, CRPS, conformal coverage (15 usages) are never announced. The popup opens only on `:hover`/`:focus-visible`; a tap on iOS Safari does not focus buttons, so nothing shows; Esc does not dismiss; hit target is 15px.
- fix: give the pop an id and set `aria-describedby`; toggle open state on click, close on Esc/blur; enlarge the hit area (padding or `::before`) to at least 24px.
- effort: M

### W6 Front-page numbers use unexplained jargon and an undefined 0-100 "health" scale
- where: web/src/views/OverviewView.tsx:50-66,99-107
- severity: risk
- changes numbers: n/a
- issue: the four headline metrics read "ρ 0.xx", "CRPS against a seasonal random walk", "calibrated interval coverage"; the definitions live only in the info tips (see W5). "Health today" and "In a demand freeze" are never defined: nothing says the scale is 0-100, higher is safer, or what 60 means. The hero (h1, lede, three buttons, live chart) does answer "what is this and what to click" well; it is the content below it that loses a non-quant.
- fix: add one plain-language line under the metrics (positive skill means better than repeating last year) and a one-line key next to the Six-twins table; pass `label` to the `Status` legend dots (prop exists) so the colours are named.
- effort: S

### W7 Hero chart cycles scenarios every 4.2 s with no pause control; weak accessible description
- where: web/src/views/HeroSim.tsx:35-40,52-53,70
- severity: risk
- changes numbers: n/a
- issue: auto-cycle runs until a chip is clicked (WCAG 2.2.2 wants a pause control for anything moving over 5 s); `matchMedia` is read once when the effect starts. `aria-label` on a plain `div` (no role) is ignored; the svg label is static with no numbers; the live readout changes with no `aria-live`.
- fix: add `role="group"` to the terminal, a Pause/Play button (or stop cycling on focus/hover inside it), put scenario, median health and run-out-of-cash % into the svg label, and mirror the readout in a `polite` live region only for user-initiated changes.
- effort: S

### W8 Clickable table rows rely on `tr` with `aria-label` and `tabIndex`; no real link
- where: web/src/ui.tsx:28-37, web/src/views/OverviewView.tsx:110, web/src/views/CompareView.tsx:124, web/src/views/TwinView.tsx:132
- severity: risk
- changes numbers: n/a
- issue: `rowActions` makes a `<tr>` focusable with no role; the `aria-label` on a row replaces its cell content for assistive tech (health values are skipped), and there is no href, so open-in-new-tab, middle-click and link lists do not work even though routing is hash-based and trivially linkable.
- fix: render the ticker cell as `<a href="#twin/AAPL">`, keep row click as a mouse convenience, and drop `tabIndex`/`aria-label` from the `tr`.
- effort: M

### W9 Command palette and help dialog: incomplete combobox/dialog ARIA, no focus management
- where: web/src/CommandPalette.tsx:57-68, web/src/App.tsx:136
- severity: risk
- changes numbers: n/a
- issue: input is `role="combobox" aria-expanded` (constant) with no `aria-activedescendant`, so arrowing through results is silent; dialogs lack `aria-modal`; the help dialog neither takes focus on open nor restores it on close.
- fix: ids on options plus `aria-activedescendant={sel option id}`, `aria-modal="true"`, focus the dialog on open and return focus to the opener.
- effort: M

### W10 Much secondary text is under 12px
- where: web/src/styles.css:127,222-223,233,249,283,298
- severity: risk
- changes numbers: n/a
- issue: axis ticks 10.5px, `.info` glyph 10px, `th` 11.5px, palette group 10.5px, `.hscale .ticks` 10px, `.kbd` 11px. On phones these are hard to read. (Contrast checked: `--muted` #6e6a61 on #f6f4ef is 4.9:1 and #949085 on dark is 5.9:1, so the colours pass; only the size is the issue.)
- fix: floor non-decorative text at 12px, and tick labels at 11px.
- effort: S

### W11 Small touch targets on mobile
- where: web/src/styles.css:117,137-138,197-200,222; web/src/views/TimeMachineView.tsx:82-92
- severity: risk
- changes numbers: n/a
- issue: nav buttons get 8px vertical padding at <=860px, `.info` is 15x15, chips and segmented buttons are compact, and Time Machine year buttons sit in a tight row; several fall below the 24x24 CSS px WCAG 2.2 minimum.
- fix: `min-height: 36px` (44px under `@media (pointer: coarse)`) for `.chip`, `.segmented button`, `.nav button`, `.info`.
- effort: S

### W12 Machine diagram clips on phones with no hint; scroller not keyboard-reachable
- where: web/src/views/MachineView.tsx:96-98
- severity: risk
- changes numbers: n/a
- issue: the 960x540 SVG has `minWidth: 640` in an `overflowX: auto` wrapper; on a 390px phone it is cut off with no affordance, text shrinks, and the scroller has no `tabIndex`, so keyboard users cannot scroll it. `role="img"` hides all the `<text>` values (stock levels, rating) from assistive tech.
- fix: `tabIndex={0} role="region" aria-label="Stock and flow diagram, scrollable"` on the wrapper, a "swipe to pan" hint under 680px, and a small visible table of the stock medians below the figure.
- effort: M

### W13 Stress lab: results update silently; on mobile controls and results are far apart
- where: web/src/views/StressLab.tsx:107-141,157; web/src/styles.css:307
- severity: risk
- changes numbers: n/a
- issue: moving a slider recomputes 2000+ paths with no status text for screen readers, and below 980px `.lab-controls` is `position: static` above the charts, so the visitor cannot see the effect of a slider without scrolling. Toggle descriptions are separate spans not linked by `aria-describedby`. The "Adjust scenario" link only goes one way.
- fix: add a visually hidden polite live line with headline health/breach after each run, and a sticky mini readout on mobile.
- effort: M

### W14 Cross-section bucketing copy-pasted between two views
- where: web/src/views/OverviewView.tsx:24-29, web/src/views/BacktestView.tsx:22-27
- severity: slop
- changes numbers: no
- issue: `rows`, `sorted`, `k = floor(n*2/5)` and `severe()` with the magic `-10` threshold are duplicated, and the same "two-fifths" / "10% of a year's revenue" appear again in prose strings; a change in one will silently diverge.
- fix: export `fragilityBuckets(xs)` from `data.ts`/`format.ts` returning `{rows, fragileSevere, robustSevere}` with `SEVERE_BURN_PCT = -10`, and use it in both.
- effort: S

### W15 Hand-copied inline styles instead of classes
- where: web/src/views/OverviewView.tsx:36-41,111-116, web/src/views/TwinView.tsx:49-51
- severity: slop
- changes numbers: n/a
- issue: the primary button (`background: var(--ink); color: var(--page); borderColor...`) is inlined in both Overview and TwinView, the "meter + number" grid `1fr 28px` appears four times, `padding: "9px 16px"` three times. Inline styles also prevent hover/active/focus variants for the primary button.
- fix: add `.btn-primary` and `.meter-cell` to styles.css and use them.
- effort: S

### W16 Large views with content tables embedded in JSX
- where: web/src/views/BacktestView.tsx (238 lines), web/src/views/StressLab.tsx (267), web/src/views/OverviewView.tsx:123-158
- severity: slop
- changes numbers: n/a
- issue: BacktestView mixes loading, two findings sections and a case-study explorer with its own three selectors; Overview defines the "how it works" and "limits" copy as tuple arrays inside the JSX, unlike `FEATURED` at module level.
- fix: hoist `HOW_IT_WORKS`/`LIMITS` to module constants; split BacktestView's case-study block (own state) into its own component.
- effort: M

### W17 Company fetch effect races and ref workaround in App
- where: web/src/App.tsx:59-63,86-95
- severity: slop
- changes numbers: n/a
- issue: the effect is keyed on `[ticker, view]`, so twin -> stress for the same ticker refetches (cheap only if data.ts caches), and a slow earlier response can still call `setCompany`/`setError` after a newer ticker (render guard `company.ticker !== ticker` hides the wrong data but a stale error still shows). `navRef`/`toggleThemeRef` are assigned in render after the effect that uses them.
- fix: key on `ticker` (plus a "needs company" boolean) and use an `ignore` flag in the cleanup; register the key handler with deps `[go, toggleTheme]` instead of refs.
- effort: S

### W18 Hero idle-callback start has no cleanup
- where: web/src/views/HeroSim.tsx:25-30
- severity: slop
- changes numbers: n/a
- issue: the idle callback/timeout is never cancelled, so leaving the page before it fires still fetches CCL and calls `setC` on an unmounted component; the `Window & {requestIdleCallback?}` cast is unnecessary with current TS lib types.
- fix: keep the handle and call `cancelIdleCallback`/`clearTimeout` in the cleanup.
- effort: S

### W19 Google Fonts: privacy and no-JS fallback
- where: web/index.html:19-20
- severity: risk
- changes numbers: n/a
- issue: every visitor's IP goes to Google Fonts (a GDPR concern for a research project), the stylesheet is both preloaded and linked, and the `media="print" onload` trick has no `<noscript>` fallback.
- fix: self-host the three families as woff2 in `public/` (or via `@fontsource`) and drop the preconnects; otherwise add the noscript link.
- effort: M

### W20 Repo and paper URLs hard-coded in many places, inconsistent `target`/`rel`
- where: web/src/App.tsx:130-152, web/src/views/MethodView.tsx:21, web/src/views/OverviewView.tsx:80
- severity: slop
- changes numbers: n/a
- issue: the GitHub and `docs/paper/fintwin.pdf` blob URLs are repeated; the Overview "Read the paper" link has no `target`/`rel` and navigates away from the app, the others open a new tab.
- fix: export `REPO_URL`/`PAPER_URL` once and use a small `ExtLink` component.
- effort: S

### W21 Compare table: no empty state for a filter with no matches; arrows read aloud
- where: web/src/views/CompareView.tsx:81,111-117
- severity: risk
- changes numbers: n/a
- issue: no "No company matches" text exists in the view (grep for "No "/"empty" finds none), so a typo leaves a header with no rows. Sort indicators are literal "↓"/"↑" text in the button, read in addition to `aria-sort`.
- fix: add an empty-state row with a "Clear filter" button; wrap the arrow in `<span aria-hidden>`.
- effort: S

### W22 Unlabelled sector select and redundant aria-label
- where: web/src/views/CompareView.tsx:82, web/src/views/VersusView.tsx:29-31
- severity: slop
- changes numbers: n/a
- issue: the Compare sector `<select>` only has an `aria-label` (no visible label); VersusView wraps its select in a `<label>` with visible text and also sets `aria-label` with the same string.
- fix: drop the duplicate `aria-label` in VersusView; give Compare's controls a visible label or make the first option "All sectors".
- effort: S

### W23 Stringly-typed view names and unnecessary optional props
- where: web/src/App.tsx:41-42, web/src/views/StressLab.tsx:57-59
- severity: slop
- changes numbers: n/a
- issue: `onGo(v: string)` accepts any string and unknown views silently fall back to overview (`VIEWS.has(viewRaw) ? viewRaw : "overview"`); StressLab's `query = ""`, `names = {}`, `onCompany?` are optional though the only caller always passes them.
- fix: `type ViewKey = "overview" | "twin" | ...` for `go`/`onGo`; make the props required.
- effort: S

### W24 Unknown ticker or route gives only a raw error
- where: web/src/App.tsx:41-42,60,120
- severity: risk
- changes numbers: n/a
- issue: `#twin/ZZZZ` makes `loadCompany` reject and the page shows the raw message with the old nav highlighted; no suggestion (search shortcut, Compare link) is offered.
- fix: detect `index.companies[ticker] === undefined` before fetching and show "No twin for ZZZZ" with a button that opens the palette and a link to Compare.
- effort: S

### W25 No tests for the view layer or routing
- where: web/src (only format.test.ts and scenarioUrl.test.ts)
- severity: test
- changes numbers: n/a
- issue: views, hash routing and loaders are untested, so the error states above and routes such as `stress/CCL/custom?...` are unguarded.
- fix: a few Vitest + Testing Library tests: App shows an error callout when `loadIndex` rejects; `rowActions` Enter/Space; route parsing.
- effort: M
