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


# ---------------------------------------------------------------------------
# the wire: a reply the cap cut is asked again, with room
# ---------------------------------------------------------------------------


def _wire(monkeypatch, replies: list[dict]) -> list[dict]:
    """Put canned answers under urllib, and collect what was asked."""
    import io
    import urllib.request

    asked: list[dict] = []

    def fake_urlopen(request, timeout=None):
        asked.append(json.loads(request.data))
        return io.BytesIO(json.dumps(replies.pop(0)).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return asked


def _answer(content: str, finish: str, prompt: int = 100, completion: int = 50) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


def test_a_reply_the_cap_cut_is_asked_again_with_room(monkeypatch):
    from core.voyager.llm import DeepInfraClient

    asked = _wire(
        monkeypatch,
        [
            _answer('{"options": [{"id": "a", "name": "w', "length", 100, 1200),
            _answer('{"options": [], "chosen": "", "why": "done"}', "stop", 100, 60),
        ],
    )
    client = DeepInfraClient("planner", "scripted-model", api_key="test-key")
    reply = client.complete("system", "user", max_tokens=1200)

    assert reply.attempts == 2
    assert reply.finish_reason == "stop"
    assert reply.text == '{"options": [], "chosen": "", "why": "done"}'
    # the second ask carried twice the room
    assert asked[0]["max_tokens"] == 1200
    assert asked[1]["max_tokens"] == 2400
    # the book counts every call, not the last one
    assert reply.usage.prompt_tokens == 200
    assert reply.usage.completion_tokens == 1260


def test_an_empty_reply_is_asked_again(monkeypatch):
    from core.voyager.llm import DeepInfraClient

    _wire(
        monkeypatch,
        [
            _answer("", "stop"),
            _answer('{"verdict": "CONFIRMED"}', "stop"),
        ],
    )
    client = DeepInfraClient("verifier", "scripted-model", api_key="test-key")
    reply = client.complete("system", "user", max_tokens=700)
    assert reply.attempts == 2
    assert reply.text == '{"verdict": "CONFIRMED"}'


def test_a_reply_that_stays_cut_is_returned_not_hidden(monkeypatch):
    from core.voyager.llm import DeepInfraClient

    _wire(monkeypatch, [_answer('{"options": [', "length")] * 3)
    client = DeepInfraClient("planner", "scripted-model", api_key="test-key")
    reply = client.complete("system", "user", max_tokens=1200)
    assert reply.attempts == 3
    assert reply.finish_reason == "length"
    assert reply.text == '{"options": ['


# ---------------------------------------------------------------------------
# the unreadable reason says why the model stopped
# ---------------------------------------------------------------------------


def test_the_unreadable_reason_says_why_the_model_stopped(tmp_path):
    class CutPlanner:
        model = "scripted"

        def complete(self, system, user, *, max_tokens=2000, temperature=0.3):
            return ModelReply(
                text="the reply is prose, not json",
                usage=TokenUsage(role="planner", model="scripted"),
                finish_reason="length",
            )

    milestones = [Milestone(key="wood", title="get wood", description="", items=("wood",))]
    env = FakeEnv(milestones=milestones)
    library = SkillLibrary(registry=vocabulary(), bodies_dir=tmp_path)
    models = ModelRouter(
        {
            "planner": CutPlanner(),
            "coder": ScriptedModel("coder", [CODE]),
            "verifier": ScriptedModel("verifier", ["{}"]),
        }
    )
    loop = VoyagerLoop(
        env=env, models=models, curriculum=Curriculum(milestones, seed=1),
        skills=library, config=LoopConfig(), budget=RunBudget(max_steps=1),
        log=lambda m: None,
    )
    record = loop.step()
    assert record.reason.startswith("planner_unreadable")
    assert "finish_reason='length'" in record.reason


# ---------------------------------------------------------------------------
# the coder is told what a primitive returns
# ---------------------------------------------------------------------------


def test_the_coder_prompt_shows_what_a_primitive_returns():
    from core.voyager.prompts import coder_prompt

    prompt = coder_prompt(
        goal="get wood",
        goal_description="hold a log",
        plan_description="walk to the tree",
        facts={},
        primitives={
            "mc.has": {"item": {"type": "string"}},
            "mc.move_to": {"x": {"type": "number"}},
        },
        returns={
            "mc.has": "{has: true|false} -- read .has; the object itself is always truthy",
            "mc.move_to": "{at: where the bot stands, why}",
        },
    )
    assert "-> {has: true|false} -- read .has" in prompt
    assert "-> {at: where the bot stands, why}" in prompt


def test_the_minecraft_returns_match_the_vocabulary():
    from core.voyager.adapters.minecraft import MC_RETURNS, mc_vocabulary

    registry = mc_vocabulary()
    for word in MC_RETURNS:
        assert registry.has(word), word
    for word in registry.words():
        if word != "voyager.skill_body":
            assert word in MC_RETURNS, word


def test_a_parameterless_primitive_is_a_word():
    from core.voyager.vocab import SkillRefusal

    registry = SkillVocabulary({"mc.reward": {}})
    assert registry.has("mc.reward")
    registry.validate_params("mc.reward", {})
    try:
        registry.validate_params("mc.reward", {"x": 1})
    except SkillRefusal as exc:
        assert exc.reason == "unknown_property"
    else:
        raise AssertionError("a parameter was accepted on a parameterless word")


def test_the_crafter_vocabulary_builds():
    from core.voyager.adapters.crafter import CRAFTER_RETURNS, crafter_vocabulary

    registry = crafter_vocabulary()
    for word in CRAFTER_RETURNS:
        assert registry.has(word), word


def test_the_crafter_adapter_round_trips():
    pytest = __import__("pytest")
    crafter = pytest.importorskip("crafter")
    from core.voyager.adapters.crafter import CrafterAdapter
    adapter = CrafterAdapter(log=lambda m: None)
    adapter.open()
    try:
        facts = adapter.observe()
        assert facts["world"] == "crafter"
        result = adapter.run_code("mc.act('noop')", timeout_s=30.0)
        assert result.ok, result.error
        check = adapter.evaluate("mc.achievements()['collect_wood'] > 0", timeout_s=10.0)
        assert check.detail == "False"  # a fresh world: no wood yet
    finally:
        adapter.close()


def test_the_crafter_spatial_fact_names_directions_the_move_primitive_accepts():
    pytest = __import__("pytest")
    pytest.importorskip("crafter")
    import re

    from core.voyager.adapters.crafter import CrafterAdapter, crafter_vocabulary

    adapter = CrafterAdapter(log=lambda m: None)
    adapter.open()
    try:
        spatial = adapter.observe()["spatial"]
        directions = crafter_vocabulary().require("mc.move")["direction"]["enum"]
        assert spatial["facing"] in directions
        assert spatial["in_front"] is None or isinstance(spatial["in_front"], str)
        assert spatial["nearest"], "the local window always holds the ground underfoot"
        for name, where in spatial["nearest"].items():
            counted = re.search(r"\((\d+) moves\)", where)
            if counted:
                # the window the pixels render is 9 x 8 with the player
                # at its centre: nothing inside it is farther than its
                # own diagonal in moves
                assert int(counted.group(1)) <= 8, (name, where)
            else:
                assert where.startswith("here"), (name, where)
            for word in re.findall(r"\b(left|right|up|down)\b", where):
                assert word in directions, (name, where)
    finally:
        adapter.close()


def test_a_dead_episode_resets_instead_of_stalling_the_run():
    pytest = __import__("pytest")
    pytest.importorskip("crafter")
    from core.voyager.adapters.crafter import CrafterAdapter

    adapter = CrafterAdapter(log=lambda m: None)
    adapter.open()
    try:
        before = adapter.observe()
        # the episode is spent: a dead player ends it (a run of hours
        # will meet zombies; the smokes never did)
        adapter._env._player.health = 0
        adapter._absorb({"achievements": {"collect_wood": 1}})
        after = adapter.observe()
        assert after["episode"] == before["episode"] + 1
        assert after["health"] > 0  # the facts describe a living player
        assert after["episodes_finished"] == 1
        # a milestone once reached stays reached across the reset
        assert adapter.goal_truth("collect_wood")
    finally:
        adapter.close()


def test_the_coder_prompt_names_the_language():
    from core.voyager.prompts import coder_prompt

    prompt = coder_prompt(
        goal="get wood",
        goal_description="hold a log",
        plan_description="walk to the tree",
        facts={},
        primitives={"mc.act": {"action": {"type": "string"}}},
        language="python",
    )
    assert "THE LANGUAGE OF THE PROGRAM: python" in prompt


def test_a_crafter_program_that_never_finishes_fails_instead_of_hanging():
    pytest = __import__("pytest")
    pytest.importorskip("crafter")
    import time as _time
    from core.voyager.adapters.crafter import CrafterAdapter

    adapter = CrafterAdapter(log=lambda m: None)
    adapter.open()
    try:
        started = _time.time()
        result = adapter.run_code("while True:\n    pass", timeout_s=2.0)
        assert not result.ok
        assert "TimeoutError" in result.error
        assert _time.time() - started < 30
    finally:
        adapter.close()


def test_a_syntax_error_names_the_language_the_world_runs():
    pytest = __import__("pytest")
    pytest.importorskip("crafter")
    from core.voyager.adapters.crafter import CrafterAdapter

    adapter = CrafterAdapter(log=lambda m: None)
    adapter.open()
    try:
        result = adapter.run_code("async function main() {}", timeout_s=10.0)
        assert not result.ok
        assert "runs python" in result.error
    finally:
        adapter.close()
