"""A sample prop, built in build123d: a block with a hinged lid.

The one structural difference from the crate is that the walls are thinner
than the lid, which is what the crate's parameter set does to.
"""

from build123d import Align, Box, Compound, Part, Pos, export_step

PARAMS = {"w": 220.0, "d": 160.0, "h": 120.0, "t": 12.0}

_w = PARAMS["w"]
_d = PARAMS["d"]
_h = PARAMS["h"]
_t = PARAMS["t"]

_base = Pos(-_w / 2, -_d / 2, 0) * Box(_w, _d, _t, align=(Align.MIN, Align.MIN, Align.MIN))
_wall = Pos(-_w / 2, _d / 2 - _t, _t) * Box(_w, _t, _h - 2 * _t, align=(Align.MIN, Align.MIN, Align.MIN))
_lid = Pos(-_w / 2, -_d / 2, _h - _t) * Box(_w, _d, _t, align=(Align.MIN, Align.MIN, Align.MIN))

BODIES = {
    "base": Part() + _base + _wall,
    "lid": Part() + _lid,
}

export_step(Compound(list(BODIES.values())), "prop.step")
