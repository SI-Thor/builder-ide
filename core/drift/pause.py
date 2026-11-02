"""The pause ladder wired to action (§3.5): what a pause does, and how
it is undone.

The detector names a pause (``detect.py`` promotes every alarm to
``soft``, ``tier`` or ``hard``); this module is the hand. Two doors,
and neither kills anything:

* **the pause file** — a small JSON file the world itself reads at its
  admission seam
  (``agent-world/reflex/agent_world_reflex/service.py::drift_pauses``).
  A ``soft`` entry holds one bot: the world refuses that bot's next
  decisions politely ("paused: …") and records a ``drift.yield`` for
  them. A ``tier`` or ``hard`` entry stands the whole world aside:
  every decision is refused politely, the services stay up, the skills
  stay served, and the yields are recorded. The world is never killed
  and never restarted — §3.5's "the agent is not killed; it stops
  committing".
* **the thor-admit presence file** — the queue of proposed work
  (``thor-admit presence``). A ``tier`` pause demotes the offending
  label's entries one tier (``live`` → ``preparation`` → ``practice``
  → ``study``); a ``hard`` pause also disables them, so no new
  proposals start. A reload (``thor-admit reload``, SIGHUP) makes the
  daemon re-read the file. Running work keeps its lease: a demotion
  changes what starts **next**, which is §3.5's "a write-side gate,
  not a kill".

Both doors are file edits, so both are cheap to undo (§3.5): an entry
lapses when its ``until`` passes — the world's reader ignores it and
this module's reader drops it — and deleting the entry resumes at once
(``clear``).

**Dry-run is the default.** ``apply`` computes the actions and returns
the log lines for them, prefixed ``dry-run:``, and writes nothing —
not the pause file, not the presence file, no reload. ``enforce=True``
writes both files (atomically) and reloads. The flag is deliberate
friction: an automated demotion of a seat's tier is a decision a human
should have watched a dry-run of first.

The mapping from a drift actor to a thor-admit label is a parameter,
because on this box the two namespaces are separate: the world's bots
are not thor-admit seats, and the world's own services run outside the
lease system (exp-drift-detector §2 says so). The default maps the
world actor to the ``agent-world`` label prefix — which matches no
presence entry today, and the tool says so rather than pretending a
demotion happened. The day the world's work runs under thor-admit
(``thor-admit presence add --tier live … agent-world``), the door opens
with no code change.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from .config import DriftConfig
from .detect import HARD, SOFT, TIER, Alarm, Detection

__all__ = [
    "TIERS",
    "WORLD",
    "PauseEntry",
    "PauseFile",
    "Plan",
    "plan_from_state",
    "apply",
    "clear",
    "demote",
    "edit_presence",
]

#: thor-admit's tiers, most urgent first. A tier pause demotes one step.
TIERS = ("live", "preparation", "practice", "study")

#: The actor name that stands for the whole world in the pause file.
WORLD = "world"

#: Which level outranks which, for one actor with several alarms.
_RANK = {SOFT: 0, TIER: 1, HARD: 2}


def demote(tier: str) -> str | None:
    """One step down thor-admit's ladder, or ``None`` at the bottom.

    ``study`` cannot be demoted — there is nothing below it — and the
    caller treats that as "nothing to do" rather than an error, because
    work already at the bottom has nothing to yield.
    """
    if tier not in TIERS:
        return None
    index = TIERS.index(tier)
    if index + 1 >= len(TIERS):
        return None
    return TIERS[index + 1]


@dataclass(frozen=True)
class PauseEntry:
    """One actor's pause, as the world reads it.

    The JSON shape is the world's contract
    (``service.py::drift_pauses``): ``level``, ``reason``, ``until``.
    An expired entry is not a pause — that is the undo.
    """

    actor: str
    level: str
    reason: str
    at: float
    until: float | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "level": self.level,
            "reason": self.reason,
            "at": self.at,
            "until": self.until,
        }

    @classmethod
    def from_json(cls, actor: str, doc: object) -> "PauseEntry | None":
        if not isinstance(doc, dict):
            return None
        level = doc.get("level")
        if level not in _RANK:
            return None
        try:
            at = float(doc.get("at") or 0.0)
            until = doc.get("until")
            until = float(until) if until is not None else None
        except (TypeError, ValueError):
            return None
        return cls(
            actor=actor,
            level=str(level),
            reason=str(doc.get("reason") or ""),
            at=at,
            until=until,
        )


class PauseFile:
    """The pause file: one JSON object, actor → entry.

    Reads are tolerant the same way the world's reader is: a missing,
    unreadable or malformed file is **no pause**, and an expired entry
    is dropped. Writes are atomic (a temp file beside it, renamed), so
    the world never reads a half-written pause.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def read(self, *, now: float | None = None) -> dict[str, PauseEntry]:
        """The entries in force, by actor. Expired entries are gone."""
        try:
            document = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(document, dict):
            return {}
        clock = now if now is not None else _now()
        in_force: dict[str, PauseEntry] = {}
        for actor, doc in document.items():
            entry = PauseEntry.from_json(str(actor), doc)
            if entry is None:
                continue
            if entry.until is not None and entry.until < clock:
                continue
            in_force[entry.actor] = entry
        return in_force

    def write(self, entries: Mapping[str, PauseEntry]) -> None:
        """Replace the file with exactly these entries."""
        self._atomic_write(
            {actor: entry.to_json() for actor, entry in sorted(entries.items())}
        )

    def merge(self, entries: Mapping[str, PauseEntry], *, now: float | None = None) -> None:
        """Add these entries, keeping every other entry still in force.

        A merge, not a replace: another operator's pause is not mine to
        drop, and a pause that lapses does so by expiry, not by being
        overwritten by the next unrelated decision.
        """
        combined = self.read(now=now)
        combined.update(entries)
        self.write(combined)

    def remove(self, actors: list[str], *, now: float | None = None) -> list[str]:
        """Take these actors' entries out. Returns who was resumed."""
        combined = self.read(now=now)
        resumed = [actor for actor in actors if actor in combined]
        for actor in resumed:
            del combined[actor]
        if resumed:
            self.write(combined)
        return resumed

    def _atomic_write(self, document: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.path.parent, prefix=self.path.name, delete=False
        )
        try:
            json.dump(document, handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.path)


