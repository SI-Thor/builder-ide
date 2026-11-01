"""The three tasks. Each one has ground truth and a paired evaluation.

T1  last-mile's paired game scenes.
    Reuses last-mile's own scene generator and its ground truth rule
    (docs/research/poc/thor/e4b.py in ~/last-mile): a 12x12 grid, an agent,
    a beacon, up to two enemies, and the rule "hide if an enemy can see A
    within 6 cells, else advance if the beacon is reachable within 10
    steps, else scout". The truth is computed from the grid, never from a
    model. The states are given in plain-language facts (the "facts"
    condition), because that is the condition last-mile measured (facts
    beat grids: d1-3B goes 0.45 -> 0.97 on action).

T2  the critic's defect classification.
    builder-ide's core/critic/reference-set.json: 60 clean bases and 30
    members, each member carrying a seeded defect class. The critic's
    own checks measure an image and say which defect they suspect; this
    task asks the model to name the defect class from the critic's
    measurements, and scores FP/FN per class. The ground truth is the
    member's planted defect; a clean base is the "no defect" class.

T3  a tile-choice task.
    A small simulated game: a context (the board, the agent, the goal)
    and K scripted tiles (options). Exactly one tile is the best move,
    by a rule computed from the context. This maps onto the tiles
    system: the options are tiles, the model is the local decision
    model, the score is the play's outcome.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

# ==========================================================================
# T1 -- last-mile's paired game scenes
# ==========================================================================

N_GRID = 12


def _world(seed: int):
    """last-mile's scene generator, verbatim in behaviour (e4b.py:world)."""
    r = random.Random(seed)
    g = [[('#' if r.random() < 0.22 else '.') for _ in range(N_GRID)]
         for _ in range(N_GRID)]

    def free():
        while True:
            x, y = r.randrange(N_GRID), r.randrange(N_GRID)
            if g[y][x] == '.':
                return (x, y)

    a = free(); g[a[1]][a[0]] = 'A'
    b = free(); g[b[1]][b[0]] = 'B'
    es = []
    for _ in range(r.randrange(0, 3)):
        e = free(); g[e[1]][e[0]] = 'E'; es.append(e)
    return g, a, b, es


def _los(g, p, q) -> bool:
    """Clear straight line of sight (Bresenham), blocked by walls."""
    (x0, y0), (x1, y1) = p, q
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while (x0, y0) != (x1, y1):
        e2 = 2 * err
        if e2 >= dy:
            err += dy; x0 += sx
        if e2 <= dx:
            err += dx; y0 += sy
        if (x0, y0) != (x1, y1) and g[y0][x0] == '#':
            return False
    return True


def _bfs(g, s, t):
    d = {s: 0}
    qq = deque([s])
    while qq:
        x, y = qq.popleft()
        if (x, y) == t:
            return d[(x, y)]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < N_GRID and 0 <= ny < N_GRID and g[ny][nx] != '#' and (nx, ny) not in d:
                d[(nx, ny)] = d[(x, y)] + 1
                qq.append((nx, ny))
    return None


def _cheb(p, q) -> int:
    return max(abs(p[0] - q[0]), abs(p[1] - q[1]))


def scene_truth(g, a, b, es) -> dict[str, Any]:
    """The ground truth rule, computed from the grid (never from a model)."""
    vis = any(_los(g, a, e) and _cheb(a, e) <= 6 for e in es)
    path = _bfs(g, a, b)
    if vis:
        act = "hide"
    elif path is not None and path <= 10:
        act = "advance"
    else:
        act = "scout"
    dx, dy = b[0] - a[0], b[1] - a[1]
    bearing = ("east" if dx > 0 else "west") if abs(dx) >= abs(dy) else ("south" if dy > 0 else "north")
    return {
        "enemy_visible": bool(vis),
        "action": act,
        "beacon_bearing": bearing,
        "beacon_reachable": path is not None,
        "path_len": path,
    }


