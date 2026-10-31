"""The calibration batch: seeded defects, nightly growth, and the FP/FN table.

Spec §1.9 (critic calibration; RV patch 15), §3.5 (the calibration night), and
plan item 12. Three facts shape it:

* **Until a critic model is chosen and measured, every automated verdict is a
  scripted check and carries `verdict@scripted` on its face** (X R4: the
  critic is "the largest unchosen dependency in the whole stack"; G §1). The
  scripted checks are analytic — watertightness, scale bounds, load floor —
  deterministic in the member's params (§2.3: scripted analytic computations,
  no physics engine).
* **The reference set is a measurement schedule, not a hope**: a fixed target
  of ~30 recipe fragments with known, planted defects (hollow meshes, wrong
  scale, broken constraints) plus clean members — without clean members there
  is nothing to false-positive on, and the band's other half is "reject no
  more than a set fraction of the clean ones".
* **It grows nightly, sized to the unused lane** (G §8-1's recommendation,
  adopted; §3.5: "the cheapest data the project will ever buy"), and runs as
  the queue's third item — placement is the night-runner seat's; the sizing
  arithmetic is here.

The FP/FN table is a **fold over `critic.verdict` events**, so it is
rebuildable from the ledger alone (§1.0), and its first published row is the
baseline the critic selection (plan item 18) later has to beat: if the
scripted checks cannot catch the seeded defects, verdicts stay `@scripted`
and critic selection is pulled forward (plan M2's named risk).

Ground truth, stated plainly: a planted defect of class K that check
`DEFECT_TARGETS[K]` does not fire on is a **false negative** — including a
defect planted deliberately below the check's threshold (`detectable=False`),
because a seeded defect is a seeded defect and the table must not hide a
miss. A check firing on a member carrying a *different* class of planted
defect is excluded from all four counts: the member is defective, so the
report is neither true of its own class nor false.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .models import (
    DEFECT_KINDS,
    DEFECT_TARGETS,
    Actor,
    AuditEvent,
    CalibrationRow,
    CheckResult,
    ConfusionCounts,
    ReferenceMember,
)
from .stubs import Rail, canonical_bytes, content_hash, short_hash

__all__ = [
    "TARGET_REFERENCE_SET",
    "MAX_MEMBERS_PER_NIGHT",
    "CALIBRATION_QUEUE_POSITION",
    "COST_PER_MEMBER",
    "SCALE_MIN",
    "SCALE_MAX",
    "LOAD_FLOOR",
    "FP_BOUND",
    "Band",
    "CalibrationTable",
    "seed_member",
    "seed_members",
    "plan_nightly_growth",
    "grow_reference_set",
    "ScriptedChecks",
    "CalibrationService",
]

#: §1.9 — "a fixed set of ~30 renders with seeded, known defects".
TARGET_REFERENCE_SET = 30

#: How many members one night's unused lane may add at most.
MAX_MEMBERS_PER_NIGHT = 8

#: §3.5 — "the queue's third item". Placement belongs to the night runner;
#: the position is stated here so it does not drift per seat.
CALIBRATION_QUEUE_POSITION = 3

#: [e] One member's cost: a scripted analytic check on the CPU lane — an
#: estimate until the first measured night replaces it (G §1: the morning
#: replaces `[e]` fields with measurements). GPU-minutes are zero by design.
COST_PER_MEMBER = Rail(gpu_minutes=0.0, hosted_cents=0, wall_minutes=0.5)

#: The scripted checks' thresholds (§1.1 `Constraint.kind`: `scale_bounds`,
#: `watertight`; §1.3's load-floor example). Analytic, from recipe params.
SCALE_MIN = 0.85
SCALE_MAX = 1.15
LOAD_FLOOR = 1.5

#: The band's false-positive half: "reject no more than a set fraction of the
#: clean ones" — settable, defaulting to one in ten.
FP_BOUND = 0.10


# -- the reference set --------------------------------------------------------


def _hash_stream(index: int, seed: int) -> bytes:
    import hashlib

    return hashlib.sha256(
        canonical_bytes({"index": index, "seed": seed})
    ).digest()


def seed_member(
    index: int,
    *,
    seed: int = 902,
    night: str | None = None,
    borderline_every: int | None = None,
) -> ReferenceMember:
    """Member `index` of the reference set — deterministic in `(index, seed)`.

    The rotation is one defect class per three members plus a clean one
    (hollow, wrong scale, broken constraint, clean), so the set always has
    clean members to false-positive on. `borderline_every` (when set) plants
    every Nth *defective* member just inside the check's thresholds — a
    severity-graded member whose miss is an honest FN, and the reason the
    first published row is a measurement rather than a tautology.
    """
    stream = _hash_stream(index, seed)
    slot = index % 4
    defect = None if slot == 3 else DEFECT_KINDS[slot]
    # Only the graded defects can sit below a threshold; a hollow shell is binary.
    borderline = (
        borderline_every is not None
        and defect in ("wrong_scale", "broken_constraint")
        and index % borderline_every == borderline_every - 1
    )

    # Clean members still jitter inside tolerance, so no two members share params.
    scale_ratio = round(0.95 + (stream[0] / 255) * 0.10, 3) if defect is None else 1.0
    load_factor = round(LOAD_FLOOR + 0.3 + (stream[1] / 255) * 0.6, 3) if defect is None else 2.0
    hollow = False

    if defect == "hollow_mesh":
        hollow = True  # binary: a hollow shell is never borderline
    elif defect == "wrong_scale":
        scale_ratio = 1.40 if not borderline else 1.12  # beyond / just inside [0.85, 1.15]
    elif defect == "broken_constraint":
        load_factor = 1.10 if not borderline else 1.60  # below / just above the floor

    return ReferenceMember(
        id=f"ref_{short_hash({'index': index, 'seed': seed})}",
        index=index,
        defect=defect,  # type: ignore[arg-type]
        detectable=not borderline,
        entry_path="props.harbor.crates",
        params={
            "hollow": hollow,
            "scale_ratio": scale_ratio,
            "load_factor": load_factor,
        },
        seed=seed,
        night=night,
    )


def seed_members(
    count: int,
    *,
    start_index: int = 0,
    seed: int = 902,
    night: str | None = None,
    borderline_every: int | None = None,
) -> tuple[ReferenceMember, ...]:
    return tuple(
        seed_member(i, seed=seed, night=night, borderline_every=borderline_every)
        for i in range(start_index, start_index + count)
    )


def plan_nightly_growth(
    *,
    existing: int,
    ceiling: Rail,
    spent: Rail,
    cost_per_member: Rail | None = None,
    target: int = TARGET_REFERENCE_SET,
    max_per_night: int = MAX_MEMBERS_PER_NIGHT,
) -> int:
    """How many members tonight's **unused lane** can add to the reference set.

    The lane's leftover rail is the budget (G §8-1: the batch is "sized to the
    night's unused lane" — the cheapest data the project will ever buy). The
    plan never exceeds the night's cap, the set's target, or what the leftover
    rail affords at `[e]` cost per member.
    """
    cost = cost_per_member or COST_PER_MEMBER
    remaining = ceiling.subtract(spent)
    affordable = max_per_night
    for axis in ("gpu_minutes", "hosted_cents", "wall_minutes"):
        unit = getattr(cost, axis)
        left = getattr(remaining, axis)
        if unit > 0:
            affordable = min(affordable, int(left // unit))
    return max(0, min(max_per_night, max(0, target - existing), affordable))


def grow_reference_set(
    existing: Sequence[ReferenceMember],
    *,
    night: str,
    ceiling: Rail,
    spent: Rail,
    seed: int = 902,
    borderline_every: int | None = None,
) -> tuple[ReferenceMember, ...]:
    """Tonight's new members: planned, generated, never duplicating an id."""
    n = plan_nightly_growth(existing=len(existing), ceiling=ceiling, spent=spent)
    known = {member.id for member in existing}
    fresh: list[ReferenceMember] = []
    index = len(existing)
    while len(fresh) < n:
        member = seed_member(index, seed=seed, night=night, borderline_every=borderline_every)
        if member.id not in known:
            fresh.append(member)
        index += 1
    return tuple(fresh)


