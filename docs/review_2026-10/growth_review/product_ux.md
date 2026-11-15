# Product / UX / SEO / LLM-tooling review of GROWTH_PLAN.md

Reviewer lens: product lead. Scope: section 0 and workstreams W, M, D, G.
Verified: the plan text; the README last line says "Not investment advice"; a plain fetch of the live dashboard returns only the title "FinTwin" (no server-rendered content). Not verified: the real in-app wording of health scores (the SPA did not render for the fetcher). Everything else is judgement.

## 1. Blocking problems

**PX-1 (Blocking) No stated primary user or job-to-be-done for the dashboard.**
Section 0 ranks value as data > benchmark > library > MCP. The dashboard is item 3, yet W, SEO and 5,300 pages make it the biggest build item. Retail investors want "is my stock OK?". Analysts want screening, peers, exports. Quants want the dataset, not the dashboard. The plan never says who the pages are for, so page copy, disclaimers and funnel are guesses.
Fix: pick one primary persona (suggest finance students and credit analysts screening and learning, not retail stock picking). Treat the dashboard as the shop window for library and dataset.

**PX-2 (Blocking) Public named-company health / bankruptcy-risk scores at scale have no legal or wording policy.**
390 large caps become 5,300 issuers including small, distressed and micro-cap names, where a "weak" label does most reputational harm and draws the most search traffic ("X bankruptcy").
- The plan mentions no legal review, disclaimer, correction channel or per-page methodology link.
- The paper itself says simulation adds nothing to ranking; AUC 0.86 still means many false positives. A page implying "risk of bankruptcy" is more confident than the evidence.
- Retail users may read a score as a recommendation. Defamation, "investment adviser" and market-manipulation questions are low probability but not zero.
Fix, minimum:
1. Never headline "bankruptcy risk" or "probability of bankruptcy" for a company. Use "financial-health indicator (rule-based, from SEC filings)".
2. Show a band or sector rank ("bottom decile in sector"), not a raw probability.
3. Above the fold and in the meta description: "as of filing date, data lag N days, not advice, not a prediction of any event".
4. Per page: accession links, "report an error", methodology link.
5. Published corrections policy with turnaround time.
6. Short legal review before the 5,300-page launch (add to G4 gate).
7. Show an "insufficient history" state instead of a score when the fit is unreliable (only 21% of bankruptcy firm-years have 8 quarters, per README).

**PX-3 (Blocking) The SEO plan rests on thin template pages with no quality gate.**
W3 admits numbers alone will not be indexed, but still proposes 5,200 near-identical pages. This is the "scaled content abuse" pattern; Google may index few and demote the whole site. github.io shares domain reputation with the repo and gives no control over headers or redirects. The current SPA is invisible to non-JS crawlers (fetch returned only a title); hash routes are not indexable at all.
Fix:
- Phase it: ship 300-500 large-cap pages first, watch Search Console "Crawled, not indexed" for 4-6 weeks, then widen.
- noindex pages below a data-quality threshold (short history, tiny firms); they live in the screener, not the sitemap.
- Each indexed page needs unique substance: latest filing, what drove the change, peer comparison vs sector median, chart with alt text, accession links.
- JSON-LD Dataset/BreadcrumbList; never fake Review/Rating markup. Unique titles.
- Consider a custom domain (without "sec"/"edgar", per A1) so reputation is portable.

## 2. Important problems

**PX-4 (High) Wrong page types first.** Likely rankers, best first: (1) sector pages and norm explainers with real aggregate content; (2) dated weekly "biggest health changes" pages (one URL per week; fresh, linkable); (3) per-company pages for well-known tickers, but Macrotrends, Stockanalysis, Simply Wall St and Yahoo dominate "is X in trouble", so only the sector-adjusted, filing-linked angle can win; (4) concept pages ("what is point-in-time data", "look-ahead bias in backtests"), cheapest to rank and best fit for students/quants. Edit: W4 before W3; archive URLs per week, not just RSS.

