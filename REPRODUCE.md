# Reproducing the paper

Everything in the paper's evaluation is generated: `docs/paper/research.json` (the statistics) -> `scripts/research_assets.py`
and `scripts/paper_assets.py` (tables, figures, number macros) -> LaTeX. There are three levels, from cheap to expensive.

| Level | What it checks | Needs | Time |
|---|---|---|---|
| 1. Paper from numbers | tables, figures and macros regenerate identically from the committed `research.json`; the PDF builds | uv, TeX Live | minutes |
| 2. Statistics from shards | `research.json` recomputes from the per-company outputs | the shard outputs (release asset) | an hour or so |
| 3. Everything | per-company simulations and all statistics from the frozen raw data | the data snapshot, an 8-vCPU machine | days of CPU, about a day on 8 vCPU |

Level 3 is heavy by design (5,220 firms, many simulation paths). Run it on an 8-vCPU machine, not a laptop.

## What defines "the paper"

The paper is built from a **git tag** named `paper-*` (for example `paper-r3`), not from a branch or from `main`.
The tag fixes the code, `engine/uv.lock` (Python and library versions), the committed `docs/paper/research.json` and the
paper sources. The raw inputs are fixed separately by the **data snapshot** (below), identified by the digest in its
`manifest.json`. A tag is never moved once it is public.

Why `main` is not the reference: the weekly job (`.github/workflows/data.yml`) refreshes the dashboard on `main` every
Monday, and Dependabot bumps libraries there. Neither can reach the paper:

- `data.yml` and `pages.yml` check out `main` explicitly, commit only the dashboard summary files
  (`web/public/data/{build_report,calibration,index,changes}.json`, `feed.xml`) as `github-actions[bot]`, and never push
  to a revision branch or a tag.
- The research statistics do not read `web/public/data`. They read the frozen snapshot (`FINTWIN_FROZEN=1`: nothing is
  fetched, a missing file is an error) and the committed CSVs in `engine/fintwin/data`.
- Do not merge `main` into the revision branch. Take bug fixes by cherry-pick, deliberately.
- `scripts/paper_assets.py` still reads two dashboard files from `web/public/data` for a few figures; those are
  whatever the tag contains, so building from the tag is what makes them stable.

## Level 1: the paper from the committed numbers

```bash
git checkout paper-r3            # the tag
make paper                       # = make paper-assets && make paper-pdf; writes docs/paper/fintwin.pdf
git diff docs/paper/numbers.tex docs/paper/research_numbers.tex docs/paper/tables   # must be empty
```

Pushing a `paper-*` tag runs `.github/workflows/paper.yml`, which does exactly this on a fixed Ubuntu 24.04 image, fails
if the regenerated text outputs differ from the committed ones, and attaches the PDF to the tag's release.

## Level 3: the full run

1. Machine: 8 vCPU, 16 GB RAM, Linux, `uv`, `make`, `git`. No network access to EDGAR or FRED is needed.
2. Get the code and inputs for the tag:
   ```bash
   git clone https://github.com/SpiliosDimakopoulos/fintwin && cd fintwin && git checkout paper-r3
   gh release download paper-data -p 'fintwin_snapshot_*.tar' -p manifest.json   # or from the Zenodo data deposit
   mkdir -p engine/snapshot && mv manifest.json engine/snapshot/
   ```
3. Run:
   ```bash
   make research JOBS=8 SNAPSHOT=fintwin_snapshot_<date>.tar    # restores and verifies the snapshot, 16 shards, merge
   make paper
   ```
   `make research` sets `FINTWIN_FROZEN=1` and pins BLAS to one thread per process (`OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1`),
   so the numbers do not depend on thread count or scheduling. Shards are resumable and stamped with a hash of the code,
   the committed data, the snapshot digest and the `FINTWIN_*` switches; `stats` refuses shards of mixed stamps.
4. Compare `docs/paper/research.json` with the committed one (the keys and numbers, not the file bytes; the run records
   its stamp). Differences at the last printed digit would point to a different CPU or library build; the pinned
   `uv.lock` makes this unlikely but different hardware can still change floating point at the 1e-15 level.

Environment: Python >= 3.11 (CI tests 3.11 and 3.13), libraries exactly as in `engine/uv.lock` (`uv sync --locked`
fails if the lock and `pyproject.toml` disagree). Use `uv sync --locked` everywhere, never plain `uv sync`.

## Making a snapshot (the maintainer, once per paper version)

```bash
cd engine
uv run python scripts/freeze_snapshot.py build    # fetches every universe company's facts and the FRED series, packs a tar + manifest.json
uv run python scripts/freeze_snapshot.py verify
```

Publish the tar and `manifest.json` as assets of a GitHub release called `paper-data` (and deposit the same files on
Zenodo, quoting the SHA-256 and the extraction dates recorded in `manifest.json`). The `research` workflow downloads
them from that release (`.github/actions/snapshot`) and verifies them against the manifest before any shard starts.
Do not re-extract after the paper's numbers are final: a new extraction is a new data vintage and a new paper version.

## CI and release checklist

1. Finish on the revision branch; CI (`ci.yml`) green on Python 3.11 and 3.13.
2. Run the research (workflow `research` from the branch, or Level 3 on a server) with `release_tag` set so the results
   stay beyond the 90-day artifact retention.
3. Commit `docs/paper/research.json` and the regenerated assets.
4. Tag `paper-<name>` on that commit (annotated). `paper.yml` builds and checks the PDF.
5. Cut the Zenodo release from the tag, set the version in `CITATION.cff` and `.zenodo.json` (they say `3.0.0-dev`
   until then), and quote the snapshot digest.
