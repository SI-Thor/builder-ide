"""Fetch the metadata/catalogue files for every asset in the dataset.

These are the small JSON and LICENCE files that describe each SimReady
package: the conformance reports, the bill of materials, the package
manifest. Together they are a catalogue of all 2,677 assets at a few tens of
megabytes, with no asset payload downloaded.

The download is plain HTTP against the ``resolve`` endpoint, one GET per
file, driven by the file index already on disk. That avoids the Hub's tree
API and its per-file token calls, which is where the anonymous rate limits
are.
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

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "metadata"
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 8

SUFFIXES = (
    ".metadata/com.nvidia.simready.conformance.Package@1.0.0.json",
    ".metadata/com.nvidia.simready.conformance.Package-Candidate@1.0.0.json",
    ".metadata/com.nvidia.simready.packaging.bom.json",
    ".metadata/com.nvidia.simready.root_usds.json",
    "/com.nvidia.simready.packaging.json",
    ".metadata/LICENSE.txt",
)


def wanted_files() -> list[tuple[str, int]]:
    wanted: list[tuple[str, int]] = []
    for line in INDEX.open():
        row = json.loads(line)
        if row["type"] != "RepoFile":
            continue
        path = row["path"]
        if not path.endswith(SUFFIXES):
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
    print(f"{len(wanted)} metadata files wanted", flush=True)
    done = 0
    failed: list[tuple[str, str]] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for path, outcome in pool.map(lambda item: fetch_one(*item), wanted):
            done += 1
            if outcome not in ("cached", "fetched"):
                failed.append((path, outcome))
            if done % 1000 == 0:
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
