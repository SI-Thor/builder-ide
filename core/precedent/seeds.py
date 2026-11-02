"""The seed content: the permission ladder, the no-grief rules, and the
hard rules — as data.

Three sources, each row carrying the document it came from in
``Rule.source``:

1. **The permission ladder** — ``docs/design/vibecode-in-world.md`` §1.4
   (three rungs: owner, supervised agent, unsupervised agent), with the
   ladder's own note that it "is not a proposal: it is already
   implemented" in ``core/auth.py`` token classes and the kid-actor rule
   in ``core/recipe/store.py``.
2. **agent-world's no-grief rules** — ``agent-world/BRIEF-playable.md``
   §2 ("never grief") and the no-grief ledger in
   ``agent-world/bots/src/humanity.js`` (the keep-out radii, the
   chest rule, the privacy rule).
3. **The hard rules** — the seven rules that "never bend", in
   ``docs/design/vibecode-in-world.md`` §3.1.

Plus two **seed precedents**: the two decided *cases* the same sources
record in prose. A rule is a standing constraint; a precedent is one
case that was adjudicated. The distinction is the store's whole reason
to exist, so both are seeded.

The key vocabulary these seeds speak — a proposal passes its own keys to
``Validator.validate`` and a rule or precedent answers when its key is
among them — is:

- ``ladder.p1`` / ``ladder.p2`` / ``ladder.p3`` and their verb forms
  (``ladder.p1.commit_main``, ``ladder.p1.preflight``, ...): who is
  acting and what they are trying to do;
- ``nogrief.*``: what a bot is doing to a person's things;
- ``hard.*``: which of §3.1's promises the proposal touches;
- ``recipe.apply``: a branch apply (the kid-actor case);
- ``world.human_request``: a person asking the crew for something.

A caller may use any other keys it likes; it just gets ``ASK_HUMAN`` for
them until a rule or a precedent answers.
"""

from __future__ import annotations

import datetime
from typing import Dict, List

from .rules import Rule, RuleEffect
from .store import Precedent, PrecedentStatus, PrecedentStore
from .validator import Validator

#: The permission ladder (docs/design/vibecode-in-world.md §1.4). The
#: rung rules say what a rung may do; the denying rows are hard because
#: the ladder "is not a proposal" — it is already enforced by
#: core/auth.py and core/recipe/store.py.
PERMISSION_LADDER_RULES: List[Rule] = [
    Rule(
        key="ladder.p3.owner",
        effect=RuleEffect.ALLOW,
        text=(
            "P3 (the owner, Casey, an owner-class token) may propose, "
            "pre-flight, commit to main, rewind, and widen its own scope."
        ),
        source="docs/design/vibecode-in-world.md §1.4, rung P3",
    ),
    Rule(
        key="ladder.p2.supervised",
        effect=RuleEffect.ALLOW,
        text=(
            "P2 (a supervised agent: panel/character token, live lease, "
            "watched) may propose, pre-flight, commit inside a ratified "
            "scope — a branch whose base is a named version and whose head "
            "is bounded by a constraint set — and rewind its own branch."
        ),
        source="docs/design/vibecode-in-world.md §1.4, rung P2",
    ),
    Rule(
        key="ladder.p2.widen_own_scope",
        effect=RuleEffect.DENY,
        hard=True,
        text="A supervised agent may not widen its own scope.",
        source="docs/design/vibecode-in-world.md §1.4, rung P2, last column",
    ),
    Rule(
        key="ladder.p2.rewind_other_branch",
        effect=RuleEffect.DENY,
        hard=True,
        text="A supervised agent may rewind only its own branch.",
        source="docs/design/vibecode-in-world.md §1.4, rung P2, rewind column",
    ),
    Rule(
        key="ladder.p2.commit_outside_scope",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "A supervised agent commits only inside the ratified scope it "
            "was given: a commit outside it is not its rung's to make."
        ),
        source="docs/design/vibecode-in-world.md §1.4, rung P2, commit column",
    ),
    Rule(
        key="ladder.p1.preflight",
        effect=RuleEffect.ALLOW,
        text=(
            "P1 (an unsupervised agent, running while the human is away) "
            "may propose and pre-flight on the Thor against a fork. This "
            "is what makes 'the human's check on return' a review and not "
            "an apology."
        ),
        source=(
            "docs/design/vibecode-in-world.md §1.4, rung P1; "
            "'What P1 gets, and why it is not a demotion'"
        ),
    ),
    Rule(
        key="ladder.p1.commit_main",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "An unsupervised agent's commit never lands: it becomes "
            "branch.proposed, and the human lands it on return."
        ),
        source=(
            "docs/design/vibecode-in-world.md §1.4, rung P1 (may commit: "
            "no); core/recipe/store.py apply_branch, the kid-actor rule"
        ),
    ),
    Rule(
        key="ladder.p1.rewind",
        effect=RuleEffect.DENY,
        hard=True,
        text="An unsupervised agent may not rewind.",
        source="docs/design/vibecode-in-world.md §1.4, rung P1, rewind column",
    ),
    Rule(
        key="ladder.p1.widen_own_scope",
        effect=RuleEffect.DENY,
        hard=True,
        text="An unsupervised agent may not widen its own scope.",
        source="docs/design/vibecode-in-world.md §1.4, rung P1, last column",
    ),
]

