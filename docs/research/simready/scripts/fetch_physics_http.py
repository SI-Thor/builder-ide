"""Fetch the physics payload of every asset in the dataset.

``payloads/Physics/physics.usda`` is the rigid-body description of an asset:
mass, centre of mass, inertia, friction, restitution, and the joint
structure. Across the whole dataset it is 24 MiB in 2,669 files — small
enough to fetch, and it turns the category priors from a guess into a
measurement, because the mass of every asset in a category becomes known
rather than one asset's.

The download is plain HTTP against the ``resolve`` endpoint, one GET per
file, driven by the file index already on disk.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data" / "repo_index.jsonl"
BASE = "https://huggingface.co/datasets/nvidia/simready-assets/resolve/main"

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "physics"
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 8

SUFFIX = "/simready_usd/payloads/Physics/physics.usda"


def wanted_files() -> list[tuple[str, int]]:
    wanted: list[tuple[str, int]] = []
    for line in INDEX.open():
        row = json.loads(line)
        if row["type"] != "RepoFile":
            continue
        path = row["path"]
        if not path.endswith(SUFFIX):
            continue
        size = (row.get("lfs") or {}).get("size") or row.get("size") or 0
        wanted.append((path, int(size)))
    return wanted


def fetch_one(path: str, size: int) -> tuple[str, str]:
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
        except Exception as error:
            if attempt == 5:
                return path, f"error-{type(error).__name__}"
            time.sleep(3)
    return path, "gave-up"


def main() -> int:
    wanted = wanted_files()
    print(f"{len(wanted)} physics payloads wanted", flush=True)
    done = 0
    failed: list[tuple[str, str]] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for path, outcome in pool.map(lambda item: fetch_one(*item), wanted):
            done += 1
            if outcome not in ("cached", "fetched"):
                failed.append((path, outcome))
            if done % 500 == 0:
                print(
                    f"  {done}/{len(wanted)} ({time.time() - started:.0f}s), "
                    f"{len(failed)} failed",
                    flush=True,
                )
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"done: {done} files, {len(failed)} failed, {total / 1024**2:.1f} MiB", flush=True)
    if failed:
        print("failures:", failed[:20], flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
