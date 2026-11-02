"""rewind_api.py — "rewind to here, keep these", as a preview that never deletes.

The screen's rewind panel picks a point on the timeline and a set of
actors/kinds to keep. This module turns that into one ``core.rewind``
selection (the language and the engine are the lane's, unchanged), runs
it, and renders **the fork it would make**: what would be replayed onto
the fork, what would be left behind and why, and the fork's name.

Nothing here writes anything. The world's ledger keeps every row it had;
a rewind is a branch, never a deletion (docs/design/vibecode-in-world.md
§2.4). The cherry-pick onto a canon fork (``core.rewind.cherry_pick``)
needs a recipe store to replay onto; this world does not commit to the
canon yet, so the preview stops at the selection and says so.
"""

from __future__ import annotations

from typing import Any

from worldview import _iso

ALL_KINDS = ["tile.played", "judge.verdict", "tile.authored", "tile.retired"]


def resolve_point(rows: list[dict], at_epoch: float | None = None,
                  seq: int | None = None) -> dict | None:
    """The ledger row a click on the timeline means (the latest row at/before it)."""
    if not rows:
        return None
    if seq is not None:
        candidates = [r for r in rows if r["seq"] <= seq]
        return candidates[-1] if candidates else rows[0]
    if at_epoch is not None:
        candidates = [r for r in rows if r["at"] <= at_epoch]
        return candidates[-1] if candidates else rows[0]
    return rows[-1]


def build_expression(point: dict, actors: list[str], kinds: list[str]) -> str:
    clauses = [f"seq > {point['seq']}"]
    if actors:
        clauses.append(f"actor in ({', '.join(actors)})")
    if kinds:
        clauses.append(f"kind in ({', '.join(kinds)})")
    return " and ".join(f"({c})" for c in clauses)


def preview(rows: list[dict], at_epoch: float | None = None, seq: int | None = None,
            actors: list[str] | None = None, kinds: list[str] | None = None) -> dict[str, Any]:
    from core.rewind import parse, select

    actors = actors or []
    kinds = [k for k in (kinds or []) if k in ALL_KINDS]
    point = resolve_point(rows, at_epoch, seq)
    if point is None:
        return {"error": "the ledger is empty"}
    expression = build_expression(point, actors, kinds)
    from ask import _as_rewind_ledger
    ledger = _as_rewind_ledger(rows)
    result = select(ledger, parse(expression))

    kept = set(result.kept_seqs)
    kept_rows = [r for r in rows if r["seq"] in kept and r["seq"] > point["seq"]]
    after_point = [r for r in rows if r["seq"] > point["seq"]]
    by_kind: dict[str, int] = {}
    by_actor: dict[str, int] = {}
    for r in kept_rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        by_actor[r["actor"]] = by_actor.get(r["actor"], 0) + 1

    reasons: dict[str, int] = {}
    for r in after_point:
        if r["seq"] in kept:
            continue
        why = result.reason_for(r["seq"]) if hasattr(result, "reason_for") else None
        key = why or "not selected"
        reasons[key] = reasons.get(key, 0) + 1

    fork = "rewind/{point}/keep-{actors}-{kinds}".format(
        point=_iso(point["at"]).replace(":", "").replace("-", ""),
        actors="-".join(actors) if actors else "all-actors",
        kinds="-".join(k.replace(".", "-") for k in kinds) if kinds else "all-kinds")

    return {
        "point": {"seq": point["seq"], "at": point["at_iso"], "kind": point["kind"],
                  "actor": point["actor"]},
        "expression": expression,
        "fork": fork,
        "rows_after_point": len(after_point),
        "kept": len(kept_rows),
        "kept_by_kind": by_kind,
        "kept_by_actor": by_actor,
        "dropped": len(after_point) - len(kept_rows),
        "drop_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:6]),
        "canon": ("this world does not commit to a canon yet, so there is nothing to "
                  "replay onto — when it does, core.rewind.cherry_pick replays the kept "
                  "events onto the fork and parks conflicts as questions"),
        "guarantee": ("nothing is deleted: the ledger keeps every row; this preview only "
                      "describes the branch it would make"),
    }
