"""The seed content: rules as data, and the verdicts they decide.

The claim under test (docs/lab/exp-precedent-store.md): the design
note's permission ladder, agent-world's no-grief rules and the seven
hard rules are rows in a table — every row carries its source — and the
validator gives the answer the design says it should, including
``ASK_HUMAN`` when nothing applies.
"""

from __future__ import annotations

import datetime

import pytest

from core.precedent import (
    HARD_RULES,
    NO_GRIEF_RULES,
    PERMISSION_LADDER_RULES,
    Rule,
    RuleEffect,
    Precedent,
    PrecedentStatus,
    PrecedentStore,
    Validator,
    VerdictType,
    seed_precedents,
    seed_rules,
    seed_store,
    seed_validator,
)


def test_the_three_sources_are_seeded() -> None:
    assert len(PERMISSION_LADDER_RULES) == 9
    assert len(NO_GRIEF_RULES) == 6
    assert len(HARD_RULES) == 7
    assert len(seed_rules()) == 9 + 6 + 7
    assert len(seed_precedents()) == 2


def test_every_row_says_where_it_came_from() -> None:
    for rule in seed_rules().values():
        assert rule.source, rule.key
        assert rule.text, rule.key


def test_no_two_rows_answer_the_same_key() -> None:
    keys = [rule.key for rule in PERMISSION_LADDER_RULES + NO_GRIEF_RULES + HARD_RULES]
    assert len(keys) == len(set(keys))


def test_hard_rows_never_allow_anything() -> None:
    for rule in HARD_RULES + NO_GRIEF_RULES:
        if rule.hard:
            assert rule.effect is RuleEffect.DENY, rule.key
    # ... and §3.1's seven are all hard.
    assert all(rule.hard for rule in HARD_RULES)
    # ... and so is every no-grief promise but the err-toward-protecting
    # permission, which is an allowance by nature.
    assert {r.key for r in NO_GRIEF_RULES if not r.hard} == {"nogrief.assume_theirs"}


def test_a_v1_string_rule_still_works() -> None:
    validator = Validator(PrecedentStore(), {"default.allow_upload": "uploads are allowed"})
    verdict = validator.validate("upload", ["default.allow_upload"])
    assert verdict.type is VerdictType.ALLOW
    assert verdict.rule_matches == ["default.allow_upload"]


SCENARIOS = {
    "p1 may not commit to main": (
        "Pebble commits to main",
        ["ladder.p1", "ladder.p1.commit_main", "recipe.commit.main"],
        VerdictType.DENY,
    ),
    "p1 may pre-flight on a fork": (
        "Pebble pre-flights on the fork",
        ["ladder.p1", "ladder.p1.preflight"],
        VerdictType.ALLOW,
    ),
    "p2 may commit inside its ratified scope": (
        "Timber commits inside the ratified scope",
        ["ladder.p2", "ladder.p2.supervised"],
        VerdictType.ALLOW,
    ),
    "p2 may not widen its own scope": (
        "Timber widens its own scope",
        ["ladder.p2", "ladder.p2.widen_own_scope"],
        VerdictType.DENY,
    ),
    "p3 may commit to main": (
        "Casey commits to main",
        ["ladder.p3", "ladder.p3.owner"],
        VerdictType.ALLOW,
    ),
    "no breaking a person's blocks": (
        "Kite breaks a human-placed block",
        ["nogrief.break_human_block", "world.break_block"],
        VerdictType.DENY,
    ),
    "no pits into a person's chest": (
        "Sprout empties a human chest",
        ["nogrief.take_from_human_chest"],
        VerdictType.DENY,
    ),
    "no attacking players": (
        "Pebble attacks TestHuman",
        ["nogrief.attack_player"],
        VerdictType.DENY,
    ),
    "the keep-out radius holds": (
        "Kite builds 3 blocks from a human build",
        ["nogrief.keep_out_radius", "world.place_block"],
        VerdictType.DENY,
    ),
    "a person's block is theirs": (
        "Treat an unknown block near a person as theirs",
        ["nogrief.assume_theirs"],
        VerdictType.ALLOW,
    ),
    "human free text is never stored": (
        "Log what TestHuman said",
        ["nogrief.privacy"],
        VerdictType.DENY,
    ),
    "a human's request becomes a proposal": (
        "Turn TestHuman's request into a board proposal",
        ["world.human_request", "board.propose"],
        VerdictType.ALLOW,
    ),
    "a kid apply asks the human": (
        "Apply Magnus's branch",
        ["recipe.apply"],
        VerdictType.ASK_HUMAN,
    ),
    "a fork pre-flight still meets the hard rule": (
        "Pre-flight straight onto main",
        ["ladder.p1.preflight", "hard.preflight_fork_only"],
        VerdictType.DENY,
    ),
    "the unleased rule holds over everything": (
        "Load the model outside a lease",
        ["hard.no_unleased_work", "ladder.p3.owner"],
        VerdictType.DENY,
    ),
    "nothing applies asks a human": (
        "Do something nobody has ruled on",
        ["unknown.action"],
        VerdictType.ASK_HUMAN,
    ),
}


