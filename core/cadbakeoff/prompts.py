"""The one prompt template both kernels get.

Hy4 guard 1: the bakeoff must not measure "the model is better at Python" or
"SolidCraft had a validator and build123d only had a human reader". So:

* the prop brief — the parameters, the cells, the joint and the action — is
  rendered from the same frozen spec for both kernels, byte for byte;
* the rules are the same for both;
* only the OUTPUT FORMAT block differs, because the two languages are
  different languages, and each one carries its own one-shot example of the
  same brief answered in that language.

The prop brief is a complete design: every cell is given as an extent, so the
model transcribes a design rather than inventing one. That is deliberate — it
keeps the two arms comparable and it makes an analytic ground truth possible
(Hy4 guard 3). What the bakeoff measures is the language and the kernel, not
the taste of the designer.
"""

from __future__ import annotations

from typing import Any

from core.cadbakeoff.specs import PROPS

__all__ = [
    "PROP_BRIEF",
    "RULES",
    "FORMAT_SOLIDCRAFT",
    "FORMAT_BUILD123D",
    "EXAMPLE_SOLIDCRAFT",
    "EXAMPLE_BUILD123D",
    "build_prompt",
    "render_prop_brief",
]

RULES = """=== RULES ===
1. Answer with the script only. Nothing before it, nothing after it: no
   explanation, no notes, no markdown fence unless the output format asks for one.
2. Build exactly the bodies, the cells, the joint and the action the brief
   lists. Do not add a body, a cell, a joint or a feature.
3. Every dimension must come from the PARAMETERS block, by name. A literal
   number is allowed only where the brief itself gives one.
4. The cells of one body end up in that one body as a single rigid part. The
   bodies stay separate from each other.
5. The joint joins the two bodies the JOINT block names, with that type, that
   axis direction, at that origin point, and inside those limits.
6. Millimetres for lengths, degrees for angles, unless the output format says
   otherwise.
7. The script runs headless, with no input, and asks nothing.
"""

FORMAT_SOLIDCRAFT = """=== OUTPUT FORMAT ===
One JSON object, and nothing else:

  {"commands": [{"command": "<command id>", "params": {<parameters>}}, ...]}

A length in a command may be a number in millimetres or an expression over the
parameter names, such as "width", "depth/2" or "height - 2*plank". An angle is
in degrees.

The commands you may use, with their parameters:

  parameters.add       name, expression, unit?: mm|cm|m|in|ft|deg|rad
  solid.box            length, width, height: expression; corner?: [x,y,z] (the
                       minimum corner; the box grows towards +x, +y and +z from
                       it); operation?: new|join|cut|intersect; targets?: [body];
                       body_name?: the name of the body it makes
  solid.cylinder       radius | diameter, height: expression; base?: [x,y,z]
                       (the centre of the bottom face); axis?: X|Y|Z|[x,y,z]
                       (default Z); operation?; targets?: [body]; body_name?
  solid.combine        target: body; tools: [body]; operation?: join|cut|intersect
  material.create      name (not a built-in material's name); density_g_cm3:
                       (0, 1000]; color?: "#rrggbb"
  material.assign      bodies: [names]; material: name
  component.from_bodies  bodies: [names] -> one new component per body, named
                       after the body
  joint.create         type: rigid|revolute|slider|cylindrical|pin_slot|planar|ball;
                       a, b: the joint origins, each
                       {occurrence: <component name>, point: [x,y,z] in world
                       millimetres, z?: [x,y,z] the joint's axis direction in world};
                       limits?: [[min, max]] (degrees for an angle, millimetres for
                       a distance); flip?: bool; name?
  file.export          path; format?: stl|obj|step|3mf|urdf|json; for urdf only:
                       mesh_prefix?, effort?, velocity?
  assembly.mass_properties   (no parameters; read-only)

How the pieces fit:
  - A cell's extent along an axis is its maximum coordinate minus its minimum
    coordinate. A box is placed by its minimum corner, a cylinder by the centre
    of its bottom face.
  - Build the cells of one body as separate bodies, then combine them into the
    body you want with solid.combine.
  - Give every body a material before you make the components, so the mass
    follows the density you set.
  - A joint's origins are plain numbers in world millimetres, not expressions.
    Give the joint's z the axis direction the brief asks for.
  - joint.create mates the two parts: by default it turns the child so the two
    origins meet as two faces meet, and it MOVES the child if it has to. Give
    both origins the same world point and the same z and x, and pass
    "flip": true, so the parts stay exactly where the brief puts them.
  - The script must end by exporting the whole assembly: file.export to
    "robot.urdf" with format "urdf", and file.export to "prop.step" with format
    "step".
"""

