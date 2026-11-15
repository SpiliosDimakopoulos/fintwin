// Drive the dashboard headless: screenshot each view, report console errors.
// usage: node shoot.mjs <baseUrl> <outDir> [theme=light|dark] [width]
import { launch } from "./lib.mjs";
import { mkdirSync } from "node:fs";

const [base = "http://localhost:5173/", out = "../docs/screenshots", theme = "light", width = "1400"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const ROUTES = [
  ["overview", "overview"],
  ["twin", "twin/CCL"], ["stress", "stress/CCL/pandemic"], ["machine", "machine/BA"],
  ["compare", "compare/CCL"], ["backtest", "backtest/CCL"], ["method", "method/CCL"], ["twin-aapl", "twin/AAPL"],
];

const browser = await launch({ args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: +width, height: 900, deviceScaleFactor: 1 });
await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: theme }]);
const errors = [];
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(`[${m.type()}] ${m.text()}`); });
page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));

for (const [name, route] of ROUTES) {
  await page.goto(`${base}#${route}`, { waitUntil: "networkidle0" });
  await page.reload({ waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 2500));
  const t0 = Date.now();
  await page.screenshot({ path: `${out}/${name}-${theme}-${width}.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  console.log(`${name}: ok${overflow ? " (HORIZONTAL OVERFLOW)" : ""} ${Date.now() - t0}ms`);
}
console.log(errors.length ? errors.join("\n") : "no console errors");
await browser.close();
