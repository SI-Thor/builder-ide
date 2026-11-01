"""The frozen prop specifications for the cad-bakeoff.

One shared spec per prop. Both kernels get the *same* spec, so the only thing
that differs between the two arms of the bakeoff is the language the model
writes it in (SolidCraft's JSON command list vs build123d Python).

Each spec is parametric: the geometry is written as expressions over named
parameters, so the sweep can re-evaluate the same spec with other values
without changing the recipe. The spec also carries the joints and the action,
which are frozen for the whole experiment — the repair round may fix code, not
the design (Hy4 guard 2).

Geometry is given as a list of *cells* per body. A cell is a closed solid:

``box``   an axis-aligned box, given by its x/y/z spans;
``cyl``   a cylinder along one axis, given by its centre, radius and length;
``tube``  a hollow cylinder (outer minus inner radius), coaxial;
``half_cyl``
          a cylinder cut in half by a plane through its axis; ``dome_dir`` names the
          direction the surviving half points (the flat face is perpendicular to it).

Cells inside one body must not overlap in volume; they may touch on faces, and
every shared face is listed in the body's ``interfaces`` so the analytic
reference can subtract the hidden area twice. :mod:`core.cadbakeoff.analytic`
checks both rules.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["PROPS", "PROP_NAMES", "expr", "DENSITY_KG_M3"]

#: Material density used for every prop in both kernels, in kg/m^3.
#: SimReady's "wood" band sits around 600-800 kg/m^3; 700 is the middle of it.
DENSITY_KG_M3 = 700.0

#: The ten physag-lite props, in the order the brief lists them.
PROP_NAMES = (
    "crate",
    "chest",
    "lantern",
    "door",
    "drawer_unit",
    "barrel",
    "cart",
    "gate",
    "ladder",
    "table",
)

_DEG = math.pi / 180.0


def expr(text: str, params: dict[str, float]) -> float:
    """Evaluate one of the spec's expressions over ``params``.

    The namespace is the parameters plus the math functions; no builtins.
    """
    names = dict(params)
    names.update(
        {
            "pi": math.pi,
            "tau": math.tau,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "atan2": math.atan2,
            "abs": abs,
            "min": min,
            "max": max,
            "floor": math.floor,
            "ceil": math.ceil,
        }
    )
    return float(eval(text, {"__builtins__": {}}, names))  # noqa: S307


# ---------------------------------------------------------------------------
# crate
# ---------------------------------------------------------------------------

_CRATE = {
    "prop": "crate",
    "description": (
        "A wooden shipping crate: an open-topped box of planks with a hinged "
        "lid on the back top edge."
    ),
    "parameters": {
        "width": 400.0,
        "depth": 300.0,
        "height": 250.0,
        "plank": 18.0,
    },
    "bodies": [
        {
            "name": "crate_body",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "floor",
                    "x": ["-width/2", "width/2"],
                    "y": ["-depth/2", "depth/2"],
                    "z": ["0", "plank"],
                },
                {
                    "kind": "box",
                    "label": "wall_front",
                    "x": ["-width/2", "width/2"],
                    "y": ["-depth/2", "-depth/2 + plank"],
                    "z": ["plank", "height - plank"],
                },
                {
                    "kind": "box",
                    "label": "wall_back",
                    "x": ["-width/2", "width/2"],
                    "y": ["depth/2 - plank", "depth/2"],
                    "z": ["plank", "height - plank"],
                },
                {
                    "kind": "box",
                    "label": "wall_left",
                    "x": ["-width/2", "-width/2 + plank"],
                    "y": ["-depth/2 + plank", "depth/2 - plank"],
                    "z": ["plank", "height - plank"],
                },
                {
                    "kind": "box",
                    "label": "wall_right",
                    "x": ["width/2 - plank", "width/2"],
                    "y": ["-depth/2 + plank", "depth/2 - plank"],
                    "z": ["plank", "height - plank"],
                },
            ],
            "interfaces": [
                ["floor", "wall_front", "plank*width"],
                ["floor", "wall_back", "plank*width"],
                ["floor", "wall_left", "plank*(depth - 2*plank)"],
                ["floor", "wall_right", "plank*(depth - 2*plank)"],
            ],
        },
        {
            "name": "lid",
            "role": "moving",
            "cells": [
                {
                    "kind": "box",
                    "label": "lid_panel",
                    "x": ["-width/2", "width/2"],
                    "y": ["-depth/2", "depth/2"],
                    "z": ["height - plank", "height"],
                }
            ],
            "interfaces": [],
        },
    ],
    "joints": [
        {
            "name": "lid_hinge",
            "type": "revolute",
            "parent": "crate_body",
            "child": "lid",
            # The lid turns about the back top edge, which runs along X.
            "axis": [1.0, 0.0, 0.0],
            "origin": ["0", "depth/2", "height - plank"],
            "limits": [0.0, 90.0 * _DEG],
        }
    ],
    "action": {"joints": ["lid_hinge"], "target": 90.0 * _DEG, "unit": "rad"},
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# chest
# ---------------------------------------------------------------------------

_CHEST = {
    "prop": "chest",
    "description": (
        "A wooden chest: a rectangular box with thick walls and a domed lid "
        "hinged on the back top edge."
    ),
    "parameters": {
        "width": 600.0,
        "depth": 400.0,
        "height": 400.0,
        "wall": 20.0,
        "dome_radius": 200.0,
    },
    "bodies": [
        {
            "name": "chest_body",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "bottom",
                    "x": ["-width/2", "width/2"],
                    "y": ["-depth/2", "depth/2"],
                    "z": ["0", "wall"],
                },
                {
                    "kind": "box",
                    "label": "wall_front",
                    "x": ["-width/2", "width/2"],
                    "y": ["-depth/2", "-depth/2 + wall"],
                    "z": ["wall", "height"],
                },
                {
                    "kind": "box",
                    "label": "wall_back",
                    "x": ["-width/2", "width/2"],
                    "y": ["depth/2 - wall", "depth/2"],
                    "z": ["wall", "height"],
                },
                {
                    "kind": "box",
                    "label": "wall_left",
                    "x": ["-width/2", "-width/2 + wall"],
                    "y": ["-depth/2 + wall", "depth/2 - wall"],
                    "z": ["wall", "height"],
                },
                {
                    "kind": "box",
                    "label": "wall_right",
                    "x": ["width/2 - wall", "width/2"],
                    "y": ["-depth/2 + wall", "depth/2 - wall"],
                    "z": ["wall", "height"],
                },
            ],
            "interfaces": [
                ["bottom", "wall_front", "wall*width"],
                ["bottom", "wall_back", "wall*width"],
                ["bottom", "wall_left", "wall*(depth - 2*wall)"],
                ["bottom", "wall_right", "wall*(depth - 2*wall)"],
            ],
        },
        {
            "name": "chest_lid",
            "role": "moving",
            "cells": [
                {
                    "kind": "half_cyl",
                    "label": "dome",
                    "axis": "x",
                    "dome_dir": "z",
                    "center": ["0", "0", "height"],
                    "r": "dome_radius",
                    "length": "width",
                }
            ],
            "interfaces": [],
        },
    ],
    "joints": [
        {
            "name": "lid_hinge",
            "type": "revolute",
            "parent": "chest_body",
            "child": "chest_lid",
            # The dome turns about the back top edge, which runs along X.
            "axis": [1.0, 0.0, 0.0],
            "origin": ["0", "depth/2", "height"],
            "limits": [0.0, 90.0 * _DEG],
        }
    ],
    "action": {"joints": ["lid_hinge"], "target": 90.0 * _DEG, "unit": "rad"},
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# lantern
# ---------------------------------------------------------------------------

_LANTERN = {
    "prop": "lantern",
    "description": (
        "A hanging lantern: a cylindrical lamp housing with a wider base "
        "disc, swinging from a hook block on a revolute joint."
    ),
    "parameters": {
        "lantern_radius": 90.0,
        "lantern_height": 240.0,
        "base_height": 30.0,
        "hang_height": 420.0,
        "hook_size": 40.0,
    },
    "bodies": [
        {
            "name": "hook",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "hook_block",
                    "x": ["-hook_size/2", "hook_size/2"],
                    "y": ["-hook_size/2", "hook_size/2"],
                    "z": ["hang_height", "hang_height + hook_size"],
                }
            ],
            "interfaces": [],
        },
        {
            "name": "lantern",
            "role": "moving",
            "cells": [
                {
                    "kind": "cyl",
                    "label": "housing",
                    "axis": "z",
                    "center": [
                        "0",
                        "0",
                        "hang_height - lantern_height/2",
                    ],
                    "r": "lantern_radius",
                    "length": "lantern_height",
                },
                {
                    "kind": "cyl",
                    "label": "base",
                    "axis": "z",
                    "center": [
                        "0",
                        "0",
                        "hang_height - lantern_height - base_height/2",
                    ],
                    "r": "lantern_radius*1.1",
                    "length": "base_height",
                },
            ],
            "interfaces": [
                ["housing", "base", "pi*lantern_radius**2"],
            ],
        },
    ],
    "joints": [
        {
            "name": "swing",
            "type": "revolute",
            "parent": "hook",
            "child": "lantern",
            # A hanging lantern swings like a pendulum, about a horizontal axis.
            "axis": [1.0, 0.0, 0.0],
            "origin": ["0", "0", "hang_height"],
            "limits": [-30.0 * _DEG, 30.0 * _DEG],
        }
    ],
    "action": {"joints": ["swing"], "target": 30.0 * _DEG, "unit": "rad"},
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# door
# ---------------------------------------------------------------------------

_DOOR = {
    "prop": "door",
    "description": (
        "A door in a frame: two jambs and a head, with a door leaf hinged on "
        "the left jamb."
    ),
    "parameters": {
        "opening_width": 800.0,
        "jamb_width": 100.0,
        "door_height": 2000.0,
        "frame_height": 2100.0,
        "leaf_thickness": 40.0,
        "leaf_gap": 10.0,
    },
    "bodies": [
        {
            "name": "frame",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "jamb_left",
                    "x": [
                        "-opening_width/2 - jamb_width",
                        "-opening_width/2",
                    ],
                    "y": ["-leaf_thickness", "0"],
                    "z": ["0", "frame_height"],
                },
                {
                    "kind": "box",
                    "label": "jamb_right",
                    "x": ["opening_width/2", "opening_width/2 + jamb_width"],
                    "y": ["-leaf_thickness", "0"],
                    "z": ["0", "frame_height"],
                },
                {
                    "kind": "box",
                    "label": "head",
                    "x": ["-opening_width/2", "opening_width/2"],
                    "y": ["-leaf_thickness", "0"],
                    "z": ["door_height", "frame_height"],
                },
            ],
            "interfaces": [],
        },
        {
            "name": "leaf",
            "role": "moving",
            "cells": [
                {
                    "kind": "box",
                    "label": "leaf_panel",
                    "x": [
                        "-opening_width/2 + leaf_gap",
                        "opening_width/2 - leaf_gap",
                    ],
                    "y": ["-leaf_thickness", "0"],
                    "z": ["0", "door_height"],
                }
            ],
            "interfaces": [],
        },
    ],
    "joints": [
        {
            "name": "hinge",
            "type": "revolute",
            "parent": "frame",
            "child": "leaf",
            "axis": [0.0, 0.0, 1.0],
            "origin": ["-opening_width/2 + leaf_gap", "0", "0"],
            "limits": [0.0, 90.0 * _DEG],
        }
    ],
    "action": {"joints": ["hinge"], "target": 90.0 * _DEG, "unit": "rad"},
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# drawer unit
# ---------------------------------------------------------------------------

_DRAWER_UNIT = {
    "prop": "drawer_unit",
    "description": (
        "A two-drawer unit: a carcass with a shelf and two drawers, each "
        "sliding forward on its own prismatic joint."
    ),
    "parameters": {
        "unit_width": 600.0,
        "unit_depth": 500.0,
        "unit_height": 800.0,
        "wall": 30.0,
        "drawer_height": 330.0,
        "drawer_travel": 300.0,
    },
    "bodies": [
        {
            "name": "carcass",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "side_left",
                    "x": ["-unit_width/2", "-unit_width/2 + wall"],
                    "y": ["-unit_depth/2", "unit_depth/2"],
                    "z": ["0", "unit_height"],
                },
                {
                    "kind": "box",
                    "label": "side_right",
                    "x": ["unit_width/2 - wall", "unit_width/2"],
                    "y": ["-unit_depth/2", "unit_depth/2"],
                    "z": ["0", "unit_height"],
                },
                {
                    "kind": "box",
                    "label": "back",
                    "x": [
                        "-unit_width/2 + wall",
                        "unit_width/2 - wall",
                    ],
                    "y": ["unit_depth/2 - wall", "unit_depth/2"],
                    "z": ["0", "unit_height"],
                },
                {
                    "kind": "box",
                    "label": "bottom",
                    "x": [
                        "-unit_width/2 + wall",
                        "unit_width/2 - wall",
                    ],
                    "y": ["-unit_depth/2", "unit_depth/2 - wall"],
                    "z": ["0", "wall"],
                },
                {
                    "kind": "box",
                    "label": "shelf",
                    "x": [
                        "-unit_width/2 + wall",
                        "unit_width/2 - wall",
                    ],
                    "y": ["-unit_depth/2", "unit_depth/2 - wall"],
                    "z": [
                        "(unit_height - wall)/2 - wall",
                        "(unit_height - wall)/2",
                    ],
                },
                {
                    "kind": "box",
                    "label": "top",
                    "x": [
                        "-unit_width/2 + wall",
                        "unit_width/2 - wall",
                    ],
                    "y": ["-unit_depth/2", "unit_depth/2 - wall"],
                    "z": ["unit_height - wall", "unit_height"],
                },
            ],
            "interfaces": [
                ["bottom", "side_left", "wall*(unit_depth - 2*wall)"],
                ["bottom", "side_right", "wall*(unit_depth - 2*wall)"],
                ["bottom", "back", "(unit_width - 2*wall)*wall"],
                ["shelf", "side_left", "wall*(unit_depth - 2*wall)"],
                ["shelf", "side_right", "wall*(unit_depth - 2*wall)"],
                ["shelf", "back", "(unit_width - 2*wall)*wall"],
                ["top", "side_left", "wall*(unit_depth - 2*wall)"],
                ["top", "side_right", "wall*(unit_depth - 2*wall)"],
                ["top", "back", "(unit_width - 2*wall)*wall"],
            ],
        },
        {
            "name": "drawer_upper",
            "role": "moving",
            "cells": [
                {
                    "kind": "box",
                    "label": "upper_box",
                    "x": [
                        "-unit_width/2 + wall + 10",
                        "unit_width/2 - wall - 10",
                    ],
                    "y": ["-unit_depth/2 + 10", "unit_depth/2 - wall - 10"],
                    "z": [
                        "(unit_height - wall)/2 + 10",
                        "(unit_height - wall)/2 + drawer_height",
                    ],
                }
            ],
            "interfaces": [],
        },
        {
            "name": "drawer_lower",
            "role": "moving",
            "cells": [
                {
                    "kind": "box",
                    "label": "lower_box",
                    "x": [
                        "-unit_width/2 + wall + 10",
                        "unit_width/2 - wall - 10",
                    ],
                    "y": ["-unit_depth/2 + 10", "unit_depth/2 - wall - 10"],
                    "z": ["wall + 10", "wall + 10 + drawer_height"],
                }
            ],
            "interfaces": [],
        },
    ],
    "joints": [
        {
            "name": "drawer_upper_slide",
            "type": "prismatic",
            "parent": "carcass",
            "child": "drawer_upper",
            "axis": [0.0, 1.0, 0.0],
            "origin": ["0", "-unit_depth/2", "(unit_height - wall)/2 + 10 + drawer_height/2"],
            "limits": [0.0, 300.0],
        },
        {
            "name": "drawer_lower_slide",
            "type": "prismatic",
            "parent": "carcass",
            "child": "drawer_lower",
            "axis": [0.0, 1.0, 0.0],
            "origin": ["0", "-unit_depth/2", "wall + 10 + drawer_height/2"],
            "limits": [0.0, 300.0],
        },
    ],
    "action": {
        "joints": ["drawer_upper_slide"],
        "target": 300.0,
        "unit": "mm",
    },
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# barrel
# ---------------------------------------------------------------------------

_BARREL = {
    "prop": "barrel",
    "description": (
        "A cooper's barrel: a hollow cylindrical wall with a solid bottom "
        "head, and a flat lid that slides straight up off the mouth."
    ),
    "parameters": {
        "radius": 220.0,
        "wall": 20.0,
        "height": 700.0,
        "lid_thickness": 20.0,
        "lift": 150.0,
    },
    "bodies": [
        {
            "name": "barrel_body",
            "role": "static",
            "cells": [
                {
                    "kind": "tube",
                    "label": "staves",
                    "axis": "z",
                    "center": ["0", "0", "(wall + height)/2"],
                    "r_outer": "radius",
                    "r_inner": "radius - wall",
                    "length": "height - wall",
                },
                {
                    "kind": "cyl",
                    "label": "bottom_head",
                    "axis": "z",
                    "center": ["0", "0", "wall/2"],
                    "r": "radius",
                    "length": "wall",
                },
            ],
            "interfaces": [
                ["bottom_head", "staves", "pi*(radius**2 - (radius - wall)**2)"],
            ],
        },
        {
            "name": "barrel_lid",
            "role": "moving",
            "cells": [
                {
                    "kind": "cyl",
                    "label": "lid_head",
                    "axis": "z",
                    "center": ["0", "0", "height + lid_thickness/2"],
                    "r": "radius",
                    "length": "lid_thickness",
                }
            ],
            "interfaces": [],
        },
    ],
    "joints": [
        {
            "name": "lid_slide",
            "type": "prismatic",
            "parent": "barrel_body",
            "child": "barrel_lid",
            "axis": [0.0, 0.0, 1.0],
            "origin": ["0", "0", "height"],
            "limits": [0.0, 150.0],
        }
    ],
    "action": {"joints": ["lid_slide"], "target": 150.0, "unit": "mm"},
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# cart
# ---------------------------------------------------------------------------

_CART = {
    "prop": "cart",
    "description": (
        "A hand cart: a planked deck with side rails on two wheels, which "
        "roll forward when the wheel axles turn."
    ),
    "parameters": {
        "bed_length": 800.0,
        "bed_width": 400.0,
        "wheel_radius": 150.0,
        "wheel_width": 40.0,
        "deck_thickness": 20.0,
    },
    "bodies": [
        {
            "name": "bed",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "deck",
                    "x": ["-bed_length/2", "bed_length/2"],
                    "y": ["-bed_width/2", "bed_width/2"],
                    "z": ["2*wheel_radius + 10", "2*wheel_radius + 10 + deck_thickness"],
                },
                {
                    "kind": "box",
                    "label": "rail_left",
                    "x": ["-bed_length/2", "-bed_length/2 + 20"],
                    "y": ["-bed_width/2", "bed_width/2"],
                    "z": [
                        "2*wheel_radius + 10 + deck_thickness",
                        "2*wheel_radius + 110",
                    ],
                },
                {
                    "kind": "box",
                    "label": "rail_right",
                    "x": ["bed_length/2 - 20", "bed_length/2"],
                    "y": ["-bed_width/2", "bed_width/2"],
                    "z": [
                        "2*wheel_radius + 10 + deck_thickness",
                        "2*wheel_radius + 110",
                    ],
                },
            ],
            "interfaces": [
                ["deck", "rail_left", "20*bed_width"],
                ["deck", "rail_right", "20*bed_width"],
            ],
        },
        {
            "name": "wheel_front",
            "role": "moving",
            "cells": [
                {
                    "kind": "cyl",
                    "label": "front_wheel",
                    "axis": "x",
                    "center": ["0", "bed_width/2 - wheel_radius", "wheel_radius"],
                    "r": "wheel_radius",
                    "length": "wheel_width",
                }
            ],
            "interfaces": [],
        },
        {
            "name": "wheel_rear",
            "role": "moving",
            "cells": [
                {
                    "kind": "cyl",
                    "label": "rear_wheel",
                    "axis": "x",
                    "center": ["0", "-(bed_width/2 - wheel_radius)", "wheel_radius"],
                    "r": "wheel_radius",
                    "length": "wheel_width",
                }
            ],
            "interfaces": [],
        },
    ],
    "joints": [
        {
            "name": "wheel_front_axle",
            "type": "revolute",
            "parent": "bed",
            "child": "wheel_front",
            "axis": [1.0, 0.0, 0.0],
            "origin": ["0", "bed_width/2 - wheel_radius", "wheel_radius"],
            "limits": [-20.0, 20.0],
        },
        {
            "name": "wheel_rear_axle",
            "type": "revolute",
            "parent": "bed",
            "child": "wheel_rear",
            "axis": [1.0, 0.0, 0.0],
            "origin": ["0", "-(bed_width/2 - wheel_radius)", "wheel_radius"],
            "limits": [-20.0, 20.0],
        },
    ],
    "action": {
        "joints": ["wheel_front_axle", "wheel_rear_axle"],
        "target": 2.0,
        "unit": "rad",
    },
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

_GATE = {
    "prop": "gate",
    "description": (
        "A field gate: two posts and a slatted leaf hinged on the left post, "
        "swinging open."
    ),
    "parameters": {
        "post_height": 1500.0,
        "post_width": 120.0,
        "post_depth": 40.0,
        "gate_width": 780.0,
        "rail_bottom_z": 150.0,
        "rail_height": 60.0,
        "slat_count": 5,
        "slat_depth": 40.0,
        "rail_depth": 50.0,
    },
    "bodies": [
        {
            "name": "posts",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "post_left",
                    "x": ["-post_width/2", "post_width/2"],
                    "y": ["-rail_depth - post_depth", "-rail_depth"],
                    "z": ["0", "post_height"],
                },
                {
                    "kind": "box",
                    "label": "post_right",
                    "x": [
                        "post_width/2 + gate_width",
                        "post_width/2 + gate_width + post_width",
                    ],
                    "y": ["-rail_depth - post_depth", "-rail_depth"],
                    "z": ["0", "post_height"],
                },
            ],
            "interfaces": [],
        },
        {
            "name": "leaf",
            "role": "moving",
            "cells": [
                {
                    "kind": "box",
                    "label": "rail_bottom",
                    "x": ["post_width/2", "post_width/2 + gate_width"],
                    "y": ["-rail_depth/2", "rail_depth/2"],
                    "z": ["rail_bottom_z", "rail_bottom_z + rail_height"],
                },
                {
                    "kind": "box",
                    "label": "rail_top",
                    "x": ["post_width/2", "post_width/2 + gate_width"],
                    "y": ["-rail_depth/2", "rail_depth/2"],
                    "z": [
                        "rail_bottom_z + gate_width + rail_height",
                        "rail_bottom_z + gate_width + 2*rail_height",
                    ],
                },
            ]
            + [
                {
                    "kind": "box",
                    "label": f"slat_{i}",
                    "x": [
                        f"post_width/2 + {i}*2*gate_width/(2*slat_count)",
                        f"post_width/2 + {i}*2*gate_width/(2*slat_count) + gate_width/(2*slat_count)",
                    ],
                    "y": ["-slat_depth/2", "slat_depth/2"],
                    "z": [
                        "rail_bottom_z + rail_height",
                        "rail_bottom_z + gate_width + rail_height",
                    ],
                }
                for i in range(5)
            ],
            "interfaces": []
            + [
                [rail, f"slat_{i}", f"gate_width/(2*slat_count)*slat_depth"]
                for i in range(5)
                for rail in ("rail_bottom", "rail_top")
            ],
        },
    ],
    "joints": [
        {
            "name": "gate_hinge",
            "type": "revolute",
            "parent": "posts",
            "child": "leaf",
            "axis": [0.0, 0.0, 1.0],
            "origin": ["post_width/2", "-rail_depth/2", "0"],
            "limits": [0.0, 80.0 * _DEG],
        }
    ],
    "action": {"joints": ["gate_hinge"], "target": 80.0 * _DEG, "unit": "rad"},
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# ladder
# ---------------------------------------------------------------------------

_LADDER = {
    "prop": "ladder",
    "description": (
        "A two-section extension ladder: a lower section with rungs, and an "
        "upper section that slides straight up to extend the ladder."
    ),
    "parameters": {
        "lower_height": 1200.0,
        "upper_height": 1200.0,
        "rail_gap": 520.0,
        "rail_width": 40.0,
        "rail_depth": 50.0,
        "rung_count": 6,
        "rung_height": 50.0,
        "extend": 600.0,
    },
    "bodies": [
        {
            "name": "lower_section",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "rail_left",
                    "x": ["-rail_gap/2 - rail_width", "-rail_gap/2"],
                    "y": ["-rail_depth/2", "rail_depth/2"],
                    "z": ["0", "lower_height"],
                },
                {
                    "kind": "box",
                    "label": "rail_right",
                    "x": ["rail_gap/2", "rail_gap/2 + rail_width"],
                    "y": ["-rail_depth/2", "rail_depth/2"],
                    "z": ["0", "lower_height"],
                },
            ]
            + [
                {
                    "kind": "box",
                    "label": f"rung_{i}",
                    "x": ["-rail_gap/2", "rail_gap/2"],
                    "y": ["-rail_depth/2 + 5", "rail_depth/2 - 5"],
                    "z": [
                        f"(lower_height - rung_height)/(rung_count + 1)*{i + 1}",
                        f"(lower_height - rung_height)/(rung_count + 1)*{i + 1} + rung_height",
                    ],
                }
                for i in range(6)
            ],
            "interfaces": [
                [rail, f"rung_{i}", f"(rail_depth - 10)*rung_height"]
                for i in range(6)
                for rail in ("rail_left", "rail_right")
            ],
        },
        {
            "name": "upper_section",
            "role": "moving",
            "cells": [
                {
                    "kind": "box",
                    "label": "rail_left",
                    "x": ["-rail_gap/2 - rail_width", "-rail_gap/2"],
                    "y": ["-rail_depth/2", "rail_depth/2"],
                    "z": ["lower_height", "lower_height + upper_height"],
                },
                {
                    "kind": "box",
                    "label": "rail_right",
                    "x": ["rail_gap/2", "rail_gap/2 + rail_width"],
                    "y": ["-rail_depth/2", "rail_depth/2"],
                    "z": ["lower_height", "lower_height + upper_height"],
                },
            ]
            + [
                {
                    "kind": "box",
                    "label": f"rung_{i}",
                    "x": ["-rail_gap/2", "rail_gap/2"],
                    "y": ["-rail_depth/2 + 5", "rail_depth/2 - 5"],
                    "z": [
                        f"lower_height + (upper_height - rung_height)/(rung_count + 1)*{i + 1}",
                        f"lower_height + (upper_height - rung_height)/(rung_count + 1)*{i + 1} + rung_height",
                    ],
                }
                for i in range(6)
            ],
            "interfaces": [
                [rail, f"rung_{i}", f"(rail_depth - 10)*rung_height"]
                for i in range(6)
                for rail in ("rail_left", "rail_right")
            ],
        },
    ],
    "joints": [
        {
            "name": "extension_slide",
            "type": "prismatic",
            "parent": "lower_section",
            "child": "upper_section",
            "axis": [0.0, 0.0, 1.0],
            "origin": ["0", "0", "lower_height"],
            "limits": [0.0, 600.0],
        }
    ],
    "action": {"joints": ["extension_slide"], "target": 600.0, "unit": "mm"},
    "density_kg_m3": DENSITY_KG_M3,
}


# ---------------------------------------------------------------------------
# table
# ---------------------------------------------------------------------------

_TABLE = {
    "prop": "table",
    "description": (
        "A dining table on four legs with aprons and a fixed top, plus a "
        "hinged drop-leaf that folds down beside it."
    ),
    "parameters": {
        "table_height": 740.0,
        "top_length": 840.0,
        "top_width": 640.0,
        "top_thickness": 32.0,
        "leaf_length": 400.0,
        "leg_thickness": 60.0,
        "leg_inset": 20.0,
        "apron_height": 140.0,
    },
    "bodies": [
        {
            "name": "frame",
            "role": "static",
            "cells": [
                {
                    "kind": "box",
                    "label": "leg_front_left",
                    "x": [
                        "-top_length/2 + leg_inset",
                        "-top_length/2 + leg_inset + leg_thickness",
                    ],
                    "y": [
                        "-top_width/2 + leg_inset",
                        "-top_width/2 + leg_inset + leg_thickness",
                    ],
                    "z": ["0", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "leg_front_right",
                    "x": [
                        "top_length/2 - leg_inset - leg_thickness",
                        "top_length/2 - leg_inset",
                    ],
                    "y": [
                        "-top_width/2 + leg_inset",
                        "-top_width/2 + leg_inset + leg_thickness",
                    ],
                    "z": ["0", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "leg_back_left",
                    "x": [
                        "-top_length/2 + leg_inset",
                        "-top_length/2 + leg_inset + leg_thickness",
                    ],
                    "y": [
                        "top_width/2 - leg_inset - leg_thickness",
                        "top_width/2 - leg_inset",
                    ],
                    "z": ["0", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "leg_back_right",
                    "x": [
                        "top_length/2 - leg_inset - leg_thickness",
                        "top_length/2 - leg_inset",
                    ],
                    "y": [
                        "top_width/2 - leg_inset - leg_thickness",
                        "top_width/2 - leg_inset",
                    ],
                    "z": ["0", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "apron_front",
                    "x": [
                        "-top_length/2 + leg_inset + leg_thickness",
                        "top_length/2 - leg_inset - leg_thickness",
                    ],
                    "y": [
                        "-top_width/2 + leg_inset",
                        "-top_width/2 + leg_inset + leg_thickness",
                    ],
                    "z": ["table_height - apron_height", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "apron_back",
                    "x": [
                        "-top_length/2 + leg_inset + leg_thickness",
                        "top_length/2 - leg_inset - leg_thickness",
                    ],
                    "y": [
                        "top_width/2 - leg_inset - leg_thickness",
                        "top_width/2 - leg_inset",
                    ],
                    "z": ["table_height - apron_height", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "apron_left",
                    "x": [
                        "-top_length/2 + leg_inset",
                        "-top_length/2 + leg_inset + leg_thickness",
                    ],
                    "y": [
                        "-top_width/2 + leg_inset + leg_thickness",
                        "top_width/2 - leg_inset - leg_thickness",
                    ],
                    "z": ["table_height - apron_height", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "apron_right",
                    "x": [
                        "top_length/2 - leg_inset - leg_thickness",
                        "top_length/2 - leg_inset",
                    ],
                    "y": [
                        "-top_width/2 + leg_inset + leg_thickness",
                        "top_width/2 - leg_inset - leg_thickness",
                    ],
                    "z": ["table_height - apron_height", "table_height"],
                },
                {
                    "kind": "box",
                    "label": "top_fixed",
                    "x": ["-top_length/2", "top_length/2"],
                    "y": ["-top_width/2", "top_width/2"],
                    "z": ["table_height", "table_height + top_thickness"],
                },
            ],
            "interfaces": [],
        },
        {
            "name": "leaf",
            "role": "moving",
            "cells": [
                {
                    "kind": "box",
                    "label": "leaf_panel",
                    "x": ["top_length/2", "top_length/2 + leaf_length"],
                    "y": ["-top_width/2", "top_width/2"],
                    "z": ["table_height", "table_height + top_thickness"],
                }
            ],
            "interfaces": [],
        },
    ],
    "joints": [
        {
            "name": "leaf_hinge",
            "type": "revolute",
            "parent": "frame",
            "child": "leaf",
            "axis": [0.0, 1.0, 0.0],
            "origin": ["top_length/2", "0", "table_height"],
            "limits": [0.0, 90.0 * _DEG],
        }
    ],
    "action": {"joints": ["leaf_hinge"], "target": 90.0 * _DEG, "unit": "rad"},
    "density_kg_m3": DENSITY_KG_M3,
}


#: Every prop, keyed by name.
PROPS: dict[str, dict[str, Any]] = {
    p["prop"]: p
    for p in (_CRATE, _CHEST, _LANTERN, _DOOR, _DRAWER_UNIT, _BARREL, _CART, _GATE, _LADDER, _TABLE)
}