FORMAT_BUILD123D = """=== OUTPUT FORMAT ===
One Python module, and nothing else. It runs headless and defines two
module-level names:

  PARAMS   a dict mapping every parameter name to its numeric value in
           millimetres
  BODIES   a dict mapping every body name to a build123d Shape (a Part, or a
           Compound of Parts) holding that body's cells, already placed in
           world coordinates: Z up, the origin at the centre of the prop's
           footprint

The module may use the build123d library, which is installed:

  from build123d import *
  Box(length, width, height, align=(Align.MIN, Align.MIN, Align.MIN))
      a box; align says which corner sits at the origin, Align.MIN on every
      axis puts the minimum corner there
  Cylinder(radius, height, align=(Align.CENTER, Align.CENTER, Align.MIN),
           rotation=(0, 0, 0))
      a cylinder along Z by default; rotation=(rx, ry, rz) in degrees turns it,
      so (0, 90, 0) puts the axis along X; Align.CENTER on every axis centres
      the cylinder on the origin
  Pos(x, y, z) * shape
      moves a shape
  shape + other       fuse two solids
  shape - other       cut
  Part() + shape      a Part holding one or more solids
  Compound([shape, ...])   an assembly of solids
  shape.volume, shape.area, shape.center()
      volume, area and centre of mass
  export_step(shape, "prop.step")
      write a STEP file

How the pieces fit:
  - A cell's extent along an axis is its maximum coordinate minus its minimum
    coordinate. A box is placed by its minimum corner, a cylinder by the centre
    of its bottom face.
  - The cells of one body are fused into one Shape; the bodies stay separate.
  - A half-cylinder is a cylinder cut by the plane through its axis, keeping
    the half the brief names.
  - The module must end by writing the whole prop to a STEP file:
    export_step(Compound(list(BODIES.values())), "prop.step").
"""

EXAMPLE_SOLIDCRAFT = """=== EXAMPLE ===
The same kind of brief, answered in this output format. The prop there is not
the prop above.

Brief: name "sample_box"; parameters w=220, d=160, h=120, t=12; body "base"
(static) with cell "base" box x=[-w/2, w/2] y=[-d/2, d/2] z=[0, t] and cell
"wall_back" box x=[-w/2, w/2] y=[d/2 - t, d/2] z=[t, h - t]; body "lid"
(moving) with cell "lid" box x=[-w/2, w/2] y=[-d/2, d/2] z=[h - t, h]; joint
"lid_hinge" revolute, parent "base", child "lid", axis [1, 0, 0], origin
[0, 80, 108], limits [0 deg, 90 deg]; action: lid_hinge -> 90 deg.

Answer:

{"commands": [{"command": "parameters.add", "params": {"name": "w", "expression": "220", "unit": "mm"}}, {"command": "parameters.add", "params": {"name": "d", "expression": "160", "unit": "mm"}}, {"command": "parameters.add", "params": {"name": "h", "expression": "120", "unit": "mm"}}, {"command": "parameters.add", "params": {"name": "t", "expression": "12", "unit": "mm"}}, {"command": "solid.box", "params": {"length": "w", "width": "d", "height": "t", "corner": ["-w/2", "-d/2", "0"], "body_name": "base"}}, {"command": "solid.box", "params": {"length": "w", "width": "t", "height": "h - 2*t", "corner": ["-w/2", "d/2 - t", "t"], "body_name": "wall_back"}}, {"command": "solid.combine", "params": {"target": "base", "tools": ["wall_back"], "operation": "join"}}, {"command": "solid.box", "params": {"length": "w", "width": "d", "height": "t", "corner": ["-w/2", "-d/2", "h - t"], "body_name": "lid"}}, {"command": "material.create", "params": {"name": "PropWood", "density_g_cm3": 0.7}}, {"command": "material.assign", "params": {"bodies": ["base", "lid"], "material": "PropWood"}}, {"command": "component.from_bodies", "params": {"bodies": ["base", "lid"]}}, {"command": "joint.create", "params": {"type": "revolute", "a": {"occurrence": "base", "point": [0, 80, 108], "z": [1, 0, 0]}, "b": {"occurrence": "lid", "point": [0, 80, 108], "z": [1, 0, 0]}, "limits": [[0, 90]], "flip": true, "name": "lid_hinge"}}, {"command": "file.export", "params": {"path": "robot.urdf", "format": "urdf"}}, {"command": "file.export", "params": {"path": "prop.step", "format": "step"}}]}
"""

