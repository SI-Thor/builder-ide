"""Walk the SimReady dataset's file index and save it as JSONL.

The index is metadata only: the tree API returns names, sizes and LFS
pointers. No asset bytes are fetched by this script.
"""
from __future__ import annotations

import json
import sys
import time

from huggingface_hub import HfApi

REPO = "nvidia/simready-assets"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/caseydigennaro/lm-wt/simready-survey/data/repo_index.jsonl"

api = HfApi()
rows: list[dict] = []
started = time.time()
for entry in api.list_repo_tree(REPO, repo_type="dataset", recursive=True):
    rows.append(
        {
            "path": entry.path,
            "type": entry.__class__.__name__,
            "size": getattr(entry, "size", None),
            "lfs": getattr(entry, "lfs", None) and {
                "size": entry.lfs.size,
                "sha256": entry.lfs.sha256,
                "pointer_size": entry.lfs.pointer_size,
            },
        }
    )
    if len(rows) % 5000 == 0:
        print(f"{len(rows)} entries {time.time()-started:.0f}s", flush=True)

with open(OUT, "w") as handle:
    for row in rows:
        handle.write(json.dumps(row) + "\n")
print(f"wrote {len(rows)} entries to {OUT} in {time.time()-started:.0f}s")