# -- the scripted checks --------------------------------------------------------


class ScriptedChecks:
    """The three analytic checks, deterministic in the member's params.

    Watertightness runs the way the spec orders it (RV patch 7; X R10): as a
    mechanical check **before** any critic, so a hollow mesh dies here.
    """

    def run(self, member: ReferenceMember) -> list[CheckResult]:
        params = member.params
        results = [
            CheckResult(
                check="watertight",
                fired=bool(params.get("hollow")),
                detail="hollow shell: mesh is not watertight"
                if params.get("hollow")
                else "closed shell",
            ),
            CheckResult(
                check="scale_bounds",
                fired=not (SCALE_MIN <= float(params.get("scale_ratio", 1.0)) <= SCALE_MAX),
                detail=f"scale_ratio {params.get('scale_ratio')} outside [{SCALE_MIN}, {SCALE_MAX}]",
            ),
            CheckResult(
                check="constraint",
                fired=float(params.get("load_factor", 2.0)) < LOAD_FLOOR,
                detail=f"load_factor {params.get('load_factor')} below floor {LOAD_FLOOR}",
            ),
        ]
        return results


# -- running the batch ----------------------------------------------------------


_CRITIC_ACTOR = Actor(kind="critic", id="critic-scripted")
_SCHEDULER_ACTOR = Actor(kind="core", id="scheduler", via="calibration")


