// Record a short demo of the Stress Lab as frames, then stitch with ffmpeg into docs/demo.gif.
// usage: node demo_gif.mjs http://localhost:4173/
import { launch } from "./lib.mjs";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";

const base = process.argv[2] ?? "http://localhost:4173/";
const FR = "frames";
rmSync(FR, { recursive: true, force: true });
mkdirSync(FR);
const browser = await launch();
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
let n = 0;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const snap = async (count = 1, gap = 120) => {
  for (let i = 0; i < count; i++) {
    await page.screenshot({ path: `${FR}/f${String(n++).padStart(4, "0")}.png`, clip: { x: 0, y: 0, width: 1280, height: 800 } });
    await sleep(gap);
  }
};
const clickChip = async (label) => {
  await page.evaluate((l) => [...document.querySelectorAll("button.chip")].find((b) => b.textContent.trim() === l)?.click(), label);
};
const setSlider = async (idx, value) => {
  await page.evaluate(({ idx, value }) => {
    const el = document.querySelectorAll('aside input[type="range"]')[idx];
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(el, String(value));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, { idx, value });
};

await page.goto(`${base}#stress/CCL/base`, { waitUntil: "networkidle0" });
await sleep(2500);
await snap(10);
for (const label of ["Recession", "Demand freeze"]) {
  await clickChip(label);
  await sleep(700);
  await snap(12);
}
// drag the revenue shock from -70% down to -95% and back to -30%
for (const v of [0.75, 0.8, 0.85, 0.9, 0.95, 0.8, 0.6, 0.45, 0.3]) {
  await setSlider(0, v);
  await sleep(350);
  await snap(2);
}
await snap(6);
// allow an emergency equity raise
await page.evaluate(() => {
  const row = [...document.querySelectorAll("label.toggle")].find((l) => l.textContent.includes("Emergency equity"));
  row?.querySelector("input")?.click();
});
await sleep(700);
await snap(14);
await browser.close();

execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "8", "-i", `${FR}/f%04d.png`,
  "-vf", "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
  "../docs/demo.gif"]);
rmSync(FR, { recursive: true, force: true });
console.log(`demo.gif from ${n} frames`);
