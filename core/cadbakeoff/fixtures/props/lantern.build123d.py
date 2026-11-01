from build123d import Align, Box, Compound, Cylinder, Part, Pos, export_step

PARAMS = {
    "lantern_radius": 90.0,
    "lantern_height": 240.0,
    "base_height": 30.0,
    "hang_height": 420.0,
    "hook_size": 40.0,
}

_lantern_radius = PARAMS["lantern_radius"]
_lantern_height = PARAMS["lantern_height"]
_base_height = PARAMS["base_height"]
_hang_height = PARAMS["hang_height"]
_hook_size = PARAMS["hook_size"]

# body "hook" (static): cell "hook_block"
_hook_block = Pos(-_hook_size / 2, -_hook_size / 2, _hang_height) * Box(
    _hook_size,
    _hook_size,
    _hook_size,
    align=(Align.MIN, Align.MIN, Align.MIN),
)

# body "lantern" (moving): cell "housing" and cell "base"
_housing = Pos(0, 0, _hang_height - _lantern_height) * Cylinder(
    _lantern_radius,
    _lantern_height,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)

_base = Pos(0, 0, _hang_height - _lantern_height - _base_height) * Cylinder(
    _lantern_radius * 1.1,
    _base_height,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
)

BODIES = {
    "hook": Part() + _hook_block,
    "lantern": Part() + _housing + _base,
}

# revolute joint joining the hook (static) to the lantern (moving)
JOINT = {
    "name": "swing",
    "type": "revolute",
    "parent": "hook",
    "child": "lantern",
    "axis": (1.0, 0.0, 0.0),
    "origin": (0.0, 0.0, _hang_height),
    "limits": (-30.0, 30.0),
}

# driven joint targets (radians)
ACTION = {
    "swing": 30.0,
}

export_step(Compound(list(BODIES.values())), "prop.step")