**PX-5 (High) MCP tools, hosting, misquote risk under-specified.**
- Proposed tools mirror the library, not agent tasks. Agents need: search_company (name/ticker to CIK, disambiguation), get_filing_facts(ticker, concept, asof), compare(tickers, metrics), sector_peers, latest_changes(since), explain_score(ticker) (components + sources), list_concepts. Keep outputs small and token-cheap (row caps, no raw panels by default).
- Misquote risk: every response carries as_of, filed, accession, data_version, score_definition, not_advice, insufficient_data. Return bands plus a quote-ready sentence so the LLM does not paraphrase numbers. Add a "how to cite" MCP resource.
- Hosting: local stdio (uvx fintwin-mcp) first (no abuse/cost). A hosted read-only endpoint over static files is the better discovery demo but needs rate limits and cost control.
- Distribution: official MCP Registry, Smithery, Glama, PulseMCP, awesome-mcp-servers; copy-paste claude_desktop_config.json, Cursor deeplink, .mcpb bundle if feasible. The plan lists only quant awesome-lists.
- Hub mode means the first call downloads Parquet and can stall an agent: pre-warm, return a clear "downloading, retry" message.
- M2 "LLM credit analyst" needs a verification step (quoted numbers checked against tool output), otherwise it demonstrates the misquote problem.

**PX-6 (High) No designed funnel dashboard -> library -> dataset.** Each company page needs a "Use this data" panel: pip install fintwin plus ft.facts("CCL") prefilled, "Open in Colab" with ticker, per-company CSV/Parquet, dataset link, citation. Same on the screener. W4 only mentions "open in notebook". 60-second path: README 3 lines return a dataframe with no identity setup (hub default) and draw a chart; Colab runs with no secrets and shows a chart by cell 3. Notebook order in D is wrong for onboarding: #1 (look-ahead study) is heavy; put a 5-minute "one company, PIT vs latest" notebook first.

**PX-7 (High) Performance, mobile, accessibility at 5,300 companies ignored.**
- Screener: virtualised table, one compact gzipped index (few hundred KB) and lazy per-company JSON. W5 only handles hosting size.
- Typeahead and compare must be sub-second on mobile.
- Prerendered pages must not hydrate the full app bundle; Lighthouse budget (LCP < 2.5 s mid mobile) in CI.
- A11y: text alternatives or data tables for charts/waterfalls; colour not the only signal for health bands; keyboard-operable stress lab sliders; semantic headings; reduced-motion; axe-core in CI.
- On-device LLM strictly opt-in, size shown, warned on mobile, never loaded on page view.

**PX-8 (High) Routing/indexing traps.** The GitHub Pages 404.html fallback returns HTTP 404, which crawlers treat as errors, so state-dependent deep links (compare, stress) must live in query/fragment on a prerendered shell. Old # links can only be redirected by JS; keep that code. Sitemap only indexable URLs, lastmod from filing date, content-hash pages so the weekly rebuild does not change every lastmod.

**PX-9 (Medium) Honesty framing on the page.** The paper credibility is its honest findings (simulation adds nothing to ranking; transmission 2.3x too strong) but the dashboard shows a polished score. Add a one-line "what this score is and is not" with the AUC and a link to limitations.

**PX-10 (Medium) No user research or feedback loop.** Metrics cover downloads/issues only. Add: 5-8 moderated sessions (student, analyst, retail investor, agent builder) on dashboard, README, Colab; the G4 "new user" LLM reviewer does not replace this. In-page "Was this useful?" and "Report an error" opening a prefilled GitHub issue (ticker, data version). Funnel metrics: visitors -> "Use this data" clicks -> pip/HF downloads -> issues; Search Console per page type; RSS subscribers; repeat visits. Instrument now with cookieless analytics (Plausible/GoatCounter); baseline is 79 visitors in 2 weeks. Go/no-go reviews at 4 and 12 weeks.

**PX-11 (Medium) One-maintainer load.** 48 h issue replies + corrections SLA + weekly builds is too much. Publish a best-effort support policy and an automated data-freshness status page.

