// Build web/public/og.png (1200x630 social card) from the live hero terminal plus headline text.
import { launch } from "./lib.mjs";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const base = process.argv[2] ?? "http://localhost:4173/";
const b = await launch();
const p = await b.newPage();
await p.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
await p.setViewport({ width: 1400, height: 900, deviceScaleFactor: 2 });
await p.goto(`${base}#overview`, { waitUntil: "networkidle0" });
await new Promise((r) => setTimeout(r, 800));
await p.evaluate(() => [...document.querySelectorAll(".term-chips button")].find((x) => x.textContent === "Demand freeze")?.click());
await new Promise((r) => setTimeout(r, 2200));
const el = await p.$(".terminal");
const png = await el.screenshot({ encoding: "base64" });
const html = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&family=Newsreader:opsz,wght@6..72,500&display=swap" rel="stylesheet">
<style>
 body{margin:0;width:1200px;height:630px;background:#f6f4ef;font-family:'IBM Plex Sans';color:#16150f;display:grid;grid-template-columns:560px 1fr;gap:36px;align-items:center;padding:0 48px;box-sizing:border-box;overflow:hidden}
 .mark{display:flex;align-items:center;gap:10px;font-family:Newsreader;font-size:28px;font-weight:600;margin-bottom:28px}
 .eyebrow{font-family:'IBM Plex Mono';font-size:14px;letter-spacing:.06em;text-transform:uppercase;color:#8a867c;margin-bottom:14px}
 h1{font-family:Newsreader;font-weight:500;font-size:54px;line-height:1.05;letter-spacing:-.015em;margin:0 0 22px}
 .stats{display:flex;gap:26px;border-top:1px solid #cdc7b8;padding-top:16px;font-size:15px;color:#4b4840}
 .stats b{display:block;font-family:Newsreader;font-weight:500;font-size:30px;color:#16150f}
 img{width:100%;border-radius:12px;box-shadow:0 30px 60px -30px rgba(22,21,15,.55)}
</style></head><body>
<div>
 <div class="mark"><svg width="30" height="30" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#16150f"/><path d="M7 20.5c3-0.2 4.6-7 8-7s4.6 4.2 10 3.5" stroke="#f6f4ef" stroke-width="2.6" fill="none" stroke-linecap="round"/></svg>FinTwin</div>
 <div class="eyebrow">390+ S&amp;P 500 companies · refreshed weekly</div>
 <h1>What happens to a company's cash when the world breaks?</h1>
 <div class="stats"><div><b>ρ 0.30</b>where cash departs from simple rules, 2014–23</div><div><b>30,414</b>out-of-sample forecasts</div><div><b>+28%</b>vs naive</div></div>
</div>
<img src="data:image/png;base64,${png}">
</body></html>`;
writeFileSync("og.html", html);
const q = await b.newPage();
await q.setViewport({ width: 1200, height: 630, deviceScaleFactor: 1 });
await q.goto(pathToFileURL("og.html").href, { waitUntil: "networkidle0" });
await q.screenshot({ path: "../web/public/og.png" });
await b.close();
console.log("og.png written");