@pytest.mark.parametrize("proposal,keys,want", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_the_seeds_decide_what_the_design_says(proposal, keys, want) -> None:
    verdict = seed_validator().validate(proposal, keys)
    assert verdict.type is want
    assert verdict.reason


def test_an_allow_rule_beats_a_deny_ask_only_through_an_override() -> None:
    # A soft deny rule stands unless the case overrides it.
    store = seed_store()
    store.append(
        Precedent(
            id="prec-pit-ok",
            gap_id="gap-pits",
            decision="allow",
            rationale="Casey asked for the quarry pit that one time",
            author="casey",
            created_at=datetime.datetime(2026, 11, 2, 8, 0),
            status=PrecedentStatus.ADJUDICATED,
            keys=["board.pit"],
        )
    )
    soften = Validator(
        store, {"board.pit": Rule(key="board.pit", text="no pits", effect=RuleEffect.DENY)}
    )
    # deny rule + allow precedent, no override: the rule wins
    assert soften.validate("dig a pit", ["board.pit"]).type is VerdictType.DENY

    overridden = Precedent(
        id="prec-pit-ok-2",
        gap_id="gap-pits",
        decision="allow",
        rationale="the same case, overriding the rule",
        author="casey",
        created_at=datetime.datetime(2026, 11, 2, 8, 1),
        status=PrecedentStatus.ADJUDICATED,
        rule_override="board.pit",
        keys=["board.pit"],
    )
    store.append(overridden)
    assert soften.validate("dig a pit", ["board.pit"]).type is VerdictType.ALLOW


def test_a_hard_rule_beats_a_precedent_that_overrides_it() -> None:
    store = seed_store()
    store.append(
        Precedent(
            id="prec-no-grief-override",
            gap_id="gap-grief",
            decision="allow",
            rationale="a misguided attempt to override a promise to a person",
            author="magnus",
            created_at=datetime.datetime(2026, 11, 2, 8, 2),
            status=PrecedentStatus.ADJUDICATED,
            rule_override="nogrief.break_human_block",
            keys=["nogrief.break_human_block"],
        )
    )
    verdict = Validator(store, seed_rules()).validate(
        "break a human block, Magnus says", ["nogrief.break_human_block"]
    )
    assert verdict.type is VerdictType.DENY
    assert "hard rule" in verdict.reason
    assert "nogrief.break_human_block" in verdict.rule_matches


def test_a_proposal_that_matches_nothing_asks_a_human() -> None:
    verdict = seed_validator().validate("something new", ["nobody.ruled.on.this"])
    assert verdict.type is VerdictType.ASK_HUMAN
    assert "No matching rule or precedent" in verdict.reason
    assert verdict.matched_precedents == []
