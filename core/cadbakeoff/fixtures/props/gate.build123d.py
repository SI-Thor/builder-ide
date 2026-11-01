from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {
    "post_height": 1500.0,
    "post_width": 120.0,
    "post_depth": 40.0,
    "gate_width": 780.0,
    "rail_bottom_z": 150.0,
    "rail_height": 60.0,
    "slat_count": 5,
    "slat_depth": 40.0,
    "rail_depth": 50.0,
}

_post_height = PARAMS["post_height"]
_post_width = PARAMS["post_width"]
_post_depth = PARAMS["post_depth"]
_gate_width = PARAMS["gate_width"]
_rail_bottom_z = PARAMS["rail_bottom_z"]
_rail_height = PARAMS["rail_height"]
_slat_count = PARAMS["slat_count"]
_slat_depth = PARAMS["slat_depth"]
_rail_depth = PARAMS["rail_depth"]

_MIN = (Align.MIN, Align.MIN, Align.MIN)


def _box(x0, x1, y0, y1, z0, z1):
    return Pos(x0, y0, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=_MIN)


# --- static body: posts -------------------------------------------------
_post_left = _box(
    -_post_width / 2,
    _post_width / 2,
    -_rail_depth - _post_depth,
    -_rail_depth,
    0.0,
    _post_height,
)
_post_right = _box(
    _post_width / 2 + _gate_width,
    _post_width / 2 + _gate_width + _post_width,
    -_rail_depth - _post_depth,
    -_rail_depth,
    0.0,
    _post_height,
)

# --- moving body: leaf --------------------------------------------------
_rail_bottom = _box(
    _post_width / 2,
    _post_width / 2 + _gate_width,
    -_rail_depth / 2,
    _rail_depth / 2,
    _rail_bottom_z,
    _rail_bottom_z + _rail_height,
)
_rail_top = _box(
    _post_width / 2,
    _post_width / 2 + _gate_width,
    -_rail_depth / 2,
    _rail_depth / 2,
    _rail_bottom_z + _gate_width + _rail_height,
    _rail_bottom_z + _gate_width + 2 * _rail_height,
)

_slats = []
for _i in range(_slat_count):
    _x0 = _post_width / 2 + _i * 2 * _gate_width / (2 * _slat_count)
    _x1 = _x0 + _gate_width / (2 * _slat_count)
    _slats.append(
        _box(
            _x0,
            _x1,
            -_slat_depth / 2,
            _slat_depth / 2,
            _rail_bottom_z + _rail_height,
            _rail_bottom_z + _gate_width + _rail_height,
        )
    )

BODIES = {
    "posts": Part() + _post_left + _post_right,
    "leaf": Part() + _rail_bottom + _rail_top + sum(_slats, Part()),
}

export_step(Compound(list(BODIES.values())), "prop.step")