from build123d import Align, Box, Compound, Cylinder, Part, Pos, export_step

PARAMS = {
    "width": 600.0,
    "depth": 400.0,
    "height": 400.0,
    "wall": 20.0,
    "dome_radius": 200.0,
}

_width = PARAMS["width"]
_depth = PARAMS["depth"]
_height = PARAMS["height"]
_wall = PARAMS["wall"]
_dome_radius = PARAMS["dome_radius"]

_bottom = Pos(-_width / 2, -_depth / 2, 0) * Box(
    _width, _depth, _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)
_wall_front = Pos(-_width / 2, -_depth / 2, _wall) * Box(
    _width, _wall, _height - _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)
_wall_back = Pos(-_width / 2, _depth / 2 - _wall, _wall) * Box(
    _width, _wall, _height - _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)
_wall_left = Pos(-_width / 2, -_depth / 2 + _wall, _wall) * Box(
    _wall, _depth - 2 * _wall, _height - _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)
_wall_right = Pos(_width / 2 - _wall, -_depth / 2 + _wall, _wall) * Box(
    _wall, _depth - 2 * _wall, _height - _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)

_dome_cylinder = Pos(0, 0, _height) * Cylinder(
    _dome_radius, _width, rotation=(0, 90, 0)
)
_dome_lower_half = Pos(
    -_width / 2 - _dome_radius,
    -_dome_radius - _wall,
    _height - _dome_radius - _wall,
) * Box(
    _width + 2 * _dome_radius,
    2 * _dome_radius + 2 * _wall,
    _dome_radius + _wall,
    align=(Align.MIN, Align.MIN, Align.MIN),
)
_dome = _dome_cylinder - _dome_lower_half

BODIES = {
    "chest_body": Part() + _bottom + _wall_front + _wall_back + _wall_left + _wall_right,
    "chest_lid": Part() + _dome,
}

JOINT = {
    "name": "lid_hinge",
    "type": "revolute",
    "parent": "chest_body",
    "child": "chest_lid",
    "axis": (1.0, 0.0, 0.0),
    "origin": (0.0, _depth / 2, _height),
    "limits": (0.0, 90.0),
    "limits_units": "deg",
}

ACTION = {
    "lid_hinge": 90.0,
    "units": "deg",
}

export_step(Compound(list(BODIES.values())), "prop.step")