// Drive "Ask the twin" like a visitor: an example chip, then a question that names another company.
// usage: node ask.mjs http://localhost:4174/ out-dir
import { launch } from "./lib.mjs";
const [base = "http://localhost:4174/", out = "."] = process.argv.slice(2);
const b = await launch();
const p = await b.newPage();
const errs = []; p.on("pageerror", (e) => errs.push(e.message)); p.on("console", (m) => m.type() === "error" && errs.push(m.text()));
await p.setViewport({ width: 1400, height: 1000 });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const state = () => p.evaluate(() => ({
  hash: location.hash, title: document.querySelector("h1")?.textContent, desc: document.querySelector("h1 + p")?.textContent,
  said: [...document.querySelectorAll("p.sub")].map((x) => x.textContent).find((t) => t.startsWith("Understood") || t.startsWith("I could not")),
}));

await p.goto(`${base}#stress/AAPL/pandemic`, { waitUntil: "networkidle0" });
await wait(2500);
const [chip] = await p.$$("xpath/.//button[contains(., 'Revenue falls 40%')]");
await chip.click();
await wait(2500);
console.log("example:", JSON.stringify(await state()));
await p.screenshot({ path: `${out}/ask-example.png` });

await p.click("#ask-twin", { clickCount: 3 });
await p.type("#ask-twin", "What if Carnival's bookings halve for a year and debt markets close?");
await p.keyboard.press("Enter");
await wait(4000);
console.log("company:", JSON.stringify(await state()));

await p.click("#ask-twin", { clickCount: 3 });
await p.type("#ask-twin", "tell me a joke");
await p.keyboard.press("Enter");
await wait(800);
console.log("miss:", JSON.stringify((await state()).said));
console.log(errs.length ? errs : "no errors");
await b.close();
