# Prop and asset recipes — what the corpus already says, and one typed format

## 1. Every recipe idea in the corpus

| # | Idea | Source file | What it says |
|---|---|---|---|
| 1 | **Recipes, not meshes, are the source of truth** | `lib-idea4.md` | "recipes, not meshes, are the absolute source of truth" — a project's state is a compact, version-controlled history |
| 2 | **Content-addressed stage cache keyed by recipe hash** | `lib-idea4.md` | "content-addressed stage cache" — the cache key is the recipe's hash, not its path |
| 3 | **Partial scene splice from a recipe delta** | `lib-idea4.md` | "executes a partial scene splice" — a recipe change produces a delta, not a rebuild |
| 4 | **Recipe ledger as an append-only audit** | `lib-idea4.md` | "a compact, version-controlled history that avatar agents modify through an audit ledger" |
| 5 | **Procedural generation from a seed** | `lib-idea4.md` | "Pulls upcoming procfunc recipes directly from the content cache" — the seed is part of the recipe |
| 6 | **Infinigen's ProcFunc graph** | `lib-idea4.md` | "Pulls the core-recipe stage graph parameters" — the recipe is a graph of stages, not a flat list |
| 7 | **glTF delta quantization + meshopt** | `lib-idea4.md` | "in-place quantization and meshopt compression" — the compiled output is a delta, not a full mesh |
| 8 | **OpenUSD layered recipe ledger** | `lib-idea4.md` | "OpenUSD Layered Recipe Ledger Stores" — USD layers are the compiled form |
| 9 | **Recipe-to-USD compilation** | `lib-idea4.md` | "compiles procedural geometry records into highly optimized glTF binary arrays" |
| 10 | **Recipe hash as the cache key** | `lib-idea4.md` | "content-addressed" — the hash is the identity |
| 11 | **Recipe as a typed manifest** | `lib-fromgoogle4.md` | "WHY.md / ECOLOGY.md" — the manifest is a typed text file, compiled to a bitmask |
| 12 | **Recipe as a declarative pipeline** | `lib-si-repos2.md` (`constraint-dsl`) | "YAML pipeline DSL → stages (snap/funnel/consensus/verify)" — the recipe is a pipeline of stages |
| 13 | **Recipe as a constraint graph** | `lib-si-repos.md` (`constraint-theory-core`) | "Tile (384 B), Origin (64 B), ConstraintBlock (192 B)" — the recipe's constraints are typed blocks |
| 14 | **Recipe as a CRDT** | `lib-si-repos2.md` (`constraint-crdt`) | "CRDT-backed constraint states" — the recipe can be merged, not just replaced |
| 15 | **Recipe as a proof-carrying spec** | `lib-dsswarm4.md` (`flux-core`) | "compile the same bytecode to a native CPU predicate" — the recipe carries its own proof |
| 16 | **Recipe as a skill package** | `docs/seed-connections.md` (seed 161) | "a bundle of (state, action, outcome, annotation) that a coach can update" |
| 17 | **Recipe as a prop with a measured prior** | `docs/seed-connections.md` (seed 159) | "executing its action in MuJoCo, with measured priors" — the recipe carries its measured affordance |
| 18 | **Recipe as a tile** | `lib-scout-top.md` (`mavis-tile-pipeline`) | "imports, validates, scores, deduplicates, versions, graphs, cascades, and stores discrete knowledge tiles" |
| 19 | **Recipe as a schema** | `lib-scout-top.md` (`cocapn-schemas`) | "JSON Schema files and a validator for the fleet's tile-based knowledge system" |
| 20 | **Recipe as a binary wire format** | `lib-scout-top.md` (`cocapn-glue-core`) | "binary wire protocol (Postcard/msgpack) for cross-tier communication" |
| 21 | **Recipe as a hash-chained envelope** | `lib-si-repos.md` (`edge-ledger`) | "per-node hash-chained envelopes, idempotent ingest" |
| 22 | **Recipe as a delta stream** | `lib-idea4.md` | "broadcast an optimized since_version delta packet over SSE" |
| 23 | **Recipe as a night-session bake** | `lib-idea4.md` | "the night-session bake" — the recipe is what the night scheduler runs |
| 24 | **Recipe as a morning reveal** | `lib-idea4.md` | "the morning reveal" — the compiled output is what the player sees |
| 25 | **Recipe as a MuJoCo scene** | `lib-si-repos2.md` (`constraint-physics`) | "Scene JSON Format" — the recipe can compile to a physics scene |

