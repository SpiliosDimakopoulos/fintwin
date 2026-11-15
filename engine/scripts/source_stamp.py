"""Write engine/SOURCE.json before a server push: the commit, whether the tree is dirty, and the code digest that
enters every shard stamp. rev3_server.sh refuses to run when the server's code digest differs (.git is not pushed,
so this file is the only record of which commit produced a run)."""

import json
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from fintwin.research.__main__ import _code_digest  # noqa: E402


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ENGINE, capture_output=True, text=True, check=True).stdout.strip()


if __name__ == "__main__":
    dirty = git("status", "--porcelain", "--", ".")
    rec = {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty),
        "dirty_files": dirty.splitlines()[:50],
        "code_digest": _code_digest(),
    }
    (ENGINE / "SOURCE.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(f"{rec['commit'][:9]} {'dirty' if dirty else 'clean'} digest {rec['code_digest'][:12]}")
