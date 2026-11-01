"""The morning report page (core-spec v2 §3.2.9).

The page is a **static HTML file over the ledger**: no panel-side state, so it
can be regenerated from the log at any time and it survives the night that
produced it (§5.4). The order of the page is the spec's, and it is the order
the owner reads it in:

1. the **status line**, computed — ``ran as planned | ran short | ran
   degraded | did not run`` plus a one-line reason;
2. the **failure line** — always present, even when it is "nothing failed";
   failures lead;
3. **the cut named**, not just the spend — what was dropped and any
   wall-clock overrun;
4. the **night numbers** — and no single prediction score, which is theatre;
5. the filmstrip, the three branches **plus the two standing options**, the
   parked questions **triaged top-3 plus a count**, the landed work orders,
   the model-change notices and the lost time;
6. the **tally**, per builder × claim type, with denominators;
7. the **three-number line**: hours of your Thor, hosted money, hours of
   your attention.
"""

from __future__ import annotations

import json
import re

import pytest

from core.night.clock import ScriptedClock
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.ledger import InMemoryLedger
from core.night.models import Actor, Rail, Task
from core.night.report import build_report, render_html, render_text, write_report
from core.night.runner import NightRunner

NIGHT = "night_2026-10-30"


def runner_actor() -> Actor:
    return Actor(kind="scheduler", id="night-runner")


def a_task(task_id: str = "task_0001", **kwargs) -> Task:
    return Task(
        id=task_id,
        intention=kwargs.pop("intention", "Forest the east slope, keep the oak"),
        **kwargs,
    )


def run_a_night(executor=None, tasks=None, rails=None, **kwargs) -> list:
    ledger = InMemoryLedger()
    executor = executor or ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}
    )
    runner = NightRunner(
        ledger,
        executor,
        night_id=NIGHT,
        rails=rails or Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0),
        clock=ScriptedClock(kwargs.pop("start", "2026-10-30T21:14:00Z")),
        **kwargs,
    )
    runner.start(tasks if tasks is not None else [a_task()])
    runner.run()
    runner.stop()
    return ledger.events()


def section_positions(html: str) -> dict[str, int]:
    """Where each section starts in the page, so the order can be checked."""
    return {
        match.group(1): match.start()
        for match in re.finditer(r'<section id="([a-z-]+)"', html)
    }


def a_judged_night(*, window: int = 50) -> list:
    """A night whose judge confidence stops separating right from wrong.

    Two windows of judgments on one scope each. The first window is the
    model at its best — the right judgments carry the higher confidence;
    the second is the model at its worst, with the confident ones wrong.
    That is the **separability lost** drift: the AUC of the newest window
    has fallen to the coin-flip line.
    """
    from core.judge.backends import BackendReply, FakeBackend
    from core.judge.judge import Judge
    from core.judge.models import Question

    class Scripted(FakeBackend):
        def __init__(self, responder):
            super().__init__()
            self.name = "d1"
            self.model = "d1-2B"
            self._responder = responder

        def ask(self, state, questions):
            distributions = {}
            confidences = {}
            for question in questions:
                distributions[question.qid] = self._responder(question)
                confidences[question.qid] = max(distributions[question.qid].values())
            return BackendReply(
                backend=self.name,
                model=self.model,
                distributions=distributions,
                confidences=confidences,
                input_tokens=1,
                wall_seconds=0.001,
            )

    ledger = InMemoryLedger()
    question = Question(qid="alive", kind="noul", instructions="The root is alive.")
    index = {"n": 0}

    def respond(_question):
        index["n"] += 1
        # the confident answers and the unsure ones alternate; which of
        # them is right flips between the windows
        confident = index["n"] % 2 == 1
        value = 0.95 if confident else 0.55
        return {"true": value, "false": round(1.0 - value, 10)}

    judge = Judge(Scripted(respond), ledger=ledger)
    for step in range(window * 2):
        scope = f"scope-{step}"
        judge.judge(task="alive", state="s", questions=[question], scope=scope)
        # the first window is right when it is confident; the second is
        # right when it is unsure — the confidence stops ordering them
        confident = step % 2 == 0
        right = confident if step < window else not confident
        ledger.append(
            type="critic.verdict",
            actor=Actor(kind="core", id="critic", via="critic"),
            subject={"entity_kind": "artifact", "entity_id": scope},
            payload={"verdict": "keep" if right else "fix", "scope": scope},
            at=f"2026-10-30T22:{step // 60:02d}:{step % 60:02d}Z",
        )
    return ledger.events()


