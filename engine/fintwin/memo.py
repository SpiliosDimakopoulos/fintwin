"""AI analyst: grounded credit memos written by Claude from the twin's simulation output.

Design choices that make the memos trustworthy rather than decorative:
* Claude sees only a compact fact sheet built from the exported simulation (no web, no memory of the company);
  the prompt forbids numbers that are not in it.
* The answer is constrained to a JSON schema (structured outputs), so the dashboard renders fields, not prose blobs.
* A deterministic number checker extracts every figure in the memo and matches it against the fact sheet.
  Memos with unmatched numbers are regenerated once with the offending figures named; anything still unmatched
  is flagged in the UI instead of hidden.
* Memos are generated at build time and committed as JSON, so the public site needs no API key.

    uv run --extra ai python -m fintwin.memo CCL AAPL      # needs ANTHROPIC_API_KEY (or an `ant auth login` profile)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from .notes import fact_sheet

if TYPE_CHECKING:
    import anthropic

# A key in the project's git-ignored .env wins over a stale shell variable.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

DATA = Path(__file__).resolve().parents[2] / "web" / "public" / "data"
MODEL = "claude-opus-5-5"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "headline", "summary", "key_risks", "resilience", "scenario_notes", "watch_list"],
    "properties": {
        "verdict": {"type": "string", "enum": ["Strong", "Adequate", "Watch", "Weak", "Distressed"]},
        "headline": {"type": "string", "description": "One sentence, at most 25 words."},
        "summary": {"type": "string", "description": "3-4 sentences for a credit committee."},
        "key_risks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["risk", "evidence"],
                "properties": {"risk": {"type": "string"}, "evidence": {"type": "string"}},
            },
        },
        "resilience": {"type": "array", "items": {"type": "string"}},
        "scenario_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scenario", "note"],
                "properties": {"scenario": {"type": "string"}, "note": {"type": "string"}},
            },
        },
        "watch_list": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Observable indicators in future filings that would change the view.",
        },
    },
}

SYSTEM = """You are a senior credit analyst writing for a credit committee.
You are given a fact sheet produced by a calibrated Monte Carlo digital twin of a company's finances.
Rules:
- Use ONLY numbers that appear in the fact sheet. Round as the sheet does. Never invent figures, dates, events,
  products, or management actions that are not in the sheet. If something is unknown, do not mention it.
- Explain mechanisms (operating leverage, maturities, market access, coverage, customer deposits) rather than
  repeating numbers; every risk needs evidence from the sheet.
- Be calibrated: the baseline is a forecast under normal conditions; scenarios are conditional what-ifs, not predictions.
- Plain, precise English. No hype, no investment advice."""


NUM = re.compile(r"-?\$?\d+(?:,\d{3})*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for m in NUM.findall(text):
        try:
            out.append(float(m.replace("$", "").replace(",", "")))
        except ValueError:
            pass
    return out


def unverified_numbers(memo: dict, sheet: dict) -> list[float]:
    """Figures in the memo that cannot be matched to the fact sheet (after rounding)."""
    allowed = set(_numbers(json.dumps(sheet)))
    allowed |= {abs(a) for a in allowed}
    bad = []
    for x in _numbers(json.dumps(memo)):
        if abs(x) <= 12 or 1990 <= x <= 2035:  # quarter counts, ordinal words, years
            continue
        if not any(abs(abs(x) - a) <= max(0.051 * abs(a), 0.6) for a in allowed):
            bad.append(x)
    return bad


def write_memo(client: anthropic.Anthropic, sheet: dict, feedback: str | None = None) -> dict:
    user = (
        "Fact sheet (JSON):\n"
        + json.dumps(sheet, indent=1)
        + "\n\nWrite the credit memo. 3-5 key risks, 2-4 resilience factors, a note for each stress scenario"
        " that matters for this company (at least 4), and 3-4 watch-list indicators."
    )
    if feedback:
        user += "\n\n" + feedback
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("memo truncated at max_tokens")
    text = next(b.text for b in resp.content if b.type == "text")
    return {
        "memo": json.loads(text),
        "model": resp.model,
        "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
    }


def main(tickers: list[str]) -> None:
    import anthropic

    client = anthropic.Anthropic()
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    out_dir = DATA / "memos"
    out_dir.mkdir(exist_ok=True)
    for t in tickers:
        c = json.loads((DATA / "companies" / f"{t}.json").read_text(encoding="utf-8"))
        sheet = fact_sheet(c, index["meta"])
        r = write_memo(client, sheet)
        bad = unverified_numbers(r["memo"], sheet)
        attempts = 1
        if bad:
            r = write_memo(
                client,
                sheet,
                feedback=f"Your previous draft used figures not in the fact sheet: {bad}. "
                "Remove or correct every one of them.",
            )
            bad = unverified_numbers(r["memo"], sheet)
            attempts = 2
        (out_dir / f"{t}.json").write_text(
            json.dumps(
                {
                    "ticker": t,
                    "generated_by": r["model"],
                    "as_of": c["params"]["last_quarter"],
                    "attempts": attempts,
                    "unverified_numbers": bad,
                    "fact_sheet": sheet,
                    **r["memo"],
                    "usage": r["usage"],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"{t}: {r['memo']['verdict']} | attempts={attempts} unverified={bad} tokens={r['usage']}")


build = main


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]])