def scene_state(g, a, b, es) -> str:
    """The 'facts' condition: code-computed facts in plain language."""
    truth = scene_truth(g, a, b, es)
    lines = [
        f"Agent A is at column {a[0]}, row {a[1]} (row 0 is north).",
        f"The beacon B is at column {b[0]}, row {b[1]}.",
    ]
    path = truth["path_len"]
    lines.append(f"A walking path to the beacon exists and is {path} steps long."
                 if path is not None else "There is no walking path to the beacon.")
    if not es:
        lines.append("No enemies are on the map.")
    for i, e in enumerate(es):
        sees = _los(g, a, e)
        lines.append(
            f"Enemy {i + 1} is {_cheb(a, e)} cells away and "
            + ("CAN see agent A (clear line of sight)." if sees
               else "cannot see agent A (a wall blocks the line of sight)."))
    return " ".join(lines)


SCENE_QUESTIONS: dict[str, Any] = {
    "enemy_visible": {
        "type": "noul",
        "instructions": (
            "Some enemy E has a clear straight line of sight to agent A "
            "(no '#' cell on the straight line between them) AND is within 6 "
            "cells (Chebyshev distance)."),
    },
    "action": {
        "type": "choice",
        "instructions": (
            "Agent A's best action by this rule: hide if an enemy is visible "
            "within 6 cells; otherwise advance if the beacon is reachable "
            "within 10 steps of 4-directional movement around walls; "
            "otherwise scout."),
        "criteria": {
            "hide": "an enemy can see A within 6 cells",
            "advance": "no visible enemy and beacon reachable in <=10 steps",
            "scout": "neither",
        },
    },
    "beacon_bearing": {
        "type": "choice",
        "instructions": (
            "Dominant compass direction from A to the beacon B (the larger of "
            "the horizontal/vertical offsets; ties go east/west)."),
        "criteria": {"north": None, "south": None, "east": None, "west": None},
    },
    "beacon_reachable": {
        "type": "noul",
        "instructions": (
            "There is a path of floor cells from A to B using 4-directional "
            "moves that avoids walls."),
    },
}

#: The question the decision actually turns on (D62's "action" gate).
SCENE_PRIMARY = "action"


def build_scenes(n: int, seed_base: int = 1000) -> list[dict[str, Any]]:
    """n fresh paired scenes, each with its state and its ground truth."""
    scenes = []
    for i in range(n):
        g, a, b, es = _world(seed_base + i)
        truth = scene_truth(g, a, b, es)
        scenes.append({
            "id": f"scene-{seed_base + i}",
            "seed": seed_base + i,
            "state": scene_state(g, a, b, es),
            "truth": {k: truth[k] for k in ("enemy_visible", "action",
                                            "beacon_bearing", "beacon_reachable")},
        })
    return scenes


def score_scene(answers: dict[str, Any], truth: dict[str, Any]) -> dict[str, bool]:
    """Per-question correctness for one scene."""
    out = {}
    for qid, want in truth.items():
        a = answers.get(qid) or {}
        if isinstance(want, bool):
            got = float(a.get("noul", 0.0)) >= 0.5
            out[qid] = (got == want)
        else:
            out[qid] = (a.get("choice") == want)
    return out


# ==========================================================================
# T2 -- the critic's defect classification
# ==========================================================================

REFERENCE_SET = Path("/home/caseydigennaro/src/builder-ide/core/critic/reference-set.json")

#: The nine seeded defect classes, plus the clean control.
DEFECT_CLASSES: tuple[str, ...] = (
    "none",
    "black_frame",
    "noise_fireflies",
    "missing_object",
    "holes",
    "texture_swap",
    "floating_object",
    "wrong_scale",
    "hollow_mesh",
    "clipped_geometry",
)


