from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {
    "opening_width": 800.0,
    "jamb_width": 100.0,
    "door_height": 2000.0,
    "frame_height": 2100.0,
    "leaf_thickness": 40.0,
    "leaf_gap": 10.0,
}

_opening_width = PARAMS["opening_width"]
_jamb_width = PARAMS["jamb_width"]
_door_height = PARAMS["door_height"]
_frame_height = PARAMS["frame_height"]
_leaf_thickness = PARAMS["leaf_thickness"]
_leaf_gap = PARAMS["leaf_gap"]

_jamb_left = Pos(-_opening_width / 2 - _jamb_width, -_leaf_thickness, 0) * Box(
    _opening_width + _jamb_width,
    _leaf_thickness,
    _frame_height,
    align=(Align.MIN, Align.MIN, Align.MIN),
)

_jamb_right = Pos(_opening_width / 2, -_leaf_thickness, 0) * Box(
    _jamb_width,
    _leaf_thickness,
    _frame_height,
    align=(Align.MIN, Align.MIN, Align.MIN),
)

_head = Pos(-_opening_width / 2, -_leaf_thickness, _door_height) * Box(
    _opening_width,
    _leaf_thickness,
    _frame_height - _door_height,
    align=(Align.MIN, Align.MIN, Align.MIN),
)

_leaf_panel = Pos(-_opening_width / 2 + _leaf_gap, -_leaf_thickness, 0) * Box(
    _opening_width - 2 * _leaf_gap,
    _leaf_thickness,
    _door_height,
    align=(Align.MIN, Align.MIN, Align.MIN),
)

BODIES = {
    "frame": Part() + _jamb_left + _jamb_right + _head,
    "leaf": Part() + _leaf_panel,
}

JOINTS = {
    "hinge": {
        "type": "revolute",
        "parent": "frame",
        "child": "leaf",
        "axis": [0.0, 0.0, 1.0],
        "origin": [-_opening_width / 2 + _leaf_gap, 0.0, 0.0],
        "limits": [0.0, 90.0],
    }
}

ACTIONS = {
    "hinge": 90.0,
}

export_step(Compound(list(BODIES.values())), "prop.step")