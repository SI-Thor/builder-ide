"""A 64-gate catalogue over last-mile's tactical scene.

Clef takes up to 64 questions per call.  C1 asks what a 64-question call
costs and how long it takes versus a 1-question call, so the 64 questions
have to be real decisions with real ground truth, not filler.

Every gate below is computed from the grid by code -- the truth is never a
model's answer.  Truth values are bool (for `noul` gates) or a single
option (for `choice` gates).

Gate ids are prefixed so the 64-question pack is one flat dict, and the
same catalogue gives the 1-question pack (the `action` gate, the decision
D62 says the cascade turns on).
"""

from __future__ import annotations

from typing import Any

from tasks import _bfs, _cheb, _los, _world

N = 12


def _cardinal(g, p):
    """The four 4-directional neighbours of p that are on the board."""
    x, y = p
    out = {}
    for name, (dx, dy) in (("north", (0, -1)), ("south", (0, 1)),
                            ("east", (1, 0)), ("west", (-1, 0))):
        nx, ny = x + dx, y + dy
        out[name] = None if not (0 <= nx < N and 0 <= ny < N) else g[ny][nx]
    return out


def build_gates(seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (questions, truth) for one scene, 64 gates."""
    g, a, b, es = _world(seed)
    path = _bfs(g, a, b)
    nbr = _cardinal(g, a)
    walls = sum(1 for row in g for c in row if c == "#")
    floor_cells = N * N - walls

    # how many of the 8 surrounding cells are free
    around = [g[ay][ax]
              for ay in range(max(0, a[1] - 1), min(N, a[1] + 2))
              for ax in range(max(0, a[0] - 1), min(N, a[0] + 2))
              if (ax, ay) != a]
    open_around = sum(1 for c in around if c != "#")

    dists = sorted(_cheb(a, e) for e in es)
    nearest = dists[0] if dists else None
    los_flags = [_los(g, a, e) for e in es]
    seen = [f for f, e in zip(los_flags, es) if f and _cheb(a, e) <= 6]

    def nbucket(d: int | None) -> str:
        if d is None:
            return "none"
        if d <= 2:
            return "0-2"
        if d <= 4:
            return "3-4"
        if d <= 6:
            return "5-6"
        return "7+"

    def pathbucket(p: int | None) -> str:
        if p is None:
            return "none"
        if p <= 3:
            return "0-3"
        if p <= 6:
            return "4-6"
        if p <= 10:
            return "7-10"
        return "11+"

    q: dict[str, Any] = {}
    t: dict[str, Any] = {}

    def noul(qid: str, instructions: str, truth: bool) -> None:
        q[qid] = {"type": "noul", "instructions": instructions}
        t[qid] = truth

    def choice(qid: str, instructions: str, options: list[str], truth: str) -> None:
        q[qid] = {"type": "choice", "instructions": instructions,
                  "criteria": {o: None for o in options}}
        t[qid] = truth

    # --- 1..8: the scene's own decision ------------------------------
    noul("g01_enemy_visible",
         "Some enemy E has a clear straight line of sight to agent A "
         "(no '#' cell on the straight line between them) AND is within 6 "
         "cells (Chebyshev distance).", bool(seen))
    choice("g02_action",
           "Agent A's best action by this rule: hide if an enemy is visible "
           "within 6 cells; otherwise advance if the beacon is reachable "
           "within 10 steps of 4-directional movement around walls; "
           "otherwise scout.",
           ["hide", "advance", "scout"],
           "hide" if seen else ("advance" if path is not None and path <= 10 else "scout"))
    choice("g03_beacon_bearing",
           "Dominant compass direction from A to the beacon B (the larger of "
           "the horizontal/vertical offsets; ties go east/west).",
           ["north", "south", "east", "west"],
           ("east" if b[0] - a[0] > 0 else "west") if abs(b[0] - a[0]) >= abs(b[1] - a[1])
           else ("south" if b[1] - a[1] > 0 else "north"))
    noul("g04_beacon_reachable",
         "There is a path of floor cells from A to B using 4-directional "
         "moves that avoids walls.", path is not None)
    noul("g05_any_enemy", "There is at least one enemy E on the map.", bool(es))
    choice("g06_n_enemies", "How many enemies E are on the map?",
           ["0", "1", "2"], str(len(es)))
    choice("g07_nearest_enemy_dist",
           "How far is the nearest enemy from A, in Chebyshev cells "
           "(0-2, 3-4, 5-6, or 7+)?", ["none", "0-2", "3-4", "5-6", "7+"],
           nbucket(nearest))
    noul("g08_enemy_within_6", "An enemy is within 6 cells of A in Chebyshev "
         "distance, regardless of line of sight.",
         any(_cheb(a, e) <= 6 for e in es))

    # --- 9..16: enemies, sight ---------------------------------------
    noul("g09_enemy_within_4", "An enemy is within 4 cells of A in "
         "Chebyshev distance.", any(_cheb(a, e) <= 4 for e in es))
    noul("g10_enemy_within_8", "An enemy is within 8 cells of A in "
         "Chebyshev distance.", any(_cheb(a, e) <= 8 for e in es))
    noul("g11_enemy_at_exactly_6",
         "An enemy is at exactly 6 cells from A in Chebyshev distance.",
         any(_cheb(a, e) == 6 for e in es))
    noul("g12_some_enemy_has_los",
         "At least one enemy has a clear line of sight to A, at any distance.",
         any(los_flags))
    noul("g13_every_enemy_blocked",
         "Every enemy on the map has a wall blocking its line of sight to A.",
         bool(es) and not any(los_flags))
    choice("g14_los_enemy_count",
           "How many enemies can see A (clear line of sight AND within 6 "
           "cells)?", ["0", "1", "2"], str(len(seen)))
    noul("g15_enemy_north",
         "An enemy is somewhere north of A (a smaller row index).",
         any(e[1] < a[1] for e in es))
    noul("g16_enemy_west",
         "An enemy is somewhere west of A (a smaller column index).",
         any(e[0] < a[0] for e in es))

    # --- 17..24: the beacon and the path -----------------------------
    choice("g17_path_len",
           "How many 4-directional steps is the shortest path from A to B? "
           "Use 'none' if no path exists.",
           ["none", "0-3", "4-6", "7-10", "11+"], pathbucket(path))
    noul("g18_path_within_10",
         "The beacon is reachable from A in 10 or fewer 4-directional steps.",
         path is not None and path <= 10)
    noul("g19_path_within_5",
         "The beacon is reachable from A in 5 or fewer 4-directional steps.",
         path is not None and path <= 5)
    noul("g20_beacon_north", "The beacon B is north of A (smaller row index).",
         b[1] < a[1])
    noul("g21_beacon_south", "The beacon B is south of A (larger row index).",
         b[1] > a[1])
    noul("g22_beacon_east", "The beacon B is east of A (larger column index).",
         b[0] > a[0])
    noul("g23_beacon_west", "The beacon B is west of A (smaller column index).",
         b[0] < a[0])
    noul("g24_beacon_close",
         "The beacon B is within 4 cells of A in Chebyshev distance.",
         _cheb(a, b) <= 4)

    # --- 25..32: walls and cover around A ----------------------------
    noul("g25_wall_north", "The cell immediately north of A is a wall '#'.",
         nbr["north"] == "#")
    noul("g26_wall_south", "The cell immediately south of A is a wall '#'.",
         nbr["south"] == "#")
    noul("g27_wall_east", "The cell immediately east of A is a wall '#'.",
         nbr["east"] == "#")
    noul("g28_wall_west", "The cell immediately west of A is a wall '#'.",
         nbr["west"] == "#")
    noul("g29_cover_adjacent",
         "At least one of the four cells immediately around A is a wall.",
         any(nbr[d] == "#" for d in nbr))
    noul("g30_no_cover",
         "None of the four cells immediately around A is a wall.",
         not any(nbr[d] == "#" for d in nbr))
    choice("g31_open_neighbours",
           "How many of the four cells immediately around A are not walls?",
           ["0", "1", "2", "3", "4"],
           str(sum(1 for d in nbr if nbr[d] != "#")))
    choice("g32_open_ring",
           "How many of the eight cells in the ring around A are not walls?",
           ["0-2", "3-4", "5-6", "7-8"],
           ("0-2" if open_around <= 2 else "3-4" if open_around <= 4
            else "5-6" if open_around <= 6 else "7-8"))

    # --- 33..40: the board -------------------------------------------
    choice("g33_wall_density",
           "How dense are the walls on the 12x12 board, as a fraction of "
           "cells? Use 'sparse' for under 20%, 'medium' for 20-30%, 'dense' "
           "for over 30%.", ["sparse", "medium", "dense"],
           "sparse" if walls / floor_cells < 0.20 else
           ("medium" if walls / floor_cells <= 0.30 else "dense"))
    noul("g34_more_floor_than_wall",
         "There are more floor cells than wall cells on the board.",
         floor_cells > walls)
    choice("g35_agent_column_band",
           "Which third of the board's columns is agent A in: west (0-3), "
           "middle (4-7) or east (8-11)?", ["west", "middle", "east"],
           "west" if a[0] <= 3 else ("middle" if a[0] <= 7 else "east"))
    choice("g36_agent_row_band",
           "Which third of the board's rows is agent A in: north (0-3), "
           "middle (4-7) or south (8-11)?", ["north", "middle", "south"],
           "north" if a[1] <= 3 else ("middle" if a[1] <= 7 else "south"))
    noul("g37_agent_in_corner",
         "Agent A is in one of the four corners of the board.",
         a[0] in (0, N - 1) and a[1] in (0, N - 1))
    noul("g38_agent_on_edge",
         "Agent A is on the border of the board.",
         a[0] in (0, N - 1) or a[1] in (0, N - 1))
    noul("g39_beacon_in_corner",
         "The beacon B is in one of the four corners of the board.",
         b[0] in (0, N - 1) and b[1] in (0, N - 1))

    # --- 41..48: geometry between A and B ---------------------------
    noul("g40_beacon_same_row", "A and B are on the same row.",
         a[1] == b[1])
    noul("g41_beacon_same_column", "A and B are on the same column.",
         a[0] == b[0])
    noul("g42_bearing_horizontal_dominates",
         "The horizontal distance from A to B is greater than the vertical "
         "distance.", abs(b[0] - a[0]) > abs(b[1] - a[1]))
    noul("g43_vertical_dominates",
         "The vertical distance from A to B is greater than the horizontal "
         "distance.", abs(b[1] - a[1]) > abs(b[0] - a[0]))
    noul("g44_beacon_within_2",
         "The beacon B is within 2 cells of A in Chebyshev distance.",
         _cheb(a, b) <= 2)
    noul("g45_beacon_beyond_8",
         "The beacon B is more than 8 cells away in Chebyshev distance.",
         _cheb(a, b) > 8)
    noul("g46_enemy_between_ab",
         "Some enemy lies within the straight line between A and B.",
         any(_los(g, a, b) and _on_segment(a, e, b) for e in es))
    noul("g47_same_quadrant",
         "A and B are in the same quadrant of the board (same half in both "
         "axes).", (a[0] < 6) == (b[0] < 6) and (a[1] < 6) == (b[1] < 6))

    # --- 49..56: the enemies' geometry ------------------------------
    noul("g48_enemies_clustered",
         "All enemies are within 3 cells of each other in Chebyshev "
         "distance.", len(es) >= 2 and all(
             _cheb(es[0], e) <= 3 for e in es[1:]))
    noul("g49_enemy_north_of_beacon",
         "Some enemy is north of the beacon B (smaller row index).",
         any(e[1] < b[1] for e in es))
    noul("g50_enemy_south_of_beacon",
         "Some enemy is south of the beacon B (larger row index).",
         any(e[1] > b[1] for e in es))
    noul("g51_enemy_closer_to_beacon",
         "Some enemy is closer to the beacon B than agent A is.",
         any(_cheb(e, b) < _cheb(a, b) for e in es))
    noul("g52_enemy_far_from_beacon",
         "Every enemy is farther from the beacon B than agent A is.",
         bool(es) and all(_cheb(e, b) > _cheb(a, b) for e in es))
    noul("g53_enemy_diagonal",
         "Some enemy is diagonally offset from A (both the row and the "
         "column differ).",
         any(e[0] != a[0] and e[1] != a[1] for e in es))
    noul("g54_enemy_orthogonal",
         "Some enemy is on the same row or the same column as A.",
         any(e[0] == a[0] or e[1] == a[1] for e in es))
    noul("g55_enemy_out_of_reach_8",
         "Every enemy is more than 8 cells from A in Chebyshev distance.",
         bool(es) and all(_cheb(a, e) > 8 for e in es))

    # --- 57..64: the decision itself --------------------------------
    choice("g56_risk_level",
           "Rate the risk of agent A advancing right now on a scale from "
           "clear to severe: clear, low, moderate, high, severe.",
           ["clear", "low", "moderate", "high", "severe"],
           "severe" if len(seen) >= 2 else
           ("high" if seen else
            ("moderate" if path is not None and path > 10 else
             ("low" if any(_cheb(a, e) <= 6 for e in es) else "clear"))))
    choice("g57_movement_plan",
           "Which movement plan fits best: retreat, hold, advance, scout?",
           ["retreat", "hold", "advance", "scout"],
           "retreat" if len(seen) >= 2 else
           ("hold" if seen else
            ("advance" if path is not None and path <= 10 else "scout")))
    noul("g58_should_engage",
         "Should agent A engage an enemy right now?",
         len(seen) >= 2)
    noul("g59_should_advance",
         "Should agent A advance towards the beacon right now?",
         not seen and path is not None and path <= 10)
    noul("g60_should_scout",
         "Should agent A scout for a route to the beacon right now?",
         not seen and not (path is not None and path <= 10))
    noul("g61_hide_is_best",
         "Hiding is the best action for agent A right now.", bool(seen))
    noul("g62_scout_is_best",
         "Scouting is the best action for agent A right now.",
         not seen and not (path is not None and path <= 10))
    choice("g63_comm_verb",
           "Which radio call should agent A make first: contact, hold, "
           "move, fallback?", ["contact", "hold", "move", "fallback"],
           "contact" if len(seen) >= 2 else
           ("fallback" if seen else
            ("move" if path is not None and path <= 10 else "hold")))
    noul("g64_route_exists_short",
         "A route of 6 or fewer steps from A to B exists.",
         path is not None and path <= 6)

    assert len(q) == 64, f"expected 64 gates, got {len(q)}"
    return q, t


def _on_segment(a, p, b) -> bool:
    """Is p on the axis-aligned rectangle's straight diagonal between a and b?"""
    (ax, ay), (px, py), (bx, by) = a, p, b
    if (px - ax) * (by - ay) != (py - ay) * (bx - ax):
        return False
    return min(ax, bx) <= px <= max(ax, bx) and min(ay, by) <= py <= max(ay, by)


def one_gate_pack(seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """The 1-question pack: the `action` gate alone (D62's decision)."""
    q, t = build_gates(seed)
    return {"g02_action": q["g02_action"]}, {"g02_action": t["g02_action"]}
