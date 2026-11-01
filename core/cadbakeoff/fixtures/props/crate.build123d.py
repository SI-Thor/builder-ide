from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {"width": 400.0, "depth": 300.0, "height": 250.0, "plank": 18.0}

_w = PARAMS["width"]
_d = PARAMS["depth"]
_h = PARAMS["height"]
_p = PARAMS["plank"]

_floor = Pos(-_w / 2, -_d / 2, 0.0) * Box(_w, _d, _p, align=(Align.MIN, Align.MIN, Align.MIN))
_wall_front = Pos(-_w / 2, -_d / 2, _p) * Box(_w, _p, _h - 2 * _p, align=(Align.MIN, Align.MIN, Align.MIN))
_wall_back = Pos(-_w / 2, _d / 2 - _p, _p) * Box(_w, _p, _h - 2 * _p, align=(Align.MIN, Align.MIN, Align.MIN))
_wall_left = Pos(-_w / 2, -_d / 2 + _p, _p) * Box(_p, _d - 2 * _p, _h - 2 * _p, align=(Align.MIN, Align.MIN, Align.MIN))
_wall_right = Pos(_w / 2 - _p, -_d / 2 + _p, _p) * Box(_p, _d - 2 * _p, _h - 2 * _p, align=(Align.MIN, Align.MIN, Align.MIN))
_lid_panel = Pos(-_w / 2, -_d / 2, _h - _p) * Box(_w, _d, _p, align=(Align.MIN, Align.MIN, Align.MIN))

BODIES = {
    "crate_body": Part() + _floor + _wall_front + _wall_back + _wall_left + _wall_right,
    "lid": Part() + _lid_panel,
}

JOINT = {
    "lid_hinge": {
        "type": "revolute",
        "parent": "crate_body",
        "child": "lid",
        "axis": (1.0, 0.0, 0.0),
        "origin": (0.0, _d / 2, _h - _p),
        "limits_deg": (0.0, 90.0),
    }
}

# lid_hinge driven to its 90 limit (brief writes "90 rad"; joint limits are in degrees)
ACTION = {"lid_hinge": 90.0}

export_step(Compound(list(BODIES.values())), "prop.step")