EXAMPLE_BUILD123D = '''=== EXAMPLE ===
The same kind of brief, answered in this output format. The prop there is not
the prop above.

Brief: name "sample_box"; parameters w=220, d=160, h=120, t=12; body "base"
(static) with cell "base" box x=[-w/2, w/2] y=[-d/2, d/2] z=[0, t] and cell
"wall_back" box x=[-w/2, w/2] y=[d/2 - t, d/2] z=[t, h - t]; body "lid"
(moving) with cell "lid" box x=[-w/2, w/2] y=[-d/2, d/2] z=[h - t, h]; joint
"lid_hinge" revolute, parent "base", child "lid", axis [1, 0, 0], origin
[0, 80, 108], limits [0 deg, 90 deg]; action: lid_hinge -> 90 deg.

Answer:

from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {"w": 220.0, "d": 160.0, "h": 120.0, "t": 12.0}

_w = PARAMS["w"]
_d = PARAMS["d"]
_h = PARAMS["h"]
_t = PARAMS["t"]

_base = Pos(-_w / 2, -_d / 2, 0) * Box(_w, _d, _t, align=(Align.MIN, Align.MIN, Align.MIN))
_wall = Pos(-_w / 2, _d / 2 - _t, _t) * Box(_w, _t, _h - 2 * _t, align=(Align.MIN, Align.MIN, Align.MIN))
_lid = Pos(-_w / 2, -_d / 2, _h - _t) * Box(_w, _d, _t, align=(Align.MIN, Align.MIN, Align.MIN))

BODIES = {
    "base": Part() + _base + _wall,
    "lid": Part() + _lid,
}

export_step(Compound(list(BODIES.values())), "prop.step")
'''


def _render_cell(cell: dict[str, Any]) -> str:
    kind = cell["kind"]
    label = cell["label"]
    if kind == "box":
        return (
            f'cell "{label}"'.ljust(26)
            + f'box      x=[{cell["x"][0]}, {cell["x"][1]}]'
            + f'  y=[{cell["y"][0]}, {cell["y"][1]}]'
            + f'  z=[{cell["z"][0]}, {cell["z"][1]}]'
        )
    if kind == "cyl":
        axis = cell["axis"]
        centre = ", ".join(cell["center"])
        return (
            f'cell "{label}"'.ljust(26)
            + f'cylinder along {axis}  centre=[{centre}]'
            + f'  radius={cell["r"]}  length={cell["length"]}'
        )
    if kind == "tube":
        axis = cell["axis"]
        centre = ", ".join(cell["center"])
        return (
            f'cell "{label}"'.ljust(26)
            + f'tube along {axis}  centre=[{centre}]'
            + f'  outer_radius={cell["r_outer"]}  inner_radius={cell["r_inner"]}'
            + f'  length={cell["length"]}'
        )
    if kind == "half_cyl":
        axis = cell["axis"]
        centre = ", ".join(cell["center"])
        return (
            f'cell "{label}"'.ljust(26)
            + f'half-cylinder along {axis}  dome towards {cell["dome_dir"]}'
            + f'  centre=[{centre}]'
            + f'  radius={cell["r"]}  length={cell["length"]}'
        )
    raise ValueError(f"unknown cell kind {kind!r}")