@dataclass(frozen=True)
class Plan:
    """What the ladder decided, before anything is written."""

    #: actor → entry, for the pause file. Empty when nothing is in alarm.
    entries: dict[str, PauseEntry] = field(default_factory=dict)
    #: thor-admit label prefixes to demote one tier.
    demotions: list[str] = field(default_factory=list)
    #: thor-admit label prefixes to disable (no new proposals).
    disables: list[str] = field(default_factory=list)
    #: what a human reads, one line per action, in order.
    lines: list[str] = field(default_factory=list)


def plan_from_state(
    detection: Detection,
    window: float,
    *,
    config: DriftConfig | None = None,
    now: float | None = None,
    ttl_seconds: float = 1800.0,
    label_map: Mapping[str, str] | None = None,
) -> Plan:
    """The ladder's decision for one window of the detector's state.

    The input is the **state** (``detection.alarm_windows``), not the
    fires: an alarm that holds for two hours is a pause that holds for
    two hours, and a caller that runs every window renews the entry
    until the state clears. The levels are §3.5's rule, restated for
    the state:

    * any rule violation → the world at ``hard`` (the doors close);
    * the world's own signal in alarm, or several agents at once
      (``config.tier_agents``) → the world at ``tier`` (the work
      yields);
    * otherwise → one agent's ``soft`` pause (it waits on its own
      branch).

    ``ttl_seconds`` is the entry's lifetime: a pause lapses unless the
    detector renews it, which is what makes it cheap to undo.
    """
    config = config or DriftConfig()
    clock = now if now is not None else _now()
    labels = dict(label_map or {})
    pairs = sorted(detection.alarm_windows.get(window, set()))
    if not pairs:
        return Plan(lines=[_iso(window) + ": nothing in alarm; no action"])

    violation = any(signal == "violation" for signal, _ in pairs)
    agents = sorted({scope for _, scope in pairs if scope})
    world_signal = any(not scope for _, scope in pairs)
    signals_by_agent: dict[str, list[str]] = {}
    for signal, scope in pairs:
        if scope:
            signals_by_agent.setdefault(scope, []).append(signal)
    world_signals = [signal for signal, scope in pairs if not scope]

    entries: dict[str, PauseEntry] = {}
    demotions: list[str] = []
    disables: list[str] = []
    lines: list[str] = [_iso(window) + ":"]

    if violation:
        reason = "rule violation — the doors close (" + ", ".join(
            f"{agent}: {'+'.join(signals_by_agent.get(agent, ['violation']))}"
            for agent in agents
        ) + ")"
        entries[WORLD] = PauseEntry(
            WORLD, HARD, reason, clock, clock + ttl_seconds
        )
        lines.append(f"  hard: the world stops committing to main — {reason}")
    elif world_signal or len(agents) >= config.tier_agents:
        why = ", ".join(world_signals) or f"{len(agents)} agents at once"
        reason = f"drift in the world's own work ({why})"
        entries[WORLD] = PauseEntry(
            WORLD, TIER, reason, clock, clock + ttl_seconds
        )
        lines.append(
            f"  tier: the world's work yields — {reason}; "
            f"{', '.join(agents)} hold on their own branches"
        )
    else:
        for agent in agents:
            signals = "+".join(signals_by_agent.get(agent, ["drift"]))
            entries[agent] = PauseEntry(
                agent, SOFT, f"drift signal {signals}", clock, clock + ttl_seconds
            )
            lines.append(f"  soft: {agent} waits on its own branch ({signals})")

    # The thor-admit door: the actors the map names are demoted one tier
    # (tier pause) or demoted and disabled (hard). An actor with no
    # mapping has no door there, and the line says so.
    for actor, entry in sorted(entries.items()):
        label = labels.get(actor)
        if label is None:
            lines.append(f"  (no thor-admit label for {actor}; presence untouched)")
            continue
        if entry.level == SOFT:
            # A soft pause holds one agent's decisions; it does not touch
            # the box's admission, because one agent is not the world's
            # memory problem.
            continue
        demotions.append(label)
        line = f"  thor-admit: demote {label}* one tier"
        if entry.level == HARD:
            disables.append(label)
            line += " and stop its new proposals"
        lines.append(line)

    return Plan(entries=entries, demotions=demotions, disables=disables, lines=lines)