def _critic_measurements(image_path: str) -> dict[str, Any] | None:
    """Run builder-ide's own critic checks over one image.

    The critic is a library in another repo; we import it read-only and
    never write to it. It gives each check's measurement and whether it
    fired -- the signal a decision model would have to read.
    """
    try:
        import sys
        for p in ("/home/caseydigennaro/lm-wt/critic-calib",
                  "/home/caseydigennaro/src/builder-ide"):
            if p not in sys.path:
                sys.path.insert(0, p)
        from core.critic.checks import run_image_checks
        from core.critic.imaging import load_rgb
        img = load_rgb(image_path)
        outs = run_image_checks(img)
        return {
            o.check: {"fired": bool(o.fired),
                      "measured": {k: round(float(v), 5) for k, v in o.measured.items()},
                      "detail": o.detail[:180]}
            for o in outs
        }
    except Exception as e:  # noqa: BLE001
        return {"__error__": f"{type(e).__name__}: {e}"}


def build_defect_cases(max_bases: int = 30) -> list[dict[str, Any]]:
    """The reference set as classification cases, with ground truth.

    A case's state is the critic's own measurements on that member's
    image; the question is which defect class the member carries. Clean
    bases are the 'none' class, so a model that always says a defect is
    punished for it.
    """
    if not REFERENCE_SET.exists():
        return []
    ref = json.loads(REFERENCE_SET.read_text())
    cases: list[dict[str, Any]] = []

    members = [m for m in ref["members"] if m.get("layer") == "image"]
    for m in members:
        path = m.get("derived_path")
        if not path or not Path(path).exists():
            continue
        meas = _critic_measurements(path)
        if meas is None or "__error__" in meas:
            continue
        cases.append({
            "id": m["member_id"],
            "state": meas,
            # a member with defect=None is the clean control: the clean
            # half of the reference set, and the 'none' class.
            "truth": m["defect"] or "none",
            "source": "member",
            "layer": "image",
        })

    # Clean controls: the bases, so the model can say "none".
    bases = [b for b in ref["bases"] if b.get("image_path") and Path(b["image_path"]).exists()]
    for b in bases[:max_bases]:
        meas = _critic_measurements(b["image_path"])
        if meas is None or "__error__" in meas:
            continue
        cases.append({
            "id": f"clean-{b['id']}",
            "state": meas,
            "truth": "none",
            "source": "base",
            "layer": "image",
        })
    return cases


def defect_state_text(meas: dict[str, Any]) -> str:
    """The critic's measurements as plain text a decision model can read."""
    lines = ["A rendered scene was measured by the critic's checks.",
             "Each check below is one measurement and whether it fired."]
    for check in sorted(meas.keys()):
        d = meas[check]
        m = d.get("measured") or {}
        ms = ", ".join(f"{k}={v:g}" for k, v in sorted(m.items()))
        lines.append(f"check {check}: fired={d.get('fired')} measured[{ms}]")
    return "\n".join(lines)


DEFECT_QUESTIONS: dict[str, Any] = {
    "defect_class": {
        "type": "choice",
        "instructions": (
            "Which defect class does this scene carry? Choose 'none' if the "
            "scene is clean: no seeded defect was planted in it."),
        "criteria": {c: None for c in DEFECT_CLASSES},
    },
}


def score_defect(pred: str | None, truth: str) -> dict[str, Any]:
    """Per-class confusion: one row for the truth, one for the prediction."""
    return {"truth": truth, "pred": pred, "correct": pred == truth}


def defect_fp_fn(cases: Sequence[dict[str, Any]], preds: Sequence[str | None]) -> dict[str, Any]:
    """False positives and false negatives per class."""
    tp = Counter(); fp = Counter(); fn = Counter()
    for c, p in zip(cases, preds):
        truth = c["truth"]
        if p == truth:
            tp[truth] += 1
        else:
            fn[truth] += 1
            if p is not None:
                fp[p] += 1
    per_class = {}
    for cls in sorted(set(list(tp) + list(fp) + list(fn))):
        support = tp[cls] + fn[cls]
        per_class[cls] = {
            "support": support,
            "tp": tp[cls],
            "fp": fp[cls],
            "fn": fn[cls],
            "recall": round(tp[cls] / support, 4) if support else None,
            "precision": round(tp[cls] / (tp[cls] + fp[cls]), 4) if (tp[cls] + fp[cls]) else None,
        }
    n = len(cases)
    correct = sum(tp.values())
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "macro_f1": _macro_f1(per_class),
        "per_class": per_class,
    }


