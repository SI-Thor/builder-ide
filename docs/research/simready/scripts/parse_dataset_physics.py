"""Parse the physics and base layers of every asset in the dataset.

Two files per asset, both small:

* ``payloads/Physics/physics.usda`` — the **PhysicsMaterialAPI**: one block
  per material the asset uses, with its density, its static and dynamic
  friction and its restitution. The material's name is in the prim path
  (``physics_mat_opaque__wood__new_a`` → wood, new finish).
* ``payloads/base.usda`` — the per-part rigid-body **mass**
  (``pxr:usd:physics_mass``) and the **semantic labels**: the Wikidata
  class and the material labels.

Together they give a material table and a mass distribution over the whole
dataset, which is what the category priors need to be more than one
observation per category.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

#: A material block in the physics layer:
#:     over "physics_mat_opaque__wood__new_a" ( ... )
#:     {
#:         float physics:density = 700
#:         float physics:dynamicFriction = 0.5
#:         float physics:restitution = 0.4
#:         float physics:staticFriction = 0.5
#:     }
MATERIAL_BLOCK = re.compile(
    r'over\s+"(physics_mat_[^"]+)"\s*\([^)]*\)\s*\{(?P<body>[^{}]*)\}', re.S
)
FLOAT = re.compile(r"float\s+physics:(\w+)\s*=\s*([-\d.eE+]+)")

#: The semantic labels on the root prim:
#:     token[] semantics:labels:wikidata_class = ["[crate]"]
LABELS = re.compile(r"token\[\]\s+semantics:labels:(\w+)\s*=\s*\[([^\]]*)\]")
MASS = re.compile(r"double\s+pxr:usd:physics_mass\s*=\s*([-\d.eE+]+)")
ASSET_TYPE = re.compile(r'string\s+asset_type\s*=\s*"([^"]*)"')
PROFILE = re.compile(r'string\s+profile\s*=\s*"([^"]*)"')
ASSET_DIR = re.compile(r'string\s+asset_dir\s*=\s*"([^"]*)"')


def _floats(body: str) -> dict[str, float]:
    return {name: float(value) for name, value in FLOAT.findall(body)}


def parse_physics(path: Path) -> list[dict]:
    """The material blocks of one asset's physics layer."""
    text = path.read_text(errors="ignore")
    out = []
    for match in MATERIAL_BLOCK.finditer(text):
        name = match.group(1)
        values = _floats(match.group("body"))
        if not values:
            continue
        out.append({"material_prim": name, **values})
    return out


def parse_base(path: Path) -> dict:
    """The mass and the semantics of one asset's base layer."""
    text = path.read_text(errors="ignore")
    masses = [float(value) for value in MASS.findall(text)]
    labels: dict[str, list[str]] = {}
    for name, values in LABELS.findall(text):
        cleaned = []
        for item in values.split(","):
            item = item.strip().strip('"').strip()
            if item:
                cleaned.append(item.strip("[]"))
        if cleaned:
            labels[name] = cleaned
    asset_type = ASSET_TYPE.search(text)
    profile = PROFILE.search(text)
    asset_dir = ASSET_DIR.search(text)
    return {
        "mass_kg": sum(masses) if masses else None,
        "mass_parts": len(masses),
        "mass_min_kg": min(masses) if masses else None,
        "mass_max_kg": max(masses) if masses else None,
        "labels": labels,
        "asset_type": asset_type.group(1) if asset_type else None,
        "profile": profile.group(1) if profile else None,
        "asset_dir": asset_dir.group(1) if asset_dir else None,
    }


def quantiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    size = len(ordered)
    return {
        "n": size,
        "min": ordered[0],
        "max": ordered[-1],
        "median": ordered[size // 2],
        "p10": ordered[int(size * 0.10)],
        "p90": ordered[min(size - 1, int(size * 0.90))],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--physics-dir", default="data/physics")
    parser.add_argument("--base-dir", default="data/base")
    parser.add_argument("--out", required=True, help="where to write the summary")
    args = parser.parse_args()

    physics_root = Path(args.physics_dir)
    base_root = Path(args.base_dir)

    # -- materials ------------------------------------------------------------
    material_values: dict[str, dict[str, list[float]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    material_assets: dict[str, set[str]] = collections.defaultdict(set)
    asset_materials: dict[str, list[str]] = {}
    physics_files = sorted(physics_root.rglob("physics.usda"))
    for path in physics_files:
        asset = path.parts[len(physics_root.parts)]
        blocks = parse_physics(path)
        names = []
        for block in blocks:
            # physics_mat_opaque__wood__new_a -> wood, finish new
            raw = block["material_prim"].removeprefix("physics_mat_")
            parts = [p for p in raw.split("__") if p]
            material = parts[1] if len(parts) > 1 else raw
            names.append(material)
            material_assets[material].add(asset)
            for key, value in block.items():
                if key != "material_prim":
                    material_values[material][key].append(value)
        asset_materials[asset] = names

    materials = {
        name: {
            "assets": len(material_assets[name]),
            "density_kg_m3": quantiles(values["density"]) if "density" in values else {"n": 0},
            "static_friction": quantiles(values["staticFriction"]) if "staticFriction" in values else {"n": 0},
            "dynamic_friction": quantiles(values["dynamicFriction"]) if "dynamicFriction" in values else {"n": 0},
            "restitution": quantiles(values["restitution"]) if "restitution" in values else {"n": 0},
        }
        for name, values in sorted(material_values.items())
    }

    # -- mass and semantics ---------------------------------------------------
    assets: dict[str, dict] = {}
    base_files = sorted(base_root.rglob("base.usda"))
    for path in base_files:
        asset = path.parts[len(base_root.parts)]
        parsed = parse_base(path)
        parsed["materials"] = asset_materials.get(asset, [])
        assets[asset] = parsed

    by_category: dict[str, list[dict]] = collections.defaultdict(list)
    for asset, parsed in assets.items():
        by_category[asset.split("_")[0]].append(parsed)

    categories = {}
    for category, members in sorted(by_category.items()):
        masses = [m["mass_kg"] for m in members if m.get("mass_kg")]
        categories[category] = {
            "assets": len(members),
            "assets_with_mass": len(masses),
            "mass_kg": quantiles(masses),
        }

    label_counts: collections.Counter = collections.Counter()
    for parsed in assets.values():
        for values in parsed.get("labels", {}).values():
            for value in values:
                label_counts[value] += 1

    summary = {
        "physics_layers_parsed": len(physics_files),
        "base_layers_parsed": len(base_files),
        "materials": materials,
        "material_count": len(materials),
        "categories": categories,
        "category_count": len(categories),
        "assets_with_mass": sum(1 for a in assets.values() if a.get("mass_kg")),
        "asset_types": dict(
            collections.Counter(a.get("asset_type") for a in assets.values()).most_common()
        ),
        "profiles": dict(
            collections.Counter(a.get("profile") for a in assets.values()).most_common()
        ),
        "semantic_labels": dict(label_counts.most_common()),
        "assets": assets,
    }
    Path(args.out).write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(
        {
            "physics_layers_parsed": summary["physics_layers_parsed"],
            "base_layers_parsed": summary["base_layers_parsed"],
            "material_count": summary["material_count"],
            "category_count": summary["category_count"],
            "assets_with_mass": summary["assets_with_mass"],
            "asset_types": summary["asset_types"],
            "top_materials": sorted(
                materials.items(), key=lambda kv: -kv[1]["assets"]
            )[:12],
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