## 2. One typed recipe format

The format below is designed to compile to **both** SolidCraft JSON command scripts (a sequence of primitive placements) **and** build123d code (a Python CAD script). It is a superset of what both need, with the fields that are not shared marked optional.

```yaml
# prop.recipe.yaml — a typed prop recipe
# Compiles to: SolidCraft JSON commands, build123d Python, glTF delta, USD layer
# Hash: BLAKE3 over the canonical form (see §3)

recipe:
  schema: "prop/v1"
  id: "crate.oak.small"          # stable, human-readable
  version: 3                      # bumped on any field change
  seed: 20261031                  # procedural seed; part of the hash

  # --- geometry: the shape, in a form both compilers understand ---
  geometry:
    kind: "box"                   # box | cylinder | sphere | extrude | revolve | union | difference
    params:
      width:  { value: 0.6, unit: "m", type: "float", min: 0.1, max: 2.0 }
      height: { value: 0.4, unit: "m", type: "float", min: 0.1, max: 2.0 }
      depth:  { value: 0.4, unit: "m", type: "float", min: 0.1, max: 2.0 }
    children: []                  # for union/difference; each child is a geometry node

  # --- joints: how the prop articulates ---
  joints:
    - id: "lid"
      kind: "hinge"               # hinge | slider | ball | fixed
      parent: "body"
      child: "lid"
      axis: [1, 0, 0]             # unit vector
      limits: { min: 0.0, max: 1.57, unit: "rad" }
      anchor: [0.0, 0.4, 0.0]     # in parent's local frame

  # --- materials: what it is made of, and how heavy ---
  materials:
    - id: "oak"
      density: { value: 700, unit: "kg/m^3", type: "float" }
      color: "#8B5A2B"
      roughness: 0.7
      metallic: 0.0
    - id: "iron_band"
      density: { value: 7870, unit: "kg/m^3", type: "float" }
      color: "#4A4A4A"
      roughness: 0.4
      metallic: 1.0

  # --- assignment: which material goes where ---
  material_bindings:
    - target: "body"
      material: "oak"
    - target: "band.*"
      material: "iron_band"

  # --- affordance: what the prop can do, with a measured prior ---
  affordance:
    - action: "open"
      joint: "lid"
      prior: { success: 0.92, trials: 50, source: "mujoco" }
    - action: "lift"
      prior: { success: 0.78, trials: 50, source: "mujoco" }

  # --- constraints: what must be true of the compiled prop ---
  constraints:
    - kind: "watertight"
      tolerance: 0.001
    - kind: "mass"
      max: { value: 25, unit: "kg" }
    - kind: "laman"
      # the constraint graph must be rigid (determined)
      required: true

  # --- provenance: who made it, from what ---
  provenance:
    author: "agent:builder-07"
    parent: "crate.oak.medium"    # the recipe this was derived from
    created: "2026-10-31T09:00:00Z"
    ledger: "sha256:..."          # the audit entry that committed it
```

### Field typing

Every numeric field is a **typed value**, not a bare number:

```yaml
{ value: 0.6, unit: "m", type: "float", min: 0.1, max: 2.0 }
```

- `value` — the number
- `unit` — the physical unit (`m`, `kg`, `rad`, `kg/m^3`, `s`)
- `type` — `float` | `int` | `bool` | `enum` | `vec3`
- `min` / `max` — optional bounds; the compiler rejects out-of-range values

This is the same discipline as `constraint-theory-core`'s typed `Tile` and `constraint-dsl`'s typed stages: the recipe is not a bag of numbers, it is a typed graph.

### Joints and articulation

Joints are first-class, not a property of the mesh. Each joint has:

- `kind` — `hinge` | `slider` | `ball` | `fixed`
- `parent` / `child` — the geometry nodes it connects
- `axis` — the rotation or translation axis
- `limits` — the allowed range
- `anchor` — the joint's position in the parent's frame

This is what lets the same recipe compile to a SolidCraft command script (which places primitives and then applies a joint) and to build123d (which builds the parts and then assembles them with a `RigidJoint` or `RevoluteJoint`).

### Materials and density

Materials are typed with density, color, roughness, and metallic. Density is what makes the mass constraint checkable: the compiler computes the volume from the geometry, multiplies by density, and checks against the `mass` constraint. This is the same check `constraint-physics` runs on its scene JSON.

### The hash

The hash is **BLAKE3 over the canonical form** of the recipe:

1. Serialize the recipe to a canonical JSON (sorted keys, no whitespace, units normalized to SI).
2. Hash the bytes with BLAKE3.
3. The hash is the cache key, the ledger entry, and the identity.

The canonical form excludes `provenance.created` and `provenance.ledger` (they change on every commit but do not change the prop). It includes `seed`, `version`, and every geometry, joint, material, and constraint field.

This is the same pattern as `lib-idea4.md`'s "content-addressed stage cache" and `lib-si-repos.md`'s "per-node hash-chained envelopes": the hash is the identity, and the identity is what the cache and the ledger agree on.

## 3. Compilation targets

### SolidCraft JSON command script

```json
{
  "commands": [
    { "op": "box", "id": "body", "size": [0.6, 0.4, 0.4], "material": "oak" },
    { "op": "box", "id": "lid", "size": [0.6, 0.05, 0.4], "material": "oak" },
    { "op": "hinge", "parent": "body", "child": "lid", "axis": [1,0,0], "limits": [0, 1.57] },
    { "op": "bind", "target": "band.*", "material": "iron_band" }
  ],
  "hash": "blake3:..."
}
```

### build123d Python

```python
from build123d import *

with BuildPart() as body:
    Box(0.6, 0.4, 0.4)
    # material: oak, density 700 kg/m^3

with BuildPart() as lid:
    Box(0.6, 0.05, 0.4)
    # material: oak

crate = body.part + lid.part
crate = crate.moved(Location((0, 0.4, 0)))
# joint: hinge, axis (1,0,0), limits (0, 1.57)
# material bindings: body=oak, lid=oak, band.*=iron_band
```

Both targets are generated from the same typed recipe. The recipe is the source of truth; the JSON and the Python are compiled artifacts, cached by hash.

## 4. What this format does not do

- **It does not describe a scene.** A scene is a collection of recipes plus their placements. The scene format is a separate schema (`scene/v1`), which references recipes by hash.
- **It does not describe animation.** A joint's limits are static; an animation is a sequence of joint states, which is a separate `motion/v1` schema.
- **It does not describe the night-session bake.** The bake is a job that consumes recipes and produces compiled artifacts; it is a `thor-admit` job, not a recipe field.
- **It does not replace the ProcFunc graph.** The ProcFunc graph is the *generator*; the recipe is the *generated*. A recipe can reference a ProcFunc node by hash, but it does not contain the node's code.

## 5. Sources

- `lib-idea4.md` — recipes as source of truth, content-addressed cache, partial splice, glTF delta, USD layers, night bake, morning reveal
- `lib-fromgoogle4.md` — typed manifests compiled to bitmasks
- `lib-si-repos2.md` — `constraint-dsl` (typed pipeline stages), `constraint-crdt` (mergeable state), `constraint-physics` (scene JSON, density, mass)
- `lib-si-repos.md` — `constraint-theory-core` (typed `Tile`, `ConstraintBlock`), `edge-ledger` (hash-chained envelopes)
- `lib-dsswarm4.md` — `flux-core` (proof-carrying spec)
- `lib-scout-top.md` — `mavis-tile-pipeline` (tile pipeline), `cocapn-schemas` (JSON Schema), `cocapn-glue-core` (binary wire format)
- `docs/seed-connections.md` — seed 159 (measured priors), seed 161 (skill packages)