class CalibrationService:
    """Runs members through the scripted checks and audits every verdict.

    Per member: `job.enqueued` (CPU lane — no model, no prediction) →
    `critic.verdict` carrying the ground truth and the `verdict@scripted`
    label → `job.done`. The batch closes with one `job.done` whose artifact
    is the published FP/FN table, content-addressed (§1.0) — no card without
    an artifact.
    """

    def __init__(self, *, ledger: Any, clock: Any, checks: ScriptedChecks | None = None) -> None:
        self._ledger = ledger
        self._clock = clock
        self._checks = checks or ScriptedChecks()

    def run_batch(self, members: Sequence[ReferenceMember], *, night: str) -> list[AuditEvent]:
        """Score every member; one `critic.verdict` event each, `verdict@scripted`."""
        verdicts: list[AuditEvent] = []
        for member in members:
            at = self._clock.now()
            self._ledger.append(_job_event("job.enqueued", member, night, at))
            results = self._checks.run(member)
            verdicts.append(
                self._ledger.append(
                    AuditEvent(
                        seq=0,
                        id=f"aud_{short_hash({'type': 'critic.verdict', 'member': member.id, 'at': at})}",
                        at=at,
                        actor=_CRITIC_ACTOR,
                        type="critic.verdict",
                        subject={"entity_kind": "reference_member", "entity_id": member.id},
                        payload={
                            "night": night,
                            "member_id": member.id,
                            "planted": member.defect,
                            "detectable": member.detectable,
                            "checks": [
                                {"check": r.check, "fired": r.fired, "detail": r.detail}
                                for r in results
                                if r.fired
                            ],
                            "silent": [
                                r.check for r in results if not r.fired
                            ],
                            "degraded": "scripted",
                            "label": "verdict@scripted",
                        },
                    )
                )
            )
            at_done = self._clock.now()
            self._ledger.append(_job_event("job.done", member, night, at_done))
        return verdicts

    def publish(self, *, night: str) -> tuple[CalibrationTable, AuditEvent]:
        """Fold the night's verdicts into the FP/FN table and publish it.

        The table is a pure fold (§1.0); publishing writes one `job.done`
        whose artifact is the table's canonical JSON, content-addressed — the
        reference set's FP/FN table publishing its row (plan item 12).
        """
        table = calibration_table(self._ledger.events(), night=night)
        payload = table.as_dict()
        blob = canonical_bytes(payload)
        digest = content_hash(payload)
        at = self._clock.now()
        event = self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'job.done', 'batch': night, 'at': at})}",
                at=at,
                actor=_SCHEDULER_ACTOR,
                type="job.done",
                subject={"entity_kind": "job", "entity_id": f"calibration-{night}"},
                payload={
                    "job_id": f"calibration-{night}",
                    "night": night,
                    "batch": True,
                    "outputs": [f"artifacts/{digest[len('sha256:'):][:2]}/{digest[7:]}"],
                },
                artifact={
                    "sha256": digest,
                    "kind": "calibration-table",
                    "bytes": len(blob),
                },
            )
        )
        return table, event