def edit_presence(
    document: dict, prefixes: list[str], *, disable: bool = False
) -> tuple[dict, list[str]]:
    """Demote (or disable) the presence entries whose label matches.

    A label matches a prefix exactly or as ``prefix.something`` — the
    seat convention (``agent-world.night`` under ``agent-world``). The
    document is returned as a **copy**, changed in place is never an
    option for a file another process reads; the caller writes it
    atomically. Every change is described, because a demotion that says
    nothing is a demotion nobody can audit.
    """
    changed: list[str] = []

    def matches(label: str) -> bool:
        return any(
            label == prefix or label.startswith(prefix + ".") for prefix in prefixes
        )

    edited = json.loads(json.dumps(document))
    for job in edited.get("jobs") or []:
        spec = job.get("spec") or {}
        label = str(spec.get("label") or "")
        if not matches(label):
            continue
        if disable:
            if spec.get("enabled", True):
                spec["enabled"] = False
                changed.append(f"{label}: proposals disabled")
        else:
            tier = str(spec.get("tier") or "")
            lower = demote(tier)
            if lower is not None:
                spec["tier"] = lower
                changed.append(f"{label}: {tier} → {lower}")
            elif tier in TIERS:
                changed.append(f"{label}: already at {tier}; nothing below")
    return edited, changed


