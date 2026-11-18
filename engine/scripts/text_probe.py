"""D4 probe for T2 (revision plan 5; docs/review_2026-11/text_pipeline/DESIGN.md). Server only: needs the optional
`fintwin[text]` dependencies and the network; not run on the local PC.

1. Checks that the ChronoBERT vintages FIRST..LAST (default 2013-2024) resolve on the Hugging Face hub.
2. Loads one vintage on CPU (sdpa attention, else eager; no flash-attn) and reports which loaded, the config class
   and the maximum sequence length read from the config.
3. Embeds N real sections (default 100) from the text cache (`--sections`: a firm-year .json.gz file or a folder of
   them, as written by fintwin.data.filings_text), or fetched first from SEC for `--ciks` at `--cutoff` (needs
   SEC_USER_AGENT; at the D4 stage the text cache is still empty), and prints seconds per section, seconds per 1k model tokens and
   peak RAM.
4. Extrapolates the hours for the embedding planner's total (`--plan`: a JSON written from
   text_features.plan_embeddings; its total.new_sections / new_tokens), or for `--total-sections`.

python scripts/text_probe.py --ciks 320193 789019 51143 --cutoff 2024-02-15 --total-sections 2000000 --threads 8
python scripts/text_probe.py --sections .cache/text --plan plan.json --threads 8
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--first", type=int, default=2013, help="first vintage year to check on the hub")
    ap.add_argument("--last", type=int, default=2024, help="last vintage year to check on the hub")
    ap.add_argument("--vintage", type=int, default=2023, help="vintage year to load and time")
    ap.add_argument("--sections", type=Path, help="firm-year .json.gz or a folder of them (filings_text cache)")
    ap.add_argument("--ciks", type=int, nargs="+", help="fetch these companies' filing text first (filings_text)")
    ap.add_argument("--cutoff", default="2024-02-15", help="cutoff date for --ciks")
    ap.add_argument("-n", type=int, default=100, help="number of sections to embed")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-length", type=int, default=None, help="cap below the config's maximum length")
    ap.add_argument("--threads", type=int, default=None, help="torch.set_num_threads")
    ap.add_argument("--plan", type=Path, help="JSON from text_features.plan_embeddings (uses total.new_*)")
    ap.add_argument("--total-sections", type=int, default=None, help="sections to extrapolate to (without --plan)")
    return ap.parse_args(argv)


def load_sections(src: Path, n: int) -> list[str]:
    files = [src] if src.is_file() else sorted(src.rglob("*.json.gz"))
    out: list[str] = []
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            rec = json.load(fh)
        for doc in rec["documents"]:
            out += [doc["sections"][s] for s in ("mda", "risk_factors") if doc["sections"].get(s)]
        if len(out) >= n:
            break
    return out[:n]


def peak_ram_mb() -> float | None:
    try:
        import resource  # Linux / macOS

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux
    except ImportError:
        return None


def main(argv=None) -> int:
    args = parse_args(argv)
    from huggingface_hub import HfApi

    from fintwin.research import text_features as T

    api = HfApi()
    missing = []
    for y in range(args.first, args.last + 1):
        repo = T.VINTAGE_REPO.format(year=y)
        try:
            api.model_info(repo)
            print(f"ok      {repo}")
        except Exception as e:  # any hub failure counts as missing; the message says which
            missing.append(repo)
            print(f"MISSING {repo}: {type(e).__name__}: {e}")
    if args.threads:
        import torch

        torch.set_num_threads(args.threads)
    if args.ciks:
        from fintwin.data.filings_text import TEXT_DIR, filing_text

        for cik in args.ciks:
            filing_text(cik, args.cutoff)
        args.sections = args.sections or TEXT_DIR
    if not args.sections:
        raise SystemExit("--sections or --ciks is required for timing (real sections, not synthetic text)")
    texts = load_sections(args.sections, args.n)
    if not texts:
        raise SystemExit(f"no sections in {args.sections}")
    vintage = T.VINTAGE_REPO.format(year=args.vintage)
    t0 = time.perf_counter()
    T.embed(texts[:1], vintage, batch_size=1, max_length=args.max_length)  # load + warm-up
    load_s = time.perf_counter() - t0
    info = T.LOAD_INFO[vintage]
    _, _, tok = T._MODELS[vintage]
    n_tokens = sum(len(tok(t, add_special_tokens=False)["input_ids"]) for t in texts)
    t0 = time.perf_counter()
    vec = T.embed(texts, vintage, batch_size=args.batch_size, max_length=args.max_length)
    secs = time.perf_counter() - t0
    per_section, per_1k = secs / len(texts), secs / max(n_tokens, 1) * 1000
    print(json.dumps({"vintage": vintage, **info, "load_and_warmup_s": round(load_s, 1), "sections": len(texts),
                      "model_tokens": n_tokens, "seconds": round(secs, 1), "s_per_section": round(per_section, 3),
                      "s_per_1k_tokens": round(per_1k, 4), "peak_ram_mb": peak_ram_mb(), "dim": vec.shape[1],
                      "missing_vintages": missing}, indent=1))  # fmt: skip
    if args.plan:
        total = json.loads(args.plan.read_text(encoding="utf-8"))["total"]
        from fintwin.data.filings_text import token_count  # the planner's tokens are filings_text tokens

        words_per_token = sum(token_count(t) for t in texts) / max(n_tokens, 1)
        print(f"plan: {total['new_sections']:,} sections -> {total['new_sections'] * per_section / 3600:.1f} h "
              f"(by section); {total['new_tokens']:,} text tokens ~ {total['new_tokens'] / max(words_per_token, 1e-9):,.0f}"
              f" model tokens -> {total['new_tokens'] / max(words_per_token, 1e-9) * per_1k / 1000 / 3600:.1f} h "
              "(by tokens)")  # fmt: skip
    elif args.total_sections:
        print(f"{args.total_sections:,} sections -> {args.total_sections * per_section / 3600:.1f} h")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
