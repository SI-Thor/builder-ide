"""The night window (§1.9, §3.2, §3.4): start with a pre-flight that may
propose but never decide, heartbeats (night.tick), the kill-switch stop,
and the four-value status line COMPUTED from the ledger — heartbeats and
admission waits, never narrated, so it survives the failure it describes
and cannot be written by whoever happens to be awake.

The night *runner* (job execution) is the other half of the skeleton; this
service owns the durable records and every computation over them.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..canon import night_id as make_night_id, now_utc
from ..errors import NotFound, Refused
from ..events import Actor, core_actor
from ..models import Night, Rail
from ..night.cost.estimates import owner_estimate
from ..night.cost.model import get_model

TICK_NOMINAL_SECONDS = 60
GAP_THRESHOLD_SECONDS = 300  # a dark stretch > 5 min is a heartbeat gap


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


class NightsService:
    def __init__(self, core, settings) -> None:
        self.core = core
        self.store = core.store
        self.settings = settings

    # ------------------------------------------------------------- start

    def start(self, actor: Actor, *, rails: Rail | None = None,
              detach_after_min: int = 30, load_budget: dict[str, int] | None = None,
              power_mode: int = 0, idem_key: str | None = None) -> dict:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return cached["body"]
        running = [n for n in self.store.scan("nights") if n.get("state") == "running"]
        if running:
            raise Refused(f"night {running[0]['id']} is already running", night=running[0]["id"])
        taken = frozenset(n["id"] for n in self.store.scan("nights"))
        nid = make_night_id(taken=taken)
        started_at = now_utc()
        deadline = (_parse(started_at) + timedelta(minutes=detach_after_min)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        # the bar comes from the cost model — the spec's 360 GPU-min / 560
        # wall-min, in one place, so the code and the document cannot drift.
        night_rails = rails or get_model().default_night_rails()
        night = Night(
            id=nid, started_at=started_at, rails=night_rails,
            load_budget=load_budget or {}, power_mode=power_mode,
            batch_start="both", detach_deadline=deadline, state="running",
        )
        # the owner's two lines, written before the night spends anything: what
        # tonight will cost, and whether it fits (the morning quotes them back).
        from .tasks import TasksService

        plan = TasksService(self.core).plan()
        estimate = owner_estimate(plan, night_rails)
        with self.store.batch():
            ev = self.store.new_event(
                "night.started", actor, {"entity_kind": "night", "entity_id": nid},
                {"night": night.model_dump(mode="json"), "rails": night.rails.model_dump(mode="json"),
                 "detach_deadline": deadline, "estimate": estimate.as_dict()},
            )
            self.store.append(ev)
            if power_mode:
                self.core.power.set_mode(power_mode)  # record-only by default (§5.5)
                self.store.append(self.store.new_event(
                    "power.mode.set", core_actor(),
                    {"entity_kind": "night", "entity_id": nid},
                    {"mode": power_mode, "at": started_at},
                ))
            # the slate becomes the queue: slated tasks join the night (§3.2)
            TasksService(self.core).attach_slate_to_night(nid)
            preflight = self.preflight(nid, actor)
        return {
            "night": self.get(nid).model_dump(mode="json"),
            "preflight": preflight,
            "preflight_line": preflight["line"],
            "estimate": estimate.as_dict(),
        }

    def preflight(self, night_id: str, actor: Actor) -> dict:
        """§3.2.2: lane load, queue depth, telemetry; proposes start-late /
        start-degraded / cancel — never decides. If telemetry is blind it
        says so, never guesses."""
        night = self.get(night_id)
        load = self.core.telemetry.lane_load()
        queue = [t for t in self.store.scan("tasks")
                 if t.get("state") in ("slated", "queued")]
        lane_free = load is not None and load < 0.9
        proposals: list[str] = []
        if load is None:
            telemetry_ok = False
            line = (f"PREFLIGHT: telemetry blind · queue {len(queue)} items · client "
                    f"detach: on close or {night.detach_deadline}, whichever first · "
                    "status will be `did not run — unknown (no telemetry)` if nothing "
                    "else is recorded — never guessed.")
        elif lane_free:
            telemetry_ok = True
            line = (f"PREFLIGHT: lane free (load {load:.1f}) · queue {len(queue)} items · "
                    f"client detach: on close or {night.detach_deadline}, whichever "
                    "first · plan starts on time.")
        else:
            telemetry_ok = True
            proposals = ["start late (admission re-checked on the 10-min tick)",
                         "start degraded (scripted checks only, renders deferred)",
                         "cancel"]
            line = (f"PREFLIGHT: lane BUSY (load {load:.1f}) · queue {len(queue)} items · "
                    f"client detach: on close or {night.detach_deadline}, whichever first · "
                    "proposals: " + " / ".join(proposals) + " — the pre-flight proposes, "
                    "the owner decides.")
        payload = {"night": night_id, "lane_load": load, "queue_depth": len(queue),
                   "telemetry_ok": telemetry_ok, "lane_free": lane_free,
                   "proposals": proposals, "line": line,
                   "at": now_utc()}
        ev = self.store.new_event(
            "night.preflight", core_actor(), {"entity_kind": "night", "entity_id": night_id},
            {"preflight": payload},
        )
        self.store.append(ev)
        return payload

    # ------------------------------------------------------------- heartbeat

    def tick(self, night_id: str, *, at: str | None = None, load: float | None = None) -> None:
        if self.store.get_row("nights", {"id": night_id}) is None:
            raise NotFound(f"night {night_id} not found", entity=night_id)
        ev = self.store.new_event(
            "night.tick", core_actor(), {"entity_kind": "night", "entity_id": night_id},
            {"at": at or now_utc(), "load": load},
        )
        self.store.append(ev)

    # ------------------------------------------------------------- stop

    def stop(self, night_id: str, actor: Actor, *, reason: str = "owner stop",
             idem_key: str | None = None) -> dict:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return cached["body"]
        night = self.get(night_id)
        if night.state == "stopped":
            return {"night": night.model_dump(mode="json"), "already_stopped": True}
        from .report import ReportBuilder

        with self.store.batch():
            status = self.compute_status(night_id)
            report = ReportBuilder(self.core).build(night_id)
            report_artifact = self.core.store.artifacts.put(
                report["json_bytes"], "report.json")
            text_artifact = self.core.store.artifacts.put(
                report["text_bytes"], "report.txt")
            calibration = self._calibration(night)
            calibration_artifact = self.core.store.artifacts.put(
                json.dumps(calibration, indent=2, sort_keys=True).encode("utf-8"),
                "calibration.json")
            ev = self.store.new_event(
                "night.stopped", actor, {"entity_kind": "night", "entity_id": night_id},
                {"stopped_at": now_utc(), "reason": reason, "status": status["status"],
                 "status_reason": status["reason"], "lost_minutes": status.get("lost_minutes", 0),
                 "report": {"json": report_artifact, "text": text_artifact},
                 "calibration": {"json": calibration_artifact}},
            )
            _, resp = self.store.append(
                ev, idem_key=idem_key,
                response_builder=lambda e: {
                    "night": self.get(night_id).model_dump(mode="json"),
                    "status": status, "report": report["doc"],
                    "calibration": calibration})
        if resp and resp.get("__replay__"):
            return resp["body"]
        return {"night": self.get(night_id).model_dump(mode="json"), "status": status,
                "report": report["doc"], "calibration": calibration}

    def _calibration(self, night) -> dict:
        """The night's calibration report, read out of the night's own log.

        A judgment is only worth scoring once something has answered it, so
        the fold pairs each judgment with the outcome that speaks about the
        same scope, after it. The report is the same one the morning
        carries a line from, so the two cannot disagree.
        """
        from core.judge.tracking import calibration_report

        events = [
            event
            for event in self.store.events_since(0)
            if event.at >= night.started_at
            and (not night.stopped_at or event.at <= night.stopped_at)
        ]
        try:
            return calibration_report(events).as_dict()
        except Exception:
            # a broken log must not lose the morning
            return {
                "confidence_definition": "top_probability",
                "n_judgments": 0,
                "n_scored": 0,
                "n_unscored": 0,
                "cells": [],
                "drift": [],
            }

    # ------------------------------------------------------------- reads

    def get(self, night_id: str) -> Night:
        row = self.store.get_row("nights", {"id": night_id})
        if row is None:
            raise NotFound(f"night {night_id} not found", entity=night_id)
        return Night(**row["payload"])

    def list(self) -> list[Night]:
        return [Night(**r["payload"]) for r in self.store.scan("nights")]

    def batches_may_start(self, night_id: str) -> dict:
        """Detach-gating (§1.9): big batches start on client detach OR the
        deadline, whichever first — the absent client never blocks the night."""
        night = self.get(night_id)
        detached = []
        for row in self.store.scan("client_presence"):
            if not row.get("attached"):
                detached.append(row["payload"].get("actor"))
        any_detached = bool(detached)  # any known client has detached
        now = _parse(now_utc())
        deadline_passed = night.detach_deadline is not None and now >= _parse(night.detach_deadline)
        return {
            "night": night_id,
            "client_detached": any_detached,
            "deadline_passed": deadline_passed,
            "deadline": night.detach_deadline,
            "batches_may_start": night.batch_start == "both" and (any_detached or deadline_passed)
            or (night.batch_start == "detach" and any_detached)
            or (night.batch_start == "deadline" and deadline_passed),
        }

    # ------------------------------------------------------------- the status line (§3.4)

    def compute_status(self, night_id: str) -> dict:
        row = self.store.get_row("nights", {"id": night_id})
        if row is None:
            return {"status": "did_not_run",
                    "reason": "no plan was started.",
                    "line": "did not run — no plan was started.", "lost_minutes": 0}
        doc = row["payload"]
        started = _parse(doc["started_at"])
        stopped = _parse(doc["stopped_at"]) if doc.get("stopped_at") else _parse(now_utc())
        ticks = sorted(
            _parse(ev.at) for ev in self.store.events_for("night", night_id, ["night.tick"]))
        preflight = None
        for ev in self.store.events_for("night", night_id, ["night.preflight"]):
            preflight = ev.payload.get("preflight", {})
        # facts
        degraded_verdicts = [
            ev for ev in self.store.events_since(0, types=["critic.verdict"])
            if ev.payload.get("degraded")
            and (not doc.get("started_at") or ev.at >= doc["started_at"])
        ]
        admission_waits = [
            ev for ev in self.store.events_since(0, types=["job.requeued"])
            if any(w in str(ev.payload.get("reason", "")).lower() for w in ("lane", "cap", "admission", "busy"))
        ]
        cut_tasks = [t for t in self.store.scan("tasks")
                     if t.get("state") == "cut" and t["payload"].get("night") == night_id]
        threshold_cuts = [
            ev for ev in self.store.events_for("night", night_id, ["budget.threshold"])
            if ev.payload.get("cut")
        ]

        if not ticks:
            lane_busy = bool(preflight and preflight.get("lane_load") is not None
                             and not preflight.get("lane_free"))
            if lane_busy:
                return {"status": "did_not_run", "lost_minutes": 0,
                        "reason": "the GPU spent the night on a foreign job; ours queued "
                                  "and was never admitted.",
                        "line": "did not run — busy: the GPU spent the night on a foreign "
                                "job. Ours queued and was never admitted."}
            if preflight is None or preflight.get("telemetry_ok") is False:
                return {"status": "did_not_run", "lost_minutes": 0,
                        "reason": "unknown (no telemetry)",
                        "line": "did not run — unknown (no telemetry). A status line may "
                                "be uncertain, never fabricated."}
            off_from = doc.get("started_at", "")
            return {"status": "did_not_run", "lost_minutes": 0,
                    "reason": f"the Thor was off from {off_from[11:16]}. Nothing ran; "
                              "nothing was lost.",
                    "line": f"did not run — off: the Thor was off from {off_from[11:16]}. "
                            "Nothing ran; nothing was lost. Your plan is unstarted, unchanged."}

        # heartbeat coverage: dark gaps between coverage points
        points = [started] + ticks + [stopped]
        lost_seconds = 0
        for a, b in zip(points, points[1:]):
            span = (b - a).total_seconds()
            if span > GAP_THRESHOLD_SECONDS:
                lost_seconds += span - GAP_THRESHOLD_SECONDS
        lost_minutes = round(lost_seconds / 60, 1)

        if cut_tasks or threshold_cuts or lost_minutes > GAP_THRESHOLD_SECONDS / 60:
            parts = []
            if cut_tasks:
                parts.append(f"{len(cut_tasks)} task(s) cut at the bar "
                             f"({', '.join(t['payload'].get('intention', t['id'])[:40] for t in cut_tasks[:2])})")
            if lost_minutes > 0:
                parts.append(f"lost {lost_minutes:.0f} min to a dark stretch")
            reason = "; ".join(parts) + " — the cut is named, re-queued for tonight"
            return {"status": "ran_short", "lost_minutes": lost_minutes, "reason": reason,
                    "line": f"ran short — {reason}"}
        if degraded_verdicts or admission_waits:
            bits = []
            if admission_waits:
                bits.append(f"{len(admission_waits)} admission wait(s) on the lane")
            if degraded_verdicts:
                bits.append(f"{len(degraded_verdicts)} verdict(s) ran scripted-only "
                            "(verdict@scripted) — see their cards")
            reason = "; ".join(bits) + " · nothing failed outright"
            return {"status": "ran_degraded", "lost_minutes": 0, "reason": reason,
                    "line": f"ran degraded — {reason}"}
        return {"status": "ran_as_planned", "lost_minutes": 0, "reason": "nothing failed",
                "line": "ran as planned"}
