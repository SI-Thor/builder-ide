#!/usr/bin/env python3
"""The reward arithmetic: a partial play carries no reward.

The playtest of 2026-11-01 found the scout's survey skill with reward
**exactly 0.5 on all 18,066 plays**. The cause was here: ``PlayRecord.
reward`` scored a partial outcome (the skill ran, nothing could be
measured) as 0.5 — a fabricated constant, and a high one, which
out-ranked every skill with a real record and taught the bandit
nothing. These tests pin the fixed behaviour; each one marked OLD fails
against the pre-fix code.

Run on the Thor, from the repo root:

    runtime/venv/bin/python tests/test_reward.py

Needs builder-ide on the import path (the chooser's bandit comes from
``core/tiles``); ``reflex/agent_world_reflex/ledger.py`` puts it there
(``AW_BUILDER_IDE`` overrides ``~/src/builder-ide``). Takes under a
second.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "reflex"))

from agent_world_reflex.chooser import Chooser  # noqa: E402
from agent_world_reflex.models import Outcome, PlayRecord, Skill, SkillAuthor  # noqa: E402

AUTHOR = SkillAuthor(model="test", provider="seed")
CTX = {"role": "scout", "phase": "day"}


def play(skill_id: str, result: str, score: float | None = None) -> PlayRecord:
    return PlayRecord(
        id=f"play_{skill_id}_{result}_{len(results)}",
        at="2026-11-01T12:00:00Z",
        skill_id=skill_id,
        skill_version=1,
        context=dict(CTX),
        outcome=Outcome(result=result, score=score),  # type: ignore[arg-type]
        candidates=(skill_id,),
    )


results: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    results.append(f"{'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
    if not ok:
        results.append("FAILED: " + name)


def main() -> None:
    # -- the reward itself -----------------------------------------------------
    # OLD: a partial scored 0.5 — the fabricated constant of the playtest.
    check("partial carries no reward", play("s", "partial").reward, None)
    check("win carries 1.0", play("s", "win").reward, 1.0)
    check("lose carries 0.0", play("s", "lose").reward, 0.0)
    check("an explicit score stands", play("s", "win", score=0.3).reward, 0.3)

    # -- the bandit learns only from scored plays ------------------------------
    chooser = Chooser(seed=0)
    for _ in range(6):
        chooser.update(play("skill_survey", "partial"))
    bucket = chooser.stats()["buckets"].get("role=scout|phase=day", {})
    stats = bucket.get("skill_survey", {})
    # OLD: six plays, mean 0.5 — the survey looked learned while nothing
    # had been measured. (A bucket with only unscorable plays does not
    # even appear in the stats.)
    check("partials do not count as plays", int(stats.get("plays", 0)), 0)
    check("no bucket exists without scorable plays", bool(bucket), False)

    chooser.update(play("skill_walk", "win"))
    walk = chooser.stats()["buckets"]["role=scout|phase=day"]["skill_walk"]
    # OLD: the same play blended with five phantom 0.5s gave 4/7 ≈ 0.571.
    check("one win alone is the estimate", round(walk["estimate"], 3), 0.75)

    # -- a refit from the log lands in the same place --------------------------
    mixed = [play("skill_mixed", "win")] + [play("skill_mixed", "partial") for _ in range(5)]
    refit = Chooser(seed=0)
    refit.fit(mixed)
    mixed_stats = refit.stats()["buckets"]["role=scout|phase=day"]["skill_mixed"]
    # OLD: the refit saw six plays where only one could be scored.
    check("fit counts only scorable plays", int(mixed_stats["plays"]), 1)
    check("fit estimate from scorable only", round(mixed_stats["estimate"], 3), 0.75)

    # -- the choice says what it knows -----------------------------------------
    survey = Skill(
        id="skill_aaa_survey", family="scout.sight", role="scout",
        title="survey", body="look", author=AUTHOR,
    )
    walk_skill = Skill(
        id="skill_bbb_walk", family="scout.ground", role="scout",
        title="walk", body="walk", author=AUTHOR,
    )
    cold = Chooser(seed=0)
    for _ in range(5):
        cold.update(play("skill_aaa_survey", "partial"))
    choice = cold.choose(dict(CTX), [survey, walk_skill], judge={})
    # OLD: the survey held a 0.5 estimate from five phantom wins.
    check("an unscorable skill stays cold", cold._plays("role=scout|phase=day", "skill_aaa_survey"), 0)

    for i in range(20):
        cold.update(play("skill_bbb_walk", "win" if i < 14 else "lose"))
    guided = cold.choose(dict(CTX), [survey, walk_skill], judge={})
    # With half the walks winning, the scorable skill outranks the flat
    # prior the unscorable one keeps.
    check("scorable evidence guides the choice", guided.skill_id, "skill_bbb_walk")

    print("\n".join(results))
    if any(r.startswith("FAIL") for r in results):
        sys.exit(1)
    print(f"all {sum(1 for r in results if r.startswith('ok'))} checks pass")


if __name__ == "__main__":
    main()