## 3. Missing opportunities

**PX-12 (High) Retention loop.** Static hosting means no accounts, so: per-ticker Atom feeds, localStorage watchlist with a "changes in your watchlist" view and shareable watchlist URL, and a weekly newsletter drafted by a GitHub Action from the changes feed (Buttondown/Beehiiv free tier, human approves, double opt-in form on every page): top movers, one chart, one explained filing, one sector. Optional auto-post of weekly movers to Bluesky/Mastodon/Discord.

**PX-13 (High) Badges and embeddable widgets.** Static SVG per ticker ("FinTwin health: Moderate, sector percentile 40, as of 2026-10-26") with a link back (backlinks are the best SEO lever), plus an iframe/web-component for blogs. Use banded wording per PX-2. Also README badges for dataset version and "uses FinTwin".

**PX-14 (Medium) Concept/tutorial content.** Look-ahead bias explainer with notebook; data dictionary doubling as glossary (Altman Z, Ohlson, coverage); "how to read this dashboard". Serves students, low legal risk.

**PX-15 (Medium) Make stress lab and time machine the differentiator.** Few sites offer "replay company as of Feb 2020 and apply Covid". Shareable scenario URLs, build-time OpenGraph cards, a curated cases gallery (Carnival, Hertz, Bed Bath and Beyond, SVB) with narrative; better HN/social material than a generic score.

**PX-16 (Medium) Agent-readable site.** llms.txt, per-page data.json, stable CSV endpoints, Dataset JSON-LD, and a "how to cite FinTwin numbers in LLM output" page, so agents without MCP still get provenance.

**PX-17 (Low) Localization** is not an SEO priority; defer G3 translations.

## 4. Concrete plan edits (section/item -> change)

- Section 0 -> add primary user/job per persona (PX-1); state scores are indicators, not predictions or advice; add funnel metrics beside the 3-month goals.
- Section 0 items 3-4 -> say the dashboard is the acquisition surface and MCP a distribution channel.
- A9 -> replace "prerender all 5,200" with phased, quality-gated rollout plus noindex rule (PX-3); decide custom domain; note 404-status caveat (PX-8).
- New A11 -> language and legal policy: banned phrases, bands not probabilities, mandatory banner, methodology and correction links, corrections SLA, legal review before >390 public pages (PX-2, PX-9).
- W2 -> add a data-quality gate deciding which firms get an indexable page, beyond MIN_COMPANIES.
- W3 -> unique content per page, JSON-LD Dataset, unique titles, lastmod from filing date, content hashing, permanent hash-redirect JS.
- W4 -> sector pages, dated weekly pages and concept pages ahead of per-company pages; add per-ticker feeds, watchlist, badges/widgets, "Use this data" panel (PX-4, 6, 12, 13).
- W5 -> client budgets: screener index size, virtualised tables, Lighthouse and axe-core in CI.
- New W6 -> accessibility and mobile acceptance criteria (PX-7).
- M1 -> redefine tools around agent tasks, capped outputs, mandatory provenance/caveat fields, quote-ready sentence; local stdio first, hosted optional.
- M2 -> add number-verification step and a misquote test suite.
- New M3 -> registry listings, config snippets, llms.txt (PX-5, 16).
- D -> add notebook 0 (one company, 60 s, no keys, hub mode, chart); Colab needs no secrets; add concept pages.
- G1 -> README leads with the one-line value and the 60 s path.
- G4 -> add MCP registry submissions, Search Console/sitemap checklist, legal review gate, 5-8 usability sessions.
- G6 -> weekly newsletter, social auto-post, support policy, freshness status page.
- Section 3 gates -> G3 adds "legal wording reviewed, Lighthouse and axe pass, indexable-page rule live"; G5 adds "usability findings addressed".
- Section 7 risks -> add: thin-content demotion; complaint/defamation claim from a listed company; LLM misquotation; github.io lock-in; analytics privacy compliance.
