import { launch } from "./lib.mjs";
const b = await launch();
const p = await b.newPage();
await p.setViewport({ width: 390, height: 800 });
for (const r of ["method/CCL", "twin/CCL", "stress/CCL"]) {
  await p.goto(`http://localhost:5173/#${r}`, { waitUntil: "networkidle0" }); await p.reload({ waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 1500));
  console.log(r, await p.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
    .slice(0, 6).map((e) => `${e.tagName}.${e.className?.baseVal ?? e.className} r=${Math.round(e.getBoundingClientRect().right)}`)));
}
await b.close();
