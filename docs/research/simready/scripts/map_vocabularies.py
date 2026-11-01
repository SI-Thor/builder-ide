"""Map the SimReady vocabulary onto builder-ide's and Infinigen's.

Three vocabularies, measured against each other:

* **SimReady** — 2,677 asset packages, grouped by the first
  underscore-delimited token of the folder name (NVIDIA's own grouping),
  and by the semantic labels the assets declare.
* **builder-ide** — the closed, typed vocabulary a builder may use: the
  words the registry ships, the namespace segments a word may carry, the
  kinds a tile may have, and the SimReady-lite semantic class the USD
  compiler writes.
* **Infinigen** — the asset factories the engine already has, by group and
  by name.

The output is the overlap and the gap, category by category.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

#: builder-ide's shipped vocabulary words (core/vocab/words.py).
BUILDER_WORDS = {
    "props.harbor.crates": {"kind": "prop", "namespace": "props"},
    "props.harbor.racks": {"kind": "prop", "namespace": "props"},
    "material.wood.weathering": {"kind": "material", "namespace": "material"},
}

#: builder-ide's namespace segments (core/vocab/registry.py).
NAMESPACE_SEGMENTS = [
    "prop", "props", "material", "materials", "terrain", "weather", "motion",
    "light", "structure", "structures", "character", "characters",
    "constraint", "constraints",
]

#: builder-ide's tile kinds (core/tiles/models.py).
TILE_KINDS = ["behaviour", "build_step", "recipe_edit"]

#: builder-ide's SimReady-lite semantic classes, as the USD compiler's demo
#: uses them. The slot is an open string today (builder_usd/vocabulary.py).
SIMREADY_LITE_DEMO = ["crate", "post", "bracket", "ground"]

#: The collision models builder-ide's USD compiler accepts.
COLLISION_MODELS = ["none", "boundingCube", "boundingSphere", "convexHull", "mesh"]

#: Words that name the same thing in more than one vocabulary. Each is a
#: plain singular noun, matched against the SimReady category and against
#: the Infinigen factory name.
SYNONYMS = {
    "crate": ["crate", "box"],
    "box": ["box", "carton"],
    "pallet": ["pallet"],
    "container": ["container", "can", "jug", "bucket"],
    "drum": ["drum", "barrel"],
    "bucket": ["bucket", "pail"],
    "bottle": ["bottle", "jug"],
    "paint": ["paint", "can"],
    "candle": ["candle"],
    "tape": ["tape"],
    "decor": ["candle", "decoration", "ornament"],
    "sign": ["sign", "signage"],
    "chair": ["chair", "stool", "seat"],
    "table": ["table", "desk"],
    "cabinet": ["cabinet", "cupboard", "locker"],
    "rack": ["rack", "shelf", "shelving", "bookcase"],
    "storage": ["shelf", "shelving", "storage"],
    "shelf": ["shelf", "shelving"],
    "lighting": ["light", "lamp", "luminaire"],
    "lamp": ["lamp", "light"],
    "light": ["light", "lamp"],
    "dishware": ["bowl", "plate", "cup", "mug", "glass", "dish"],
    "kitchenware": ["pan", "pot", "knife", "fork", "spoon", "kettle"],
    "food": ["food", "snack", "produce"],
    "utensils": ["scissors", "tool", "utensil"],
    "utensil": ["knife", "fork", "spoon", "utensil"],
    "instrument": ["spoon", "knife", "instrument"],
    "stationery": ["pen", "pencil", "marker", "stationery"],
    "ppe": ["glove", "respirator", "helmet", "goggles", "mask", "clog"],
    "medicine": ["medicine", "drug", "vaccine", "tablet"],
    "handTool": ["hammer", "wrench", "screwdriver", "plier", "chisel", "tool"],
    "tool": ["tool", "hammer", "wrench"],
    "tools": ["tool"],
    "powerTool": ["drill", "saw", "grinder", "sander", "tool"],
    "testingTool": ["multimeter", "meter", "tester", "gauge"],
    "serviceTool": ["lathe", "press", "tool", "jack"],
    "tireTool": ["changer", "balancer", "tool"],
    "equipment": ["equipment", "machine", "device", "vise"],
    "vehicle": ["forklift", "car", "truck", "vehicle"],
    "vehicleSupport": ["jack", "stand", "ramp", "support"],
    "structure": ["beam", "wall", "structure"],
    "warehouse": ["conveyor", "rack", "pallet", "warehouse"],
    "factory": ["factory", "workstation"],
    "workstation": ["workstation", "bench", "desk"],
    "engineComponent": ["engine", "camshaft", "piston", "valve", "component"],
    "engineAssembly": ["engine", "assembly"],
    "drivetrain": ["drivetrain", "axle", "gear"],
    "suspension": ["suspension", "shock", "arm"],
    "brakeSystem": ["brake", "caliper"],
    "steeringSystem": ["steering", "wheel"],
    "steering": ["steering", "wheel"],
    "bodyPart": ["door", "lid", "boot", "trunk", "panel", "body"],
    "interiorPart": ["seat", "console", "dashboard", "interior"],
    "coolingSystem": ["cooler", "fan", "cooling"],
    "fuelSystem": ["fuel", "tank", "pump"],
    "exhaustSystem": ["exhaust", "muffler"],
    "electricalSystem": ["starter", "alternator", "battery", "electrical"],
    "electrical": ["socket", "outlet", "switch", "electrical"],
    "airSystem": ["compressor", "filter", "hose"],
    "computer": ["computer", "pc", "tower"],
    "monitor": ["monitor", "screen", "display"],
    "screen": ["screen", "display", "monitor"],
    "appliance": ["appliance", "fridge", "oven", "washer"],
    "refrigerator": ["fridge", "refrigerator"],
    "climate": ["hvac", "air", "climate"],
    "hvac": ["hvac", "ventilation", "air"],
    "ventilation": ["ventilation", "duct", "fan"],
    "fireProtection": ["extinguisher", "hydrant", "alarm", "sprinkler"],
    "safety": ["helmet", "goggle", "safety", "vest"],
    "ppe2": [],
    "medical": ["medical", "stethoscope", "syringe", "xray"],
    "IV": ["iv", "pole", "infusion"],
    "syringe": ["syringe", "needle"],
    "needle": ["needle"],
    "bandage": ["bandage", "dressing"],
    "anesthesia": ["anesthesia", "machine"],
    "disinfectant": ["disinfectant", "sanitiser", "sanitizer"],
    "cleaning": ["soap", "sponge", "cleaner", "brush", "broom"],
    "consumable": ["consumable", "fuse", "filter", "refill"],
    "pump": ["pump"],
    "pipe": ["pipe", "hose", "tube"],
    "wire": ["wire", "cable"],
    "tube": ["tube", "pipe"],
    "paper": ["paper", "tissue", "roll"],
    "paperbag": ["bag", "paper bag"],
    "pack": ["pack", "package", "wrap"],
    "hardware": ["bolt", "screw", "nut", "hinge"],
    "screw": ["screw", "bolt"],
    "fixture": ["fixture", "cabinet", "bracket", "light"],
    "blinds": ["blind", "shade"],
    "chair2": [],
    "furniture": ["furniture", "sofa", "table", "shelf", "bed"],
    "sofa": ["sofa", "couch"],
    "bed": ["bed", "mattress"],
    "book": ["book"],
    "magazine": ["magazine", "book"],
    "toy": ["toy", "ball", "doll"],
    "toys": ["toy"],
    "fauset": ["faucet", "tap", "fauset"],
    "sink": ["sink", "basin", "washbasin"],
    "washBasin": ["basin", "sink"],
    "toilet": ["toilet"],
    "bathroom": ["bathroom", "toilet", "sink", "mirror"],
    "mirror": ["mirror"],
    "faucet2": [],
    "bedding": ["bedding", "sheet", "pillow"],
    "pillow": ["pillow"],
    "mattress": ["mattress", "bed"],
    "clogs": ["clog", "shoe"],
    "footwear": ["shoe", "boot", "clog"],
    "mask": ["mask", "respirator"],
    "facemask": ["mask"],
    "o2": [],
    "acc": [],
    "accessory": ["accessory"],
    "arm": ["arm"],
    "handTruck": ["hand truck", "dolly", "handtruck"],
    "tiltTruck": ["tilt truck", "hand truck"],
    "palletJack": ["pallet jack", "jack"],
    "hopper": ["hopper"],
    "ibcTank": ["ibc", "tank"],
    "extrusion": ["extrusion", "profile", "beam"],
    "conveyor": ["conveyor", "belt"],
    "scaffold": ["scaffold"],
    "ramp": ["ramp"],
    "stapler": ["stapler"],
    "phone": ["phone", "mobile"],
    "video": ["video", "camera", "monitor"],
    "TV": ["tv", "television"],
    "cap": ["cap"],
    "thermometer": ["thermometer"],
    "oximeter": ["oximeter"],
    "defibrillator": ["defibrillator"],
    "humidifier": ["humidifier"],
    "warmer": ["warmer"],
    "purifier": ["purifier"],
    "extractor": ["extractor", "hood"],
    "detector": ["detector"],
    "pen": ["pen"],
    "grid": ["grid", "mesh", "grating"],
    "rail": ["rail"],
    "fence": ["fence", "barrier"],
    "barrier": ["barrier", "fence"],
    "environmental": [],
    "environment": ["environment", "ground"],
    "water": ["water"],
    "blood": ["blood", "bag"],
    "cannulae": ["cannula", "tube"],
    "catheter": ["catheter", "tube"],
    "drainage": ["drain", "drainage"],
    "drape": ["drape", "cloth"],
    "sanitary": ["sanitary", "hygiene"],
    "case": ["case", "box"],
    "scissor": ["scissors"],
    "bicycle": ["bicycle", "bike"],
    "wheelChair": ["wheelchair"],
    "robot": ["robot"],
    "robotics": ["robot"],
    "robotic": ["robot"],
    "machine": ["machine"],
    "machineGuard": ["guard", "machine guard"],
    "facilitySystem": ["facility", "system"],
    "facilityEquipment": ["equipment"],
    "facilityFurniture": ["furniture"],
    "workshopSystem": ["workshop", "system"],
    "storageSystem": ["storage", "system"],
    "digitalSystem": ["display", "panel", "system"],
    "panel": ["panel", "control panel"],
    "switch": ["switch"],
    "unit": ["unit", "machine"],
    "trash": ["trash", "waste", "bin"],
    "trashCan": ["trash can", "bin", "waste"],
    "waste": ["waste", "garbage"],
    "wasteManagement": ["waste", "compactor"],
    "construction": ["construction"],
    "supply": ["supply"],
    "other": [],
    "asset": [],
}


def normalise(text: str) -> str:
    """Lowercase, split camelCase and spaces into words, drop the suffixes.

    The suffix matters: every Infinigen factory class is called
    ``SomethingFactory``, and without dropping it the word "factory" is a
    token of every one of them and matches any category called "factory".
    """
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    words = text.lower().split()
    while words and words[-1] in ("factory", "base", "instance"):
        words.pop()
    return " ".join(words)


def load_infinigen(root: Path) -> dict[str, list[str]]:
    """The asset factories, by group and by name."""
    objects = root / "src" / "infinigen" / "assets" / "objects"
    factories: dict[str, list[str]] = collections.defaultdict(list)
    if not objects.exists():
        return {}
    for path in sorted(objects.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(errors="ignore")
        for match in re.finditer(r"class\s+(\w+)\s*\(\s*AssetFactory", text):
            group = str(path.parent.relative_to(objects)).replace("/", ".")
            factories[group].append(match.group(1))
    return {group: sorted(names) for group, names in factories.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", required=True, help="the repo file index JSONL")
    parser.add_argument("--report", help="the sample report JSON")
    parser.add_argument("--infinigen", required=True, help="the infinigen-thor checkout")
    parser.add_argument("--out", required=True, help="where to write the mapping")
    args = parser.parse_args()

    # -- SimReady -------------------------------------------------------------
    assets: list[str] = []
    for line in Path(args.index).open():
        row = json.loads(line)
        if row["type"] != "RepoFile":
            continue
        path = row["path"]
        if "/" not in path:
            continue
        assets.append(path.split("/")[0])
    assets = sorted(set(assets))
    categories: dict[str, int] = collections.Counter(
        asset.split("_")[0] for asset in assets
    )

    # -- Infinigen ------------------------------------------------------------
    factories = load_infinigen(Path(args.infinigen))
    factory_names = sorted(
        {normalise(name) for names in factories.values() for name in names}
    )
    factory_lookup: dict[str, list[str]] = collections.defaultdict(list)
    # A factory is also indexed by each of its **whole words**, so a
    # category can be matched on a token ("rack" in "plate on rack base")
    # without matching inside a word ("pan" in "pants", "can" in "cabinet").
    factory_tokens: dict[str, list[str]] = collections.defaultdict(list)
    for group, names in factories.items():
        for name in names:
            full = normalise(name)
            factory_lookup[full].append(f"{group}.{name}")
            for token in set(full.split()):
                factory_tokens[token].append(f"{group}.{name}")

    # -- builder-ide ----------------------------------------------------------
    builder_words = {word: dict(info) for word, info in BUILDER_WORDS.items()}

    # -- the mapping ----------------------------------------------------------
    rows = []
    for category, count in sorted(categories.items(), key=lambda kv: (-kv[1], kv[0])):
        key = normalise(category)
        words = SYNONYMS.get(category, [])
        if not words:
            words = [key] if key else []
        matched_factories: list[str] = []
        for word in words:
            word_key = normalise(word)
            if word_key in factory_lookup:
                matched_factories.extend(factory_lookup[word_key])
            elif word_key in factory_tokens:
                matched_factories.extend(factory_tokens[word_key])
        matched_factories = sorted(set(matched_factories))
        covered_by_word = [
            word for word, info in builder_words.items()
            if any(
                normalise(part) in key
                for part in info["namespace"].split()
                for part in [part]
            ) and normalise(word.split(".")[-1]) in key
        ]
        rows.append(
            {
                "simready_category": category,
                "assets": count,
                "candidate_words": words,
                "infinigen_factories": matched_factories,
                "builder_ide_word": covered_by_word[0] if covered_by_word else None,
                "builder_ide_namespace": "props"
                if count
                else None,
            }
        )

    covered = [r for r in rows if r["infinigen_factories"]]
    uncovered = [r for r in rows if not r["infinigen_factories"]]
    mapping = {
        "simready": {
            "assets": len(assets),
            "categories": len(categories),
            "category_counts": dict(sorted(categories.items(), key=lambda kv: (-kv[1], kv[0]))),
            "largest_categories": dict(
                sorted(categories.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
            ),
        },
        "builder_ide": {
            "words": builder_words,
            "namespace_segments": NAMESPACE_SEGMENTS,
            "tile_kinds": TILE_KINDS,
            "simready_lite_semantic_classes_used": SIMREADY_LITE_DEMO,
            "simready_lite_semantic_slot": (
                "open string today (builder_usd/vocabulary.py accepts any "
                "string for semantic_type); no closed list exists yet"
            ),
            "collision_models": COLLISION_MODELS,
        },
        "infinigen": {
            "groups": len(factories),
            "factories": sum(len(names) for names in factories.values()),
            "by_group": {group: sorted(names) for group, names in sorted(factories.items())},
        },
        "overlap": {
            "simready_categories": len(categories),
            "categories_with_an_infinigen_factory": len(covered),
            "categories_without": len(uncovered),
            "categories_without_names": [r["simready_category"] for r in uncovered],
            "simready_assets_covered_by_an_infinigen_factory": sum(
                r["assets"] for r in covered
            ),
            "simready_assets_covered_share": round(
                sum(r["assets"] for r in covered) / max(len(assets), 1), 4
            ),
        },
        "mapping": rows,
    }
    Path(args.out).write_text(json.dumps(mapping, indent=2) + "\n")
    print(json.dumps(mapping["overlap"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
