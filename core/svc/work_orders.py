"""Work orders: schema, states and transitions exactly as §1.3 defines
them, persisted through the ledger. Every arrow in the transition table is
one audit event; guards run in the service BEFORE the append, compare-
and-swap runs in the fold, and a stale transition fails closed (§5.3).
Multi-event operations (keep/reject, edit-and-refile) run in one store
batch so an Idempotency-Key covers the whole decision atomically."""
from __future__ import annotations

from typing import Any

from ..canon import new_id, now_utc
from ..errors import NotFound, Refused
from ..events import Actor, core_actor
from ..models import (
    CHECKABLE_KINDS,
    AcceptanceCheck,
    Attempt,
    Budget,
    Deliverable,
    Estimate,
    Evidence,
    Origin,
    Rail,
    WorkOrder,
    confirm_line_valid,
)
from ..store import LedgerStore


class WorkOrdersService:
    def __init__(self, core) -> None:
        self.core = core
        self.store: LedgerStore = core.store

    # ------------------------------------------------------------- helpers

    def get(self, wo_id: str) -> WorkOrder:
        row = self.store.get_row("work_orders", {"id": wo_id})
        if row is None:
            raise NotFound(f"work order {wo_id} not found", entity=wo_id)
        return WorkOrder(**row["payload"])

    def list(self, state: str | None = None) -> list[WorkOrder]:
        out = []
        for row in self.store.scan("work_orders"):
            if state and row.get("state") != state:
                continue
            out.append(WorkOrder(**row["payload"]))
        return out

    def _spend_so_far(self, wo_id: str) -> Rail:
        wo = self.get(wo_id)
        if wo.spend_so_far:
            return Rail(**wo.spend_so_far)
        return Rail()

    # ------------------------------------------------------------- filing & compile

    def file(
        self,
        filed_by: Actor,
        origin: Origin,
        title: str,
        *,
        goal: str = "",
        targets: list[str] | None = None,
        vocabulary_gap: dict | None = None,
        acceptance: list[dict] | None = None,
        budget: Budget | None = None,
        branch: str | None = None,
        packet_snapshot: dict | None = None,
        packet_artifact: dict | None = None,
    ) -> WorkOrder:
        wo = WorkOrder(
            id=new_id("work_order"), filed_by=filed_by, origin=origin, title=title,
            goal=goal, targets=targets or [], vocabulary_gap=vocabulary_gap,
            acceptance=acceptance or [], budget=budget or Budget(), branch=branch,
        )
        payload: dict[str, Any] = {"work_order": wo.model_dump(mode="json")}
        if packet_snapshot is not None:
            payload["packet_snapshot"] = packet_snapshot
        ev = self.store.new_event(
            "wo.filed", filed_by, {"entity_kind": "work_order", "entity_id": wo.id},
            payload, artifact=packet_artifact,
        )
        self.store.append(ev)
        return self.get(wo.id)

    def compile_draft(
        self, wo_id: str, *, title: str, goal: str, targets: list[str],
        acceptance: list[dict], budget: Budget | None, estimate: Estimate | None,
        confirm_line: str, vocabulary_gap: dict | None = None,
        promote: dict | None = None, idem_key: str | None = None,
        response_builder=None,
    ) -> WorkOrder:
        """compiling → draft. Guards (§1.3): confirm_line ≤ 25-word spec
        sentence AND both price lines; ≥ 1 machine-checkable acceptance
        check; `manual` checks only on owner-filed orders."""
        wo = self.get(wo_id)
        if wo.state != "compiling":
            raise Refused(f"work order {wo_id} is {wo.state}, not compiling", entity=wo_id)
        try:
            checks = [AcceptanceCheck(**a) for a in acceptance]
        except Exception as e:
            raise Refused(f"acceptance checks are not schema-valid: {e}", entity=wo_id) from e
        if not any(a.kind in CHECKABLE_KINDS for a in checks):
            raise Refused(
                "a work order needs ≥ 1 machine-checkable acceptance check to compile "
                "(§1.3 guard)", entity=wo_id)
        if any(a.kind == "manual" for a in checks) and wo.filed_by.kind != "owner":
            raise Refused(
                "a manual check can exist only on owner-filed orders (§1.3)", entity=wo_id)
        if estimate is None or not confirm_line_valid(confirm_line, estimate):
            raise Refused(
                "confirm line invalid: ≤ 25-word spec sentence and BOTH price lines "
                "(build/verify and generate/test) are required — a one-line estimate "
                "is a build failure (§3.1)", entity=wo_id)
        ev = self.store.new_event(
            "wo.compiled", core_actor(), {"entity_kind": "work_order", "entity_id": wo_id},
            {
                "from_state": "compiling", "title": title, "goal": goal,
                "targets": targets, "acceptance": [a.model_dump() for a in checks],
                "budget": (budget or wo.budget).model_dump(mode="json"),
                "estimate": estimate.model_dump(mode="json") if estimate else None,
                "confirm_line": confirm_line, "vocabulary_gap": vocabulary_gap,
                "promote": promote,
            },
        )
        self.store.append(ev, idem_key=idem_key, response_builder=response_builder)
        return self.get(wo_id)

    def question(self, wo_id: str, question_id: str, candidates: list[dict],
                 *, idem_key: str | None = None, response_builder=None) -> WorkOrder:
        """compiling → questioned [≥ 2 plausible referent sets] — NEVER guess."""
        wo = self.get(wo_id)
        if len(candidates) < 2:
            raise Refused("questioning requires ≥ 2 plausible referent sets (§1.3)", entity=wo_id)
        if wo.state != "compiling":
            raise Refused(f"work order {wo_id} is {wo.state}, not compiling", entity=wo_id)
        ev = self.store.new_event(
            "wo.questioned", core_actor(),
            {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": "compiling", "question": question_id, "candidates": candidates},
        )
        self.store.append(ev, idem_key=idem_key, response_builder=response_builder)
        return self.get(wo_id)

    # ------------------------------------------------------------- confirm / cancel

    def confirm(self, wo_id: str, actor: Actor, answer: str, *,
                idem_key: str | None = None, amendments: dict | None = None) -> dict:
        """draft → queued on "go" [Idempotency-Key; budget admitted against
        night rail]. "no" cancels. "edit" cancels this draft and re-files an
        amended order (the spec's table has no draft→compiling arrow, and a
        wrong compile is cheap to reject — §3.1)."""
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return cached["body"]
        wo = self.get(wo_id)
        if answer == "go":
            if wo.state != "draft":
                raise Refused(f"work order {wo_id} is {wo.state}, not draft", entity=wo_id)
            self._admit_against_night_rail(wo)
            ev = self.store.new_event(
                "wo.confirmed", actor, {"entity_kind": "work_order", "entity_id": wo_id},
                {"from_state": "draft", "confirmed_by": actor.id},
            )
            with self.store.batch():
                _, resp = self.store.append(
                    ev, idem_key=idem_key,
                    response_builder=lambda e: self.get(wo_id).model_dump(mode="json"))
            if resp and resp.get("__replay__"):
                return resp["body"]
            return self.get(wo_id).model_dump(mode="json")
        if answer == "no":
            return self.cancel(wo_id, actor, idem_key=idem_key)
        if answer == "edit":
            with self.store.batch():
                self.cancel(wo_id, actor, idem_key=None)
                origin = wo.origin.model_copy(update={"utterance": None})
                new = self.file(
                    actor, origin, wo.title,
                    goal=amendments.get("goal", wo.goal) if amendments else wo.goal,
                    targets=amendments.get("targets", wo.targets) if amendments else wo.targets,
                    acceptance=(amendments.get("acceptance") if amendments else None)
                    or [a.model_dump() for a in wo.acceptance],
                    budget=wo.budget, vocabulary_gap=wo.vocabulary_gap,
                    branch=wo.branch,
                )
                est = amendments.get("estimate") if amendments else (
                    wo.estimate.model_dump(mode="json") if wo.estimate else None)
                line = amendments.get("confirm_line", wo.confirm_line) if amendments else wo.confirm_line
                drafted = self.compile_draft(
                    new.id, title=new.title, goal=new.goal, targets=new.targets,
                    acceptance=[a if isinstance(a, dict) else a.model_dump() for a in new.acceptance],
                    budget=new.budget, estimate=est, confirm_line=line,
                    vocabulary_gap=new.vocabulary_gap, promote=wo.promote,
                )
            return {"refiled": new.id, "work_order": drafted.model_dump(mode="json")}
        raise Refused(f"answer must be go|no|edit, got {answer!r}")

    def _admit_against_night_rail(self, wo: WorkOrder) -> None:
        night = wo.budget.night
        if not night:
            return
        row = self.store.get_row("nights", {"id": night})
        if row is None:
            raise Refused(f"night {night} does not exist; cannot admit", entity=wo.id)
        budget = self.store.get_row("budget", {"night": night})
        rails = Rail(**(row["payload"].get("rails") or {}))
        spend = (budget or {}).get("payload", {})
        per_order = wo.budget.per_order
        if (float(spend.get("gpu_minutes", 0)) + per_order.gpu_minutes > rails.gpu_minutes
                or float(spend.get("wall_minutes", 0)) + per_order.wall_minutes > rails.wall_minutes
                or int(spend.get("hosted_cents", 0)) + per_order.hosted_cents > rails.hosted_cents):
            raise Refused(
                "night rail cannot cover this order (admission refuses before spend, §5.5)",
                entity=wo.id, night=night)

    def cancel(self, wo_id: str, actor: Actor, *, idem_key: str | None = None) -> dict:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return cached["body"]
        wo = self.get(wo_id)
        if wo.state not in ("draft", "queued"):
            raise Refused(f"work order {wo_id} is {wo.state}; only draft/queued can cancel",
                          entity=wo_id)
        ev = self.store.new_event(
            "wo.cancelled", actor, {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": wo.state, "cancelled_by": actor.id},
        )
        _, resp = self.store.append(ev, idem_key=idem_key,
                                    response_builder=lambda e: self.get(wo_id).model_dump(mode="json"))
        if resp and resp.get("__replay__"):
            return resp["body"]
        return self.get(wo_id).model_dump(mode="json")

    # ------------------------------------------------------------- attempts & gate

    def start_attempt(self, wo_id: str, engineer: str) -> Attempt:
        """queued → building [seat built; rails pre-checked]."""
        wo = self.get(wo_id)
        if wo.state not in ("queued", "testing"):
            raise Refused(f"work order {wo_id} is {wo.state}; attempts start from queued "
                          "(or testing, as attempt n+1 after a failed gate)", entity=wo_id)
        n = (wo.attempts[-1].n + 1) if wo.attempts else 1
        # rails pre-checked (§2.2): per_attempt must fit the remaining per_order
        spent = self._spend_so_far(wo_id)
        per_order, per_attempt = wo.budget.per_order, wo.budget.per_attempt
        if (spent.gpu_minutes + per_attempt.gpu_minutes > per_order.gpu_minutes + 1e-9
                or spent.hosted_cents + per_attempt.hosted_cents > per_order.hosted_cents):
            self.fail(wo_id, "per_order rail cannot cover another attempt")
            raise Refused("per_order rail exhausted; order failed (§2.2)", entity=wo_id)
        seat_dir = self.core.settings.sandboxes_dir / wo_id / str(n)
        seat_dir.mkdir(parents=True, exist_ok=True)
        attempt = Attempt(
            n=n, engineer=engineer,
            seat=str(seat_dir.relative_to(self.core.settings.home)),
        )
        ev = self.store.new_event(
            "wo.attempt.started", core_actor(),
            {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": wo.state, "attempt": attempt.model_dump(mode="json")},
        )
        self.store.append(ev)
        return attempt

    def deliver(self, wo_id: str, deliverable: dict) -> WorkOrder:
        """building → testing [Deliverable schema-valid]."""
        wo = self.get(wo_id)
        if wo.state != "building":
            raise Refused(f"work order {wo_id} is {wo.state}, not building", entity=wo_id)
        if not wo.attempts:
            raise Refused("no attempt running", entity=wo_id)
        try:
            d = Deliverable(**deliverable)
        except Exception as e:
            raise Refused(f"deliverable is not schema-valid: {e}", entity=wo_id) from e
        if not any(e.kind == "test_run" for e in d.evidence):
            raise Refused("deliverable evidence must include ≥ 1 test_run (§2.1)", entity=wo_id)
        ev = self.store.new_event(
            "wo.attempt.delivered", core_actor(),
            {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": "building", "attempt_n": wo.attempts[-1].n,
             "deliverable": d.model_dump(mode="json")},
        )
        self.store.append(ev)
        return self.get(wo_id)

    def run_gate(self, wo_id: str) -> dict:
        """The merge gate (§2.3), ordered; any hard fail stops it. Engine
        rungs (deterministic rebuild, render ladder, analytic checks, critic)
        go through the MergeGateEngine seam — without that half the gate
        fails closed rather than landing unverified work."""
        wo = self.get(wo_id)
        if wo.state != "testing":
            raise Refused(f"work order {wo_id} is {wo.state}, not testing", entity=wo_id)
        results: list[dict] = []

        def fail(reason: str) -> dict:
            results.append({"check": "gate", "ok": False, "reason": reason})
            return {"passed": False, "checks": results}

        d = wo.last_deliverable or {}
        # 8. budget audit: claimed vs recorded spend (mismatch > 20% fails)
        claimed = (d.get("budget_spend") or {})
        recorded = self._spend_so_far(wo_id)
        for unit, got in (("gpu_minutes", recorded.gpu_minutes),
                          ("wall_minutes", recorded.wall_minutes)):
            want = float(claimed.get(unit, got))
            if want > 0 and abs(got - want) / want > 0.20:
                return fail(f"budget audit: {unit} recorded {got:.2f} vs claimed {want:.2f} (>20%)")
        results.append({"check": "budget_audit", "ok": True})
        # 7. licence scan: every new asset has a complete licence row
        for ev in self.store.events_for("work_order", wo_id, ["asset.created"]):
            licence = (ev.payload.get("asset", {}) or {}).get("licence", {})
            if not licence.get("spdx") or "dependency_terms" not in licence:
                return fail(f"licence scan: asset {ev.subject_id} lacks a complete row")
        results.append({"check": "licence_scan", "ok": True})
        # 1–6: engine-dependent rungs behind the seam
        try:
            checks = [
                {"kind": a.kind, "spec": a.spec} for a in wo.acceptance
                if a.kind in ("constraint", "geometry", "render_rung")
            ]
            engine_results = self.core.gate_engine.run_checks(checks) if checks else []
            if any(not r.get("ok") for r in engine_results):
                return fail(f"engine checks failed: "
                            f"{[r for r in engine_results if not r.get('ok')]}")
            results.extend(engine_results or [{"check": "engine", "ok": True, "note": "no engine checks"}])
            critic = next((a for a in wo.acceptance if a.kind == "critic"), None)
            if critic is not None:
                verdict = self.core.gate_engine.render_rung(
                    int(critic.spec.get("rung", 2)), int(critic.spec.get("seed", 0)))
                results.append({"check": "critic", "ok": True, "verdict": verdict})
        except Exception as e:
            return fail(f"engine seam unavailable: {e}")
        return {"passed": True, "checks": results}

    def land(self, wo_id: str, preview_artifact: dict, evidence: list[dict],
             gate: dict | None = None) -> WorkOrder:
        """testing → landed [all checks pass; preview artifact exists]."""
        wo = self.get(wo_id)
        if wo.state != "testing":
            raise Refused(f"work order {wo_id} is {wo.state}, not testing", entity=wo_id)
        if not preview_artifact.get("sha256") or not self.store.artifacts.has(preview_artifact["sha256"]):
            raise Refused("the preview artifact must exist before landed (§2.3)", entity=wo_id)
        for e in evidence:
            Evidence(**e)  # schema-valid evidence or refuse
        ev = self.store.new_event(
            "wo.landed", core_actor(), {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": "testing", "preview": preview_artifact,
             "evidence": evidence, "gate": gate or {}},
        )
        self.store.append(ev)
        return self.get(wo_id)

    def fail(self, wo_id: str, reason: str) -> WorkOrder:
        wo = self.get(wo_id)
        if wo.state not in ("testing", "building"):
            raise Refused(f"work order {wo_id} is {wo.state}; fail needs testing/building",
                          entity=wo_id)
        ev = self.store.new_event(
            "wo.failed", core_actor(), {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": wo.state, "gate": {"reason": reason}},
        )
        self.store.append(ev)
        return self.get(wo_id)

    # ------------------------------------------------------------- park / resume

    def park(self, wo_id: str, reason: str) -> WorkOrder:
        wo = self.get(wo_id)
        if wo.state not in ("queued", "building", "testing"):
            raise Refused(f"work order {wo_id} is {wo.state}; park needs queued/building/testing",
                          entity=wo_id)
        ev = self.store.new_event(
            "wo.parked", core_actor(), {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": wo.state, "park_reason": reason},
        )
        self.store.append(ev)
        return self.get(wo_id)

    def resume(self, wo_id: str, actor: Actor) -> WorkOrder:
        wo = self.get(wo_id)
        if wo.state != "parked":
            raise Refused(f"work order {wo_id} is {wo.state}, not parked", entity=wo_id)
        ev = self.store.new_event(
            "wo.resumed", actor, {"entity_kind": "work_order", "entity_id": wo_id},
            {"from_state": "parked", "resumed_by": actor.id},
        )
        self.store.append(ev)
        return self.get(wo_id)

    # ------------------------------------------------------------- keep / reject

    def keep(self, wo_id: str, actor: Actor, *, idem_key: str | None = None,
             reason_code: str | None = None) -> dict:
        """landed → kept. Promotion is one core transaction (§2.3): branch
        fast-forwarded, outstanding taste_keep predictions scored, the word
        activated, the character notified."""
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return cached["body"]
        wo = self.get(wo_id)
        if wo.state != "landed":
            raise Refused(f"work order {wo_id} is {wo.state}, not landed", entity=wo_id)
        from .predictions import PredictionsService
        from .taste import TasteService

        scored: list[str] = []
        promotion: dict | None = None

        def build(e) -> dict:
            return {
                "work_order": self.get(wo_id).model_dump(mode="json"),
                "promotion": promotion,
                "scored": scored,
            }

        with self.store.batch():
            scored = PredictionsService(self.core).score_taste_keep_on_branch(
                wo.branch or wo.id, actor, "keep")
            if wo.promote:
                word = wo.promote.get("word")
                ev = self.store.new_event(
                    "vocab.word.added", core_actor(),
                    {"entity_kind": "vocab_word", "entity_id": word},
                    {"word": word, "status": "active",
                     "entry": {**wo.promote, "status": "active"},
                     "provenance": {"origin": wo_id, "at": now_utc()}},
                )
                self.store.append(ev)
                promotion = {"word": word, "status": "active"}
            if wo.branch:
                self._merge_branch_on_keep(wo.branch, actor)
            if reason_code:
                TasteService(self.core).append_note(
                    actor, author=actor.id, subject={"work_order": wo_id},
                    artifact_ref=wo.branch or wo_id, verdict="keep",
                    reason_code=reason_code)
            ev = self.store.new_event(
                "wo.kept", actor, {"entity_kind": "work_order", "entity_id": wo_id},
                {"from_state": "landed", "decided_by": actor.id, "decided_at": now_utc(),
                 "promotion": promotion, "kept_branch": wo.branch},
            )
            _, resp = self.store.append(ev, idem_key=idem_key, response_builder=build)
        if resp and resp.get("__replay__"):
            return resp["body"]
        return build(ev)

    def reject(self, wo_id: str, actor: Actor, *, idem_key: str | None = None,
               reason_code: str | None = None) -> dict:
        """landed → rejected [branch retained; word stays coming-soon or
        retires]; taste_keep predictions on the branch score as miss."""
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return cached["body"]
        wo = self.get(wo_id)
        if wo.state != "landed":
            raise Refused(f"work order {wo_id} is {wo.state}, not landed", entity=wo_id)
        from .predictions import PredictionsService
        from .taste import TasteService

        scored: list[str] = []
        with self.store.batch():
            scored = PredictionsService(self.core).score_taste_keep_on_branch(
                wo.branch or wo.id, actor, "reject")
            if wo.branch and self.store.get_row("branches", {"id": wo.branch}) is not None:
                ev = self.store.new_event(
                    "branch.rejected", actor,
                    {"entity_kind": "branch", "entity_id": wo.branch},
                    {"retained": True},
                )
                self.store.append(ev)
            if reason_code:
                TasteService(self.core).append_note(
                    actor, author=actor.id, subject={"work_order": wo_id},
                    artifact_ref=wo.branch or wo_id, verdict="reject",
                    reason_code=reason_code)
            ev = self.store.new_event(
                "wo.rejected", actor, {"entity_kind": "work_order", "entity_id": wo_id},
                {"from_state": "landed", "decided_by": actor.id, "decided_at": now_utc()},
            )
            _, resp = self.store.append(
                ev, idem_key=idem_key,
                response_builder=lambda e: {
                    "work_order": self.get(wo_id).model_dump(mode="json"), "scored": scored})
        if resp and resp.get("__replay__"):
            return resp["body"]
        return {"work_order": self.get(wo_id).model_dump(mode="json"), "scored": scored}

    def _merge_branch_on_keep(self, branch_id: str, actor: Actor) -> None:
        """On keep the branch merges per the owner's choice. The pointer move
        onto main is a fast-forward here; when main moved meanwhile, a
        question is parked — ambiguity is resolved by asking, never by
        guessing (§1.2)."""
        row = self.store.get_row("branches", {"id": branch_id})
        if row is None:
            return
        head = row["payload"].get("head")
        mains = [b for b in self.store.scan("branches") if b.get("purpose") == "main"]
        if not mains:
            return
        main = mains[0]
        ev = self.store.new_event(
            "branch.head.moved", actor, {"entity_kind": "branch", "entity_id": main["id"]},
            {"from_head": main["payload"].get("head"), "to": head,
             "via": "wo.keep fast-forward"},
        )
        try:
            self.store.append(ev)
        except Exception:
            from .questions import QuestionsService

            QuestionsService(self.core).park(
                core_actor(),
                name=f"Merge {branch_id} into main: main moved meanwhile",
                branch=branch_id,
                options=["three-way merge at entry granularity (recipe half)",
                         "keep the branch unmerged"])

    # ------------------------------------------------------------- record spend

    def record_spend(self, wo_id: str, night: str | None, spend: dict) -> None:
        ev = self.store.new_event(
            "budget.spend", core_actor(),
            {"entity_kind": "work_order", "entity_id": wo_id},
            {"wo": wo_id, "night": night, "spend": spend},
        )
        self.store.append(ev)
        if night:
            from .nights import NightsService

            NightsService(self.core, self.core.settings).check_thresholds(night)
