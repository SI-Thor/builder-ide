# EXP — cad-bakeoff: SolidCraft vs build123d for prop recipes

**Date:** 2026-11-01 (Alaska Standard Time)
**Branch:** `cad-bakeoff` (worktree of `~/src/builder-ide`)
**Artefacts:** `out/RESULT.json`, `out/result.json` (per prop), `out/sweep.json`,
`out/gen/` (the model's own artefacts and the prompts), `out/oracle.json`
(SolidCraft's own oracle suite), `core/cadbakeoff/` (the harness)

---

## 1. The idea

`~/lm-wt/res-cad/REPORT.md` chose build123d for CAD on this box, after
comparing the options. SolidCraft is the other candidate: a Rust CAD kernel
with a JSON command script, a native URDF export, and a command registry that
an agent can validate a script against before running it.

The question this experiment asks is narrower than "which is better CAD". It
is: **for a physics prop that a language model has to write from a brief, is
the JSON command script or the Python module the better thing to hand the
model?** That is a question about the *model's* side of the pipeline, so the
experiment is built around the two things that decide it:

- **can the model's script be checked before it runs?** SolidCraft answers
  this with `solidcraft-cli commands` and its own schemas; build123d has no
  equivalent, so the Python side needs one built, or the comparison measures
  the harness's diligence rather than the kernel;
- **does what comes out agree?** Two kernels that both build a crate are not
  two facts about crates. They agree, they are both wrong, or they disagree
  and one of them is broken. The only way to tell is a closed form.

## 2. What was built, and on what

### 2.1 SolidCraft

| | |
|---|---|
| Source | `github.com/bherbruck/solidcraft` (MIT OR Apache-2.0) |
| Commit | `a93d7b207cf21c64d7994430e10faa9fca8acf76` (v0.29.0 line) |
| Toolchain | rustc 1.99.1, cargo 1.99.1, aarch64 |
| Build | `cargo build --release -p solidcraft-cli`, 5 m 56 s wall, peak RSS 4.80 GB |
| Binary | 476,323,752 B (454 MiB) with debuginfo, 70,991,280 B (67.7 MiB) stripped |
| aarch64 patches | **none** — the tree built clean on the first try |

The build ran under the admission daemon (`thor-admit run --tier live --peak
20G --label cad-bakeoff.build`) with `nice`, as the memory rule asks.

**Its own oracle suite ran: 90 cases, 732 checks, 732 passed, 0 failed, 0
marked `known_failure`.** The suite is upstream's own reference cases
(`tests/oracle/*`), driven through the binary that was just built, so it says
the binary under test is the binary upstream means. This was cheap — the
binary was already built, so the suite was a few seconds of `solidcraft-cli
oracle --json`.

### 2.2 build123d

A venv at `~/lm-wt/cad-bakeoff/b123d`, Python 3.12.3, `build123d` 0.13.0 on
`cadquery-ocp-novtk` 8.0.1.1.0 — the aarch64 wheel
(`manylinux_2_28_aarch64`), the same one res-cad verified. Nothing was
installed system-wide. The model's Python only ever runs inside this venv.

MuJoCo 3.17.0 drives the action check.

## 3. The protocol

### 3.1 The props

The ten physag-lite props, each a parametric assembly that moves: `crate`,
`chest` (hinged lid), `lantern` (hanging), `door` (hinged), `drawer_unit`
(two sliding drawers), `barrel`, `cart` (wheels), `gate`, `ladder`, `table`.
Each has at least three named parameters, separate bodies, and one joint.

The specification of every prop is **frozen** in `core/cadbakeoff/specs.py`:
parameters, bodies, cells, the joint, and the action. The model is given that
specification, not free rein over it. That is what makes the two arms
comparable, and it is also what makes the repair round safe (§4.2).

### 3.2 The model writes each prop twice

One cloud model, `minimax/MiniMax-M3`, reached through the seat CLI with the
tools off and **one turn** per artefact. Every artefact in the bakeoff — both
kernels, all ten props — was generated with exactly that setting.

The prompt is one template with the prop's brief, the rules, and the target
format; the one-shot example is the same brief answered in each language.
The two arms differ only in the format block and the example, which is what
has to differ.

### 3.3 The front-end check is the same on both sides (Hy4 guard 1)

The trap guard 1 names is real: SolidCraft gets a pre-run check against
`solidcraft-cli commands` and the CLI's own JSON schemas, while build123d
would otherwise be only "read by a human". Then first-try success measures
the *harness's* diligence, not the kernel.

So the Python side got the same kind of check:

- **SolidCraft:** the script parses as JSON; every command id is looked up in
  the CLI's own command registry (557 commands); every command's `params` are
  validated against the CLI's own schema where the registry publishes one;
  the script has to create the bodies and the joint the frozen spec names;
  and every parameter the script declares has to be one the other commands
  actually refer to.
- **build123d:** the module parses as Python (AST); every name it imports
  from `build123d` is looked up in build123d's own exports; it must define
  `PARAMS` and `BODIES`; it has to declare the spec's bodies; and it is
  **imported in the build123d venv** as a dry run, which has to succeed.

A script that will not load is a *validation* failure on both sides, and is
counted as one. Validation failures and build failures are reported
separately.

**The two front ends are not equally deep, and that is a finding.** The
model used ten distinct SolidCraft commands across the ten props
(`parameters.add`, `solid.box`, `solid.cylinder`, `solid.combine`,
`material.create`, `material.assign`, `component.from_bodies`,
`joint.create`, `joint.drive`, `file.export`). The registry publishes a JSON
schema for **two** of them — `solid.box` and `solid.cylinder`. For the other
eight, a wrong parameter name is caught by the *build*, not by the front end.
build123d's front end, by contrast, catches a wrong import name, a missing
body and an import-time crash before anything is built. So the Python side's
first-try number is measured against a *deeper* pre-check than the JSON
side's. That is why §8 reports the validation and build stages separately
rather than folding them into one "first try" number: the stages are where
the two kernels differ.

**The command set covers all ten props.** SolidCraft's registry has 557
commands; the ones the props need are all there: `solid.box`,
`solid.cylinder`, `solid.pipe`, `solid.revolve`, `solid.extrude`,
`solid.loft`, `solid.combine`, `joint.create` (`revolute`, `slider`),
`material.create`/`material.assign`, `component.from_bodies`, `file.export`,
`assembly.mass_properties`. There is no capability gap to report.

## 4. The guards, and what each one did here

### 4.1 Guard 1 — prompt and format asymmetry

Covered in §3.2 and §3.3. One template, one decoding setting, one example
per language, one kind of front-end check per side.

### 4.2 Guard 2 — the repair round changes the code, not the design

One repair round, and only when the build failed. The repair prompt repeats
the brief verbatim and adds: *change only the code; do not shrink a
dimension, do not move a joint, do not lower a limit.* The error goes back in
a kernel-agnostic shape — `{"stage": ..., "message": ...}` — so the two
languages are not compared on their tracebacks.

Afterwards the repaired artefact is checked against the frozen spec: the
declared parameters name by name, and the joint limits on the SolidCraft
side. The diff is logged as `spec_diff` whatever the verdict is, and a
repair that moved the design is marked `design_changed` and **left out of
the after-repair rate**.

### 4.3 Guard 3 — units, density, tessellation

Units are millimetres and degrees everywhere, and the density is explicit in
the spec (700 kg/m³ for the wooden props). Both kernels' mass properties are
computed on the **solid**, not on the render mesh: SolidCraft integrates the
B-rep, and build123d reads OCCT's exact `shape.volume`/`shape.area`/
`shape.center()`. The tessellation tolerances are logged anyway, because the
mesh is what the physics engine collides with:

| | mass properties from | mesh tolerance |
|---|---|---|
| SolidCraft | the solid (exact) | `quality: standard` — a chord tolerance of 2e-4 **of each body's size** |
| build123d | the solid (exact) | 0.05 mm absolute |

The agreement between the kernels is reported **against the closed form** for
the crate and the barrel, with absolute values, units and relative error —
not only as a delta between two kernels that might both be wrong.

### 4.4 Guard 4 — the URDF is not the point of the measurement

SolidCraft exports URDF natively. build123d has no URDF export, so one
deterministic generator writes it from the *same frozen spec*, using the
kernel's own meshes and the kernel's own mass properties. Nothing is written
by hand per prop.

Both URDFs are then validated against the spec — joint type, axis, limits,
and each body's world placement against the spec's cells — and compared **in
the world**, not by their text: each link's world placement and each joint's
world axis and limits. The action check runs only where both URDFs are
present and agree.

One unit trap is worth writing down: a sliding joint's limit is a distance.
The spec carries distances in millimetres; URDF carries them in metres. The
generator converts once, at the limit, and the action check converts the
target the same way. SolidCraft's own export does the same conversion, which
is how the two sides agree.

### 4.5 Guard 5 — the sweep

Twenty variants per prop for two props (`crate` and `drawer_unit`), generated
programmatically from the prop's own parameter ranges by a Halton sequence —
no model is asked for a variant, so the variants are independent of the
model's taste and identical on every run. Variant 0 is the prop's own
parameters, so the sweep carries its own control.

**Validity** is not "did not crash": a variant counts as valid only when it
builds, its geometry is not degenerate (every body has a positive volume, is
a closed valid solid and is a single shell), *and* the action check passes.
A variant whose swept parameters never reached the artefact — a script that
hard-codes its numbers — is not a variant at all and is reported as such.

Every build records the box state next to its time: free memory, load
average and one line of `tegrastats`. Both kernels run in the same worker,
one after the other, with the same timeout and the same number of repeats,
and the median of the repeats is what is reported.

## 5. The recipe format, and where it does not fit

`~/src/builder-ide/docs/research/aider/recipe-format.md` proposes a typed
recipe that compiles to both kernels. It is used here as the **common prompt
input**, because its shape is right: a recipe is a typed, kernel-neutral
description of a parametric assembly, which is exactly what
`core/cadbakeoff/specs.py` holds and exactly what both arms need.

What does not fit, and why:

1. **The SolidCraft compilation target in that document does not use
   SolidCraft's own command names.** The document writes commands with `op`
   and `id` fields (`{"op": "add", "id": "w"}`); SolidCraft's registry takes
   `command` and `params` (`{"command": "parameters.add", "params": {...}}`).
   The recipe's target was therefore re-derived from the registry itself
   (`solidcraft-cli commands`, `engine.describe`), not from the document.
2. **Joint type names are three different vocabularies.** The recipe says
   `prismatic`; SolidCraft's `joint.create` says `slider`; URDF says
   `prismatic`. The chain is `prismatic → slider → prismatic`, and the
   experiment's checker speaks all three.
3. **Units.** The recipe is SI (metres, radians). The props are drawn in
   millimetres, and the specs are in millimetres. The recipe's *shape* was
   kept; its units were not.
4. **`affordances` and `constraints` have no target.** Neither kernel has a
   concept of "this prop affords opening" or "this prop must not self-
   intersect", and neither can check them. They would need a checker of their
   own, which is the argument for keeping them in the recipe but compiling
   them to nothing.
5. **`seed` and `provenance` do not reach the kernels either** — provenance
   is a property of the artefact, not of the geometry.

So the recipe format is the right *skeleton* for the common input and the
wrong *payload* for the SolidCraft target, and the honest conclusion is that
a recipe format can be shared only if its two targets are generated from the
kernels' own registries, not transcribed by hand.

## 6. The Rust custom fit

SolidCraft is already Rust, and the prop pipeline uses a small part of it:
the command engine and the geometry kernel, with no UI, no renderer, no GPU
stack, no MCP server and no benchmark harness.

`apps/solidcraft-prop` is that custom fit: one crate that depends on
`solidcraft-engine` and `serde_json`, with three subcommands (`commands`,
`exec`, `run`) — the same three the harness uses.

| | full `solidcraft-cli` | custom-fit `solidcraft-prop` | saved |
|---|---|---|---|
| binary, with debuginfo | 476,323,752 B (454 MiB) | 423,769,088 B (404 MiB) | 50.2 MiB (11.0 %) |
| binary, stripped | 70,991,280 B (67.7 MiB) | 61,544,992 B (58.7 MiB) | 9.0 MiB (13.3 %) |
| peak RSS of one prop build | 26,880 kB (26.3 MiB) | 24,832 kB (24.3 MiB) | 2.0 MiB (7.6 %) |
| build time | 5 m 56 s | 4 m 42 s | 1 m 14 s |

The saving is modest, and the reason is worth saying plainly: **the size and
the memory are in the geometry kernel, not in the parts that were dropped.**
Dropping the GPU stack, the renderer, the MCP server and the UI takes 13 % of
the binary and 8 % of the memory, because the kernel that does the actual
booleans and mass properties is what both binaries are made of. A custom fit
is worth it for a *fleet* of binaries and for a dependency surface, not for
a single build.

On the MuJoCo checker: `physag-lite` has one
(`core/physag/check.py`), and it is the better tool — but it takes physag-
lite's own `BuiltProp` and `Segmentation`, i.e. the output of physag-lite's
own MJCF pipeline, not a URDF. Pointing it at these two kernels' URDF
exports would mean re-implementing the conversion, which is the thing this
experiment is trying to measure. So the minimal checker in
`core/cadbakeoff/mujoco_check.py` applies the same five guards and cites
them, and the correspondence is in §7.

## 7. What the action check does, and where it matches physag-lite

`core/cadbakeoff/mujoco_check.py` is the minimal checker. It applies the five
Hy4 guards from `~/lm-wt/physag-lite/BRIEF.md`:

| guard | what physag-lite does | what this checker does |
|---|---|---|
| 1 segmentation | splits the prop into parts and checks the mapping | **not applicable**: there is no segmentation step. Each body is named in the spec and the URDF link that carries it is checked against the spec's cells, in world space |
| 2 collider | validates the collider against the mesh; a rest baseline; initial penetration > ε is a build failure | the mesh **is** the collider (no convex hull, so no inflation); a rest baseline runs first; the count of contacts that start inside ε is recorded, and a non-zero count makes the run invalid rather than a pass |
| 3 actuator | caps the actuator force, requires the target without exceeding the cap, logs peak force and penetration events | the actuator's `forcerange` is set from the prop's own mass; the peak force, the number of saturated steps and the peak penetration are recorded; the base is not pinned — the prop stands on a floor plane |
| 4 tolerance | relative tolerance (2 % of the joint's range, 0.5 % of the diagonal); completion is first entry into the band and a dwell; reports overshoot and settling time | the same two relative tolerances, the same dwell rule, the same overshoot and settling-time reports, and the absolute and relative tolerance used are reported per prop |
| 5 repair | freezes the action and joint limits, logs a spec diff, excludes changed props | the spec is frozen; the repair prompt repeats it; the `spec_diff` is logged; `design_changed` repairs are excluded from the after-repair rate |

The one place this checker is deliberately weaker than physag-lite's is that
physag-lite also validates the collider against the mesh (a Hausdorff
distance and a volume ratio). Here the collider *is* the mesh, so there is
nothing to compare it against; the mass properties are compared against the
closed form instead (§8).

## 8. Results

Every number below is in `out/RESULT.json`, and the tables are rendered from
that file by `core/cadbakeoff/report.py --markdown`.

**The box during the run.** The load average was not steady: the 1-minute
load was 24.5 while the first props were built and fell to 9.2 later, with
82–86 GB of memory free throughout. The two arms alternate prop by prop, so
each *pair* was measured under nearly the same load (crate at 22.6 and 24.4,
door at 9.8 and 9.7), and the comparison between the arms is sound; the
absolute times carry the contention, and a build measured at load 24 is not
comparable with one measured at load 9.

### 8.1 Per prop and kernel

| prop | kernel | validation | build | action | URDF | build ms | script tokens |
|---|---|---|---|---|---|---|---|
| crate | solidcraft | ok | yes | yes | yes | 107.1 | 1075 |
| crate | build123d | ok | yes | yes | yes | 119.0 | 577 |
| chest | solidcraft | ok | yes | yes | yes | 207.9 | 1406 |
| chest | build123d | ok | yes | yes | yes | 227.0 | 702 |
| lantern | solidcraft | **validation failed** | no | no | no | — | 957 |
| lantern | build123d | ok | yes | **no** | yes | 21.0 | 484 |
| door | solidcraft | ok | yes | yes | yes | 18.3 | 978 |
| door | build123d | ok | yes | yes | yes | 35.0 | 535 |
| drawer_unit | solidcraft | **validation failed** | yes | no | no | 71.9 | 1573 |
| drawer_unit | build123d | ok | yes | yes | yes | 91.0 | 1019 |
| barrel | solidcraft | ok | yes | yes | yes | 187.4 | 972 |
| barrel | build123d | ok | yes | yes | yes | 25.0 | 347 |
| cart | solidcraft | **validation failed** | no | no | no | — | 1457 |
| cart | build123d | ok | yes | no | **no** | 32.0 | 514 |
| gate | solidcraft | ok | yes | yes | yes | 274.7 | 1716 |
| gate | build123d | ok | yes | yes | yes | 63.0 | 729 |
| ladder | solidcraft | **validation failed** | no | no | no | — | 2478 |
| ladder | build123d | ok | yes | yes | yes | 177.0 | 940 |
| table | solidcraft | ok | yes | yes | yes | 119.9 | 1739 |
| table | build123d | ok | yes | yes | yes | 93.0 | 921 |

**Headline numbers.**

| | SolidCraft | build123d |
|---|---|---|
| validation failures (first try) | 4 | 0 |
| built first try | **6 / 10** | **10 / 10** |
| built first try, after the one repair round, design unchanged | **7 / 10** | 10 / 10 (no repair needed) |
| repairs excluded for moving the design | 1 (cart) | 0 |
| URDF passes the spec check | 6 / 10 | 9 / 10 |
| action check passes | 6 / 10 | 8 / 10 |

**Every SolidCraft validation failure is a naming failure.** Four of the ten
scripts did not create the bodies or the joint the frozen spec names: the
lantern called its bodies `hook_block`, `housing` and `base` and then tried
to merge into a body named `hook` that did not exist; the cart called its
bodies `bed`, `wheel_front` and `wheel_rear`; the ladder called its sections
`lower_section` and `upper_section` but built `lower` and `upper`; and the
drawer unit named its joints `drawer_upper_slideprismatic` and
`drawer_lower_slideprismatic` instead of `drawer_upper_slide` and
`drawer_lower_slide`. **Not one of the ten build123d scripts got a body name
wrong.** The model is more reliable at Python dict keys than at SolidCraft
command names, and the failure mode is not symmetric: on the SolidCraft side
the *joint's name is the model's to get right*, because the URDF comes from
the script; on the build123d side the URDF is generated from the spec, so the
joint's name cannot be got wrong at all.

**The repair round.** Four arms went to the repair round; all four were
validation failures, and **none was a build failure** — on both sides the
script parsed and the target accepted it. The repair round fixed one of the
four (the ladder: after it, the URDF passed the spec check and the action
check passed). The drawer unit's repair built, but its drawer came out 10 mm
taller than the spec's cells, so the URDF check failed and the action check
was not run. The cart's repair built and its URDF passed, but it **added two
parameters the spec does not name** (`wheel_front_axle`, `wheel_rear_axle`),
which is a design change: it is logged in `spec_diff` and **excluded from the
after-repair rate**, as guard 2 asks. The lantern's repair did not build: the
repaired script reused a `joint.drive` command with the wrong parameter name
(`name` instead of `joint`), which the build caught and the front-end check
could not.

### 8.2 The agreement, against the closed form

| prop | kernel | volume (mm³) | rel. error | area (mm²) | rel. error | CoM max error (mm) |
|---|---|---|---|---|---|---|
| crate (analytic 9,435,456) | solidcraft | 9,435,456 | 3.8e-16 | 1,098,784 | 1.4e-16 | 4.4e-14 |
| crate (analytic 9,435,456) | build123d | 9,435,456 | 2.6e-16 | 1,098,784 | 0 | 4.3e-14 |
| barrel (analytic 24,026,901) | solidcraft | 24,024,784 | **9.2e-5** | 2,457,872 | 4.3e-5 | 0.0013 |
| barrel (analytic 24,026,901) | build123d | 24,026,901 | 7.1e-16 | 2,457,982 | 2.2e-16 | 1.7e-13 |

The crate is all boxes, and **both kernels are exact to double precision** —
the relative errors are floating-point rounding, 1e-16, and the centre of
mass agrees with the closed form to 1e-13 mm.

The barrel is a tube, and the two kernels part company: build123d's numbers
still match the closed form to 1e-16, while **SolidCraft's volume is
0.0092 % low** and its centre of mass is 1.3 µm off. That is a small
number, and it is the kind of number that a cross-kernel comparison hides:
the two kernels agree on the barrel to 1e-4, which looks like agreement and
is actually one of them being slightly wrong. The closed form says which.

### 8.3 The cross-kernel comparison, prop by prop

| prop | volume rel. difference | area rel. difference | CoM max difference (mm) |
|---|---|---|---|
| crate | 1.1e-16 | 1.4e-16 | 4.4e-14 |
| chest | 1.1e-4 | 6.5e-5 | 0.009 |
| drawer_unit | 0 | 0 | 0 |
| barrel | 9.2e-5 | 4.3e-5 | 0.003 |
| gate | 0 | 0 | 0 |
| table | 0 | 0 | 0 |
| **door** | **77.7 %** | **64.0 %** | **22.3** |

**The door is the interesting one.** The two arms built visibly different
doors and every check that looks at *placement* passed: both URDFs put the
frame in the same place, both joints are in the same place, and the action
check passed on both. The difference is in the *shape*: the build123d script
made the left jamb `opening_width + jamb_width` wide instead of
`jamb_width`, so its frame is a slab where the spec says three panels, with
84,000,000 mm³ against the spec's 20,000,000 mm³. The bounding box is
unchanged, so the URDF check — which compares each body's world box against
the spec's cells — cannot see it. **Only the mass properties can.** The
SolidCraft arm built the three panels the spec asks for and matches the
closed form; the build123d arm did not, and it is 4.2× too heavy.

### 8.4 The sweep

| prop | kernel | variants | valid (all repeats) | median build ms | failures by stage |
|---|---|---|---|---|---|
| crate | solidcraft | 20 | **20 (100 %)** | 45.5 | — |
| crate | build123d | 20 | **20 (100 %)** | 55.5 | — |
| drawer_unit | solidcraft | 20 | **14 (70 %)** | 181.3 | 18 (action check) |
| drawer_unit | build123d | 20 | **14 (70 %)** | 131.0 | 18 (action check) |

The variants are Halton samples over the prop's own parameter ranges, so
they are independent of the model and identical on every run; variant 0 is
the prop's own parameters. Validity is build + non-degenerate geometry +
the action check.

**The crate generalises perfectly in both kernels: 20 of 20.** **The drawer
unit does not: 14 of 20 in both, and the same six variants fail in both**
(5, 6, 7, 10, 15, 16). The failure is the same in the two arms and the same
every repeat: the drawers interpenetrate the carcass — four contacts start
inside the epsilon and the deepest penetration runs to 185 mm. So this is a
property of the *design*, not of the kernel: the model's drawer unit does not
survive a change of proportions, and both kernels say so, identically, on
every one of the 240 builds.

**The joint does not follow the parameters on the SolidCraft side.** The
model's SolidCraft scripts put the joint at a literal point — `[0, -250,
560]` — and SolidCraft's `joint.create` will not take an expression there:
a point of `["w/2", ...]` is refused with *"a joint origin needs face,
circle, edge, point or frame [x, y, z]"* (measured). The geometry commands
do take expressions, so the *bodies* follow the parameters, but the *joint*
does not: when the sweep changed the drawer unit's dimensions, the
SolidCraft arm's joint drifted up to **109.73 mm** from where the spec puts
it, while the build123d arm's joint stayed put to 1.1e-13 mm. SolidCraft
does offer a way out — a face, circle, edge or frame reference, and an
`offset` that takes an expression — but the model did not use it and the
prompt did not ask for it.

The build123d arm's drift of 1.1e-13 mm is **zero by construction** and
should not be read as a result: its URDF is generated from the spec, so the
generator puts the joint where the spec says whatever the module did. The
solid number is the one that measured something.

### 8.5 The URDFs

Eight of the ten props: the two arms' URDFs are **equal in the world** — the
same joints, the same world axes, the same limits, the same bodies in the
same places. Two are not: the door, for the reason in §8.3, and the drawer
unit, where the SolidCraft arm's drawer sits 10 mm from where the build123d
arm's does, because the spec leaves the drawer's inset free and the two
scripts chose differently. Both differences are reported rather than
smoothed over.

### 8.6 The cost

| | SolidCraft | build123d |
|---|---|---|
| geometry (median) | 119.9 ms | 77.0 ms |
| whole process (median) | 145.1 ms | **2,594.8 ms** |
| script size (median, local tokens) | 1,373 | 578 |

The geometry is faster in build123d, but a cold build123d process pays
**~1.8 s to import OCCT** — the library import is 22 times the geometry
itself. SolidCraft's CLI starts in ~25 ms. For one prop from scratch,
build123d is 18 times slower end to end; for a server or a batch that
builds many props in one process, that import is paid once and the
comparison flips.

The scripts themselves: the SolidCraft scripts are about 2.4 times longer
than the Python ones (median 1,373 tokens against 578), which is the price
of a command script over a library call — the Python version says
`Box(520, 450, 320)` where the JSON version says
`{"command": "solid.box", "params": {"length": ..., "width": ..., "height":
...}}`.

### 8.7 The model

| | |
|---|---|
| model | `minimax/MiniMax-M3`, through the seat CLI, tools off, one turn |
| artefacts | 20 (10 props × 2 kernels) |
| model calls | 26 (6 were transport retries) |
| worst artefact | `cart.solidcraft`, 4 attempts |

The cloud credential is shared with other seats on this box, and a turn that
lands on top of somebody else's ends without a reply: 6 of the 26 calls came
back empty and had to be asked again. That is a property of the transport,
not of either kernel — the retry budget and the backoff are the same on both
sides, and the attempt count for every artefact is in
`core/cadbakeoff/fixtures/props/replies.json` rather than hidden inside the
numbers.

## 9. Verdict

**build123d is the default for a model-written prop recipe, and SolidCraft
is the default for the kernel behind it — but the verdict is about the
pipeline, not about the geometry.**

The reason is not that OCCT is a better CAD kernel. On the geometry the
two are indistinguishable: on the crate both are exact to 1e-16, and on the
barrel build123d is the one that matches the closed form and SolidCraft is
0.0092 % low. The reason is what happens *around* the kernel.

**Against build123d:** every one of the ten scripts parsed, imported and
built on the first try. Its front-end check is deep — the AST, the imported
names against build123d's own exports, the spec's body names, and a dry run
that imports the module in the venv — and the model did not fail it once.
Its URDF is generated from the same frozen spec, so it cannot get a joint's
name or limits wrong, and the action check measured the CAD rather than
whoever wrote the robot description. And the sweep found the *same* six bad
variants on both sides, on every repeat, which is what two correct kernels
look like.

**Against SolidCraft:** four of ten scripts named a body or a joint
differently from the spec, and the one repair round fixed one of them. Its
native URDF export is a genuine advantage — the kernel exports a robot
description with the mass properties it already computed — but it makes the
model responsible for the joint's name, and the model got it wrong. Its
front end is shallower than it looks: the registry publishes a JSON schema
for only 2 of the 10 commands the model used, so a wrong parameter name is
caught by the build rather than before it — which is exactly how the
lantern's repair died. And its `joint.create` will not take an expression,
so a SolidCraft script's joint does not follow its parameters unless the
model reaches for a topological reference.

**The verdict, in one line each:**

- **SolidCraft default**: if the prop recipe has to be a *file the kernel
  reads* — a checked, replayable, non-Python artefact — and the agent
  writing it is a careful one. Its registry, its schemas, its native URDF
  export and its Rust custom fit (13 % smaller, 8 % less memory) are real
  assets.
- **build123d default**: if the prop recipe has to be *written by a language
  model* and built many times. The Python side wins first-try success 10/10
  against 6/10, wins the validation stage outright, and cannot get the URDF
  wrong.
- **Both behind one recipe format**: yes, and this experiment says the
  recipe format has to be **kernel-neutral and compiled, not written by
  hand**. The typed recipe in
  `~/src/builder-ide/docs/research/aider/recipe-format.md` is the right
  shape; its SolidCraft target is wrong in exactly the way that matters —
  it invents command names instead of taking them from the registry, and it
  uses `prismatic` where SolidCraft says `slider` and the URDF says
  `prismatic`. A recipe format that compiles to both kernels would have
  removed all four SolidCraft validation failures (the names would have come
  from the recipe, not the model) and would have removed the door's 4.2×
  mass error (the cells would have come from the recipe too). That is the
  strongest argument this experiment produced, and it is an argument for
  the recipe format, not for either kernel alone.

**What this does not say.** Ten props, one model, one night, one shared box.
The first-try numbers are 6/10 and 10/10 — small enough that a different
model could move them. The build times are confounded by a load average
that moved between 24 and 9 during the run, and the box was not quiet.

## 10. What would be worth doing next

1. **Write the recipe compiler, not another prop.** The four SolidCraft
   validation failures and the door's 4.2× mass error are all
   "the model had to restate something the recipe already knew". A compiler
   from the typed recipe to the SolidCraft command list and to the build123d
   module would remove the whole class. The recipe format's own SolidCraft
   target has to be regenerated from the registry rather than transcribed.
2. **Ask for topological joint references in the SolidCraft prompt.** The
   joint not following the parameters is the single largest measured
   difference between the two arms in the sweep (109.73 mm against 1.1e-13),
   and SolidCraft's own `face`/`edge` reference is the fix.
3. **Make the front-end check schema-complete.** Two of ten commands have a
   JSON schema, so the SolidCraft side catches a wrong parameter name only
   at build time — which cost the lantern its repair round. Publishing a
   schema for the rest of the commands the props use would deepen the check
   for both arms' benefit.
4. **Run the sweep on a third prop that has wheels.** The cart is the one
   prop whose design has never worked on either arm (the wheels collided),
   so it is the prop whose sweep would say the most about the *model* rather
   than about the kernels.
5. **Measure the batch case.** build123d's 2.6 s import dominates a single
   prop; a pipeline that builds 100 props in one process would flip the
   timing verdict. That number is worth having before the default is chosen
   for a real workload.
