from build123d import Align, Cylinder, Compound, Part, Pos, export_step

PARAMS = {
    "radius": 220.0,
    "wall": 20.0,
    "height": 700.0,
    "lid_thickness": 20.0,
    "lift": 150.0,
}

_radius = PARAMS["radius"]
_wall = PARAMS["wall"]
_height = PARAMS["height"]
_lid_thickness = PARAMS["lid_thickness"]
_lift = PARAMS["lift"]

_staves = (
    Pos(0, 0, (_wall + _height) / 2)
    * Cylinder(
        _radius,
        _height - _wall,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    - Pos(0, 0, (_wall + _height) / 2)
    * Cylinder(
        _radius - _wall,
        _height - _wall,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
)

_bottom_head = Pos(0, 0, _wall / 2) * Cylinder(
    _radius,
    _wall,
    align=(Align.CENTER, Align.CENTER, Align.CENTER),
)

_lid_head = Pos(0, 0, _height + _lid_thickness / 2) * Cylinder(
    _radius,
    _lid_thickness,
    align=(Align.CENTER, Align.CENTER, Align.CENTER),
)

BODIES = {
    "barrel_body": Part() + _staves + _bottom_head,
    "barrel_lid": Part() + _lid_head,
}

export_step(Compound(list(BODIES.values())), "prop.step")