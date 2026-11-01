#!/usr/bin/env python3
"""One neutral description per frame, from the local VLM.

The Jev candidate is a **text-only** critic: it never sees a picture. What it
sees is a description of the frame and the scripted checks' measurements. The
description has to come from somewhere, and the only describer on this box is
the local VLM — so this arm of the bake-off is a *pipeline*: the VLM looks,
and Jev judges what it wrote down.

The prompt is deliberately **neutral**: it asks what the picture shows and
what looks wrong, without naming the defect classes, so the description is
not a hint about which class is planted.

    python docs/lab/critic-select-scripts/caption_frames.py

Writes ``results/captions.json``: ``{member_id: description}``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.critic.candidates.vlm import DEFAULT_ENDPOINT, ask_vlm  # noqa: E402
from core.critic.grow import ensure_derived  # noqa: E402
from core.critic.set import read_bases, read_manifest  # noqa: E402

MANIFEST = ROOT / "core" / "critic" / "reference-set.json"
CACHE = ROOT / "core" / "critic" / ".cache"
RESULTS = ROOT / "docs" / "lab" / "critic-select-scripts" / "results"

PROMPT = (
    "Describe this picture in two sentences: what kind of scene it shows, "
    "what objects are in it, and anything that looks broken, wrong or out of "
    "place."
)


def main() -> int:
    members = read_manifest(MANIFEST)
    bases = read_bases(MANIFEST)
    members = ensure_derived(members, bases, CACHE)

    out_path = RESULTS / "captions.json"
    captions: dict[str, str] = {}
    if out_path.is_file():
        captions = json.loads(out_path.read_text(encoding="utf-8"))

    for member in members:
        if member.layer != "image" or not member.derived_path:
            continue
        if member.member_id in captions:
            continue
        answer, elapsed, usage = ask_vlm(
            DEFAULT_ENDPOINT, member.derived_path, PROMPT, max_tokens=768
        )
        captions[member.member_id] = answer
        print(
            f"  {member.member_id} {member.defect or 'clean':18s} "
            f"{elapsed:6.1f}s  {answer[:110]!r}"
        )

    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(captions, indent=1), encoding="utf-8")
    print(f"wrote {out_path} ({len(captions)} descriptions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
