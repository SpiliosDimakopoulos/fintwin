// After `vite build`: one plain HTML page per company (dist/c/<TICKER>.html), an index of them, and a sitemap.
// The dashboard is a single-page app behind a hash router, so search engines see one empty page; these pages give
// each company a crawlable URL with its headline numbers, and link into the live twin.
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SITE = "https://spiliosdimakopoulos.github.io/fintwin/";
const REPO = "https://github.com/SpiliosDimakopoulos/fintwin";
const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const data = join(dist, "data");

const index = JSON.parse(readFileSync(join(data, "index.json"), "utf8"));
const presets = index.meta.presets;
const generated = index.meta.generated;
const horizon = index.meta.horizon;

const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
const pct = (p) => (p == null ? "n/a" : `${(100 * p).toFixed(p > 0 && p < 0.1 ? 1 : 0)}%`);
const score = (h) => (h == null ? "n/a" : Math.round(h).toString());
const titleCase = (name) => (name === name.toUpperCase() ? name.toLowerCase().replace(/\b\w/g, (ch) => ch.toUpperCase()) : name);

const STYLE = `body{font:16px/1.55 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 16px;color:#1d1c19;background:#f6f4ef}
a{color:#23518f}table{border-collapse:collapse;width:100%}td,th{padding:.35rem .5rem;border-bottom:1px solid #ddd8cc;text-align:left}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}.cta{display:inline-block;margin:1rem 0;padding:.6rem 1rem;background:#1d1c19;color:#f6f4ef;border-radius:6px;text-decoration:none}
small{color:#5d5a52}@media (prefers-color-scheme:dark){body{background:#121211;color:#e8e5dc}a{color:#8fb3e8}td,th{border-color:#33312c}.cta{background:#e8e5dc;color:#121211}small{color:#a29e93}}`;

function page({ title, description, canonical, body, jsonLd }) {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title><meta name="description" content="${esc(description)}">
<link rel="canonical" href="${canonical}"><meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}"><meta property="og:image" content="${SITE}og.png">
<meta property="og:url" content="${canonical}"><meta name="twitter:card" content="summary_large_image">
${jsonLd ? `<script type="application/ld+json">${JSON.stringify(jsonLd).replace(/</g, "\\u003c")}</script>` : ""}
<style>${STYLE}</style></head><body>${body}
<hr><small>FinTwin is an open research project (MIT code). Data: SEC EDGAR XBRL and FRED, rebuilt every Monday; this page was generated on ${generated}.
Not investment advice. <a href="${REPO}">Source code</a> · <a href="${SITE}c/">All companies</a></small></body></html>
`;
}

function companyPage(c, entry) {
  const name = titleCase(c.name);
  const base = c.presets.base;
  const lastQuarter = c.params?.last_quarter ?? entry.last_quarter;
  const worst = Object.entries(c.presets).filter(([k]) => k !== "base").sort((a, b) => a[1].health_score - b[1].health_score)[0];
  const rows = Object.entries(c.presets).map(([k, p]) =>
    `<tr><td>${esc(presets[k]?.label ?? k)}</td><td class="r">${score(p.health_score)}</td><td class="r">${pct(p.p_breach)}</td></tr>`).join("");
  const description = `${name} (${c.ticker}) cash and debt stress test from SEC filings: health ${score(base.health_score)}/100 in the baseline, `
    + `${pct(base.p_breach)} chance of running out of cash within ${horizon} quarters; worst preset ${presets[worst[0]]?.label ?? worst[0]}.`;
  const live = `${SITE}#twin/${encodeURIComponent(c.ticker)}`;
  const body = `<p><a href="${SITE}">FinTwin</a> › <a href="${SITE}c/">Companies</a></p>
<h1>${esc(name)} (${esc(c.ticker)}): cash and debt under stress</h1>
<p>${esc(c.sector)} · ${esc(c.gics)} · latest quarter ${esc(lastQuarter)} · ${c.quality.quarters} quarters of
<a href="${esc(c.edgar_url)}">SEC filings</a></p>
<p>FinTwin models ${esc(name)}'s cash, debt and margins as a stock-and-flow system calibrated on its own filings, then runs
thousands of Monte Carlo paths over the next ${horizon} quarters under each crisis below. The health score (0-100) summarises
runway, interest coverage, leverage and solvency; "runs out of cash" is the share of paths in which liquidity hits zero.</p>
<table><thead><tr><th>Scenario</th><th class="r">Health</th><th class="r">Runs out of cash</th></tr></thead><tbody>${rows}</tbody></table>
<a class="cta" href="${live}">Open the interactive twin</a>
<p>In the stress lab you can design your own shock, pull CFO levers, find the revenue drop that breaks the company
(<a href="${SITE}#stress/${encodeURIComponent(c.ticker)}">stress lab</a>) or rewind it to what the model said in past years
(<a href="${SITE}#time/${encodeURIComponent(c.ticker)}">time machine</a>). Raw numbers:
<a href="${SITE}data/companies/${encodeURIComponent(c.ticker)}.json">${esc(c.ticker)}.json</a>.</p>
<p><small>Out of sample, the model's bankruptcy ranking equals that of its scoring formula without simulation, and a 16-quarter
cash-flow margin forecasts cash flow better in levels. Read <a href="${REPO}#results">the evidence</a> before relying on any number here.</small></p>`;
  return page({
    title: `${name} (${c.ticker}) stress test: cash, debt and default risk | FinTwin`,
    description,
    canonical: `${SITE}c/${encodeURIComponent(c.ticker)}.html`,
    body,
    jsonLd: {
      "@context": "https://schema.org", "@type": "WebPage", name: `${name} (${c.ticker}) stress test`, description,
      dateModified: generated, about: { "@type": "Corporation", name, tickerSymbol: c.ticker },
      isPartOf: { "@type": "WebSite", name: "FinTwin", url: SITE },
    },
  });
}

