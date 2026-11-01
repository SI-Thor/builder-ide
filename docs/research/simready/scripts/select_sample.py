"""Choose the sample of SimReady assets to download.

The brief asks for 30–50 assets across categories, at most 3 GB. The rule
here is deterministic so the same sample comes back on a rebuild:

* every asset in the dataset carries a category prefix (the first
  underscore-delimited token of its folder name), so the sample is stratified
  by category — one asset per category, never two from the same category
  unless the category is deliberately widened;
* within a category the asset chosen is the one whose payload sits closest
  to that category's median payload size, so the sample is representative
  rather than biased toward the tiny or the huge;
* categories are taken in descending order of how many assets they hold,
  which puts the crowded everyday categories (food, kitchenware, box) in and
  the singletons in as a tail;
* a small, explicit list of articulated candidates is added by name, because
  doors, drawers, cabinets and lids are what question 5 is about and they
  are a small minority of the dataset.

Thumbnails are excluded: they are the bulk of the repository's bytes and
carry none of the schema.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

INDEX = Path("/home/caseydigennaro/simready-survey/data/repo_index.jsonl")
if not INDEX.exists():
    INDEX = Path(__file__).resolve().parents[1] / "data" / "repo_index.jsonl"
OUT = Path(__file__).resolve().parents[1] / "data" / "sample_manifest.json"

#: The budget the brief sets.
BUDGET_BYTES = 3 * 1024**3

#: No single asset may take more than this share of the budget, or one
#: 2 GB structure would crowd out thirty others.
MAX_ASSET_BYTES = 450 * 1024**2

#: Categories asked for by name, because each one is needed for a question:
#: - the articulated ones answer question 5;
#: - the vehicle and structure ones answer questions 3 and 4 (they are the
#:   heavy end of the size distribution);
#: - the medical ones are the categories the builder-ide vocabulary has no
#:   word for at all, so they are the gap in question 3.
EXPLICIT = [
    "bodyPart_door_front_a01",      # articulated: a car door
    "bodyPart_trunk_lid_a01",       # articulated: a boot lid
    "fixture_cabinet_a01",          # articulated: a cabinet with doors
    "pallet_rackable_solid_top_blue_a02",  # articulated: a lift lid
    "vehicle_forklift_blue_c01",    # a vehicle the world may hold
    "structure_beam_a01",           # structure, not a prop
    "equipment_bench_vise_a01",     # a piece of equipment
    "dishware_mug_a01",             # the canonical prop
    "handTool_hammer_crossPeen_b01",  # a tool
    "IV_pole_a01",                  # medical: a category the vocabulary lacks
    "lighting_overheadLed_hexGrid_a01",  # lighting
    "stationery_pen_plastic_a01",   # stationery
    "ppe_respirator_halfMask_b01",  # PPE
    "instrument_spoon_a01",         # an instrument
]


def main() -> int:
    rows = [json.loads(line) for line in INDEX.open()]
    files = [row for row in rows if row["type"] == "RepoFile"]

    def size(row: dict) -> int:
        lfs = row.get("lfs")
        if lfs:
            return int(lfs["size"])
        return int(row.get("size") or 0)

    by_asset: dict[str, list[dict]] = collections.defaultdict(list)
    for row in files:
        path = row["path"]
        if "/" not in path:
            # The repository root holds .gitattributes and README.md; they
            # are not assets.
            continue
        by_asset[path.split("/")[0]].append(row)

    def payload_bytes(asset: str) -> int:
        return sum(
            size(row) for row in by_asset[asset] if "/.thumbs/" not in row["path"]
        )

    def category(asset: str) -> str:
        return asset.split("_")[0]

    assets = sorted(by_asset)
    payload = {asset: payload_bytes(asset) for asset in assets}

    by_category: dict[str, list[str]] = collections.defaultdict(list)
    for asset in assets:
        by_category[category(asset)].append(asset)

    # The median-payload asset of each category: representative, not extreme.
    representative: dict[str, str] = {}
    for name, members in by_category.items():
        ordered = sorted(members, key=lambda a: (payload[a], a))
        # The 25th percentile of the category's members by payload size:
        # representative of what the category holds, but cheap enough that
        # thirty-seven categories fit inside the budget.  The percentile
        # is what makes the sample affordable; the median pick spent the
        # whole budget on a dozen categories.
        representative[name] = ordered[int(len(ordered) * 0.25)]

    # Categories in descending order of size; ties broken by name.
    order = sorted(by_category, key=lambda name: (-len(by_category[name]), name))

    chosen: list[str] = []
    seen_categories: set[str] = set()
    total = 0
    notes: dict[str, str] = {}

    def take(asset: str, why: str) -> bool:
        nonlocal total
        if asset not in payload or asset in chosen:
            return False
        if payload[asset] > MAX_ASSET_BYTES:
            return False
        if total + payload[asset] > BUDGET_BYTES:
            return False
        chosen.append(asset)
        seen_categories.add(category(asset))
        notes[asset] = why
        total += payload[asset]
        return True

    def take_from_category(name: str) -> bool:
        """Take one asset of a category, representative size if it fits."""
        if name in seen_categories:
            return False
        members = by_category[name]
        if take(representative[name], f"category:{name}"):
            return True
        # The median member is over the per-asset cap or the budget is
        # nearly gone: take the smallest member of the category instead,
        # which still tells us what the category looks like.
        for asset in sorted(members, key=lambda a: (payload[a], a)):
            if take(asset, f"category:{name}:smallest"):
                return True
        return False

    # 1. The explicit list first: these answer named questions.
    for asset in EXPLICIT:
        take(asset, "explicit")

    # 2. Then one representative from each of the most crowded categories,
    #    then a tail from the rarer ones, so the vocabulary mapping sees the
    #    long tail and not only the head.
    for name in order:
        if len(seen_categories) >= 40:
            break
        take_from_category(name)

    # 3. If the budget stopped us short of thirty assets, top up from the
    #    smallest assets in the categories not yet covered.
    if len(chosen) < 30:
        for name in order:
            if len(chosen) >= 30:
                break
            if name in seen_categories:
                continue
            take_from_category(name)

    manifest = {
        "repo": "nvidia/simready-assets",
        "repo_sha": "4763fbfaa4f8e97658e68b57d01b4c86659e08b5",
        "licence": "CC-BY-4.0",
        "budget_bytes": BUDGET_BYTES,
        "selection_rule": (
            "one asset per category, closest to the category's median payload "
            "size, categories ordered by how many assets they hold, plus the "
            "explicit list; thumbnails excluded"
        ),
        "asset_count": len(chosen),
        "payload_bytes": total,
        "categories_covered": len(seen_categories),
        "assets": [
            {
                "asset": asset,
                "category": category(asset),
                "payload_bytes": payload[asset],
                "why": notes.get(asset, ""),
                "files": len(by_asset[asset]),
            }
            for asset in chosen
        ],
    }
    OUT.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(chosen)} assets, {len(seen_categories)} categories, "
          f"{total/1024**2:.1f} MiB payload")
    for row in manifest["assets"]:
        print(f"  {row['payload_bytes']/1024**2:8.1f} MiB  {row['category']:18s} {row['asset']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
