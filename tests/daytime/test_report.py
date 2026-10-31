"""The line the owner sees when he comes back.

One short line, written from the day's fold — never narrated by whoever
happens to be awake to write it.
"""

from __future__ import annotations


def _day(**over):
    day = {
        "ticks": 12,
        "minutes": 0.01,
        "changes": [
            {"kind": "light", "target": "room", "count": 12},
            {"kind": "tidy", "target": "harbor.crates", "count": 3},
            {"kind": "grow", "target": "terrain.harbor", "count": 4},
        ],
        "light_from": "night",
        "light_to": "day",
    }
    day.update(over)
    return day


def test_the_line_says_what_the_world_did():
    from core.daytime.report import while_you_were_away

    out = while_you_were_away(_day())
    line = out["line"]
    assert "12 daytime ticks" in line
    assert "night → day" in line
    assert "harbor.crates was tidied 3×" in line
    assert "terrain.harbor grew 4×" in line
    assert out["ticks"] == 12


def test_a_day_with_nothing_in_it_says_so():
    from core.daytime.report import while_you_were_away

    out = while_you_were_away(
        {"ticks": 0, "minutes": 0.0, "changes": [], "light_from": None, "light_to": None}
    )
    assert "stood still" in out["line"]
    assert out["ticks"] == 0


def test_one_tick_is_one_tick():
    from core.daytime.report import while_you_were_away

    out = while_you_were_away(_day(ticks=1, changes=[], light_from="night", light_to="night"))
    assert "1 daytime tick while you were away" in out["line"]
    assert "stayed night" in out["line"]


def test_the_line_is_short():
    from core.daytime.report import while_you_were_away

    # one line, and a line a person reads in a second
    assert "\n" not in while_you_were_away(_day())["line"]
    assert len(while_you_were_away(_day())["line"]) < 200
