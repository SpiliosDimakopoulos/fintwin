# Contributing to FinTwin

Thanks for taking a look. Bug reports, questions, new scenarios, data fixes and criticism of the method are all welcome.

## Where to start

- Issues labelled [`good first issue`](https://github.com/SpiliosDimakopoulos/fintwin/labels/good%20first%20issue) are small and self-contained.
- Questions and ideas go to [Discussions](https://github.com/SpiliosDimakopoulos/fintwin/discussions).
- If you think a result in the paper is wrong, open an issue with the test, the number you expected and why.

## Setup

The quickest start is [GitHub Codespaces](https://codespaces.new/SpiliosDimakopoulos/fintwin): it installs Python, uv, Node and all dependencies for you. Locally:

```bash
cp .env.example .env                       # set SEC_USER_AGENT (required by the SEC)
cd engine && uv sync && uv run pytest -q   # Python engine and tests
cd ../web && npm ci && npm test && npm run dev
```

The full research pipeline (`scripts/full_pipeline.sh`) takes hours; you don't need it for most changes.

## Pull requests

- Keep each PR to one change and say what it fixes.
- Run `uv run pytest -q` (engine) and `npm test` (web) before pushing. CI also runs ruff, mypy and the Python <-> TypeScript parity tests.
- The model exists twice, in `engine/fintwin/model` (Python) and `web/src/engine` (TypeScript). A change to one needs the same change in the other, or the parity tests fail.
- Don't commit generated data under `web/public/data`; the weekly workflow rebuilds it.

By contributing you agree that your work is released under the [MIT licence](LICENSE).
