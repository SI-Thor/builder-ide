"""The loop's tests — no network, no GPU, no model call.

Every model in these tests is scripted, and every world is a fake one:
the seat's claim is that the loop can be exercised before the world
lands, and this suite is that claim.

    ~/lm-wt/voyager-port/.venv/bin/python -m pytest tests/voyager -q
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.tiles.models import Outcome
from core.voyager.budget import ProbeBudget, RunBudget
from core.voyager.curriculum import Curriculum
from core.voyager.llm import ModelRouter
from core.voyager.models import Milestone, ModelReply, TokenUsage
from core.voyager.ports import CheckResult, ExecResult, ProgressSnapshot
from core.voyager.prompts import parse_json_block
from core.voyager.runner import LoopConfig, VoyagerLoop
from core.voyager.skills import SkillLibrary, fold_skills
from core.voyager.vocab import SkillVocabulary, scan_primitives

# ---------------------------------------------------------------------------
# the fakes
# ---------------------------------------------------------------------------


class FakeEnv:
    """A world that answers from a script."""

    name = "fake"
    language = "javascript"

    def __init__(self, milestones=(), inventory=None, truth=()) -> None:
        self._milestones = {m.key: m for m in milestones}
        self.inventory = dict(inventory or {})
        self._truth = set(truth)
        self.runs: list[str] = []
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def observe(self) -> dict[str, Any]:
        return {
            "world": self.name,
            "inventory": dict(self.inventory),
            "milestones": {k: self.goal_truth(k) for k in self._milestones},
        }

    def run_code(self, code: str, *, timeout_s: float) -> ExecResult:
        self.runs.append(code)
        if "throw" in code:
            return ExecResult(ok=False, error="the program threw", log=("boom",), seconds=0.1)
        return ExecResult(ok=True, error="", log=("did the thing",), seconds=0.2)

    def evaluate(self, code: str, *, timeout_s: float) -> CheckResult:
        return CheckResult(passed="true" in code, detail="true", seconds=0.01)

    def goal_truth(self, key: str) -> bool:
        return key in self._truth

    def progress(self) -> ProgressSnapshot:
        return ProgressSnapshot(
            unique_items=len(self.inventory),
            items=dict(self.inventory),
            milestones={k: self.goal_truth(k) for k in self._milestones},
        )

    def primitives(self) -> tuple[str, ...]:
        return ("mc.move_to",)

    def primitive_schemas(self) -> Mapping[str, Any]:
        return {"mc.move_to": {"x": {"type": "number", "minimum": -1, "maximum": 1}}}


class ScriptedModel:
    """A model that returns a fixed answer, and counts its own tokens."""

    def __init__(self, role: str, replies: list[str], model: str = "scripted") -> None:
        self.role = role
        self.model = model
        self.replies = list(replies)
        self.calls = 0
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system, user, *, max_tokens=2000, temperature=0.3):
        self.calls += 1
        self.prompts.append((system, user))
        text = self.replies.pop(0) if self.replies else "{}"
        usage = TokenUsage(
            role=self.role,
            model=self.model,
            prompt_tokens=100,
            completion_tokens=50,
            seconds=0.5,
        )
        return ModelReply(text=text, usage=usage)


def router(planner: list[str], coder: list[str], verifier: list[str]) -> ModelRouter:
    return ModelRouter(
        {
            "planner": ScriptedModel("planner", planner),
            "coder": ScriptedModel("coder", coder),
            "verifier": ScriptedModel("verifier", verifier),
        }
    )


def vocabulary() -> SkillVocabulary:
    from core.voyager.vocab import BODY_SCHEMA, BODY_WORD

    return SkillVocabulary(
        {
            "mc.move_to": {
                "x": {"type": "number", "minimum": -1000, "maximum": 1000},
                "y": {"type": "number", "minimum": -100, "maximum": 100},
            },
            BODY_WORD: BODY_SCHEMA,
        }
    )


PLAN = json.dumps(
    {
        "options": [
            {"id": "a", "name": "walk", "description": "walk to the tree",
             "facts": ["a tree is 12 blocks away"], "effect": "the log is in hand"}
        ],
        "chosen": "a",
        "why": "it is the first step",
    }
)

CODE = json.dumps(
    {
        "title": "walk to the tree",
        "description": "walks to the tree and cuts it",
        "code": "console.log('cutting'); return await mc.move_to(1, 2, 3)",
        "verify_code": "return true",
        "primitives": ["mc.move_to"],
    }
)


# ---------------------------------------------------------------------------
# the curriculum
# ---------------------------------------------------------------------------


def test_the_curriculum_respects_the_tech_tree():
    milestones = [
        Milestone(key="wood", title="wood", description="", items=("wood",)),
        Milestone(key="stone", title="stone", description="", needs=("wood",), items=("stone",)),
        Milestone(key="iron", title="iron", description="", needs=("stone",), items=("iron",)),
    ]
    curriculum = Curriculum(milestones, seed=1)
    assert [m.key for m in curriculum.eligible()] == ["wood"]
    curriculum.record_achieved("wood")
    assert [m.key for m in curriculum.eligible()] == ["stone"]
    curriculum.record_achieved("stone")
    assert [m.key for m in curriculum.eligible()] == ["iron"]
    curriculum.record_achieved("iron")
    assert curriculum.eligible() == ()
    assert curriculum.pick() is None


def test_the_curriculum_is_novelty_biased():
    milestones = [
        Milestone(key="a", title="a", description=""),
        Milestone(key="b", title="b", description=""),
    ]
    curriculum = Curriculum(milestones, seed=3)
    curriculum.record_attempt("a")
    curriculum.record_attempt("a")
    # A has been tried twice, B never: B must outscore A.
    assert curriculum.score("b") > curriculum.score("a")


def test_the_curriculum_repeats_itself():
    milestones = [Milestone(key="a", title="a", description=""),
                   Milestone(key="b", title="b", description="")]
    first = [Curriculum(milestones, seed=11).pick().key for _ in range(5)]
    second = [Curriculum(milestones, seed=11).pick().key for _ in range(5)]
    assert first == second


def test_the_curriculum_rotates_away_from_the_last():
    milestones = [Milestone(key="a", title="a", description=""),
                   Milestone(key="b", title="b", description="")]
    curriculum = Curriculum(milestones, seed=5)
    curriculum.record_attempt("a")
    assert curriculum.score("a") < curriculum.score("b")


# ---------------------------------------------------------------------------
# the vocabulary — the static door
# ---------------------------------------------------------------------------


def test_the_scan_reads_the_calls_out_of_the_body():
    code = "await mc.move_to(1,2,3); await mc.craft('stick'); other.fn(4)"
    assert scan_primitives(code) == ("mc.craft", "mc.move_to")


def test_an_unknown_primitive_is_refused():
    from core.tiles.models import TileRefusal

    vocabulary_ = vocabulary()
    from core.voyager.skills import SkillLibrary

    library = SkillLibrary(registry=vocabulary_, bodies_dir="/tmp/voyager-test-bodies")
    from core.voyager.models import SkillProposal

    proposal = SkillProposal(
        title="bad", description="", family="fake.wood",
        code="return await mc.teleport(1,2,3)",
    )
    record = library.submit(proposal, author_model="scripted", disposition="admitted")
    assert record.disposition == "rejected"
    assert "primitive_unknown" in record.reason


def test_the_schema_refuses_a_bad_parameter():
    vocabulary_ = vocabulary()
    with __import__("pytest").raises(Exception):
        vocabulary_.validate_params("mc.move_to", {"x": "not a number"})
    with __import__("pytest").raises(Exception):
        vocabulary_.validate_params("mc.move_to", {"z": 1})  # unknown property
    vocabulary_.validate_params("mc.move_to", {"x": 1, "y": 2})


# ---------------------------------------------------------------------------
# the skill library and the ledger
# ---------------------------------------------------------------------------


def test_one_event_per_skill(tmp_path):
    from core.night.ledger import InMemoryLedger

    ledger = InMemoryLedger()
    library = SkillLibrary(registry=vocabulary(), ledger=ledger, bodies_dir=tmp_path)
    from core.voyager.models import SkillProposal

    proposal = SkillProposal(
        title="walk", description="", family="fake.wood",
        code="return await mc.move_to(1,2,3)",
    )
    record = library.submit(proposal, author_model="scripted", disposition="admitted")
    assert record.disposition == "admitted"
    authored = [e for e in ledger.events() if e.type == "tile.authored"]
    assert len(authored) == 1
    assert authored[0].payload["tile_id"] == record.id

    # A rejected skill: one event, and it is a retirement of a tile the
    # log never authored.
    bad = SkillProposal(
        title="stumble", description="", family="fake.wood",
        code="return await mc.move_to(4,5,6)",
    )
    rejected = library.submit(bad, author_model="scripted", disposition="rejected",
                              reason="verifier:denied")
    assert rejected.disposition == "rejected"
    retired = [e for e in ledger.events() if e.type == "tile.retired"]
    assert len(retired) == 1
    assert retired[0].payload["disposition"] == "rejected"
    assert retired[0].payload["reason"].startswith("rejected:")


def test_a_new_skill_supersedes_the_old_one(tmp_path):
    from core.night.ledger import InMemoryLedger

    ledger = InMemoryLedger()
    library = SkillLibrary(registry=vocabulary(), ledger=ledger, bodies_dir=tmp_path)
    from core.voyager.models import SkillProposal

    first = library.submit(
        SkillProposal(title="a", description="", family="fake.wood",
                      code="return await mc.move_to(1,2,3)"),
        author_model="scripted",
    )
    second = library.submit(
        SkillProposal(title="b", description="", family="fake.wood",
                      code="return await mc.move_to(7,8,9)"),
        author_model="scripted",
    )
    assert first.version == 1
    assert second.version == 2
    retired = [e for e in ledger.events() if e.type == "tile.retired"]
    assert len(retired) == 1
    assert retired[0].payload["reason"] == f"superseded:{second.id}"
    counts = library.counts()
    # One disposition per skill: the first was admitted and later
    # superseded, the second is active.
    assert counts["admitted"] == 2
    assert counts["superseded"] == 1
    assert counts["active"] == 1
    assert counts["rejected"] == 0


def test_the_library_folds_back_out_of_the_log(tmp_path):
    from core.night.ledger import InMemoryLedger

    ledger = InMemoryLedger()
    library = SkillLibrary(registry=vocabulary(), ledger=ledger, bodies_dir=tmp_path)
    from core.voyager.models import SkillProposal

    library.submit(
        SkillProposal(title="a", description="", family="fake.wood",
                      code="return await mc.move_to(1,2,3)"),
        author_model="scripted",
    )
    folded = fold_skills(ledger.events(), registry=vocabulary())
    assert len(folded.tiles()) == 1
    assert folded.tiles()[0].title == "a"


def test_a_skill_is_content_addressed(tmp_path):
    from core.night.ledger import InMemoryLedger

    ledger = InMemoryLedger()
    library = SkillLibrary(registry=vocabulary(), ledger=ledger, bodies_dir=tmp_path)
    from core.voyager.models import SkillProposal

    proposal = SkillProposal(title="a", description="", family="fake.wood",
                             code="return await mc.move_to(1,2,3)")
    first = library.submit(proposal, author_model="scripted")
    second = library.submit(proposal, author_model="scripted")
    assert first.id == second.id
    assert len([e for e in ledger.events() if e.type == "tile.authored"]) == 1


# ---------------------------------------------------------------------------
# the budgets
# ---------------------------------------------------------------------------


def test_the_probe_budget_closes_after_the_first_execution():
    budget = ProbeBudget(max_probes_before_first_execution=2)
    assert budget.allow_probe() is True
    assert budget.allow_probe() is True
    assert budget.allow_probe() is False
    budget.note_execution()
    assert budget.allow_probe() is False
    budget.reopen()
    assert budget.allow_probe() is True


def test_the_run_budget_stops_the_run():
    budget = RunBudget(max_steps=2, max_wall_seconds=1000, max_tokens=10**9)
    clock = [0.0]
    budget.start(lambda: clock[0])
    budget.note_step()
    assert budget.exhausted() is False
    budget.note_step()
    assert budget.exhausted() is True
    assert budget.why() == "steps"


def test_the_run_budget_stops_on_the_clock():
    clock = [0.0]
    budget = RunBudget(max_steps=100, max_wall_seconds=10, max_tokens=10**9)
    budget.start(lambda: clock[0])
    clock[0] = 11.0
    assert budget.exhausted() is True
    assert budget.why() == "wall_clock"


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------


def test_the_loop_admits_a_skill_that_works(tmp_path):
    from core.night.ledger import InMemoryLedger

    milestones = [Milestone(key="wood", title="get wood", description="cut a tree",
                             items=("wood",))]
    env = FakeEnv(milestones=milestones, truth={"wood"})
    ledger = InMemoryLedger()
    library = SkillLibrary(registry=vocabulary(), ledger=ledger, bodies_dir=tmp_path)
    models = router([PLAN], [CODE], [
        json.dumps({"verdict": "CONFIRMED", "reason": "the log is in hand",
                    "evidence": "inventory"})
    ])
    curriculum = Curriculum(milestones, seed=1)
    loop = VoyagerLoop(
        env=env, models=models, curriculum=curriculum, skills=library,
        config=LoopConfig(), budget=RunBudget(max_steps=1), log=lambda m: None,
    )
    record = loop.step()
    assert record is not None
    assert record.verdict == "CONFIRMED"
    assert record.disposition == "admitted"
    assert record.truth is True
    assert curriculum.achieved() == ("wood",)
    assert len([e for e in ledger.events() if e.type == "tile.played"]) == 1


def test_the_loop_rejects_a_skill_that_fails(tmp_path):
    from core.night.ledger import InMemoryLedger

    milestones = [Milestone(key="wood", title="get wood", description="cut a tree",
                             items=("wood",))]
    env = FakeEnv(milestones=milestones, truth=set())
    ledger = InMemoryLedger()
    library = SkillLibrary(registry=vocabulary(), ledger=ledger, bodies_dir=tmp_path)
    models = router([PLAN], [CODE], [
        json.dumps({"verdict": "DENIED", "reason": "nothing was gained", "evidence": "x"})
    ])
    loop = VoyagerLoop(
        env=env, models=models, curriculum=Curriculum(milestones, seed=1),
        skills=library, config=LoopConfig(), budget=RunBudget(max_steps=1),
        log=lambda m: None,
    )
    record = loop.step()
    assert record.disposition == "rejected"
    assert record.truth is False
    # The play is on the log even though the skill was refused: the drift
    # detector has to see the failure.
    plays = [e for e in ledger.events() if e.type == "tile.played"]
    assert len(plays) == 1
    assert plays[0].payload["outcome"]["result"] == "lose"
    assert plays[0].payload["context"]["bot"] == "voyager"


def test_the_loop_feeds_the_failure_back(tmp_path):
    milestones = [Milestone(key="wood", title="get wood", description="",
                             items=("wood",))]
    env = FakeEnv(milestones=milestones, truth=set())
    library = SkillLibrary(registry=vocabulary(), bodies_dir=tmp_path)
    models = router([PLAN, PLAN], [CODE, CODE], [
        json.dumps({"verdict": "DENIED", "reason": "it went the wrong way",
                    "evidence": "x"}),
        json.dumps({"verdict": "DENIED", "reason": "it went the wrong way",
                    "evidence": "x"}),
    ])
    loop = VoyagerLoop(
        env=env, models=models, curriculum=Curriculum(milestones, seed=1),
        skills=library, config=LoopConfig(), budget=RunBudget(max_steps=2),
        log=lambda m: None,
    )
    loop.step()
    loop.step()
    second_prompt = models.client("coder").prompts[1][1]
    assert "YOUR PREVIOUS ATTEMPT" in second_prompt
    assert "it went the wrong way" in second_prompt


def test_the_loop_survives_an_unreadable_plan(tmp_path):
    milestones = [Milestone(key="wood", title="get wood", description="",
                             items=("wood",))]
    env = FakeEnv(milestones=milestones)
    library = SkillLibrary(registry=vocabulary(), bodies_dir=tmp_path)
    models = router(["not json at all"], [], [])
    loop = VoyagerLoop(
        env=env, models=models, curriculum=Curriculum(milestones, seed=1),
        skills=library, config=LoopConfig(), budget=RunBudget(max_steps=1),
        log=lambda m: None,
    )
    record = loop.step()
    assert record.reason.startswith("planner_unreadable")


# ---------------------------------------------------------------------------
# the prompts
# ---------------------------------------------------------------------------


def test_the_json_reader_takes_the_first_object():
    assert parse_json_block('noise {"a": 1} tail') == {"a": 1}
    assert parse_json_block('```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_json_block('{"a": {"b": 1}}') == {"a": {"b": 1}}
