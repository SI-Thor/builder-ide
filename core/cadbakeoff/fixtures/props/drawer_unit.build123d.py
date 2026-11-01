from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {
    "unit_width": 600.0,
    "unit_depth": 500.0,
    "unit_height": 800.0,
    "wall": 30.0,
    "drawer_height": 330.0,
    "drawer_travel": 300.0,
}

_unit_width = PARAMS["unit_width"]
_unit_depth = PARAMS["unit_depth"]
_unit_height = PARAMS["unit_height"]
_wall = PARAMS["wall"]
_drawer_height = PARAMS["drawer_height"]
_drawer_travel = PARAMS["drawer_travel"]

_inner_width = _unit_width - 2 * _wall
_inner_depth = _unit_depth - _wall
_mid_z = (_unit_height - _wall) / 2
_inset = 10

_side_left = Pos(-_unit_width / 2, -_unit_depth / 2, 0) * Box(
    _wall, _unit_depth, _unit_height, align=(Align.MIN, Align.MIN, Align.MIN)
)
_side_right = Pos(_unit_width / 2 - _wall, -_unit_depth / 2, 0) * Box(
    _wall, _unit_depth, _unit_height, align=(Align.MIN, Align.MIN, Align.MIN)
)
_back = Pos(-_unit_width / 2 + _wall, _unit_depth / 2 - _wall, 0) * Box(
    _inner_width, _wall, _unit_height, align=(Align.MIN, Align.MIN, Align.MIN)
)
_bottom = Pos(-_unit_width / 2 + _wall, -_unit_depth / 2, 0) * Box(
    _inner_width, _inner_depth, _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)
_shelf = Pos(-_unit_width / 2 + _wall, -_unit_depth / 2, _mid_z - _wall) * Box(
    _inner_width, _inner_depth, _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)
_top = Pos(-_unit_width / 2 + _wall, -_unit_depth / 2, _unit_height - _wall) * Box(
    _inner_width, _inner_depth, _wall, align=(Align.MIN, Align.MIN, Align.MIN)
)

_drawer_x = -_unit_width / 2 + _wall + _inset
_drawer_y = -_unit_depth / 2 + _inset
_drawer_length = _inner_width - 2 * _inset
_drawer_width = _inner_depth - 2 * _inset

_upper_z0 = _mid_z + _inset
_upper_z1 = _mid_z + _drawer_height
_upper_box = Pos(_drawer_x, _drawer_y, _upper_z0) * Box(
    _drawer_length, _drawer_width, _upper_z1 - _upper_z0,
    align=(Align.MIN, Align.MIN, Align.MIN),
)

_lower_z0 = _wall + _inset
_lower_z1 = _wall + _inset + _drawer_height
_lower_box = Pos(_drawer_x, _drawer_y, _lower_z0) * Box(
    _drawer_length, _drawer_width, _lower_z1 - _lower_z0,
    align=(Align.MIN, Align.MIN, Align.MIN),
)

BODIES = {
    "carcass": Part() + _side_left + _side_right + _back + _bottom + _shelf + _top,
    "drawer_upper": Part() + _upper_box,
    "drawer_lower": Part() + _lower_box,
}

JOINT = {
    "drawer_upper_slideprismatic": {
        "type": "slideprismatic",
        "parent": "carcass",
        "child": "drawer_upper",
        "axis": [0.0, 1.0, 0.0],
        "origin": [0.0, -_unit_depth / 2, _mid_z + _inset + _drawer_height / 2],
        "limits": [0.0, _drawer_travel],
    },
    "drawer_lower_slideprismatic": {
        "type": "slideprismatic",
        "parent": "carcass",
        "child": "drawer_lower",
        "axis": [0.0, 1.0, 0.0],
        "origin": [0.0, -_unit_depth / 2, _wall + _inset + _drawer_height / 2],
        "limits": [0.0, _drawer_travel],
    },
}

ACTION = {"drawer_upper_slide": _drawer_travel}
ACTION_JOINT = {"drawer_upper_slide": "drawer_upper_slideprismatic"}

export_step(Compound(list(BODIES.values())), "prop.step")