from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {
    "lower_height": 1200.0,
    "upper_height": 1200.0,
    "rail_gap": 520.0,
    "rail_width": 40.0,
    "rail_depth": 50.0,
    "rung_count": 6,
    "rung_height": 50.0,
    "extend": 600.0,
}

_lower_height = PARAMS["lower_height"]
_upper_height = PARAMS["upper_height"]
_rail_gap = PARAMS["rail_gap"]
_rail_width = PARAMS["rail_width"]
_rail_depth = PARAMS["rail_depth"]
_rung_count = int(PARAMS["rung_count"])
_rung_height = PARAMS["rung_height"]
_extend = PARAMS["extend"]

_rail_inset = 5


def _cell(x0, x1, y0, y1, z0, z1):
    """Axis-aligned box spanning the given world-space min/max corners."""
    return Pos(x0, y0, z0) * Box(
        x1 - x0,
        y1 - y0,
        z1 - z0,
        align=(Align.MIN, Align.MIN, Align.MIN),
    )


def _fuse(cells):
    """Fuse a body's cells into one rigid shape."""
    shape = Part()
    for cell in cells:
        shape = shape + cell
    return shape


_lower_cells = []
_lower_cells.append(
    _cell(
        -_rail_gap / 2 - _rail_width,
        -_rail_gap / 2,
        -_rail_depth / 2,
        _rail_depth / 2,
        0.0,
        _lower_height,
    )
)
_lower_cells.append(
    _cell(
        _rail_gap / 2,
        _rail_gap / 2 + _rail_width,
        -_rail_depth / 2,
        _rail_depth / 2,
        0.0,
        _lower_height,
    )
)
for _i in range(_rung_count):
    _z0 = (_lower_height - _rung_height) / (_rung_count + 1) * (_i + 1)
    _lower_cells.append(
        _cell(
            -_rail_gap / 2,
            _rail_gap / 2,
            -_rail_depth / 2 + _rail_inset,
            _rail_depth / 2 - _rail_inset,
            _z0,
            _z0 + _rung_height,
        )
    )

_upper_cells = []
_upper_cells.append(
    _cell(
        -_rail_gap / 2 - _rail_width,
        -_rail_gap / 2,
        -_rail_depth / 2,
        _rail_depth / 2,
        _lower_height,
        _lower_height + _upper_height,
    )
)
_upper_cells.append(
    _cell(
        _rail_gap / 2,
        _rail_gap / 2 + _rail_width,
        -_rail_depth / 2,
        _rail_depth / 2,
        _lower_height,
        _lower_height + _upper_height,
    )
)
for _i in range(_rung_count):
    _z0 = _lower_height + (_upper_height - _rung_height) / (_rung_count + 1) * (_i + 1)
    _upper_cells.append(
        _cell(
            -_rail_gap / 2,
            _rail_gap / 2,
            -_rail_depth / 2 + _rail_inset,
            _rail_depth / 2 - _rail_inset,
            _z0,
            _z0 + _rung_height,
        )
    )

BODIES = {
    "lower_section": _fuse(_lower_cells),
    "upper_section": _fuse(_upper_cells),
}

JOINTS = {
    "extension_slide": {
        "type": "prismatic",
        "parent": "lower_section",
        "child": "upper_section",
        "axis": (0.0, 0.0, 1.0),
        "origin": (0.0, 0.0, _lower_height),
        "limits": (0.0, _extend),
    }
}

ACTIONS = {
    "extension_slide": _extend,
}

export_step(Compound(list(BODIES.values())), "prop.step")