def _macro_f1(per_class: dict[str, Any]) -> float | None:
    vals = []
    for cls, d in per_class.items():
        if d["support"] == 0:
            continue
        prec = d["precision"] or 0.0
        rec = d["recall"] or 0.0
        vals.append(0.0 if (prec + rec) == 0 else 2 * prec * rec / (prec + rec))
    return round(sum(vals) / len(vals), 4) if vals else None


# ==========================================================================
# T3 -- the tile-choice task
# ==========================================================================

#: The scripted tiles. Each is a behaviour a cloud LLM might have written,
#: and each has a payoff that depends on the context.
TILE_LIBRARY: dict[str, str] = {
    "dash_east": "Sprint east through the open lane, ignoring cover.",
    "dash_west": "Sprint west through the open lane, ignoring cover.",
    "take_north": "Climb north toward the high ledge.",
    "take_south": "Descend south into the low basin.",
    "take_cover": "Hold behind the nearest cover and wait for the next tick.",
    "grab_loot": "Detour to pick up the loot crate in the open.",
    "repair_here": "Stop and repair the rig where it stands.",
    "push_beacon": "Push the beacon, ignoring everything else.",
}

TILE_PAYOFF_RULES = {
    "dash_east":   lambda c: c["east_open"] * 3 + c["east_threat"] * -4 + c["rig_hurt"] * 2,
    "dash_west":   lambda c: c["west_open"] * 3 + c["west_threat"] * -4 + c["rig_hurt"] * 2,
    "take_north":  lambda c: c["north_open"] * 3 + c["north_threat"] * -4 + c["low_basin"] * -1,
    "take_south":  lambda c: c["south_open"] * 3 + c["south_threat"] * -4 + c["low_basin"] * 2,
    "take_cover":  lambda c: c["threat_near"] * 2 + c["rig_hurt"] * 3 + c["beacon_close"] * -2,
    "grab_loot":   lambda c: c["loot_near"] * 4 + c["threat_near"] * -3,
    "repair_here": lambda c: c["rig_hurt"] * 5 + c["threat_near"] * -2,
    "push_beacon": lambda c: c["beacon_close"] * 5 + c["threat_near"] * -2,
}


@dataclass
class TileCase:
    id: str
    context: dict[str, Any]
    truth: str
    payoff: dict[str, float]
    options: list[str]
    text: str


def _tile_context(r: random.Random) -> dict[str, Any]:
    ctx = {
        "east_open": r.choice([0, 1]),
        "west_open": r.choice([0, 1]),
        "north_open": r.choice([0, 1]),
        "south_open": r.choice([0, 1]),
        "east_threat": r.choice([0, 0, 1]),
        "west_threat": r.choice([0, 0, 1]),
        "north_threat": r.choice([0, 0, 1]),
        "south_threat": r.choice([0, 0, 1]),
        "low_basin": r.choice([0, 1]),
        "rig_hurt": r.choice([0, 0, 1, 2]),
        "loot_near": r.choice([0, 1]),
        "beacon_close": r.choice([0, 0, 1]),
    }
    ctx["threat_near"] = int(any(ctx[f"{d}_threat"] for d in ("east", "west", "north", "south")))
    return ctx


