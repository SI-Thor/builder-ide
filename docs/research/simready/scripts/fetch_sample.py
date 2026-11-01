"""Download the sample of SimReady assets into ~/lm-cold/simready-sample/.

Only the asset payload is fetched: the USD stage, the payloads, the textures
and the package metadata. The thumbnails are left behind — they are the bulk
of the repository's bytes and carry none of the schema. The ``source_assets``
folder is left behind too: it holds a second copy of the same textures and
the MDL material library, which ``materials.usda`` already references.

The run is resumable and rate-limit aware: Hugging Face caps anonymous
resolve requests at 5,000 per five minutes, and the sweep is restarted until
it stops making progress.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from huggingface_hub import snapshot_download

REPO = "nvidia/simready-assets"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "sample_manifest.json"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "lm-cold" / "simready-sample"


def bytes_on_disk(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    assets = [row["asset"] for row in manifest["assets"]]
    allow = [f"{asset}/*" for asset in assets]
    OUT.mkdir(parents=True, exist_ok=True)

    previous = bytes_on_disk(OUT)
    print(f"{len(assets)} assets; {previous / 1024**2:.1f} MiB already on disk", flush=True)
    for attempt in range(30):
        started = time.time()
        try:
            snapshot_download(
                repo_id=REPO,
                repo_type="dataset",
                allow_patterns=allow,
                ignore_patterns=["*/.thumbs/*", "*/source_assets/*"],
                local_dir=str(OUT),
                local_dir_use_symlinks=False,
                max_workers=6,
            )
        except Exception as error:
            print(f"attempt {attempt}: {type(error).__name__}: {error}", flush=True)
        now = bytes_on_disk(OUT)
        print(
            f"attempt {attempt}: {now / 1024**3:.2f} GiB "
            f"(+{(now - previous) / 1024**2:.0f} MiB) in {time.time() - started:.0f}s",
            flush=True,
        )
        if now == previous:
            print("complete", flush=True)
            return 0
        previous = now
        time.sleep(15)
    print(f"stopped at {bytes_on_disk(OUT) / 1024**3:.2f} GiB", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