def test_the_morning_carries_one_line_per_drifting_model():
    report = build_report(a_judged_night())
    assert report.calibration.n_judgments == 100
    assert report.calibration.n_scored == 100
    assert report.calibration.drifting, "the confidence stopped separating; the morning says so"
    line = report.calibration.drifting[0]
    assert line.model == "d1:d1-2B"
    assert line.task == "alive"
    assert line.kind == "separability_lost"
    assert line.retune
    # one line per drifting model, not one per reason
    models = [card.model for card in report.calibration.drifting]
    assert len(models) == len(set(models))


def test_the_drifting_models_are_on_the_page_and_in_the_text():
    report = build_report(a_judged_night())
    html = render_html(report)
    assert "d1:d1-2B" in html
    assert "separability" in html
    text = render_text(report)
    assert "d1:d1-2B" in text
    assert "alive" in text


def test_a_night_with_no_judgments_says_the_calibration_is_empty():
    report = build_report(run_a_night())
    assert report.calibration.n_judgments == 0
    assert report.calibration.drifting == []
    assert "calibration" in render_html(report).lower()


def test_the_status_line_is_the_first_thing_on_the_page():
    html = render_html(build_report(run_a_night()))
    assert html.index("ran as planned") < html.index("Nothing failed")
    positions = section_positions(html)
    assert positions["status"] < positions["failures"]
    assert positions["failures"] < positions["cut"]
    assert positions["cut"] < positions["numbers"]
    assert positions["numbers"] < positions["morning"]
    assert positions["morning"] < positions["tally"]
    assert positions["tally"] < positions["three-numbers"]


def test_the_failure_line_is_present_even_when_nothing_failed():
    html = render_html(build_report(run_a_night()))
    assert "Nothing failed" in html


def test_a_failure_leads_with_its_reason_and_its_artifact():
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                outcome="failed",
                reason="hollow mesh from the image-to-3D model",
                artifact="artifacts/ab/ab1234.png",
            )
        }
    )
    html = render_html(build_report(run_a_night(executor)))
    assert "hollow mesh from the image-to-3D model" in html
    assert "artifacts/ab/ab1234.png" in html
    positions = section_positions(html)
    assert positions["failures"] < positions["numbers"]


def test_the_cut_is_named_with_the_work_that_was_dropped():
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(gpu_minutes=300.0, wall_minutes=45.0),
            "task_0002": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0),
        }
    )
    tasks = [a_task("task_0001"), a_task("task_0002", intention="Light the north lantern")]
    report = build_report(run_a_night(executor, tasks))
    assert len(report.cut) == 1
    assert report.cut[0].intention == "Light the north lantern"
    assert "re-queued for tonight" in report.cut[0].reason
    assert "re-queued for tonight" in render_html(report)


def test_the_numbers_carry_no_single_prediction_score():
    """The one number both reports must kill (X C2)."""
    html = render_html(build_report(run_a_night()))
    assert "prediction score" not in html.lower()
    assert "overall score" not in html.lower()