def _tile_text(c: dict[str, Any]) -> str:
    def d(flag: int) -> str:
        return "open" if flag else "blocked"
    threats = [d_ for d_ in ("east", "west", "north", "south") if c[f"{d_}_threat"]]
    return (
        f"You are the rig. The east lane is {d(c['east_open'])}; "
        f"the west lane is {d(c['west_open'])}. "
        f"The north slope is {d(c['north_open'])}; "
        f"the south basin is {d(c['south_open'])}. "
        f"Threats are visible to the {', '.join(threats) if threats else 'none'}. "
        f"The rig is in {'bad' if c['rig_hurt'] >= 2 else ('worn' if c['rig_hurt'] == 1 else 'fine')} shape. "
        f"A loot crate is {'nearby' if c['loot_near'] else 'far away'}. "
        f"The beacon is {'close' if c['beacon_close'] else 'far'}. "
        f"The south basin is {'low and slow' if c['low_basin'] else 'a clear drop'}."
    )


def build_tile_cases(n: int, seed: int = 20261031, k_options: int = 5) -> list[TileCase]:
    """n tile-choice cases with ground truth (the best tile by the payoff rule).

    A case is only kept when the best tile is *strictly* better than every
    other tile: a tie would make the ground truth ambiguous, and an
    ambiguous item measures nothing. Rejected contexts are redrawn, so the
    case set is a deterministic function of (n, seed).
    """
    r = random.Random(seed)
    cases: list[TileCase] = []
    names = list(TILE_LIBRARY.keys())
    attempts = 0
    max_attempts = n * 200
    while len(cases) < n and attempts < max_attempts:
        attempts += 1
        c = _tile_context(r)
        payoff = {name: fn(c) for name, fn in TILE_PAYOFF_RULES.items()}
        ordered = sorted(payoff.items(), key=lambda kv: (-kv[1], kv[0]))
        best, best_val = ordered[0]
        # reject ties at the top
        if sum(1 for _, v in ordered if v == best_val) != 1:
            continue
        # K options: the best one plus K-1 distractors. Distractors are
        # drawn without replacement, deterministically, so every model sees
        # the same case in the same order.
        pool = [k for k in names if k != best]
        r.shuffle(pool)
        options = [best] + pool[: k_options - 1]
        r.shuffle(options)
        cases.append(TileCase(
            id=f"tile-{len(cases):04d}",
            context=c,
            truth=best,
            payoff=payoff,
            options=options,
            text=_tile_text(c),
        ))
    if len(cases) < n:
        raise RuntimeError(f"only {len(cases)}/{n} unambiguous tile cases "
                           f"after {attempts} attempts")
    return cases


def tile_questions(options: Sequence[str]) -> dict[str, Any]:
    return {
        "tile": {
            "type": "choice",
            "instructions": (
                "Which scripted tile should the rig play now? Pick the one "
                "whose payoff in this situation is highest: an open lane or "
                "slope you can take is worth +3, a visible threat in that "
                "direction is worth -4, the south basin is worth -1 if it is "
                "low and +2 if it is a clear drop, a worn rig is worth +2 for "
                "a dash and +3 for cover, a badly damaged rig is worth +5 to "
                "repair, a nearby loot crate is worth +4, a close beacon is "
                "worth -2 for cover, +5 for pushing it and -3 for looting near "
                "threats, and a nearby threat is worth -2 for cover, repair "
                "and push."),
            "criteria": {o: TILE_LIBRARY[o] for o in options},
        }
    }


def tile_questions_for(case: dict[str, Any]) -> dict[str, Any]:
    """The tile question for ONE case.

    The options are per-case (K of them, chosen when the case was built),
    so the question builder has to take the case and not a bare list.
    """
    return tile_questions(case["options"])


def score_tile(pred: str | None, case: TileCase) -> bool:
    return pred == case.truth


def tile_case_rows(cases: Sequence[TileCase]) -> list[dict[str, Any]]:
    return [{"id": c.id, "state": c.text, "options": c.options, "truth": c.truth,
             "payoff": c.payoff} for c in cases]


def cases_digest(cases: Sequence[Any]) -> str:
    """A hash of the whole case set: the pairing key for every comparison."""
    h = hashlib.sha256()
    for c in cases:
        if isinstance(c, TileCase):
            h.update(json.dumps([c.id, c.text, c.options, c.truth], sort_keys=True).encode())
        else:
            h.update(json.dumps(c, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]
