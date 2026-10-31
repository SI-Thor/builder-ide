# `core/usd` — the USD backbone

The compiled scene format of builder-ide. The recipe is the source of truth;
this package compiles it into a **layered USD stage**: one layer per concern,
provenance in `customData`, and byte-identical output for the same recipe.

Plan Week 2 item 8 · rev-tech spike 3 · res-cad §8 and §10.

## What it does

```
recipe (spec v2 §1.1)
  ├─ geometry.usda    what is where: placements, transforms, reference arcs
  ├─ materials.usda   the surfaces and their bindings
  ├─ physics.usda     rigid bodies: mass, collision approximation
  ├─ semantics.usda   what the things are (SimReady-lite, in custom attributes)
  ├─ provenance.usda  prompt / model / seed / version / licence, and pinned files
  └─ root.usda        the composition root
```

Each CAD part also gets an asset layer (`assets/<part>.usda`) with the
tessellated mesh, plus the two interchange files: `<part>.step` (the master,
in millimetres) and `<part>.glb` (the interchange copy, in metres, with UVs).

## Using it

```bash
export PYTHONPATH=core/usd/src        # or: pip install -e core/usd

.venv/bin/python -m builder_usd compile --demo --out /tmp/stage
.venv/bin/python -m builder_usd verify --demo --out /tmp/stage
.venv/bin/python -m builder_usd read    --out /tmp/stage
.venv/bin/python -m builder_usd probe
```

`verify` re-emits into a temporary directory and compares every file by
hash — that is the determinism claim, checkable by hand.

## The seam

The recipe store lives on branch `core-recipe` and is **not merged** here.
This package codes against `builder_usd.recipe_source.RecipeSource`:

- `StubRecipeSource` — a recipe in memory or loaded from JSON;
- `BuilderRecipeSource` — an adapter over the real store, calling
  `RecipeStore.get_document(version_id)`.

Both sides are tested in `tests/usd/test_seam.py`; the adapter is tested
against a fake store with the same interface, so the conversation is pinned
without the branch.

## The measurements

`docs/lab/usd-backbone-spike.md` has the numbers, the box's state beside
them, and the six things the measurements changed about the design.
