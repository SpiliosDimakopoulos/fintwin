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


# A hyphen right after a digit, letter or point joins a range or a date ("2024-25", "Q3-2026", "2025-03-31"), so it
# is read as a minus sign only after a space, punctuation or the start of the text.
NUM = re.compile(r"(?:(?<![\w.])-)?\$?\d+(?:,\d{3})*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    # notes._money writes a typographic minus (U+2212); without this the sign of every negative figure is lost
    text = text.replace("−", "-")
    out = []
    for m in NUM.findall(text):
        neg = m.startswith("-")
        try:
            v = float(m.replace("$", "").replace(",", "").lstrip("-"))
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def unverified_numbers(memo: dict, sheet: dict, strict: bool = False) -> list[float]:
    """Figures in the memo that cannot be matched to the fact sheet (after rounding).

    With ``strict`` a memo figure written with a minus sign must match a negative sheet figure (a flipped sign is
    an error). The default skips |x| <= 12 as quarter counts and ordinals; ``strict`` (used when generating memos) checks them too and enforces signs:
    an integer must equal a sheet figure rounded, a decimal must match within one rounding step.
    """
    allowed = _numbers(json.dumps(sheet, ensure_ascii=False))
    bad = []
    for x in _numbers(json.dumps(memo, ensure_ascii=False)):
        small = abs(x) <= 12
        if (small and not strict) or 1990 <= x <= 2035:  # quarter counts, ordinal words, years
            continue
        pool = [a for a in allowed if a < 0] if (x < 0 and strict) else [abs(a) for a in allowed]
        if small:
            tol = 0.5 if float(x).is_integer() else 0.051
            ok = any(abs(abs(x) - abs(a)) < tol or (tol == 0.5 and round(abs(a)) == abs(x)) for a in pool)
        else:
            ok = any(abs(abs(x) - abs(a)) <= max(0.051 * abs(a), 0.6) for a in pool)
        if not ok:
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

    # A key in the project's git-ignored .env wins over a stale shell variable.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

    client = anthropic.Anthropic()
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    out_dir = DATA / "memos"
    out_dir.mkdir(exist_ok=True)
    for t in tickers:
        c = json.loads((DATA / "companies" / f"{t}.json").read_text(encoding="utf-8"))
        sheet = fact_sheet(c, index["meta"])
        r = write_memo(client, sheet)
        bad = unverified_numbers(r["memo"], sheet, strict=True)
        attempts = 1
        if bad:
            r = write_memo(
                client,
                sheet,
                feedback=f"Your previous draft used figures not in the fact sheet: {bad}. "
                "Remove or correct every one of them.",
            )
            bad = unverified_numbers(r["memo"], sheet, strict=True)
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


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]])
