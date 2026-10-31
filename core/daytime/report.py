"""What the owner sees when he comes back.

One short line: while you were away the room kept living, and this is what
changed. It is written from the day's fold — the same numbers the ledger
holds — and never narrated by whoever happens to be awake to write it.

The line is the daytime seat's own; the spine's morning report asks it for
the line and puts it where the owner reads it.
"""

from __future__ import annotations

from typing import Any

__all__ = ["while_you_were_away", "CHANGE_VERBS"]

#: How a change reads in a sentence. A closed vocabulary, like everything
#: else that reaches the log or a panel.
CHANGE_VERBS: dict[str, str] = {
    "tidy": "was tidied",
    "grow": "grew",
}


def while_you_were_away(day: dict[str, Any]) -> dict[str, Any]:
    """The line, and the numbers behind it.

    ``day`` is the daytime projection's day: how many ticks it ran, what
    each change was, and how the light moved.
    """
    ticks = int(day.get("ticks") or 0)
    changes = list(day.get("changes") or [])
    light_from = day.get("light_from")
    light_to = day.get("light_to")

    if ticks == 0:
        return {
            "line": "the room stood still while you were away",
            "ticks": 0,
            "minutes": round(float(day.get("minutes") or 0.0), 6),
            "changes": changes,
            "light_from": light_from,
            "light_to": light_to,
        }

    parts = [f"{ticks} daytime tick{'s' if ticks != 1 else ''} while you were away"]
    if light_from and light_to:
        if light_from == light_to:
            parts.append(f"the light stayed {light_to}")
        else:
            parts.append(f"the light went {light_from} → {light_to}")
    for change in changes:
        kind = change.get("kind")
        if kind == "light":
            continue
        verb = CHANGE_VERBS.get(kind)
        if verb is None:
            continue
        parts.append(f"{change.get('target')} {verb} {change.get('count')}×")

    return {
        "line": " · ".join(parts),
        "ticks": ticks,
        "minutes": round(float(day.get("minutes") or 0.0), 6),
        "changes": changes,
        "light_from": light_from,
        "light_to": light_to,
    }
