"""The pause ladder wired to action (§3.5): the doors, and the undo.

The claims under test:

* the ladder maps the detector's state to the three levels — one agent
  is a soft pause, the world's own signal or several agents is a tier
  pause, a rule violation is hard;
* **dry-run is the default** and it writes nothing — not the pause
  file, not the presence file, and it asks no reload;
* ``--enforce`` writes the pause file (a merge, not a replace), demotes
  the mapped labels one tier in thor-admit's presence file, disables
  their new proposals at the hard level, and reloads only when the
  presence file changed;
* a pause lapses on its own (``until``), and ``clear`` resumes at once.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.drift.config import DriftConfig
from core.drift.detect import HARD, SOFT, TIER, Detection
from core.drift.pause import (
    TIERS,
    PauseEntry,
    PauseFile,
    apply,
    clear,
    demote,
    edit_presence,
    plan_from_state,
)

NOW = 1_700_000_000.0
WINDOW = NOW - (NOW % 300)


def _detection(pairs: set[tuple[str, str]]) -> Detection:
    detection = Detection()
    detection.alarm_windows[WINDOW] = pairs
    return detection


def _presence(path: Path, tier: str = "live", label: str = "agent-world.night") -> Path:
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "spec": {
                            "id": 0,
                            "label": label,
                            "tier": tier,
                            "peak_bytes": 1,
                            "resumable": True,
                            "command": ["true"],
                            "enabled": True,
                        },
                        "state": "done",
                        "attempts": 1,
                    }
                ],
                "next_id": 1,
            }
        )
    )
    return path


# -- the file -----------------------------------------------------------------


def test_the_pause_file_round_trips_and_expires(tmp_path: Path) -> None:
    pause = PauseFile(tmp_path / "drift-pause.json")
    pause.write(
        {
            "world": PauseEntry("world", TIER, "refusal rate 1.0", NOW, NOW + 600),
            "Kite": PauseEntry("Kite", SOFT, "stall", NOW, None),
        }
    )
    in_force = pause.read(now=NOW)
    assert set(in_force) == {"world", "Kite"}
    # the world's contract: level, reason, until — nothing more needed
    doc = json.loads(pause.path.read_text())["world"]
    assert doc["level"] == TIER and "until" in doc

    later = pause.read(now=NOW + 601)
    assert "world" not in later, "the tier pause lapsed"
    assert "Kite" in later, "a pause with no until does not lapse"


def test_a_missing_or_malformed_file_is_no_pause(tmp_path: Path) -> None:
    pause = PauseFile(tmp_path / "absent.json")
    assert pause.read() == {}
    pause.path.write_text("{not json")
    assert pause.read() == {}
    pause.path.write_text(json.dumps({"world": {"level": "sideways"}}))
    assert pause.read() == {}


def test_merge_keeps_other_actors_entries(tmp_path: Path) -> None:
    pause = PauseFile(tmp_path / "drift-pause.json")
    pause.write({"Sprout": PauseEntry("Sprout", SOFT, "stall", NOW, NOW + 600)})
    pause.merge({"Kite": PauseEntry("Kite", SOFT, "spend", NOW, NOW + 600)}, now=NOW)
    assert set(pause.read(now=NOW)) == {"Kite", "Sprout"}


# -- the ladder ---------------------------------------------------------------


def test_one_agent_alone_is_a_soft_pause(tmp_path: Path) -> None:
    plan = plan_from_state(
        _detection({("stall", "Kite")}), WINDOW, now=NOW
    )
    assert set(plan.entries) == {"Kite"}
    assert plan.entries["Kite"].level == SOFT
    assert plan.entries["Kite"].until == NOW + 1800.0
    assert not plan.demotions and not plan.disables


def test_the_worlds_own_signal_is_a_tier_pause(tmp_path: Path) -> None:
    plan = plan_from_state(
        _detection({("errors", "")}), WINDOW, now=NOW, label_map={"world": "agent-world"}
    )
    assert set(plan.entries) == {"world"}
    assert plan.entries["world"].level == TIER
    assert plan.demotions == ["agent-world"]
    assert plan.disables == []


def test_two_agents_at_once_promote_to_the_tier(tmp_path: Path) -> None:
    plan = plan_from_state(
        _detection({("stall", "Kite"), ("stall", "Pebble")}), WINDOW, now=NOW
    )
    assert set(plan.entries) == {"world"}
    assert plan.entries["world"].level == TIER


def test_a_rule_violation_is_hard_and_stops_new_proposals() -> None:
    plan = plan_from_state(
        _detection({("violation", "Kite"), ("stall", "Kite")}),
        WINDOW,
        now=NOW,
        label_map={"world": "agent-world"},
    )
    assert plan.entries["world"].level == HARD
    assert plan.demotions == ["agent-world"]
    assert plan.disables == ["agent-world"]


def test_nothing_in_alarm_is_no_action() -> None:
    plan = plan_from_state(_detection(set()), WINDOW, now=NOW)
    assert plan.entries == {} and plan.lines


# -- dry-run writes nothing ----------------------------------------------------


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    detection = _detection({("errors", "")})
    plan = plan_from_state(
        detection, WINDOW, now=NOW, label_map={"world": "agent-world"}
    )
    pause_file = PauseFile(tmp_path / "drift-pause.json")
    presence = _presence(tmp_path / "presence.json")
    before = presence.read_text()
    calls: list[int] = []
    lines = apply(
        plan,
        pause_file=pause_file,
        presence_path=presence,
        reload=lambda: calls.append(1) or True,
        enforce=False,
    )
    assert not pause_file.path.exists(), "dry-run wrote a pause file"
    assert presence.read_text() == before, "dry-run edited the presence file"
    assert calls == [], "dry-run asked the daemon to reload"
    assert any(line.startswith("dry-run:") for line in lines)


# -- enforce writes both doors --------------------------------------------------


def test_enforce_writes_the_pause_file_and_demotes_the_tier(tmp_path: Path) -> None:
    detection = _detection({("errors", "")})
    plan = plan_from_state(
        detection, WINDOW, now=NOW, label_map={"world": "agent-world"}
    )
    pause_file = PauseFile(tmp_path / "drift-pause.json")
    presence = _presence(tmp_path / "presence.json", tier="live")
    calls: list[int] = []
    lines = apply(
        plan,
        pause_file=pause_file,
        presence_path=presence,
        reload=lambda: calls.append(1) or True,
        enforce=True,
    )
    in_force = pause_file.read(now=NOW)
    assert in_force["world"].level == TIER
    document = json.loads(presence.read_text())
    assert document["jobs"][0]["spec"]["tier"] == "preparation"
    assert document["jobs"][0]["spec"]["enabled"] is True
    assert calls == [1], "the daemon was asked to reload once"
    assert any("live → preparation" in line for line in lines)


def test_enforce_at_hard_stops_new_proposals(tmp_path: Path) -> None:
    plan = plan_from_state(
        _detection({("violation", "Kite")}),
        WINDOW,
        now=NOW,
        label_map={"world": "agent-world"},
    )
    pause_file = PauseFile(tmp_path / "drift-pause.json")
    presence = _presence(tmp_path / "presence.json", tier="preparation")
    apply(
        plan,
        pause_file=pause_file,
        presence_path=presence,
        reload=lambda: True,
        enforce=True,
    )
    document = json.loads(presence.read_text())
    spec = document["jobs"][0]["spec"]
    assert spec["tier"] == "practice"
    assert spec["enabled"] is False


def test_an_unmapped_actor_leaves_the_presence_file_alone(tmp_path: Path) -> None:
    plan = plan_from_state(_detection({("stall", "Kite")}), WINDOW, now=NOW)
    pause_file = PauseFile(tmp_path / "drift-pause.json")
    presence = _presence(tmp_path / "presence.json")
    before = presence.read_text()
    lines = apply(
        plan,
        pause_file=pause_file,
        presence_path=presence,
        enforce=True,
        reload=lambda: True,
    )
    assert presence.read_text() == before
    assert pause_file.read(now=NOW)["Kite"].level == SOFT


def test_a_label_that_matches_nothing_says_so(tmp_path: Path) -> None:
    plan = plan_from_state(
        _detection({("errors", "")}), WINDOW, now=NOW, label_map={"world": "absent"}
    )
    pause_file = PauseFile(tmp_path / "drift-pause.json")
    presence = _presence(tmp_path / "presence.json")
    lines = apply(
        plan,
        pause_file=pause_file,
        presence_path=presence,
        reload=lambda: True,
        enforce=True,
    )
    assert any("no presence entry matches" in line for line in lines)
    assert pause_file.read(now=NOW)["world"].level == TIER, "the pause file is written anyway"


# -- the undo ------------------------------------------------------------------


def test_clear_resumes_and_reports(tmp_path: Path) -> None:
    pause_file = PauseFile(tmp_path / "drift-pause.json")
    pause_file.write(
        {"world": PauseEntry("world", TIER, "refusal rate 1.0", NOW, NOW + 600)}
    )
    dry = clear(pause_file, ["world", "Kite"], enforce=False, now=NOW)
    assert any("would resume world" in line for line in dry)
    assert "world" in pause_file.read(now=NOW), "dry-run resumed nothing"
    lines = clear(pause_file, ["world", "Kite"], enforce=True, now=NOW)
    assert pause_file.read(now=NOW) == {}
    assert any("resumed world" in line for line in lines)


# -- the tier ladder ------------------------------------------------------------


def test_the_tier_ladder_steps_one_at_a_time() -> None:
    assert demote("live") == "preparation"
    assert demote("preparation") == "practice"
    assert demote("practice") == "study"
    assert demote("study") is None
    assert demote("nonsense") is None
    assert TIERS == ("live", "preparation", "practice", "study")


def test_the_label_match_is_a_prefix_not_a_substring() -> None:
    document = {
        "jobs": [
            {"spec": {"label": "agent-world.night", "tier": "live", "enabled": True}},
            {"spec": {"label": "agent-worldx", "tier": "live", "enabled": True}},
            {"spec": {"label": "other", "tier": "live", "enabled": True}},
        ]
    }
    edited, changes = edit_presence(document, ["agent-world"])
    assert changes == ["agent-world.night: live → preparation"]
    assert edited["jobs"][1]["spec"]["tier"] == "live"
    assert document["jobs"][0]["spec"]["tier"] == "live", "the input is never mutated"