def _render_joint(joint: dict[str, Any]) -> str:
    axis = ", ".join(str(v) for v in joint["axis"])
    origin = ", ".join(joint["origin"])
    lo, hi = joint["limits"]
    if joint["type"] == "prismatic":
        unit = "mm"
        lo_s, hi_s = f"{lo:g}", f"{hi:g}"
    else:
        unit = "deg"
        lo_s, hi_s = f"{lo * 180.0 / 3.141592653589793:g}", f"{hi * 180.0 / 3.141592653589793:g}"
    return (
        f'  {joint["name"]}'.ljust(20)
        + f'{joint["type"]}'.ljust(14)
        + f'{joint["parent"]}'.ljust(18)
        + f'{joint["child"]}'.ljust(18)
        + f'[{axis}]'.ljust(14)
        + f'[{origin}]'.ljust(42)
        + f'[{lo_s} {unit}, {hi_s} {unit}]'
    )


def render_prop_brief(spec: dict[str, Any]) -> str:
    """The prop half of the prompt: identical for both kernels."""
    lines: list[str] = ["=== THE PROP ==="]
    lines.append(f'name: {spec["prop"]}')
    lines.append(f'description: {spec["description"]}')
    lines.append("")
    lines.append("=== PARAMETERS ===")
    lines.append("Every dimension comes from these names. A length is in millimetres.")
    for name, value in spec["parameters"].items():
        lines.append(f"  {name} = {value:g}")
    lines.append("")
    lines.append("=== BODIES ===")
    lines.append(
        "Each body is one rigid part of the assembly. A cell is a closed solid;"
    )
    lines.append(
        "its extent along an axis is the maximum coordinate minus the minimum."
    )
    for body in spec["bodies"]:
        lines.append(f'  body "{body["name"]}" ({body["role"]}):')
        for cell in body["cells"]:
            lines.append("    " + _render_cell(cell))
    lines.append("")
    lines.append("=== JOINT ===")
    lines.append(
        f'  {"name".ljust(20)}{"type".ljust(14)}{"parent".ljust(18)}'
        f'{"child".ljust(18)}{"axis".ljust(14)}{"origin (world)".ljust(42)}limits'
    )
    for joint in spec["joints"]:
        lines.append(_render_joint(joint))
    lines.append("")
    lines.append("=== ACTION ===")
    lines.append("  Drive these joints to these values:")
    action = spec["action"]
    unit = action["unit"]
    for name in action["joints"]:
        target = action["target"]
        shown = f"{target:g}" if unit == "mm" else f"{target * 180.0 / 3.141592653589793:g}"
        lines.append(f"    {name} -> {shown} {unit}")
    return "\n".join(lines)


def build_prompt(prop: str, kernel: str) -> str:
    """The whole prompt for one prop in one kernel.

    ``kernel`` is "solidcraft" or "build123d". Everything except the OUTPUT
    FORMAT and EXAMPLE blocks is the same string in both cases.
    """
    spec = PROPS[prop]
    if kernel == "solidcraft":
        fmt, example = FORMAT_SOLIDCRAFT, EXAMPLE_SOLIDCRAFT
    elif kernel == "build123d":
        fmt, example = FORMAT_BUILD123D, EXAMPLE_BUILD123D
    else:
        raise ValueError(f"unknown kernel {kernel!r}")
    return "\n".join(
        [
            "You are a mechanical CAD prop designer. You write one script that",
            "builds one prop: a parametric rigid-body assembly for a physics",
            "simulation.",
            "",
            render_prop_brief(spec),
            "",
            RULES,
            "",
            fmt,
            "",
            example,
        ]
    )
