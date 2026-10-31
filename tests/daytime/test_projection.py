"""The world is a fold over the log — and the fold agrees with the arithmetic.

The ledger is the daytime world's only state. These tests fold the log back
and check it against the independent arithmetic derivation, which is what
makes "the same recipe and tick reconstruct the same world" a fact rather
than a promise.
"""

from __future__ import annotations


def _events(planned, actor):
    """The planned events as the log would hold them."""
    from core.records import AuditEvent

    return [
        AuditEvent(id=f"ev_{i:04d}", actor=actor, type=item.type, payload=item.payload)
        for i, item in enumerate(planned)
    ]


def test_folding_the_log_gives_the_same_world_as_the_recipe_and_the_tick(fjellvik, actor):
    from core.daytime.plan import plan
    from core.daytime.projection import DayProjection
    from core.daytime.world import world_at

    projection = DayProjection(_events(plan(fjellvik, "ver_0192", 12), actor))
    assert projection.world == world_at(fjellvik, "ver_0192", 12)


def test_the_clock_is_the_tick_count(fjellvik, actor):
    from core.daytime.plan import plan
    from core.daytime.projection import DayProjection

    projection = DayProjection(_events(plan(fjellvik, "ver_0192", 7), actor))
    assert projection.world is not None
    assert projection.world.tick == 7


def test_an_empty_log_has_no_world(fjellvik, actor):
    from core.daytime.projection import DayProjection

    assert DayProjection([]).world is None


def test_a_refused_event_changes_nothing(fjellvik, actor):
    from core.daytime.plan import plan
    from core.daytime.projection import DayProjection

    events = _events(plan(fjellvik, "ver_0192", 4), actor)
    grow = [
        e
        for e in events
        if e.type == "day.change" and e.payload["change"]["kind"] == "grow"
    ][-1]
    events = [e.model_copy(update={"refused": True}) if e is grow else e for e in events]

    projection = DayProjection(events)
    world = projection.world
    assert world is not None
    terrain = next(o for o in world.room.objects if o.path == "terrain.harbor")
    # the grow that was refused did not happen: the terrain grew once, not twice
    assert terrain.changes == {"grow": 1}


def test_the_projection_knows_when_the_night_lane_is_busy(actor):
    from core.daytime.projection import DayProjection
    from core.records import AuditEvent

    started = AuditEvent(
        id="ev_0001",
        actor=actor,
        type="night.started",
        subject={"entity_kind": "night", "entity_id": "night_1"},
    )
    assert DayProjection([started]).night_lane_busy is True

    stopped = AuditEvent(
        id="ev_0002",
        actor=actor,
        type="night.stopped",
        subject={"entity_kind": "night", "entity_id": "night_1"},
    )
    assert DayProjection([started, stopped]).night_lane_busy is False
