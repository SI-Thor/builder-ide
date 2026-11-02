"""Read the world ledger, and turn it into buckets the detector can read.

The world's log of record is one SQLite file with one table, ``audit``
(``core/night/ledger.py``'s ``SQLiteLedger`` writes it). This module
opens it **read-only** (``mode=ro``) and folds it into fixed windows, so
that the detector never has to know about SQLite and the calibration can
run off a committed table instead of the live ledger.

The world's ledger carries four event types
(``agent-world/reflex/agent_world_reflex/ledger.py``):

| event | what it holds |
|---|---|
| ``tile.played`` | who played what, the outcome, and the cost |
| ``judge.verdict`` | the decision model's answer, or its refusal |
| ``tile.authored`` | a skill entering the library |
| ``tile.retired`` | a skill leaving the eligible set |
| ``drift.yield`` | the world stood aside: who was told to wait, and why |

``drift.yield`` is the event that separates "could not act" from
"chose not to act". The world's admission rule refuses work when the
box is full and the drift pause refuses it when the detector says
hold; both are the world behaving correctly, and both write this
event. A gap between two plays that has a yield inside it is **not
stall evidence** — the agent demonstrably tried during it, and the
world said "not now". The folding censors those gaps and excuses the
idle of a window the agent spent standing aside; the stall signal
needs no change of its own.

Per-actor attribution is in the payload: ``context.bot`` for a play,
``judgments[].qid`` for a verdict. The ``actor`` column holds a JSON
blob of the *seat* that wrote the row (the reflex, the judge), not the
agent the row is about — so the payload is the attribution.
"""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "AgentBucket",
    "WorldBucket",
    "WorldSeries",
    "YIELD_TYPE",
    "build_series",
    "parse_at",
    "read_plays",
    "read_verdicts",
    "read_yields",
    "rule_violation_events",
    "series_from_dataset",
]

#: The event type the world would write for a rule violation. It does
#: not exist yet — the bots' humanity promises are enforced in the
#: bots' own code (``agent-world/bots/src/humanity.js``) and are never
#: written to the ledger. The detector reads the type so that the day
#: the world starts writing it, the hard path is already wired.
RULE_VIOLATION_TYPE = "drift.rule_violation"

#: The event type the world would write for a build that has left its
#: ratified scope. Same story: the world's ledger has no branch and no
#: constraint set, so nothing writes it yet.
BUILD_DRIFT_TYPE = "drift.build_drift"

#: The event the world writes when it stands aside: its admission rule
#: (``may_act`` — the box is full) or a drift pause (§3.5). One event
#: per admission decision, every bot it covers in ``payload.bots``.
#: Written by ``agent-world/reflex/agent_world_reflex/ledger.py``
#: since build #3; before that the ledger recorded "the agent did not
#: play" and not "the agent declined to play because the box was
#: busy", so the two were the same silence.
YIELD_TYPE = "drift.yield"


def parse_at(value: str) -> float:
    """An ISO-8601 timestamp from the ledger, as epoch seconds."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()


@dataclass
class AgentBucket:
    """One agent's activity inside one window.

    Not frozen: this is the aggregate the reader fills in, one window
    at a time.
    """

    agent: str
    plays: int = 0
    wins: int = 0
    losses: int = 0
    partials: int = 0
    #: The median gap between consecutive plays *inside* this window.
    gap_p50: float | None = None
    #: The 99th percentile of those gaps. One sample makes this the
    #: sample itself.
    gap_p99: float | None = None
    #: The largest of those gaps.
    gap_max: float | None = None
    #: Seconds from the agent's last play to the end of the window.
    #: ``None`` when the agent has never played. This is the stall.
    #: ``None`` as well when the agent spent the window standing
    #: aside (a yield inside it): an excused idle is not a stall, and
    #: the folding is where the excuse is applied.
    idle_seconds: float | None = None
    #: How many times the agent was told to wait in this window. The
    #: censoring uses the yield *points*, not this count; the count is
    #: carried so a reader of a folded dataset can see which windows
    #: were excused and why.
    yields: int = 0
    gpu_minutes: float = 0.0
    hosted_cents: float = 0.0


@dataclass
class WorldBucket:
    """One window of the world, with every agent's slice of it."""

    start: float
    end: float
    agents: dict[str, AgentBucket] = field(default_factory=dict)
    verdicts: int = 0
    refused: int = 0
    error_codes: dict[str, int] = field(default_factory=dict)
    #: Rule violations, by the agent they were about. The count is
    #: zero-tolerance: one occurrence escalates.
    rule_violations: dict[str, int] = field(default_factory=dict)

    def agent(self, name: str) -> AgentBucket:
        """One agent's bucket, empty if the agent did nothing in it."""
        return self.agents.get(name, AgentBucket(agent=name))


