"""Fetch the metadata/catalogue files for every asset in the dataset.

These are the small JSON and LICENCE files that describe each SimReady
package: conformance reports, the bill of materials, the package manifest.
Together they are a catalogue of all 2,677 assets at a few tens of
megabytes, with no asset payload downloaded.

Hugging Face rate-limits anonymous resolve requests to 5,000 per five
minutes, and this sweep is about 19,000 files, so the worker count is kept
low and the run is restarted until it stops making progress. The download
is resumable: files already on disk are not fetched again.
"""
from __future__ import annotations

import os
import sys
import time

from huggingface_hub import snapshot_download

REPO = "nvidia/simready-assets"
OUT = sys.argv[1] if len(sys.argv) > 1 else str(
    __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "metadata"
)

ALLOW = [
    "*/.metadata/*.json",
    "*/com.nvidia.simready.packaging.json",
    "*/.metadata/LICENSE.txt",
]


def count() -> int:
    total = 0
    for root, _dirs, names in os.walk(OUT):
        total += len(names)
    return total


def main() -> int:
    previous = count()
    print(f"starting from {previous} files", flush=True)
    for attempt in range(40):
        started = time.time()
        try:
            snapshot_download(
                repo_id=REPO,
                repo_type="dataset",
                allow_patterns=ALLOW,
                local_dir=OUT,
                local_dir_use_symlinks=False,
                max_workers=4,
            )
        except Exception as error:  # rate limit, transient network
            print(f"attempt {attempt}: {type(error).__name__}: {error}", flush=True)
        now = count()
        print(
            f"attempt {attempt}: {now} files (+{now - previous}) "
            f"in {time.time() - started:.0f}s",
            flush=True,
        )
        if now == previous:
            # No progress in a whole attempt: the sweep is done.
            print(f"complete: {now} files", flush=True)
            return 0
        previous = now
        time.sleep(20)
    print(f"stopped with {count()} files", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
