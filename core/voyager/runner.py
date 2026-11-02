"""The loop — plan, write, run, check, judge, admit.

This is Voyager's shape, re-engineered to be system-agnostic. One turn:

1. **observe** — the world's facts, in the player's terms;
2. **curriculum** — the milestone to work on, chosen by novelty;
3. **plan** — the planner model offers two to eight whole steps and
   picks one (the harness rule, ``docs/research/autopilot.md`` §1.1);
4. **write** — the coder model writes one skill that does that step,
   using only the world's closed vocabulary of primitives;
5. **run** — the skill runs in the world's sandbox, under a timeout;
6. **check** — the skill's own self-verification runs, and the world's
   ground truth is asked whether the goal is met;
7. **judge** — the verifier model, a **different model from the coder**,
   answers CONFIRMED / DENIED / INCONCLUSIVE;
8. **record** — one disposition event for the skill, one play event for
   the execution, and the curriculum's bookkeeping.

Two rules the loop keeps:

* **the environment's answer outranks the model's.** The ground truth
  decides whether the goal is reached; the verifier decides whether the
  *skill* is worth keeping. Neither overrules the other.
* **the failure is fed back.** The next coder prompt carries the last
  program, the error it produced and the verifier's critique, so the
  next program is a revision rather than a fresh guess. This is
  Voyager's second contribution and the reason a loop with a skill
  library is more than a loop.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from core.canon import content_hash, now_utc

from .budget import ProbeBudget, RunBudget
from .curriculum import Curriculum
from .llm import ModelRouter
from .metrics import Metrics
from .models import (
    Disposition,
    ModelReply,
    RunReport,
    SkillProposal,
    StepRecord,
    Verdict,
)
from .ports import EnvironmentPort
from .prompts import (
    CODER_SYSTEM,
    PLANNER_SYSTEM,
    VERIFIER_SYSTEM,
    coder_prompt,
    parse_json_block,
    planner_prompt,
    verifier_prompt,
)
from .skills import SkillLibrary

__all__ = ["VoyagerLoop", "LoopConfig"]


@dataclass
class LoopConfig:
    """The loop's numbers.

    ``exec_timeout_s`` is the wall a skill may take in the world; a
    skill that hangs is a failed skill, not a stuck run.
    """

    exec_timeout_s: float = 120.0
    verify_timeout_s: float = 30.0
    planner_max_tokens: int = 1200
    coder_max_tokens: int = 2400
    verifier_max_tokens: int = 700
    planner_temperature: float = 0.3
    coder_temperature: float = 0.2
    verifier_temperature: float = 0.1
    #: How many probes the loop may take before the first execution of a
    #: step. After that the budget is closed.
    max_probes: int = 2


class VoyagerLoop:
    """The agent loop."""

    def __init__(
        self,
        *,
        env: EnvironmentPort,
        models: ModelRouter,
        curriculum: Curriculum,
        skills: SkillLibrary,
        config: LoopConfig | None = None,
        budget: RunBudget | None = None,
        agent: str = "voyager",
        log: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.time,
        wall_clock: Callable[[], str] = now_utc,
    ) -> None:
        self._env = env
        self._models = models
        self._curriculum = curriculum
        self._skills = skills
        self._config = config or LoopConfig()
        self._budget = budget or RunBudget()
        self._agent = agent
        self._log = log or (lambda message: None)
        self._clock = clock
        self._wall_clock = wall_clock
        self._probe = ProbeBudget(max_probes_before_first_execution=self._config.max_probes)
        self._metrics = Metrics(world=env.name)
        self._index = 0
        self._last_code = ""
        self._last_error = ""
        self._last_critique = ""
        self._last_outcome = ""
        self._started = False

    # -- the run ---------------------------------------------------------------

    def run(self) -> RunReport:
        """Run until the budget stops it.

        The loop is the only place that decides to stop, and it says
        why: the report's ``stopped_by`` field names the limit.
        """
        self._metrics.started_at = self._wall_clock()
        self._budget.start(self._clock)
        while not self._budget.exhausted():
            record = self.step()
            if record is None:
                break
        self._metrics.finished_at = self._wall_clock()
        self._metrics.wall_seconds = self._budget.elapsed()
        counts = self._skills.counts()
        return self._metrics.report(
            skills_admitted=counts.get("admitted", 0),
            skills_rejected=counts.get("rejected", 0),
            skills_superseded=counts.get("superseded", 0),
        )

    def step(self) -> StepRecord | None:
        """One turn of the loop.

        ``None`` means the curriculum is exhausted — there is nothing
        left to work on.
        """
        if self._started:
            self._probe.reopen()
        self._started = True
        self._index += 1

        facts = self._env.observe()
        goal = self._curriculum.pick()
        if goal is None:
            self._log("the curriculum is exhausted")
            return None

        self._curriculum.record_attempt(goal.key, at=self._wall_clock())
        usages: list[Any] = []
        options: tuple[str, ...] = ()

        # -- plan ---------------------------------------------------------------
        plan_reply = self._models.complete(
            "planner",
            PLANNER_SYSTEM,
            planner_prompt(
                goal=goal.title,
                goal_description=goal.description,
                facts=facts,
                library=self._library_brief(),
                last_outcome=self._last_outcome,
            ),
            max_tokens=self._config.planner_max_tokens,
            temperature=self._config.planner_temperature,
        )
        usages.append(plan_reply.usage)
        try:
            plan = parse_json_block(plan_reply.text)
        except ValueError as exc:
            return self._failed_step(
                goal.key, facts, usages, f"planner_unreadable: {exc}", options
            )
        options = tuple(
            str(option.get("name", "")) for option in (plan.get("options") or [])
        )
        chosen_id = str(plan.get("chosen", ""))
        chosen = next(
            (
                option
                for option in (plan.get("options") or [])
                if str(option.get("id", "")) == chosen_id
            ),
            None,
        )
        if chosen is None and plan.get("options"):
            chosen = plan["options"][0]
        chosen_description = (
            f"{chosen.get('name', '')}: {chosen.get('description', '')}"
            if isinstance(chosen, dict)
            else ""
        )

        # -- write --------------------------------------------------------------
        coder_reply = self._models.complete(
            "coder",
            CODER_SYSTEM,
            coder_prompt(
                goal=goal.title,
                goal_description=goal.description,
                plan_description=chosen_description or goal.description,
                facts=facts,
                primitives=self._primitives(),
                previous_code=self._last_code,
                previous_error=self._last_error,
                critique=self._last_critique,
            ),
            max_tokens=self._config.coder_max_tokens,
            temperature=self._config.coder_temperature,
        )
        usages.append(coder_reply.usage)
        try:
            written = parse_json_block(coder_reply.text)
        except ValueError as exc:
            return self._failed_step(
                goal.key, facts, usages, f"coder_unreadable: {exc}", options
            )
        code = str(written.get("code", ""))
        if not code.strip():
            return self._failed_step(
                goal.key, facts, usages, "coder_wrote_no_code", options
            )
        proposal = SkillProposal(
            title=str(written.get("title", "a skill")),
            description=str(written.get("description", "")),
            family=f"{self._env.name}.{goal.key}",
            code=code,
            verify_code=str(written.get("verify_code", "")),
            primitives=tuple(str(p) for p in (written.get("primitives") or [])),
            milestone=goal.key,
            language=self._env.language,
        )
        self._last_code = code

        # -- run ----------------------------------------------------------------
        execution = self._env.run_code(code, timeout_s=self._config.exec_timeout_s)
        self._probe.note_execution()

        # -- check --------------------------------------------------------------
        self_verified: bool | None = None
        if proposal.verify_code.strip():
            check = self._env.evaluate(
                proposal.verify_code, timeout_s=self._config.verify_timeout_s
            )
            self_verified = check.passed
        truth = bool(self._env.goal_truth(goal.key))

        # -- judge --------------------------------------------------------------
        after = self._env.observe()
        verifier_reply = self._models.complete(
            "verifier",
            VERIFIER_SYSTEM,
            verifier_prompt(
                goal=goal.title,
                goal_description=goal.description,
                before=facts,
                after=after,
                log=execution.log,
                self_verified=self_verified,
                ground_truth=truth,
                code=code,
            ),
            max_tokens=self._config.verifier_max_tokens,
            temperature=self._config.verifier_temperature,
        )
        usages.append(verifier_reply.usage)
        try:
            judged = parse_json_block(verifier_reply.text)
        except ValueError as exc:
            judged = {"verdict": "INCONCLUSIVE", "reason": f"unreadable: {exc}"}
        verdict = str(judged.get("verdict", "INCONCLUSIVE")).upper()
        if verdict not in ("CONFIRMED", "DENIED", "INCONCLUSIVE"):
            verdict = "INCONCLUSIVE"
        critique = str(judged.get("reason", ""))

        # -- record -------------------------------------------------------------
        disposition: Disposition = "admitted" if verdict == "CONFIRMED" else "rejected"
        reason = "" if disposition == "admitted" else f"verifier:{verdict.lower()}"
        if not execution.ok:
            disposition = "rejected"
            reason = f"execution_error:{execution.error}"[:400]
        elif not verdict == "CONFIRMED" and not reason:
            reason = f"verifier:{verdict.lower()}"

        prompt_hash = content_hash(
            {
                "goal": goal.key,
                "plan": chosen_description,
                "code": code,
                "facts": dict(facts),
            }
        )
        record = self._skills.submit(
            proposal,
            author_model=self._models.client("coder").model,
            author_role="coder",
            prompt_hash=prompt_hash,
            disposition=disposition,
            reason=reason,
        )

        outcome_result = {
            "CONFIRMED": "win",
            "DENIED": "lose",
            "INCONCLUSIVE": "partial",
        }[verdict]
        from core.tiles.models import Outcome

        play = self._skills.record_play(
            tile_id=record.id,
            context={
                "bot": self._agent,
                "goal": goal.key,
                "milestone": goal.title,
                "world": self._env.name,
                "exec_ok": execution.ok,
                "self_verified": self_verified,
                "ground_truth": truth,
            },
            outcome=Outcome(
                result=outcome_result,
                measure="critic",
                score=1.0 if outcome_result == "win" else (0.0 if outcome_result == "lose" else 0.5),
                detail=critique[:500],
            ),
        )

        # -- the curriculum and the tally ---------------------------------------
        if truth:
            self._curriculum.record_achieved(
                goal.key, at=self._wall_clock(), step=self._index
            )
            self._metrics.note_milestone(
                goal.key,
                at_seconds=self._budget.elapsed(),
                tokens=self._metrics.total_tokens + sum(u.total_tokens for u in usages),
            )
        self._metrics.note_items(self._env.progress().items)
        self._metrics.note_step(
            StepRecord(
                index=self._index,
                at=self._wall_clock(),
                goal=goal.key,
                plan=options,
                proposal=proposal,
                exec_ok=execution.ok,
                exec_error=execution.error,
                exec_log=execution.log,
                exec_seconds=execution.seconds,
                self_verified=self_verified,
                truth=truth,
                verdict=verdict,  # type: ignore[arg-type]
                verdict_detail=critique,
                disposition=disposition,
                reason=reason,
                skill_id=record.id,
                usage=tuple(usages),
                facts=dict(facts),
            )
        )
        self._budget.note_step(sum(u.total_tokens for u in usages))

        # -- feed the next step back --------------------------------------------
        self._last_error = execution.error or ""
        self._last_critique = critique
        self._last_outcome = (
            f"the last program aimed at {goal.title}; it "
            + ("ran" if execution.ok else "failed")
            + (f" and the verifier said {verdict}" if verdict else "")
            + (f"; the goal is {'met' if truth else 'not met'}")
        )
        self._log(
            f"step {self._index}: goal={goal.key} verdict={verdict} "
            f"truth={truth} disposition={disposition} "
            f"tokens={sum(u.total_tokens for u in usages)}"
        )
        return self._metrics.steps[-1]

    # -- the helpers -----------------------------------------------------------

    def _primitives(self) -> Mapping[str, Any]:
        """The world's primitives and their schemas, for the coder."""
        return getattr(self._env, "primitive_schemas", lambda: {})()

    def _library_brief(self) -> Sequence[Mapping[str, Any]]:
        """The library, as the planner sees it."""
        out: list[Mapping[str, Any]] = []
        for tile in self._skills.active():
            out.append(
                {
                    "id": tile.id,
                    "title": tile.title,
                    "description": str(tile.provenance.get("description", "")),
                }
            )
        return out

    def _failed_step(
        self,
        goal: str,
        facts: Mapping[str, Any],
        usages: Sequence[Any],
        reason: str,
        options: tuple[str, ...],
    ) -> StepRecord:
        """A turn that did not get as far as running anything.

        It is still a turn: it is on the log, it is counted, and the next
        turn knows what went wrong.
        """
        record = StepRecord(
            index=self._index,
            at=self._wall_clock(),
            goal=goal,
            plan=options,
            verdict="INCONCLUSIVE",
            disposition="rejected",
            reason=reason,
            usage=tuple(usages),
            facts=dict(facts),
        )
        self._metrics.note_step(record)
        self._budget.note_step(sum(u.total_tokens for u in usages))
        self._last_error = reason
        self._last_critique = ""
        self._last_outcome = f"the last turn failed: {reason}"
        self._log(f"step {self._index}: failed ({reason})")
        return record