@dataclass
class WorldSeries:
    """The whole run, bucketed."""

    buckets: list[WorldBucket]
    agents: list[str]
    bucket_seconds: int
    #: The reference period's first bucket, and the end of the reference
    #: horizon. The baselines are computed over it.
    reference_start: float
    reference_end: float

    @property
    def start(self) -> float:
        return self.buckets[0].start if self.buckets else 0.0

    @property
    def end(self) -> float:
        return self.buckets[-1].end if self.buckets else 0.0

    @property
    def hours(self) -> float:
        return (self.end - self.start) / 3600.0 if self.buckets else 0.0

    def slice(self, start: float, end: float) -> list[WorldBucket]:
        """The buckets whose start falls in ``[start, end)``."""
        return [b for b in self.buckets if start <= b.start < end]


def _percentile(values: list[float], q: float) -> float | None:
    """A linear-interpolation percentile, or ``None`` for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _connect(path: Path | str) -> sqlite3.Connection:
    """Open the ledger read-only. The world is running; we do not lock it."""
    resolved = Path(path).expanduser()
    return sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)


def read_plays(path: Path | str) -> list[dict[str, object]]:
    """Every ``tile.played`` row, reduced to what the signals need."""
    connection = _connect(path)
    try:
        rows = connection.execute(
            "select at, payload from audit where type = 'tile.played' order by seq"
        )
        plays: list[dict[str, object]] = []
        for at, payload in rows:
            data = json.loads(payload)
            context = data.get("context") or {}
            outcome = data.get("outcome") or {}
            cost = data.get("cost") or {}
            agent = context.get("bot")
            if not agent:
                continue
            plays.append(
                {
                    "at": parse_at(at),
                    "agent": str(agent),
                    "outcome": outcome.get("result"),
                    "skill_id": data.get("skill_id"),
                    "gpu_minutes": float(cost.get("gpu_minutes") or 0.0),
                    "hosted_cents": float(cost.get("hosted_cents") or 0.0),
                }
            )
        return plays
    finally:
        connection.close()


def read_verdicts(path: Path | str) -> list[dict[str, object]]:
    """Every ``judge.verdict`` row, reduced to what the signals need."""
    connection = _connect(path)
    try:
        rows = connection.execute(
            "select at, payload from audit where type = 'judge.verdict' order by seq"
        )
        verdicts: list[dict[str, object]] = []
        for at, payload in rows:
            data = json.loads(payload)
            error = data.get("error") or {}
            cost = data.get("cost") or {}
            judgments = data.get("judgments") or []
            qids = [j.get("qid") for j in judgments if j.get("qid")]
            verdicts.append(
                {
                    "at": parse_at(at),
                    "agent": qids[0] if qids else None,
                    "refused": bool(data.get("refused")) or bool(error.get("code")),
                    "error_code": error.get("code"),
                    "gpu_minutes": float(cost.get("gpu_minutes") or 0.0),
                    "hosted_cents": float(cost.get("hosted_cents") or 0.0),
                    "latency_seconds": float(data.get("latency_seconds") or 0.0),
                }
            )
        return verdicts
    finally:
        connection.close()


def rule_violation_events(path: Path | str) -> list[dict[str, object]]:
    """Every rule-violation event in the ledger.

    There are none today. The query is kept, and tested, so that the
    hard path is exercised by the test suite and not only by a claim.
    """
    connection = _connect(path)
    try:
        rows = connection.execute(
            "select at, payload from audit where type = ? order by seq",
            (RULE_VIOLATION_TYPE,),
        )
        events: list[dict[str, object]] = []
        for at, payload in rows:
            data = json.loads(payload)
            events.append(
                {
                    "at": parse_at(at),
                    "agent": data.get("agent"),
                    "rule": data.get("rule"),
                    "detail": data.get("detail"),
                }
            )
        return events
    finally:
        connection.close()


def read_yields(path: Path | str) -> list[dict[str, object]]:
    """Every ``drift.yield`` point, one per bot it covers.

    An event whose payload names four bots is four points: the stall
    signal is per agent, so the attribution is per bot. The historical
    ledger has none of these events (the world began writing them in
    build #3); ``build_series`` accepts ``extra_yields`` so the
    committed snapshot can be re-folded with the yields reconstructed
    from the clients' own refusal records
    (``tools/drift/extract.py --yields-from-bots``).
    """
    connection = _connect(path)
    try:
        rows = connection.execute(
            "select at, payload from audit where type = ? order by seq",
            (YIELD_TYPE,),
        )
        points: list[dict[str, object]] = []
        for at, payload in rows:
            data = json.loads(payload)
            reason = data.get("reason")
            for bot in data.get("bots") or ():
                points.append(
                    {"at": parse_at(at), "agent": str(bot), "reason": reason}
                )
        return points
    finally:
        connection.close()


def _any_in(times: list[float], low: float, high: float) -> bool:
    """Is any yield point inside ``(low, high]``?

    ``(low, high]`` and not ``[low, high]``: a yield at the same
    instant as the play that ended the gap explains the gap before it,
    and a yield exactly at the window's start belongs to the window.
    """
    index = bisect_right(times, low)
    return index < len(times) and times[index] <= high


def build_series(
    path: Path | str,
    *,
    bucket_seconds: int = 300,
    baseline_horizon_seconds: int = 24 * 3600,
    extra_yields: list[dict[str, object]] | None = None,
    until: float | None = None,
) -> WorldSeries:
    """Fold the live ledger into buckets.

    ``extra_yields`` are yield points the ledger itself does not carry
    (the backfill from the clients' refusal records). They are folded
    exactly as the ledger's own ``drift.yield`` events are.

    ``until`` cuts the run at a wall-clock time (events strictly before
    it): the ledger is live, and a before/after comparison must be cut
    from the same span of world.

    The reference period is the first ``baseline_horizon_seconds`` of
    the run. The baselines are computed over it and **frozen**: a
    baseline that follows the drift stops being a baseline.
    """
    plays = read_plays(path)
    verdicts = read_verdicts(path)
    violations = rule_violation_events(path)
    yield_points = read_yields(path) + list(extra_yields or [])
    if until is not None:
        plays = [p for p in plays if float(p["at"]) < until]
        verdicts = [v for v in verdicts if float(v["at"]) < until]
        violations = [v for v in violations if float(v["at"]) < until]
        yield_points = [y for y in yield_points if float(y["at"]) < until]
    yields_by_agent: dict[str, list[float]] = {}
    for point in yield_points:
        agent = str(point.get("agent") or "")
        if agent:
            yields_by_agent.setdefault(agent, []).append(float(point["at"]))
    for times in yields_by_agent.values():
        times.sort()

    if not plays and not verdicts:
        return WorldSeries(
            buckets=[],
            agents=[],
            bucket_seconds=bucket_seconds,
            reference_start=0.0,
            reference_end=0.0,
        )

    times = [float(p["at"]) for p in plays] + [float(v["at"]) for v in verdicts]
    first = min(times)
    last = max(times)
    first_bucket = int(first // bucket_seconds) * bucket_seconds
    last_bucket = int(last // bucket_seconds) * bucket_seconds

    buckets: dict[int, WorldBucket] = {}
    for start in range(first_bucket, last_bucket + bucket_seconds, bucket_seconds):
        buckets[start] = WorldBucket(
            start=float(start), end=float(start + bucket_seconds)
        )
    ordered_buckets = [buckets[start] for start in sorted(buckets)]

    # -- plays ----------------------------------------------------------------
    # One pass per agent over the ordered play times and the ordered
    # buckets. Each play is charged to its bucket; each gap is charged
    # to the bucket of the play that *ended* it; a window where the
    # agent did nothing records how long it had been idle instead.
    by_agent: dict[str, list[dict[str, object]]] = {}
    for play in plays:
        by_agent.setdefault(str(play["agent"]), []).append(play)

    for agent, agent_plays in by_agent.items():
        agent_plays.sort(key=lambda p: p["at"])
        times_only = [float(p["at"]) for p in agent_plays]
        index = 0
        previous: float | None = None
        for bucket in ordered_buckets:
            gaps: list[float] = []
            plays_in = 0
            agent_yields = yields_by_agent.get(agent, [])
            while index < len(times_only) and times_only[index] < bucket.end:
                at = times_only[index]
                if at < bucket.start:
                    break
                plays_in += 1
                if previous is not None and not _any_in(
                    agent_yields, previous, at
                ):
                    # A gap with a yield inside it is the agent trying
                    # and the world saying "not now": not stall
                    # evidence, so it is not in the gaps at all.
                    gaps.append(at - previous)
                previous = at
                index += 1
            if plays_in == 0:
                continue
            entry = bucket.agents.get(agent)
            if entry is None:
                entry = AgentBucket(agent=agent)
                bucket.agents[agent] = entry
            entry.plays += plays_in
            entry.gap_p50 = _percentile(gaps, 0.50)
            entry.gap_p99 = _percentile(gaps, 0.99)
            entry.gap_max = max(gaps) if gaps else None
            entry.idle_seconds = 0.0

    # The outcome and the cost are a second pass over the same rows: they
    # are per play, and the first pass only had to know which bucket each
    # play fell into.
    for agent, agent_plays in by_agent.items():
        for play in agent_plays:
            at = float(play["at"])
            start = int(at // bucket_seconds) * bucket_seconds
            entry = buckets[start].agents[agent]
            outcome = play["outcome"]
            if outcome == "win":
                entry.wins += 1
            elif outcome == "lose":
                entry.losses += 1
            elif outcome == "partial":
                entry.partials += 1
            entry.gpu_minutes += float(play["gpu_minutes"] or 0.0)
            entry.hosted_cents += float(play["hosted_cents"] or 0.0)

    # Idle time: from the agent's last play to the end of the window, for
    # the windows where the agent did nothing at all.
    for agent, agent_plays in by_agent.items():
        times_only = [float(p["at"]) for p in agent_plays]
        index = 0
        last_before: float | None = None
        for bucket in ordered_buckets:
            while index < len(times_only) and times_only[index] < bucket.start:
                last_before = times_only[index]
                index += 1
            if index < len(times_only) and times_only[index] < bucket.end:
                continue  # the agent played in this window: idle is zero
            entry = bucket.agents.get(agent)
            if entry is None:
                entry = AgentBucket(agent=agent)
                bucket.agents[agent] = entry
            if _any_in(yields_by_agent.get(agent, []), bucket.start, bucket.end):
                # The agent spent this window standing aside: a yield
                # inside the window is the agent trying, so the idle is
                # excused rather than counted.
                entry.idle_seconds = None
            else:
                entry.idle_seconds = (
                    bucket.end - last_before if last_before is not None else None
                )

    # -- yields ----------------------------------------------------------------
    # The count is carried for the reader; the censoring above already
    # used the points. An agent that only ever yielded still gets its
    # (empty) buckets, so the series knows it exists — it has no
    # baseline and no signal, which is the honest answer for an agent
    # that has never played.
    for agent, times in yields_by_agent.items():
        for at in times:
            start = int(at // bucket_seconds) * bucket_seconds
            bucket = buckets.get(start)
            if bucket is None:
                continue
            entry = bucket.agents.get(agent)
            if entry is None:
                entry = AgentBucket(agent=agent)
                bucket.agents[agent] = entry
            entry.yields += 1

    # -- verdicts -------------------------------------------------------------
    for verdict in verdicts:
        at = float(verdict["at"])
        start = int(at // bucket_seconds) * bucket_seconds
        bucket = buckets[start]
        bucket.verdicts += 1
        if verdict["refused"]:
            bucket.refused += 1
            code = verdict["error_code"] or "refused"
            bucket.error_codes[code] = bucket.error_codes.get(code, 0) + 1
        # The spend of the world is the decision model's. A verdict is
        # charged to the agent it was about (``judgments[].qid``), which
        # is the only attribution the ledger carries for it.
        agent = verdict["agent"]
        if agent:
            entry = bucket.agents.get(str(agent))
            if entry is None:
                entry = AgentBucket(agent=str(agent))
                bucket.agents[str(agent)] = entry
            entry.gpu_minutes += float(verdict["gpu_minutes"] or 0.0)
            entry.hosted_cents += float(verdict["hosted_cents"] or 0.0)

    # -- rule violations ------------------------------------------------------
    for event in violations:
        at = float(event["at"])
        start = int(at // bucket_seconds) * bucket_seconds
        agent = str(event.get("agent") or "")
        counts = buckets[start].rule_violations
        counts[agent] = counts.get(agent, 0) + 1

    return WorldSeries(
        buckets=ordered_buckets,
        agents=sorted(set(by_agent) | set(yields_by_agent)),
        bucket_seconds=bucket_seconds,
        reference_start=first_bucket,
        reference_end=first_bucket + baseline_horizon_seconds,
    )


def series_from_dataset(document: dict) -> WorldSeries:
    """Rebuild a series from a dataset written by ``tools/drift/extract.py``.

    The detector runs off a committed table, not only off the live
    ledger: the numbers in the lab note have to be reproducible after
    the world has moved on.
    """
    meta = document.get("meta") or {}
    bucket_seconds = int(meta.get("bucket_seconds") or 300)
    buckets: list[WorldBucket] = []
    agents: set[str] = set()
    for row in document.get("buckets") or []:
        start = float(row["at"])
        bucket = WorldBucket(
            start=start,
            end=start + bucket_seconds,
            verdicts=int(row.get("verdicts") or 0),
            refused=int(row.get("refused") or 0),
            error_codes=dict(row.get("error_codes") or {}),
            rule_violations=dict(row.get("rule_violations") or {}),
        )
        for agent, entry in (row.get("agents") or {}).items():
            agents.add(agent)
            bucket.agents[agent] = AgentBucket(
                agent=agent,
                plays=int(entry.get("plays") or 0),
                wins=int(entry.get("wins") or 0),
                losses=int(entry.get("losses") or 0),
                partials=int(entry.get("partials") or 0),
                gap_p50=entry.get("gap_p50"),
                gap_p99=entry.get("gap_p99"),
                gap_max=entry.get("gap_max"),
                idle_seconds=entry.get("idle_seconds"),
                yields=int(entry.get("yields") or 0),
                gpu_minutes=float(entry.get("gpu_minutes") or 0.0),
                hosted_cents=float(entry.get("hosted_cents") or 0.0),
            )
        buckets.append(bucket)
    reference_start = float(meta.get("reference_start") or (buckets[0].start if buckets else 0.0))
    reference_end = float(
        meta.get("reference_end")
        or (reference_start + 24 * 3600 if buckets else 0.0)
    )
    return WorldSeries(
        buckets=buckets,
        agents=sorted(agents),
        bucket_seconds=bucket_seconds,
        reference_start=reference_start,
        reference_end=reference_end,
    )
