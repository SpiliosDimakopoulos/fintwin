# Interfaces from workstream D

- Environment: `FINTWIN_FROZEN=1` is set by the `make` targets and by `.github/actions/snapshot`; BLAS threads are pinned
  to 1 (`OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`) in the Makefile, research.yml, research-stats.yml, paper.yml.
- Make targets: `sync`, `test`, `snapshot-restore SNAPSHOT=`, `snapshot-verify`, `research [JOBS=8 SHARDS=16 SNAPSHOT=]`,
  `paper-assets`, `paper-pdf`, `paper`.
- Workflows: `paper.yml` (tag `paper-*`); `research.yml` new inputs `snapshot_release` (default `paper-data`, empty = live)
  and `release_tag`; `research-stats.yml` input `snapshot_release`; composite action `.github/actions/snapshot`.
- Versions: pyproject and `fintwin.__version__` `3.0.0.dev0`; package.json, CITATION.cff, .zenodo.json `3.0.0-dev`.
- pyproject: `lxml` dropped from the dev group (unused); `[tool.coverage.report] fail_under = 85`; research code no longer omitted.
