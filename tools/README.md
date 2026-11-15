# tools

Headless-Chrome helpers for screenshots and demo assets. They drive a running dashboard (`npm run dev` or
`npm run preview` in `web/`), not the engine.

    cd tools && npm ci
    CHROME_PATH=/path/to/chrome node shoot.mjs http://localhost:5173/ ../docs/screenshots

`CHROME_PATH` is optional on Windows (the default is the standard Chrome install path) and required elsewhere.
`lib.mjs` holds the shared launch code.

| script | what it does |
|---|---|
| `shoot.mjs` | screenshot every view, report console errors |
| `ask.mjs` | drive "Ask the twin" with an example chip and a question |
| `demo_gif.mjs` | record the Stress Lab as frames and stitch `docs/demo.gif` with ffmpeg |
| `og.mjs` | build `web/public/og.png` (social card) |
| `hero.mjs` | one screenshot of a URL, light or dark |
| `overflow.mjs` | list elements that overflow a 390 px viewport (mobile check) |
| `palette.mjs` | screenshot the command palette to `shots/palette.png` |