def _job_event(kind: str, member: ReferenceMember, night: str, at: str) -> AuditEvent:
    job_id = f"{kind.split('.')[0]}_{short_hash({'member': member.id, 'night': night})}"
    return AuditEvent(
        seq=0,
        id=f"aud_{short_hash({'type': kind, 'member': member.id, 'night': night, 'at': at})}",
        at=at,
        actor=_SCHEDULER_ACTOR,
        type=kind,
        subject={"entity_kind": "job", "entity_id": job_id},
        payload={"job_id": job_id, "night": night, "member_id": member.id, "lane": "cpu"},
    )


# -- the FP/FN table ------------------------------------------------------------


@dataclass(frozen=True)
class Band:
    """The target band (§1.9): catch the seeded defects; reject no more than a
    set fraction of the clean ones. A critic enters service only inside it."""

    fp_bound: float = FP_BOUND

    def holds_for(self, counts: ConfusionCounts) -> bool:
        if counts.fn > 0:
            return False
        rate = counts.fp_rate
        return rate is None or rate <= self.fp_bound


@dataclass(frozen=True)
class CalibrationTable:
    """One night's row of the FP/FN table, per check and overall."""

    night: str
    rows: tuple[CalibrationRow, ...]
    totals: ConfusionCounts = field(default_factory=ConfusionCounts)
    band: Band = field(default_factory=Band)
    label: str = "verdict@scripted"

    @property
    def in_band(self) -> bool:
        return self.band.holds_for(self.totals)

    def as_dict(self) -> dict[str, Any]:
        return {
            "night": self.night,
            "label": self.label,
            "rows": [
                {
                    "check": row.check,
                    "tp": row.counts.tp,
                    "fp": row.counts.fp,
                    "fn": row.counts.fn,
                    "tn": row.counts.tn,
                    "fp_rate": row.counts.fp_rate,
                    "fn_rate": row.counts.fn_rate,
                    "label": row.label,
                }
                for row in self.rows
            ],
            "totals": {
                "tp": self.totals.tp,
                "fp": self.totals.fp,
                "fn": self.totals.fn,
                "tn": self.totals.tn,
            },
            "band": {"fp_bound": self.band.fp_bound},
            "in_band": self.in_band,
        }


def calibration_table(events: Iterable[Any], *, night: str) -> CalibrationTable:
    """Fold a night's `critic.verdict` events into the FP/FN table.

    Every input the fold needs rides in the verdict payloads — the planted
    defect (ground truth) and which checks fired — so the table rebuilds from
    the ledger alone after a kill -9.
    """
    counts: dict[str, ConfusionCounts] = {check: ConfusionCounts() for check in ("watertight", "scale_bounds", "constraint")}
    for event in events:
        if getattr(event, "type", None) != "critic.verdict":
            continue
        payload = event.payload or {}
        if payload.get("night") != night or payload.get("label") != "verdict@scripted":
            continue
        planted = payload.get("planted")
        fired = {entry["check"] for entry in payload.get("checks", ()) if entry.get("fired")}
        for check in counts:
            targeted = planted is not None and DEFECT_TARGETS.get(planted) == check
            if planted is None:
                # A clean member: any firing is a false positive.
                if check in fired:
                    counts[check] = _bump(counts[check], "fp")
                else:
                    counts[check] = _bump(counts[check], "tn")
            elif targeted:
                if check in fired:
                    counts[check] = _bump(counts[check], "tp")
                else:
                    counts[check] = _bump(counts[check], "fn")
            # a different check firing on a defective member: excluded (above)

    rows = tuple(
        CalibrationRow(night=night, check=check, counts=counts[check])  # type: ignore[arg-type]
        for check in ("watertight", "scale_bounds", "constraint")
    )
    totals = ConfusionCounts(
        tp=sum(r.counts.tp for r in rows),
        fp=sum(r.counts.fp for r in rows),
        fn=sum(r.counts.fn for r in rows),
        tn=sum(r.counts.tn for r in rows),
    )
    return CalibrationTable(night=night, rows=rows, totals=totals)


def _bump(counts: ConfusionCounts, key: str) -> ConfusionCounts:
    from dataclasses import replace

    return replace(counts, **{key: getattr(counts, key) + 1})
