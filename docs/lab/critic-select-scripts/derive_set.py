#!/usr/bin/env python3
"""Re-derive the reference set's derived images and check them against the manifest.

The reference set is a **recipe**: every member records the base render's
sha256 and the recipe of its seeded defect. This script re-derives every
image member from its base render and its own recipe, and compares the
result with the hash the manifest recorded.

That comparison is the check that matters for a bake-off: if the plant does
not re-derive to the same bytes, then the members this seat measures are not
the members the table was published from, and every number downstream is
about a different set.

    python docs/lab/critic-select-scripts/derive_set.py

Writes the derived images into the worktree's cache (``core/critic/.cache``)
and prints one line per member.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.critic.set import materialise, read_bases, read_manifest  # noqa: E402

MANIFEST = ROOT / "core" / "critic" / "reference-set.json"
CACHE = ROOT / "core" / "critic" / ".cache"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    members = read_manifest(MANIFEST)
    bases = read_bases(MANIFEST)
    CACHE.mkdir(parents=True, exist_ok=True)

    rows = []
    for member in members:
        if member.layer != "image":
            continue
        rebuilt = materialise(member, bases, out_dir=CACHE)
        digest = sha256_file(Path(rebuilt.derived_path))
        recorded = member.derived_sha256 or ""
        rows.append(
            {
                "member_id": member.member_id,
                "base_id": member.base_id,
                "defect": member.defect,
                "recorded": recorded,
                "rederived": digest,
                "match": digest == recorded,
                "path": rebuilt.derived_path,
            }
        )

    matched = sum(1 for r in rows if r["match"])
    print(f"re-derived {len(rows)} image members; {matched} match the manifest")
    for row in rows:
        if not row["match"]:
            print(
                f"  MISMATCH {row['member_id']} {row['base_id']} {row['defect']}: "
                f"recorded {row['recorded'][:12]} re-derived {row['rederived'][:12]}"
            )
    out = ROOT / "docs" / "lab" / "critic-select-scripts" / "results" / "derive.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    return 0 if matched == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
