# Reproduce the paper. See REPRODUCE.md. Needs: uv, GNU make, bash, and (for paper-pdf) latexmk with TeX Live.
#
#   make test                                  # engine tests (quick, offline)
#   make snapshot-restore SNAPSHOT=<tar>       # unpack + verify the frozen inputs (engine/snapshot/manifest.json required)
#   make research JOBS=8 SNAPSHOT=<tar>        # the full research run on the frozen inputs, ~days of CPU: use an 8-vCPU machine
#   make paper                                 # tables/figures/numbers from docs/paper/research.json, then the PDF
SHELL := /bin/bash

SHARDS ?= 16
JOBS   ?= 8
SNAPSHOT ?=

# Same numbers whatever the thread count or scheduling: one BLAS thread per process (R9).
export OPENBLAS_NUM_THREADS := 1
export OMP_NUM_THREADS := 1
export MKL_NUM_THREADS := 1
export PYTHONWARNINGS := ignore

# Frozen inputs only for the recipes that read the snapshot; `make test` runs as CI does, without it.
snapshot-restore snapshot-verify research: export FINTWIN_FROZEN := 1

.PHONY: sync test snapshot-restore snapshot-verify research paper paper-assets paper-pdf

sync:
	cd engine && uv sync --locked

test: sync
	cd engine && uv run python -m pytest -q -p no:cacheprovider

snapshot-restore: sync
	@test -n "$(SNAPSHOT)" || { echo "usage: make snapshot-restore SNAPSHOT=fintwin_snapshot_<date>.tar (with engine/snapshot/manifest.json)"; exit 2; }
	cd engine && uv run python scripts/freeze_snapshot.py restore "$(abspath $(SNAPSHOT))"

snapshot-verify: sync
	cd engine && uv run python scripts/freeze_snapshot.py verify

# Restore the snapshot (when given), run all shards in parallel, merge. Shards are resumable and stamped.
research: sync
	@if [ -n "$(SNAPSHOT)" ]; then $(MAKE) snapshot-restore SNAPSHOT="$(SNAPSHOT)"; else $(MAKE) snapshot-verify; fi
	cd engine && seq 0 $$(( $(SHARDS) - 1 )) | xargs -P $(JOBS) -I{} uv run python -m fintwin.research shard {} $(SHARDS)
	cd engine && uv run python -m fintwin.research stats

paper-assets: sync
	cd engine && uv run python scripts/research_assets.py
	cd engine && uv run python scripts/paper_assets.py
	cd engine && uv run python scripts/rev3_assets.py

paper-pdf:
	cd docs/paper && latexmk -pdf -interaction=nonstopmode -halt-on-error fintwin.tex

paper: paper-assets paper-pdf