mkdirSync(join(dist, "c"), { recursive: true });
const tickers = readdirSync(join(data, "companies")).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort();
const listed = [];
for (const t of tickers) {
  const c = JSON.parse(readFileSync(join(data, "companies", `${t}.json`), "utf8"));
  const entry = index.companies[t] ?? {};
  if (!c.presets?.base) continue;
  writeFileSync(join(dist, "c", `${t}.html`), companyPage(c, entry));
  listed.push({ t, name: titleCase(c.name), sector: c.gics, health: c.presets.base.health_score });
}

const bySector = Map.groupBy(listed, (x) => x.sector);
const sections = [...bySector.keys()].sort().map((s) => `<h2>${esc(s)}</h2><ul>${bySector.get(s)
  .map((x) => `<li><a href="${encodeURIComponent(x.t)}.html">${esc(x.name)} (${esc(x.t)})</a>, health ${score(x.health)}</li>`).join("")}</ul>`).join("");
writeFileSync(join(dist, "c", "index.html"), page({
  title: `Stress tests of ${listed.length} US public companies from SEC filings | FinTwin`,
  description: `Cash, debt and default-risk stress tests for ${listed.length} US public companies, built from SEC XBRL filings and rebuilt weekly. Open data and code.`,
  canonical: `${SITE}c/`,
  body: `<p><a href="${SITE}">FinTwin</a></p><h1>${listed.length} companies</h1><p>Each page shows the baseline health score
(0-100) and how it moves under eight crisis scenarios. <a href="${SITE}">Open the dashboard</a> to run your own.</p>${sections}`,
  jsonLd: {
    "@context": "https://schema.org", "@type": "Dataset", name: "FinTwin company stress tests",
    description: `Quarterly cash, debt and margin histories from SEC XBRL filings and Monte Carlo stress-test results under eight crisis scenarios for ${listed.length} US public companies, rebuilt weekly.`,
    url: `${SITE}c/`, sameAs: REPO, license: `${REPO}/blob/main/LICENSE`, isAccessibleForFree: true, dateModified: generated,
    creator: { "@type": "Person", name: "Spilios Dimakopoulos" }, keywords: ["SEC EDGAR", "XBRL", "stress testing", "credit risk", "Monte Carlo"],
    distribution: [{ "@type": "DataDownload", encodingFormat: "application/json", contentUrl: `${SITE}data/index.json` }],
  },
}));

const urls = [SITE, `${SITE}c/`, ...listed.map((x) => `${SITE}c/${encodeURIComponent(x.t)}.html`)];
writeFileSync(join(dist, "sitemap.xml"), `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map((u) => `  <url><loc>${u}</loc><lastmod>${generated}</lastmod></url>`).join("\n")}
</urlset>
`);
console.log(`static pages: ${listed.length} companies, sitemap with ${urls.length} URLs`);
