# fintwin (engine)

The Python package behind FinTwin: SEC XBRL facts -> system-dynamics model -> Monte Carlo stress tests, plus the
research and backtest code that produces the paper's numbers.

Install from git (the package lives in the `engine/` subfolder):

    pip install "git+https://github.com/SpiliosDimakopoulos/fintwin#subdirectory=engine"

`pip` resolves the `>=` floors in `pyproject.toml` to the newest libraries. The paper's numbers are reproducible only
with the pinned set: `uv sync --locked` from a clone (see `REPRODUCE.md` in the repository root).

The SEC asks for a contact address in the User-Agent: set `SEC_USER_AGENT` before fetching filings.
Documentation, dashboard and paper: https://github.com/SpiliosDimakopoulos/fintwin
