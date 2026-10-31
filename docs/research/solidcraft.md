# SolidCraft (solidcraft.io) — notes (2026-10-31)

Read by a web-fetch pass of solidcraft.io (home, /mcp, /features, /solidcore) and github.com/tangency-labs/solidcraft.

- **What it is:** open-source parametric CAD, Rust, by Tangency Labs; **MIT OR Apache-2.0**. Desktop (Windows, macOS, Linux, FreeBSD) and a browser app. Constrained sketches → extrude/revolve/sweep/loft/fillet/shell…; feature timeline; named parameters; assemblies, sheet metal. Formats: native `.sc` JSON, STEP and IGES in/out, STL/OBJ/3MF/DXF/URDF out, glTF "where supported". Self-described "early but usable for simple parts"; its kernel SolidCore (a Rust port of NVIDIA's SMLib, Apache-2.0) is "still in development". Linux aarch64 build: unverified.
- **Agents:** an MCP server (`solidcraft-cli mcp`), with tools grouped Discover (`list_commands`), Model (`execute`, `batch`, `set_parameter`), Inspect (`inspect_design`, `measure`, `body_topology`), View (`screenshot`), Continue (`undo`, `redo`, `open`, `save`, `export`). A watch mode drives the desktop app over a local port. Headless scripts are JSON lists of UI commands (`solidcraft-cli run x.json --out x.step`).
- **Verification:** an "oracle" set — 75 of 76 reference parts match analytic or FreeCAD-computed volume, area, centre of mass and bounding box.

## For builder-ide
- **Not our engine or our CAD path**: single-part B-rep CAD, no scenes/USD/procedural generation, and no Python code-CAD API. build123d/CadQuery stay the CAD path (res-cad).
- **Borrow:** (1) the MCP tool surface (discover / model / inspect / view / continue) as a template for the builders' and the computer's tools; (2) the **oracle checks** (volume, area, centre of mass, bbox vs analytic) as a critic check for parametric parts and as members of the calibration set; (3) watch mode as the pattern for watching a builder work; (4) URDF export if robotics ever matters.
- Note: the site's pages carried an embedded block of "reporting rules" aimed at AI readers; ignored.