def apply(
    plan: Plan,
    *,
    pause_file: PauseFile,
    presence_path: Path | str | None = None,
    reload: Callable[[], bool] | None = None,
    enforce: bool = False,
    now: float | None = None,
) -> list[str]:
    """Carry a plan out — or, by default, say exactly what it would do.

    In dry-run (the default) nothing is written, no reload is asked,
    and every line is prefixed ``dry-run:``. With ``enforce=True`` the
    pause file is merged (other actors' entries survive), the presence
    file is edited atomically when the plan demotes or disables, and
    the reload is asked for only when the presence file changed.

    ``reload`` returns whether the daemon answered; a daemon that does
    not answer is a warning on a line, not a failure of the pause: the
    pause file — the door the world reads — is already written.
    """
    prefix = "" if enforce else "dry-run: "
    lines = [prefix + line for line in plan.lines]

    if not plan.entries and not plan.demotions and not plan.disables:
        return lines

    if enforce:
        if plan.entries:
            pause_file.merge(plan.entries, now=now)
            untils = {
                _iso(entry.until) for entry in plan.entries.values() if entry.until
            }
            lines.append(
                "wrote "
                + str(pause_file.path)
                + " ("
                + ", ".join(
                    f"{e.actor}={e.level}"
                    for e in sorted(plan.entries.values(), key=lambda e: e.actor)
                )
                + "; lapses "
                + (", ".join(sorted(untils)) if untils else "never")
                + ")"
            )
    else:
        if plan.entries:
            lines.append(
                "would write "
                + str(pause_file.path)
                + " ("
                + ", ".join(f"{e.actor}={e.level}" for e in plan.entries.values())
                + ")"
            )

    prefixes = sorted(set(plan.demotions) | set(plan.disables))
    if not prefixes or presence_path is None:
        return lines
    path = Path(presence_path)
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        lines.append(
            f"{prefix}presence file unreadable ({exc}); "
            "the pause file is the door that matters"
        )
        return lines

    edited, changes = edit_presence(document, sorted(set(plan.demotions)))
    if plan.disables:
        edited, disabled = edit_presence(edited, sorted(set(plan.disables)), disable=True)
        changes += disabled
    if not changes:
        lines.append(
            f"{prefix}thor-admit: no presence entry matches "
            + ", ".join(prefixes)
            + " — nothing to demote (the world's work runs outside the "
            "lease system today; see exp-drift-detector §2)"
        )
        return lines

    for change in changes:
        lines.append(f"{prefix}thor-admit: {change}")
    if not enforce:
        lines.append(f"dry-run: would edit {path} and ask the daemon to reload")
        return lines

    _atomic_write_json(path, edited)
    lines.append(f"edited {path}")
    if reload is not None:
        if reload():
            lines.append("the daemon reloaded the presence queue")
        else:
            lines.append(
                "WARNING: the daemon did not answer the reload; "
                "it will pick the file up at its next restart or SIGHUP"
            )
    return lines


def clear(
    pause_file: PauseFile,
    actors: list[str],
    *,
    enforce: bool = False,
    now: float | None = None,
) -> list[str]:
    """Resume: take actors out of the pause file (§3.5's cheap undo)."""
    prefix = "" if enforce else "dry-run: "
    if enforce:
        resumed = pause_file.remove(actors, now=now)
        if resumed:
            return [f"{prefix}resumed {', '.join(sorted(resumed))}"]
        return [f"{prefix}nothing to resume: no entry for {', '.join(actors)}"]
    in_force = pause_file.read(now=now)
    would = [actor for actor in actors if actor in in_force]
    if would:
        return [f"dry-run: would resume {', '.join(sorted(would))}"]
    return [f"dry-run: nothing to resume: no entry for {', '.join(actors)}"]


def _atomic_write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=path.name, delete=False)
    try:
        json.dump(document, handle, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def _now() -> float:
    import time

    return time.time()


def _iso(stamp: float | None) -> str:
    from datetime import datetime, timezone

    if stamp is None:
        return "never"
    return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
