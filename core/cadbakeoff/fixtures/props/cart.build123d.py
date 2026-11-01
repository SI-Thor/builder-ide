from build123d import Align, Box, Compound, Cylinder, Part, Pos, export_step

PARAMS = {
    "bed_length": 800.0,
    "bed_width": 400.0,
    "wheel_radius": 150.0,
    "wheel_width": 40.0,
    "deck_thickness": 20.0,
}

_bed_length = PARAMS["bed_length"]
_bed_width = PARAMS["bed_width"]
_wheel_radius = PARAMS["wheel_radius"]
_wheel_width = PARAMS["wheel_width"]
_deck_thickness = PARAMS["deck_thickness"]

_deck_z = 2 * _wheel_radius + 10
_rail_top_z = 2 * _wheel_radius + 110

_deck = Pos(-_bed_length / 2, -_bed_width / 2, _deck_z) * Box(
    _bed_length, _bed_width, _deck_thickness, align=(Align.MIN, Align.MIN, Align.MIN)
)
_rail_left = Pos(-_bed_length / 2, -_bed_width / 2, _deck_z + _deck_thickness) * Box(
    20, _bed_width, _rail_top_z - (_deck_z + _deck_thickness),
    align=(Align.MIN, Align.MIN, Align.MIN),
)
_rail_right = Pos(_bed_length / 2 - 20, -_bed_width / 2, _deck_z + _deck_thickness) * Box(
    20, _bed_width, _rail_top_z - (_deck_z + _deck_thickness),
    align=(Align.MIN, Align.MIN, Align.MIN),
)

_front_wheel = Pos(0, _bed_width / 2 - _wheel_radius, _wheel_radius) * Cylinder(
    _wheel_radius, _wheel_width,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
    rotation=(0, 90, 0),
)
_rear_wheel = Pos(0, -(_bed_width / 2 - _wheel_radius), _wheel_radius) * Cylinder(
    _wheel_radius, _wheel_width,
    align=(Align.CENTER, Align.CENTER, Align.MIN),
    rotation=(0, 90, 0),
)

BODIES = {
    "bed": Part() + _deck + _rail_left + _rail_right,
    "wheel_front": Part() + _front_wheel,
    "wheel_rear": Part() + _rear_wheel,
}

export_step(Compound(list(BODIES.values())), "prop.step")