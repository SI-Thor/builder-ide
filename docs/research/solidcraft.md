# SolidCraft: parametric CAD in pure Rust, driven by scripts and MCP (2026-10-31)

Source: https://github.com/tangency-labs/solidcraft (MIT OR Apache-2.0; created 2026-10-07, pushed 2026-11-01, 12.7k stars, active). Casey asked for a deep dive. This note is from the README and docs (`mcp.md`, `scripts.md`, `architecture.md`). Building and running it needs Casey's OK (CLAUDE.md).

## What it is
A parametric 3D CAD application: sketch, constrain, then build solids on an editable **feature timeline**. Change a dimension and the model rebuilds.
- **Features:** extrude, revolve, sweep, loft, fillet, chamfer, shell, draft, holes, threads, patterns and booleans; sheet metal.
- **Assemblies:** joints, motion studies, contact sets, interference checks and **mass properties**.
- **Formats:** STEP, IGES, 3MF, STL, OBJ and glTF in and out, plus **URDF export**.
- **Front ends:** the desktop app, the browser app, the headless CLI and the MCP server all run **the same command registry**.

**Correctness discipline.** 75 of 76 public reference parts match their analytic or FreeCAD-computed volume, area, centre of mass and bounding box (an "oracle" test suite). The 76th is a tracked bug.

**Architecture** (layered crates):
- **L0** `geom`;
- **L1** `sketch` (its own constraint solver), `kernel` (the B-rep boundary, on the `truck` kernel), `render`;
- **L2** `doc` (parameters, expressions, the timeline's incremental evaluation);
- **L3** `io`;
- **L4** `engine` (the session; "everything is a command");
- **L5** `gpu` (compute-shader tessellation), `ui-egui`, `mcp`.

## The mechanism that matters to us
**A design is a script.** A JSON list of commands (`sketch.create`, `sketch.rectangle.two_point`, `solid.extrude`, `solid.fillet`, …) that `solidcraft-cli run script.json --out part.step` executes headless. The MCP server exposes the same commands to an agent, with render jobs for screenshots.

This is B2 in its cleanest form:
- **The cloud model writes the script.** The script is the tile: small, typed, diffable, and scored by results.
- **The deterministic kernel builds the solid.** It is exact, watertight and parametric, with mass properties from the geometry.

## Why it matters
1. **Props with parts and joints by construction.** physag-lite's hardest step is splitting a generated mesh into functional parts, and Hy4's review flagged segmentation as trap #1. A CAD prop has no such step: the drawer *is* a separate body with a joint, defined in the script. The assembly exports to URDF, which MuJoCo loads directly. **physag-lite gets a second arm:** CAD-from-script vs TRELLIS + segmentation, on the same props and the same checks.
2. **Measured priors instead of guesses.** Mass properties come from the solid, given a material density. SimReady supplies the density ranges per category, which closes PhysAg3D's admitted gap (seed 159).
3. **Parameters as the variation axis.** One crate script with `width`, `height` and `plank_count` parameters gives a family of props. The night varies the parameters, the critic scores, and the winners are kept. That is cheap variety with guaranteed validity.
4. **Rust and the browser.** It is pure Rust with a WASM browser app. That matches thor-world's viewer and our Rust direction (thor-admit, mission B's stream), and the kernel could run in the viewer for live parametric edits.
5. **Determinism.** The same script gives the same solid, so replays, caching by script hash and byte-identical world-stream deltas all carry over.

## Against what we chose before
`res-cad` (2026-10-31) recommended **build123d** (Apache-2.0, Python, on the OCCT kernel; aarch64 wheels verified on the Thor) with CadQuery as second.

| | build123d / OCCT | SolidCraft / truck |
|---|---|---|
| Kernel maturity | OCCT: decades, industrial | truck: young; 75/76 oracle parts |
| Language | Python (code as the script) | Rust; JSON command scripts |
| Agent interface | write Python | MCP plus typed commands (narrower, safer to execute) |
| Assemblies/joints → sim | by hand | built in; URDF export |
| Browser | no | yes (WASM) |
| Install on the Thor | wheels verified | cargo build (ARM64 builds published); to verify |

**The difference that counts for us:** a JSON command list is *data*, not code. A cloud-written script can be validated against the command registry and executed without running arbitrary Python. That matters under our "don't auto-run LLM-written code" rule: a typed command script is the safer artefact.

## Proposed evaluation (needs Casey's OK to build)
`cad-bakeoff`: build SolidCraft's CLI on the Thor (aarch64) in its own worktree.
- A cloud seat writes the same 10 physag-lite props, both as SolidCraft scripts and as build123d code.
- **Measure:**
  - the build success rate on the first try and after one repair;
  - build time;
  - mass-property agreement between the two kernels;
  - URDF → MuJoCo action completion;
  - the script size in tokens (the cost per prop for the cloud model).
- **Verdict:** which kernel becomes the default for prop recipes, or both behind one recipe format (res-cad's "own typed format, compiled one way").
