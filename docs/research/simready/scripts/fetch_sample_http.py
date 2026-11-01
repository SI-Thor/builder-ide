"""Download the sample of SimReady assets over plain HTTP, from the file index.

``snapshot_download`` asks the Hub for the tree and then for a token per
file, and the Hub answers an anonymous client with two rate limits: 5,000
resolver requests per five minutes and 1,000 API requests per five minutes.
The tree is already on disk (``data/repo_index.jsonl``), so this script
skips the tree entirely and issues **one** GET per file against the
``resolve`` endpoint. That is the cheapest way through the resolver quota.

The run is resumable: a file already on disk with the right size is left
alone, and the list of files still wanted is recomputed from the index.
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
MANIFEST = ROOT / "data" / "sample_manifest.json"
BASE = "https://huggingface.co/datasets/nvidia/simready-assets/resolve/main"

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "lm-cold" / "simready-sample"
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 6


def wanted_files() -> list[tuple[str, int]]:
    """Every file of the sample, with the size the index says it has."""
    manifest = json.loads(MANIFEST.read_text())
    assets = {row["asset"] for row in manifest["assets"]}
    wanted: list[tuple[str, int]] = []
    for line in INDEX.open():
        row = json.loads(line)
        if row["type"] != "RepoFile":
            continue
        path = row["path"]
        if path.split("/")[0] not in assets:
            continue
        if "/.thumbs/" in path:
            continue
        size = (row.get("lfs") or {}).get("size") or row.get("size") or 0
        wanted.append((path, int(size)))
    return wanted


def fetch_one(path: str, size: int) -> tuple[str, str]:
    """Download one file, skipping it if it is already the right size."""
    target = OUT / path
    if target.exists() and target.stat().st_size == size:
        return path, "cached"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    for attempt in range(6):
        try:
            request = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": "simready-survey/1.0"})
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
    print(f"{len(wanted)} files wanted", flush=True)
    done = 0
    failed: list[tuple[str, str]] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for path, outcome in pool.map(lambda item: fetch_one(*item), wanted):
            done += 1
            if outcome not in ("cached", "fetched"):
                failed.append((path, outcome))
            if done % 200 == 0:
                print(
                    f"  {done}/{len(wanted)} ({time.time() - started:.0f}s), "
                    f"{len(failed)} failed",
                    flush=True,
                )
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"done: {done} files, {len(failed)} failed, {total / 1024**3:.2f} GiB", flush=True)
    if failed:
        print("failures:", failed[:20], flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
