from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {
    "table_height": 740.0,
    "top_length": 840.0,
    "top_width": 640.0,
    "top_thickness": 32.0,
    "leaf_length": 400.0,
    "leg_thickness": 60.0,
    "leg_inset": 20.0,
    "apron_height": 140.0,
}

_H = PARAMS["table_height"]
_L = PARAMS["top_length"]
_W = PARAMS["top_width"]
_TT = PARAMS["top_thickness"]
_LL = PARAMS["leaf_length"]
_LT = PARAMS["leg_thickness"]
_LI = PARAMS["leg_inset"]
_AH = PARAMS["apron_height"]

_XL0 = -_L / 2 + _LI
_XL1 = -_L / 2 + _LI + _LT
_XR0 = _L / 2 - _LI - _LT
_XR1 = _L / 2 - _LI
_YF0 = -_W / 2 + _LI
_YF1 = -_W / 2 + _LI + _LT
_YB0 = _W / 2 - _LI - _LT
_YB1 = _W / 2 - _LI


def _box(x, y, z):
    return Pos(x[0], y[0], z[0]) * Box(
        x[1] - x[0],
        y[1] - y[0],
        z[1] - z[0],
        align=(Align.MIN, Align.MIN, Align.MIN),
    )


_leg_front_left = _box([_XL0, _XL1], [_YF0, _YF1], [0.0, _H])
_leg_front_right = _box([_XR0, _XR1], [_YF0, _YF1], [0.0, _H])
_leg_back_left = _box([_XL0, _XL1], [_YB0, _YB1], [0.0, _H])
_leg_back_right = _box([_XR0, _XR1], [_YB0, _YB1], [0.0, _H])

_apron_front = _box([_XL1, _XR0], [_YF0, _YF1], [_H - _AH, _H])
_apron_back = _box([_XL1, _XR0], [_YB0, _YB1], [_H - _AH, _H])
_apron_left = _box([_XL0, _XL1], [_YF1, _YB0], [_H - _AH, _H])
_apron_right = _box([_XR0, _XR1], [_YF1, _YB0], [_H - _AH, _H])

_top_fixed = _box([-_L / 2, _L / 2], [-_W / 2, _W / 2], [_H, _H + _TT])

_leaf_panel = _box([_L / 2, _L / 2 + _LL], [-_W / 2, _W / 2], [_H, _H + _TT])

BODIES = {
    "frame": (
        Part()
        + _leg_front_left
        + _leg_front_right
        + _leg_back_left
        + _leg_back_right
        + _apron_front
        + _apron_back
        + _apron_left
        + _apron_right
        + _top_fixed
    ),
    "leaf": Part() + _leaf_panel,
}

JOINT = {
    "name": "leaf_hinge",
    "type": "revolute",
    "parent": "frame",
    "child": "leaf",
    "axis": [0.0, 1.0, 0.0],
    "origin": [_L / 2, 0.0, _H],
    "limits": [0.0, 90.0],
}

ACTION = {
    "leaf_hinge": 90.0,
}

export_step(Compound(list(BODIES.values())), "prop.step")