def test_the_night_numbers_name_the_measurements():
    executor = ScriptedExecutor(
        {"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0, model="trellis2")}
    )
    report = build_report(run_a_night(executor))
    assert report.numbers.sealed_bets == 0
    assert report.numbers.gpu_minutes_spent == 30.0
    assert report.numbers.model_loads == {"trellis2": 1}
    assert report.numbers.kept_critic == 1


def test_the_page_carries_the_three_number_line():
    html = render_html(build_report(run_a_night()))
    assert "of your Thor" in html
    assert "hosted (local)" in html
    assert "of your attention" in html
    assert "budget 10" in html


def test_the_morning_line_carries_the_joules_as_its_fourth_number():
    """Plan item 17: the three-number line has a fourth — joules — measured.

    The board's rails were measured in lab round 3, so the line quotes a
    number rather than saying the joules are not measured yet.
    """
    report = build_report(run_a_night())
    assert report.three_numbers.joules is not None
    assert report.three_numbers.joules > 0
    html = render_html(report)
    assert "kJ" in html
    assert "not measured" not in html
    assert "kJ" in render_text(report)


def test_the_joules_on_the_line_come_from_the_measured_rails():
    """47.5 W on the VIN rail over the night's wall time."""
    report = build_report(run_a_night())
    expected = 47.5 * report.numbers.wall_time_minutes * 60.0 / 1000.0
    assert report.three_numbers.joules == pytest.approx(expected)
    # and the rendered line quotes that kJ figure, not a thousandth of it
    # (the honest-week run caught the line printing 0.4 kJ for a 400 kJ night)
    assert f"{expected:.1f} kJ" in render_text(report)


def test_the_attention_estimate_is_the_cost_models_number():
    """The one estimate in the model — and it stays marked as one."""
    from core.night.cost import get_model
    from core.night.report import MINUTES_PER_DECISION

    assert MINUTES_PER_DECISION == get_model().attention_minutes_per_decision()


def test_the_branch_set_always_has_the_two_standing_options():
    report = build_report(run_a_night())
    names = [branch.name for branch in report.branches]
    assert "keep yesterday" in names
    assert "back to the plan" in names


def test_parked_questions_are_triaged_to_three_with_a_count_of_the_rest():
    ledger = InMemoryLedger()
    runner = NightRunner(
        ledger,
        ScriptedExecutor({"task_0001": ScriptedTask(gpu_minutes=30.0, wall_minutes=45.0)}),
        night_id=NIGHT,
        rails=Rail(gpu_minutes=360.0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
    )
    runner.start([a_task()])
    runner.run()
    runner.stop()
    for index in range(5):
        ledger.append(
            type="question.parked",
            actor=runner._actor,
            subject={"entity_kind": "question", "entity_id": f"q_{index:04d}"},
            payload={
                "question_id": f"q_{index:04d}",
                "name": f"keep the {index}th crate?",
                "blocking": False,
            },
        )

    report = build_report(ledger.events())
    assert len(report.questions) == 3
    assert report.questions_total == 5
    assert "2 more" in render_html(report)


def test_the_tally_is_per_builder_and_claim_type_with_denominators():
    executor = ScriptedExecutor(
        {
            "task_0001": ScriptedTask(
                gpu_minutes=30.0,
                wall_minutes=45.0,
                predictions=[
                    {
                        "prediction_id": "pr_0001",
                        "builder": "prop-maker",
                        "claim_type": "shadow_count",
                        "claim": "the crates will read weathered",
                        "confidence": "guess",
                        "basis": "0 observations",
                    }
                ],
                verdicts=[{"prediction_id": "pr_0001", "verdict": "hit"}],
            )
        }
    )
    report = build_report(run_a_night(executor))
    assert len(report.tally) == 1
    row = report.tally[0]
    assert row.builder == "prop-maker"
    assert row.claim_type == "shadow_count"
    assert row.total == 1
    assert row.hits == 1


def test_a_night_with_no_predictions_says_the_empty_thing():
    report = build_report(run_a_night())
    assert report.tally == []
    assert "not taste yet" in render_html(report)


def test_the_report_renders_with_zero_panel_side_state():
    html = render_html(build_report(run_a_night()))
    assert "<script" not in html.lower()
    assert "javascript:" not in html.lower()
    assert "onclick" not in html.lower()


def test_the_report_is_regenerable_from_the_log_at_any_time():
    events = run_a_night()
    assert render_html(build_report(events)) == render_html(build_report(events))


def test_the_text_mode_is_the_same_ledger_read():
    events = run_a_night()
    text = render_text(build_report(events))
    assert "ran as planned" in text
    assert "of your Thor" in text


def test_the_wall_time_is_the_nights_own_clock_and_not_the_machines():
    """Regression: every row of the night carries the night's clock."""
    report = build_report(run_a_night())
    assert report.numbers.wall_time_minutes == 45.0


def test_a_did_not_run_morning_re_offers_the_plan_verbatim():
    """§3.4 — the plan survives every one of these nights, and is re-offered."""
    ledger = InMemoryLedger()
    ledger.append(
        type="night.task.created",
        actor=runner_actor(),
        subject={"entity_kind": "task", "entity_id": "task_0001"},
        payload={
            "task": {
                "id": "task_0001",
                "night": None,
                "author": "casey",
                "owner_character": "prop-maker",
                "intention": "Weather the harbour crates",
                "recipe_scope": [],
                "cost_estimate": {"gpu_minutes": 30.0, "hosted_cents": 0, "wall_minutes": 45.0},
                "rail": {"gpu_minutes": 40.0, "hosted_cents": 0, "wall_minutes": 60.0},
                "state": "slated",
                "predictions": [],
                "branches": [],
            }
        },
    )
    report = build_report(ledger.events())
    assert report.status.status == "did not run"
    assert report.status.variant == "off"
    assert "start now" in report.recovery
    assert "tonight" in report.recovery
    assert "drop it" in report.recovery
    assert "start now" in render_html(report)


def test_writing_the_report_writes_the_page_its_json_and_its_text(tmp_path):
    report = build_report(run_a_night())
    written = write_report(report, tmp_path)
    assert (tmp_path / "report.html").exists()
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.txt").exists()
    payload = json.loads((tmp_path / "report.json").read_text())
    assert payload["night_id"] == NIGHT
    assert payload["status"]["status"] == "ran as planned"
    assert written == tmp_path / "report.html"
