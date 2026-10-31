"""Check the bake-off's artifacts for the API key — before they are committed.

The key must never be in a result file, a log or a committed script. This
walks every artifact in the scripts directory and reports any leak; it prints
the *where*, never the key itself.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.critic.candidates.jev import read_api_key  # noqa: E402

TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")
BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{8,}")


def main() -> int:
    key = read_api_key()
    here = pathlib.Path(__file__).resolve().parent
    leaks: list[str] = []
    for path in sorted(here.rglob("*")):
        if path.is_dir() or "__pycache__" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if key and key in text:
            leaks.append(f"{path}: the key itself")
        for match in BEARER.finditer(text):
            leaks.append(f"{path}: {match.group(0)[:24]}...")
        for match in TOKEN.finditer(text):
            if key and match.group(0) == key:
                leaks.append(f"{path}: the key as a token")
    if leaks:
        print("LEAKS:")
        for leak in leaks:
            print(" ", leak)
        return 1
    print("no leaks: the key is in none of the artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
