"""Fetch five fresh SimReady packages and convert them to GLB.

**The rule.** The brief's mesh set is "the critic's reference set plus 5
SimReady samples" — five assets the prior was **not** fitted on. They are
picked by a rule this script recomputes, not by hand:

* the categories are the five shape kinds the critic has to tell apart —
  a **shell** (`dishware_mug`), a **multi-part vehicle**
  (`vehicle_forklift_blue`), a **near-convex ball** (`misc_golfBall`), a
  **thin plate** (`sign_hospital_board`), a **sparse frame**
  (`storage_shelf_basic`);
* within each, the unsampled asset **closest to the category's median
  payload size** — the survey's own selection rule, one step along.

**What it needs.** The survey's file index (`repo_index.jsonl`) and the
reference set's asset names, both on disk already; `pxr` (USD) only for the
conversion half — run it with `~/lm-wt/mesh-repair/.venv/bin/python`, the
venv the survey itself used. Downloads go to `~/lm-cold/simready-extra`
(resumable: a file of the right size is left alone), one plain GET per file
against the Hub's resolve endpoint — the survey's way through the anonymous
rate limit. The GLBs land in `~/lm-wt/simready-survey/data/glb-extra/`,
beside the reference set's GLBs, outside the repository.

Usage::

    ~/lm-wt/mesh-repair/.venv/bin/python docs/lab/open3d-critic/fetch_extra_samples.py
    ~/lm-wt/mesh-repair/.venv/bin/python docs/lab/open3d-critic/fetch_extra_samples.py --fetch-only

Dataset: nvidia/simready-assets, CC-BY-4.0, credited. Five packages, not a
mirror.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SURVEY = Path.home() / "lm-wt" / "simready-survey"
INDEX = SURVEY / "data" / "repo_index.jsonl"
REFERENCE = Path(__file__).resolve().parents[3] / "core" / "genbatch" / "simready-reference.json"
OUT = Path.home() / "lm-cold" / "simready-extra"
GLB_DIR = SURVEY / "data" / "glb-extra"
BASE = "https://huggingface.co/datasets/nvidia/simready-assets/resolve/main"

#: The five categories, and the shape kind each stands for.
CATEGORIES: dict[str, str] = {
    "dishware_mug": "a shell — the reference set's own mug category",
    "vehicle_forklift_blue": "a multi-part vehicle — the 32-primitive kind",
    "misc_golfBall": "a near-convex solid",
    "sign_hospital_board": "a thin plate — the category of the one flagged real asset",
    "storage_shelf_basic": "a sparse frame — the shape the visual hull fails on",
}


def pick_five() -> list[tuple[str, str, int]]:
    """The five (category, asset, payload bytes), by the rule above."""
    sampled = {a["name"] for a in json.loads(REFERENCE.read_text())["assets"]}
    payloads: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for line in INDEX.open():
        row = json.loads(line)
        if row["type"] != "RepoFile":
            continue
        path = row["path"]
        if "/.thumbs/" in path:
            continue
        size = (row.get("lfs") or {}).get("size") or row.get("size") or 0
        payloads[path.split("/")[0]][path] = int(size)

    def category(name: str) -> str:
        head, _, tail = name.rpartition("_")
        return head if tail else name

    picked = []
    for wanted, _kind in CATEGORIES.items():
        members = {name: sum(files.values()) for name, files in payloads.items()
                   if category(name) == wanted}
        unsampled = {name: size for name, size in members.items() if name not in sampled}
        if not unsampled:
            raise SystemExit(f"category {wanted} has no unsampled asset")
        median = statistics.median(members.values())
        name = min(unsampled, key=lambda n: abs(unsampled[n] - median))
        picked.append((wanted, name, unsampled[name]))
    return picked


def wanted_files(asset: str) -> list[tuple[str, int]]:
    rows = []
    for line in INDEX.open():
        row = json.loads(line)
        if row["type"] != "RepoFile":
            continue
        path = row["path"]
        if path.split("/")[0] != asset or "/.thumbs/" in path:
            continue
        size = (row.get("lfs") or {}).get("size") or row.get("size") or 0
        rows.append((path, int(size)))
    return rows


def fetch_one(path: str, size: int) -> tuple[str, str]:
    """Download one file, skipping it if it is already the right size."""
    target = OUT / path
    if target.exists() and target.stat().st_size == size:
        return path, "cached"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    for attempt in range(6):
        try:
            request = urllib.request.Request(
                f"{BASE}/{path}", headers={"User-Agent": "simready-survey/1.0"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                with open(temporary, "wb") as handle:
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        handle.write(chunk)
            os.replace(temporary, target)
            return path, "fetched"
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(20 + 10 * attempt)
                continue
            return path, f"http-{error.code}"
        except Exception as error:  # noqa: BLE001 - reported, not raised
            if attempt == 5:
                return path, f"error-{type(error).__name__}"
            time.sleep(3)
    return path, "gave-up"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch-only", action="store_true")
    args = parser.parse_args()

    picked = pick_five()
    for category, name, size in picked:
        print(f"{category:28s} {name} ({size / 1e6:.1f} MB)")
    total = sum(size for _, _, size in picked)
    print(f"total payload: {total / 1e6:.0f} MB")

    wanted: list[tuple[str, int]] = []
    for _, name, _ in picked:
        wanted.extend(wanted_files(name))
    print(f"{len(wanted)} files wanted", flush=True)

    failed: list[tuple[str, str]] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for path, outcome in pool.map(lambda item: fetch_one(*item), wanted):
            if outcome not in ("cached", "fetched"):
                failed.append((path, outcome))
    fetched = sum(1 for f in OUT.rglob("*") if f.is_file())
    size_gib = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1024**2
    print(f"fetch done in {time.time() - started:.0f}s: {fetched} files, "
          f"{size_gib:.0f} MB, {len(failed)} failed", flush=True)
    if failed:
        print("failures:", failed[:20], flush=True)
        return 1
    if args.fetch_only:
        return 0

    # -- the conversion half: pxr USD -> GLB, the survey's own converter ----
    sys.path.insert(0, str(SURVEY / "scripts"))
    from simready_loader import convert_asset  # noqa: E402 - needs the path above

    GLB_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for _, name, _ in picked:
        out = GLB_DIR / f"{name}.glb"
        stats = convert_asset(OUT / name, out)
        manifest.append({
            "asset": name,
            "glb": str(out),
            "triangles": stats.triangles,
            "primitives": stats.primitives,
            "seconds": round(stats.seconds, 3),
        })
        print(f"converted {name}: {stats.triangles} tris, "
              f"{stats.primitives} primitives, {stats.seconds:.1f}s", flush=True)
    (Path(__file__).resolve().parent / "results" / "extra_samples.json").write_text(
        json.dumps(manifest, indent=2)
    )
    print("wrote results/extra_samples.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
