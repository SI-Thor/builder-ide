"""The night-runner seat (branch `night-runner`): the night's own logic.

The spine (core-api) already owns the HTTP night — start, pre-flight,
heartbeat ticks, the computed status line, the report. This seat is the
**reference implementation** of the same rules, run beside it for the same
script facts: its `NightRunner` works a scripted queue under real rails —
admission before spend, the graduated 80/95/100% throttle, the
detach-or-deadline rule, heartbeats, and a status line computed from the
log — and the session asserts the two seats agree on what the morning may
say (spec §3.4: computed, never narrated; the plan's standing gate).

The executor is the seat's own `ScriptedExecutor` — simulated work behind
the two-method seam the engine and GPU stations will implement. That the
work is scripted is the M1 slice's documented shape (plan §2 M1 risks);
that the rails, the throttle and the status line are real is the point.
"""

from __future__ import annotations

from typing import Callable


class NightRunnerSeat:
    def __init__(self, seats) -> None:
        self.night = seats.night

    # -- a scripted night, the same shape as the spine's --------------------------

    def run_reference_night(
        self,
        *,
        night_id: str,
        tasks: list[dict],           # [{id, intention, ask{gpu,wall}, script{...}}]
        rails: dict,                 # {gpu_minutes, wall_minutes, hosted_cents}
        load_budget: dict[str, int] | None = None,
        detach_after_min: int = 30,
    ) -> dict:
        """Play one night on the seat's own ledger; return what it produced."""
        n = self.night
        ledger = n.InMemoryLedger()
        clock = n.ScriptedClock("2026-10-30T21:20:00Z")

        executor = n.ScriptedExecutor()
        task_models = []
        for spec in tasks:
            ask = spec.get("ask", {})
            task_models.append(
                n.Task(
                    id=spec["id"],
                    intention=spec["intention"],
                    owner_character=spec.get("owner_character", "prop-maker"),
                    recipe_scope=spec.get("recipe_scope", []),
                    cost_estimate=n.Rail(**ask),
                    rail=n.Rail(**ask),
                )
            )
            script = spec.get("script", {})
            executor.script(
                spec["id"],
                n.ScriptedTask(
                    model=script.get("model"),
                    gpu_minutes=script.get("gpu_minutes"),
                    wall_minutes=script.get("wall_minutes"),
                    actual_wall_minutes=script.get("actual_wall_minutes"),
                    outcome=script.get("outcome", "kept"),
                    reason=script.get("reason"),
                    degraded=script.get("degraded", False),
                    artifact=script.get("artifact"),
                ),
            )

        runner = n.NightRunner(
            ledger, executor,
            night_id=night_id, rails=n.Rail(**rails), clock=clock,
            load_budget=load_budget, detach_deadline_minutes=detach_after_min,
        )
        runner.start(task_models)
        runner.run()
        status = runner.stop()
        report = n.build_report(ledger.events())

        return {
            "status": {"status": status.status, "reason": status.reason,
                       "variant": getattr(status, "variant", None)},
            "report_text": report.text if hasattr(report, "text") else "",
            "report": report,
            "ledger": ledger,
            "events": [
                {"seq": e.seq, "type": e.type, "payload": e.payload}
                for e in ledger.events()
            ],
        }

    # -- the resume rule (§5.2 step 5), for the kill -9 parity ---------------------

    def night_killed_mid_run(
        self,
        *,
        night_id: str,
        tasks: list[dict],
        rails: dict,
    ) -> dict:
        """Start a night, 'kill' it (drop the runner object — only the log
        survives), rebuild it from the log and stop it: the morning's status
        must be computed from the heartbeats alone (§5.4's extension)."""
        n = self.night
        ledger = n.InMemoryLedger()
        clock = n.ScriptedClock("2026-10-30T21:20:00Z")
        executor = n.ScriptedExecutor()
        task_models = []
        for spec in tasks:
            ask = spec.get("ask", {})
            task_models.append(
                n.Task(id=spec["id"], intention=spec["intention"],
                       cost_estimate=n.Rail(**ask), rail=n.Rail(**ask))
            )
            executor.script(
                spec["id"],
                n.ScriptedTask(gpu_minutes=spec.get("script", {}).get("gpu_minutes"),
                               outcome=spec.get("script", {}).get("outcome", "kept")),
            )

        runner = n.NightRunner(
            ledger, executor, night_id=night_id, rails=n.Rail(**rails), clock=clock
        )
        runner.start(task_models)
        # the kill: nothing but the ledger survives the process
        del runner

        resumed = n.NightRunner.resume(
            ledger, n.ScriptedExecutor(), night_id=night_id, clock=clock
        )
        status = resumed.stop()
        return {"status": {"status": status.status, "reason": status.reason}}
