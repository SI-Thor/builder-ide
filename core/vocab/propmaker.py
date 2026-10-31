"""The Prop-maker's loop, scripted.

D §23:04, one loop in full — the fish-crate bet:

    1. **Edit** (2 s): a typed vocabulary call, never code —
       `props.harbor.crates: {count: 12, style: weathered, from_library: 6}`.
    2. **Predict** (4 s): the prediction is **sealed** — hashed into the ledger
       *before* any render exists. It cannot be edited after the fact.
    3. **Preview** (38 s): renders through the model scheduler.
    4. **Critic** (9 s): the vision model reads every render.
    5. **Act** (1 s): 10 kept, 2 reverted to library crates.

There is no LLM in this loop yet — the slice allows a scripted loop (§6.1) —
but every rule that matters is the rule the LLM will have to obey:

* the edit goes **through the vocabulary**, so it is typed and bounded, and a
  call outside the schema is refused at the door (§1.5);
* the bets are **sealed before the render job exists**, hashed, and cannot be
  edited afterwards (§1.7, §5.1);
* the **confidence gate** decides whether the builder may act alone; with no
  priors it may bet, and it must ask (§1.7, G §1 20:44);
* the night's keep or revert is a **critic verdict plus an audited branch op**,
  never a taste write (§1.7, X C5). The taste bet stays open until the owner
  acts.

The Critic here is a script, and it says so on the card: `verdict@scripted`
(RV patch 15 — automated verdicts are scripted checks until a critic is chosen
and calibrated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .call import CallRefusal, VocabularyService
from .clock import Clock
from .gate import Gate, ObservationCounts
from .hashing import short_hash
from .models import Actor, AuditEvent, Prediction, RecipeEdit
from .ports import RenderRequest, SchedulerPort
from .predictions import PredictionService
from .projections import fold_predictions
from .registry import VocabularyRegistry

__all__ = [
    "CrateBet",
    "ScriptedFinding",
    "ScriptedCritic",
    "NightOutcome",
    "PropMaker",
    "CRATES_WORD",
    "TASTE_AXIS",
]

#: The word the Prop-maker works in this slice (spec §6.1).
CRATES_WORD = "props.harbor.crates"

#: The taste axis the crates word's notes sit on: Casey's crates sets are
#: kept when they are busy (4/4 kept) and dropped when they are sparse.
TASTE_AXIS = "too_busy"


@dataclass(frozen=True)
class CrateBet:
    """The bet the Prop-maker proposes on one night."""

    count: int = 12
    style: str = "weathered"
    from_library: int = 6
    seed: int = 42
    node: str = "crates_0001"

    def params(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "style": self.style,
            "from_library": self.from_library,
            "seed": self.seed,
        }


@dataclass(frozen=True)
class ScriptedFinding:
    """What the scripted Critic found in the renders."""

    texture_pass: int
    geometry_pass: int
    population: int
    hollow: tuple[int, ...]
    kept: int
    reverted: tuple[int, ...]

    @property
    def summary(self) -> str:
        """The line on the evidence card — `verdict@scripted` says so on its face."""
        hollow = ", ".join(str(index) for index in self.hollow) or "none"
        return (
            f"verdict@scripted · texture {self.texture_pass}/{self.population} · "
            f"geometry {self.geometry_pass}/{self.population} · hollow {hollow}"
        )


class ScriptedCritic:
    """The stand-in for the vision Critic.

    Deterministic in the seed: the same seed always produces the same hollow
    crates, which is what makes the night's bet replayable. The known seed
    reproduces the documented failure mode — crates hollow from below (R §2);
    any other seed gets a deterministic fallback.
    """

    def __init__(self, *, critic_id: str = "critic-local") -> None:
        self.critic_id = critic_id

    def hollow_crates(self, *, seed: int, count: int) -> tuple[int, ...]:
        known = {42: (7, 11)}
        if seed in known:
            return tuple(index for index in known[seed] if index < count)
        return tuple(index for index in range(count) if (seed + index) % 7 == 0)

    def read(self, bet: CrateBet) -> ScriptedFinding:
        hollow = self.hollow_crates(seed=bet.seed, count=bet.count)
        texture_pass = bet.count if bet.style == "weathered" else bet.count - 1
        geometry_pass = bet.count - len(hollow)
        kept = bet.count - len(hollow)
        return ScriptedFinding(
            texture_pass=texture_pass,
            geometry_pass=geometry_pass,
            population=bet.count,
            hollow=hollow,
            kept=kept,
            reverted=hollow,
        )


@dataclass
class NightOutcome:
    """Everything one night of the loop produced."""

    bet: CrateBet
    edit: RecipeEdit | None = None
    refusal: CallRefusal | None = None
    predictions: list[Prediction] = field(default_factory=list)
    refused_claims: list[str] = field(default_factory=list)
    job_id: str | None = None
    finding: ScriptedFinding | None = None
    verdict: str | None = None
    head: str | None = None
    parked_question: str | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def sealed(self) -> list[Prediction]:
        return list(self.predictions)


class PropMaker:
    """One character, one scripted loop, one room."""

    def __init__(
        self,
        *,
        registry: VocabularyRegistry,
        ledger: Any,
        recipes: Any,
        scheduler: SchedulerPort,
        clock: Clock,
        predictions: PredictionService,
        builder_id: str = "prop-maker",
        branch: str = "br_main",
        critic: ScriptedCritic | None = None,
    ) -> None:
        self._registry = registry
        self._ledger = ledger
        self._recipes = recipes
        self._scheduler = scheduler
        self._clock = clock
        self._predictions = predictions
        self._builder_id = builder_id
        self._branch = branch
        self._critic = critic or ScriptedCritic()
        self._vocab = VocabularyService(
            registry=registry, ledger=ledger, clock=clock, recipes=recipes
        )

    # -- the loop --------------------------------------------------------------

    def run(self, bet: CrateBet | None = None) -> NightOutcome:
        """One night: edit, predict and seal, preview, critic, act."""
        bet = bet or CrateBet()
        outcome = NightOutcome(bet=bet)

        edit = self.edit(bet)
        if isinstance(edit, CallRefusal):
            outcome.refusal = edit
            outcome.lines.append(edit.line)
            return outcome
        outcome.edit = edit

        outcome.predictions, outcome.refused_claims = self.predict(bet)
        if not outcome.predictions:
            # Nothing could be sealed: do not render a bet nobody made.
            outcome.lines.append("I have nothing to bet on yet.")
            return outcome

        job = self.preview(bet, outcome.predictions)
        outcome.job_id = job.id

        finding = self.critique(bet, job.id)
        outcome.finding = finding
        outcome.verdict = self.score_world_bet(outcome.predictions, finding)

        head, parked = self.act(bet, finding)
        outcome.head = head
        outcome.parked_question = parked
        return outcome

    # -- 1. edit ---------------------------------------------------------------

    def edit(self, bet: CrateBet) -> RecipeEdit | CallRefusal:
        """A typed vocabulary call, never code."""
        actor = Actor(kind="character", id=self._builder_id, via="word")
        result = self._vocab.call(
            word=CRATES_WORD,
            params=bet.params(),
            actor=actor,
            node=bet.node,
            base=self._recipes.head(self._branch),
        )
        if isinstance(result, CallRefusal):
            return result
        # The store validates the resulting document against the vocabulary
        # (§1.1) before the version is committed.
        self._recipes.apply_edit(result)
        return result

    # -- 2. predict and seal ----------------------------------------------------

    def predict(self, bet: CrateBet) -> tuple[list[Prediction], list[str]]:
        """Seal the bets, before any render exists.

        The gate is consulted here for the *taste* claim: a builder may not
        speak a taste claim below two prior observations on that reason code.
        Sealing a world bet is always allowed — the gate forbids pretending to
        a view, not betting.
        """
        sealed: list[Prediction] = []
        refused: list[str] = []
        gate = self._gate()
        branch_ref = f"{self._branch}@{self._recipes.head(self._branch)}"

        world = self._world_claim(bet, gate, branch_ref)
        if world is not None:
            sealed.append(world)

        taste = self._taste_claim(bet, gate, branch_ref)
        if taste is None:
            refused.append("taste_keep")
        else:
            sealed.append(taste)
        return sealed, refused

    def _world_claim(
        self, bet: CrateBet, gate: Gate, branch_ref: str
    ) -> Prediction | None:
        confidence = gate.world_confidence("material_read")
        render_spec = {"rung": 2, "resolution": "480p", "seed": bet.seed}
        return self._predictions.seal(
            builder=self._builder_id,
            claim=f"Weathered timber reads as weathered on all {bet.count} crates",
            claim_type="material_read",
            confidence=confidence.confidence,
            basis=confidence.basis,
            branch_ref=branch_ref,
            render_spec=render_spec,
        )

    def _taste_claim(
        self, bet: CrateBet, gate: Gate, branch_ref: str
    ) -> Prediction | None:
        decision = gate.may_speak_taste(TASTE_AXIS)
        if not decision.allowed:
            return None
        claimed = self._survival_claim(bet, gate)
        return self._predictions.seal(
            builder=self._builder_id,
            claim=f"Casey keeps {claimed} of {bet.count} crates",
            claim_type="taste_keep",
            confidence=decision.confidence,
            basis=decision.basis,
            branch_ref=branch_ref,
            render_spec={"rung": 2, "resolution": "480p", "seed": bet.seed},
            reason_code=TASTE_AXIS,
        )

    def _survival_claim(self, bet: CrateBet, gate: Gate) -> int:
        """How many of the crates the builder expects to survive.

        The builder's own record on `material_read` is the denominator for
        this: it expects to keep the fraction its record supports. With no
        record at all, the taste claim is refused by the gate long before this
        number is used.
        """
        ratio = self._survival_ratio(gate)
        return max(0, round(bet.count * ratio))

    def _survival_ratio(self, gate: Gate) -> float:
        counts = gate.counts
        sealed = counts.world_sealed.get("material_read", 0)
        if sealed:
            return counts.world_hit.get("material_read", 0) / sealed
        observed = counts.taste_observed.get(TASTE_AXIS, 0)
        if observed:
            return counts.taste_kept.get(TASTE_AXIS, 0) / observed
        return 0.5

    # -- 3. preview ------------------------------------------------------------

    def preview(self, bet: CrateBet, predictions: Sequence[Prediction]) -> Any:
        """Enqueue the render — after the seal, never before.

        The request carries the sealed prediction's id, and the ledger refuses
        a `job.enqueued` that references a bet which is not sealed (§5.1).
        """
        world = next(
            (p for p in predictions if p.claim_type == "material_read"), None
        )
        if world is None:  # pragma: no cover - a world bet is always sealable
            raise ValueError("no world bet to render")
        request = RenderRequest(
            branch_ref=f"{self._branch}@{self._recipes.head(self._branch)}",
            entry_paths=(self._registry.entry_path(CRATES_WORD),),
            rung=2,
            resolution="480p",
            seed=bet.seed,
            prediction_id=world.id,
        )
        return self._scheduler.enqueue_render(request)

    # -- 4. critic -------------------------------------------------------------

    def critique(self, bet: CrateBet, job_id: str) -> ScriptedFinding:
        """The Critic reads the render. It holds, fixes or keeps, and never praises."""
        finding = self._critic.read(bet)
        self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'critic.verdict', 'job': job_id})}",
                at=self._clock.now(),
                actor=Actor(kind="critic", id=self._critic.critic_id),
                type="critic.verdict",
                subject={"entity_kind": "job", "entity_id": job_id},
                payload={
                    "job_id": job_id,
                    "verdict": "fix" if finding.hollow else "keep",
                    "code": "hollow_from_below" if finding.hollow else "reads_as_asked",
                    "kept": finding.kept,
                    "population": finding.population,
                    "texture_pass": finding.texture_pass,
                    "geometry_pass": finding.geometry_pass,
                    "hollow": list(finding.hollow),
                    "degraded": True,
                    "label": "verdict@scripted",
                    "summary": finding.summary,
                },
            )
        )
        return finding

    def score_world_bet(
        self, predictions: Sequence[Prediction], finding: ScriptedFinding
    ) -> str | None:
        """Score the world bet with the Critic's finding — a verdict write."""
        world = next(
            (p for p in predictions if p.claim_type == "material_read"), None
        )
        if world is None:
            return None
        claimed = finding.population
        verdict = (
            "hit"
            if finding.texture_pass == claimed
            else "partial"
            if finding.texture_pass > claimed / 2
            else "miss"
        )
        self._predictions.score(
            world,
            verdict=verdict,
            actor=Actor(kind="critic", id=self._critic.critic_id),
        )
        return verdict

    # -- 5. act ----------------------------------------------------------------

    def act(
        self, bet: CrateBet, finding: ScriptedFinding
    ) -> tuple[str | None, str | None]:
        """Keep or revert — as an audited branch op, never as a taste write.

        If the gate does not let the builder act alone, the builder asks
        instead: the question is parked and the branch does not move.
        """
        gate = self._gate()
        decision = gate.may_act_alone(namespace="world", claim_type="material_read")
        if not decision.allowed:
            question = self._park_question(
                bet=bet,
                reason=decision.reason,
                basis=decision.basis,
            )
            return None, question

        # The hollow crates fall back to the library: the edit is amended and
        # the branch head moves to the amended version.
        amended = CrateBet(
            count=bet.count,
            style=bet.style,
            from_library=bet.from_library + len(finding.reverted),
            seed=bet.seed,
            node=bet.node,
        )
        actor = Actor(kind="character", id=self._builder_id, via="word")
        edit = self._vocab.call(
            word=CRATES_WORD,
            params=amended.params(),
            actor=actor,
            node=bet.node,
            base=self._recipes.head(self._branch),
        )
        if isinstance(edit, CallRefusal):  # pragma: no cover - defensive
            return None, self._park_question(bet=bet, reason="edit_refused", basis="")
        version = self._recipes.apply_edit(edit)
        self._recipes.move_head(self._branch, version.id)
        self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'branch.head.moved', 'branch': self._branch, 'head': version.id})}",
                at=self._clock.now(),
                actor=Actor(kind="character", id=self._builder_id, via="word"),
                type="branch.head.moved",
                subject={"entity_kind": "branch", "entity_id": self._branch},
                payload={
                    "branch": self._branch,
                    "head": version.id,
                    "kept": finding.kept,
                    "reverted": list(finding.reverted),
                    "label": "verdict@scripted",
                },
            )
        )
        return version.id, None

    def _park_question(
        self, *, bet: CrateBet, reason: str, basis: str
    ) -> str:
        """Park the one question the builder cannot answer alone."""
        question_id = f"q_{short_hash({'branch': self._branch, 'node': bet.node})}"
        self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'question.parked', 'q': question_id})}",
                at=self._clock.now(),
                actor=Actor(kind="character", id=self._builder_id, via="word"),
                type="question.parked",
                subject={"entity_kind": "question", "entity_id": question_id},
                payload={
                    "question_id": question_id,
                    "branch": self._branch,
                    "node": bet.node,
                    "reason": reason,
                    "basis": basis,
                    "question": (
                        f"{bet.count} weathered crates, {bet.from_library} from the library. "
                        "Keep them, or fewer?"
                    ),
                },
            )
        )
        return question_id

    # -- the owner's morning ----------------------------------------------------

    def owner_applies(
        self, *, verdict: str = "keep", finding: ScriptedFinding | None = None
    ) -> list[Prediction]:
        """The owner's keep/apply/reject — which is what scores a taste bet.

        The night's automated keep/revert never resolves a `taste_keep`
        prediction: only the owner does (§1.7, X C5).
        """
        scored: list[Prediction] = []
        for prediction in self._taste_predictions():
            if prediction.verdict is not None:
                continue
            actual = finding.kept if finding is not None else 0
            outcome = _score_taste_claim(prediction.claim, actual, self._population())
            scored.append(
                self._predictions.score(
                    prediction,
                    verdict=outcome,
                    actor=Actor(kind="owner", id="casey"),
                )
            )
        return scored

    # -- internals -------------------------------------------------------------

    def _gate(self) -> Gate:
        counts = ObservationCounts.from_events(
            self._ledger.events(),
            builder=self._builder_id,
            author="casey",
            subject_prefix=self._registry.entry_path(CRATES_WORD),
        )
        return Gate(counts)

    def _taste_predictions(self) -> list[Prediction]:
        predictions = fold_predictions(self._ledger.events())
        return [
            prediction
            for prediction in predictions.values()
            if prediction.claim_type == "taste_keep"
            and prediction.builder == self._builder_id
        ]

    def _population(self) -> int:
        events = self._ledger.events(types=["critic.verdict"])
        if not events:
            return 0
        return int(events[-1].payload.get("population", 0))


def _score_taste_claim(claim: str, actual_kept: int, population: int) -> str:
    """Score a taste claim of the form "Casey keeps 8 of 12 crates"."""
    claimed = _claimed_count(claim)
    if claimed is None or population <= 0:
        return "partial"
    difference = abs(claimed - actual_kept)
    if difference == 0:
        return "hit"
    tolerance = max(2, round(population / 4))
    return "partial" if difference <= tolerance else "miss"


def _claimed_count(claim: str) -> int | None:
    """The claimed number in "keeps 8 of 12 crates"."""
    words = claim.split()
    for index, word in enumerate(words):
        if word == "keeps" and index + 1 < len(words):
            try:
                return int(words[index + 1])
            except ValueError:  # pragma: no cover - the builder writes numbers
                return None
    return None