#: agent-world's no-grief rules (agent-world/BRIEF-playable.md §2; the
#: no-grief ledger in agent-world/bots/src/humanity.js). A promise to a
#: person is not a rate (core/drift/detect.py): every row is hard.
NO_GRIEF_RULES: List[Rule] = [
    Rule(
        key="nogrief.break_human_block",
        effect=RuleEffect.DENY,
        hard=True,
        text="Never break a block a person placed.",
        source=(
            "agent-world/bots/src/humanity.js, the no-grief ledger "
            "(canDig); agent-world/BRIEF-playable.md §2"
        ),
    ),
    Rule(
        key="nogrief.take_from_human_chest",
        effect=RuleEffect.DENY,
        hard=True,
        text="Never open or empty a person's chest.",
        source=(
            "agent-world/bots/src/humanity.js (isChest: 'never open, never "
            "empty it'); agent-world/BRIEF-playable.md §2"
        ),
    ),
    Rule(
        key="nogrief.attack_player",
        effect=RuleEffect.DENY,
        hard=True,
        text="Never attack a player.",
        source="agent-world/BRIEF-playable.md §2",
    ),
    Rule(
        key="nogrief.keep_out_radius",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "Stay out of the keep-out radius around a person's build "
            "unless invited: 4 blocks of digging, 8 of building. An invite "
            "opens the radius."
        ),
        source=(
            "agent-world/bots/src/humanity.js, DIG_KEEP_OUT=4 / "
            "BUILD_KEEP_OUT=8 and canDig/canPlace ('An invite opens the "
            "radius')"
        ),
    ),
    Rule(
        key="nogrief.assume_theirs",
        effect=RuleEffect.ALLOW,
        text=(
            "A block that appears while a person is close enough to have "
            "placed it is theirs from then on: the heuristic errs the only "
            "safe way, towards protecting."
        ),
        source="agent-world/bots/src/humanity.js, the no-grief ledger's comment",
    ),
    Rule(
        key="nogrief.privacy",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "What a person says is never written down: the log holds the "
            "command word and who answered it, never the free text."
        ),
        source=(
            "agent-world/bots/src/humanity.js ('the kids' privacy rule'); "
            "docs/design/vibecode-in-world.md §3.1, rule 7"
        ),
    ),
]

