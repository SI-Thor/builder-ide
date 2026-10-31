"""The daytime world behind the spine's own doors.

Casey has not decided B3, so the daytime is off unless one setting says
otherwise — and the morning report still reads the log either way.
"""

from __future__ import annotations

from core.events import owner_actor


def test_the_daytime_is_on_by_default(settings):
    assert settings.daytime_enabled is True


def test_the_daytime_does_nothing_while_it_is_off(core, settings, fjellvik):
    settings.daytime_enabled = False
    from core.svc.daytime import DaytimeService

    daytime = DaytimeService(core, settings)
    assert daytime.enabled is False
    assert daytime.tick(fjellvik, "ver_0192") is None
    assert daytime.world() is None


def test_a_daytime_tick_lands_in_the_spines_one_ledger(core, settings, fjellvik):
    from core.svc.daytime import DaytimeService

    settings.daytime_enabled = True
    daytime = DaytimeService(core, settings)

    world = daytime.tick(fjellvik, "ver_0192")

    assert world is not None
    assert world.tick == 1
    # it is in the spine's log, not in a side file
    types = [e.type for e in core.store.events_since(0)]
    assert "day.world.opened" in types
    assert "day.tick" in types
    assert daytime.world() == world


def test_the_morning_report_says_what_the_world_did_while_nobody_watched(
    core, settings, fjellvik
):
    from core.svc.daytime import DaytimeService
    from core.svc.nights import NightsService
    from core.svc.report import ReportBuilder

    settings.daytime_enabled = True
    daytime = DaytimeService(core, settings)
    for _ in range(4):
        daytime.tick(fjellvik, "ver_0192")

    actor = owner_actor("casey")
    nights = NightsService(core, settings)
    night_id = nights.start(actor)["night"]["id"]
    nights.stop(night_id, actor, reason="rails spent")

    doc = ReportBuilder(core).build(night_id)["doc"]
    away = doc["while_you_were_away"]
    assert away["ticks"] == 4
    assert "4 daytime ticks" in away["line"]
    assert "harbor.crates was tidied" in away["line"]


def test_the_report_still_renders_with_the_daytime_off(core, settings):
    from core.svc.nights import NightsService
    from core.svc.report import ReportBuilder

    actor = owner_actor("casey")
    nights = NightsService(core, settings)
    night_id = nights.start(actor)["night"]["id"]
    nights.stop(night_id, actor, reason="rails spent")

    built = ReportBuilder(core).build(night_id)
    assert "while you were away" in built["text_bytes"].decode("utf-8")
    assert built["doc"]["while_you_were_away"]["ticks"] == 0


def test_the_daytime_stands_down_for_a_running_night(core, settings, fjellvik):
    from core.svc.daytime import DaytimeService
    from core.svc.nights import NightsService

    settings.daytime_enabled = True
    daytime = DaytimeService(core, settings)

    actor = owner_actor("casey")
    nights = NightsService(core, settings)
    night_id = nights.start(actor)["night"]["id"]

    # the night is working: the daytime yields
    assert daytime.tick(fjellvik, "ver_0192") is None
    yields = [e for e in core.store.events_since(0) if e.type == "day.yielded"]
    assert len(yields) == 1
    assert yields[0].payload["lane"] == "night"

    nights.stop(night_id, actor, reason="rails spent")
    # and with the night over, the room lives again
    assert daytime.tick(fjellvik, "ver_0192") is not None
