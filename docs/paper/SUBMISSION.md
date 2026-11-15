# Publishing the paper

The paper is published on **Zenodo** together with the code and data:

- Concept DOI (always the latest version): [10.5281/zenodo.23434606](https://doi.org/10.5281/zenodo.23434606)
- Each GitHub release is archived automatically as a new version under that DOI (`.zenodo.json` holds the metadata).

To publish a new version after changing the paper or the code:

```bash
cd engine
uv run python scripts/research_assets.py      # tables, figures and numbers from docs/paper/research.json
uv run python scripts/arxiv_bundle.py         # PDF + self-contained LaTeX source in docs/paper/dist/
gh release create vX.Y.Z docs/paper/dist/fintwin.pdf docs/paper/dist/fintwin-arxiv.tar.gz
```

`arxiv_bundle.py` also writes a plain-text abstract (`abstract.txt`) and compiles the LaTeX source in an empty folder,
so the bundle is ready if the paper is ever submitted to arXiv, SSRN or a journal.

**Title:** Does Filing-Based Cash-Flow Simulation Beat Persistence? A Benchmark with Committed Decision Rules on a Survivorship-Free Panel of SEC Filers

**Keywords:** forecast evaluation; cash-flow forecasting; density forecasts; stress testing; forecast encompassing; corporate liquidity; XBRL

**JEL:** C53, G17, G32, G33, M41