#: The validator's hard rules (docs/design/vibecode-in-world.md §3.1:
#: "these never bend"). Whichever row a proposal touches, the answer is
#: deny: the constraints are enforced deep in core/*, and the validator's
#: job is to refuse the proposal before it reaches them.
HARD_RULES: List[Rule] = [
    Rule(
        key="hard.preflight_fork_only",
        effect=RuleEffect.DENY,
        hard=True,
        text="Pre-flight runs on a fork, never on main.",
        source="docs/design/vibecode-in-world.md §3.1, rule 1",
    ),
    Rule(
        key="hard.deferred_constraint_not_pass",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "A deferred constraint is not a pass: the critic must close it "
            "before the commit lands."
        ),
        source="docs/design/vibecode-in-world.md §3.1, rule 2",
    ),
    Rule(
        key="hard.critic_band_holds",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "The critic's band holds or the verdict does not land: no "
            "false negatives on seeded defects, and no more than one in "
            "ten clean controls rejected."
        ),
        source="docs/design/vibecode-in-world.md §3.1, rule 3",
    ),
    Rule(
        key="hard.stale_transition_closed",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "A stale transition fails closed: compare-and-swap on "
            "from_state, and a mismatch rolls the append back."
        ),
        source="docs/design/vibecode-in-world.md §3.1, rule 4",
    ),
    Rule(
        key="hard.durable_on_disk_first",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "Nothing is claimed durable before it is on disk: WAL + "
            "synchronous=FULL, side effects only after commit."
        ),
        source="docs/design/vibecode-in-world.md §3.1, rule 5",
    ),
    Rule(
        key="hard.no_unleased_work",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "No unleased work: anything that takes the box's memory by "
            "surprise runs under a thor-admit lease or not at all."
        ),
        source=(
            "docs/design/vibecode-in-world.md §3.1, rule 6; agent-world "
            "BRIEF-playable.md, the HARD RULE of 2026-11-01 16:35"
        ),
    ),
    Rule(
        key="hard.no_human_pixels",
        effect=RuleEffect.DENY,
        hard=True,
        text=(
            "No human pixels, audio or transcripts are stored: the watcher "
            "keeps derived events only — what changed, and the decision."
        ),
        source="docs/design/vibecode-in-world.md §3.1, rule 7",
    ),
]


def seed_rules() -> Dict[str, Rule]:
    """Every seed rule, keyed for ``Validator(store, rules)``.

    Raises on a key collision: two sources answering the same key would
    make the verdict depend on dict order, and verdicts are byte-
    identical or they are nothing.
    """
    merged: Dict[str, Rule] = {}
    for rule in PERMISSION_LADDER_RULES + NO_GRIEF_RULES + HARD_RULES:
        if rule.key in merged:
            raise ValueError(f"two seed rules share the key {rule.key!r}")
        merged[rule.key] = rule
    return merged


def seed_precedents() -> List[Precedent]:
    """The two decided cases the seed sources record in prose.

    A fixed ``created_at`` (the date the ruling was written down) so the
    seed store hashes identically on every machine.
    """
    kid = Precedent(
        id="seed-kid-apply",
        gap_id="gap-ladder-p1-apply",
        decision="ask",
        rationale=(
            "A kid actor's apply is a proposal: a branch apply is a real "
            "edit, so Magnus's becomes branch.proposed until the owner "
            "confirms it. The ladder lets P1 pre-flight and propose; "
            "whether a proposed apply lands is the human's answer, not the "
            "agent's — so the verdict on the apply is ask_human."
        ),
        author="casey",
        created_at=datetime.datetime(2026, 11, 1, 16, 35),
        status=PrecedentStatus.ADJUDICATED,
        keys=["recipe.apply"],
        metadata={
            "source": (
                "core/recipe/store.py apply_branch, the kid-actor rule; "
                "docs/design/vibecode-in-world.md §1.4"
            )
        },
    )
    human_request = Precedent(
        id="seed-human-request",
        gap_id="gap-human-request",
        decision="allow",
        rationale=(
            "A person's request in chat becomes a project proposal on the "
            "community board — through the validator like any other "
            "proposal — and the crew adapts to it. The chat line itself is "
            "never recorded (the privacy rule)."
        ),
        author="casey",
        created_at=datetime.datetime(2026, 11, 1, 13, 40),
        status=PrecedentStatus.ADJUDICATED,
        keys=["world.human_request"],
        metadata={
            "source": (
                "agent-world/BRIEF.md, community-loop item 4; "
                "agent-world/bots/src/humanity.js, COMMANDS"
            )
        },
    )
    return [kid, human_request]


def seed_store() -> PrecedentStore:
    """A fresh store holding the seed precedents."""
    store = PrecedentStore()
    for precedent in seed_precedents():
        store.append(precedent)
    return store


def seed_validator() -> Validator:
    """The validator community-loop calls: seed store, seed rules."""
    return Validator(seed_store(), seed_rules())
