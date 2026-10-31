"""POST /v1/call (§3.1): utterance + client view (or kid chips) → a
ContextPacket → compile → a question XOR a draft. Never guess: when the
top-2 candidate referent sets are both plausible, the second line is a
question naming candidates by what they are.

Kid actors cannot submit free text — refused by actor class in code and
audited as call.refused (§4.1); there is nothing of Magnus's to retain.

The compile here is deterministic (referents through the node registry,
acceptance and estimates from the request's intent hints); the model-driven
compiler is a later work item — the flow, states, guards and the
question-XOR-draft contract are what this half owns.
"""
from __future__ import annotations

from ..canon import canonical_bytes, new_id, now_utc
from ..errors import Refused
from ..events import Actor, core_actor, owner_actor
from ..models import (
    Budget,
    ContextPacket,
    ConvLabel,
    Estimate,
    History,
    Origin,
    ProjectState,
    Rail,
    View,
    enforce_packet_bounds,
)


class CallService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    # ------------------------------------------------------------- entry

    def handle(self, actor: Actor, *, utterance: str | None = None,
               chips: list[str] | None = None, view: dict | None = None,
               conversation: list[dict] | None = None, intent: dict | None = None,
               idem_key: str | None = None) -> dict:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return cached["body"]
        kid = actor.id in self.store.kid_actors
        if kid and utterance:
            ev = self.store.new_event(
                "call.refused", actor, {"entity_kind": "call", "entity_id": actor.id},
                {"reason": "kid actor class cannot submit free text (§4.1)",
                 "utterance_present": True},
            )
            self.store.append(ev)
            raise Refused(
                "kid actors cannot submit free text — the privacy rule is structure, "
                "not policy (§4.1); chips only")
        view = view or {}
        packet = self.capture_packet(actor, view, conversation or [])
        if chips:
            return self._handle_chips(actor, packet, chips, intent or {})
        if not utterance:
            raise Refused("an utterance (owner) or chips (kid) is required")
        return self.compile(actor, packet, utterance, intent or {}, idem_key=idem_key)

    # ------------------------------------------------------------- packet capture (§1.4)

    def capture_packet(self, actor: Actor, view: dict, conversation: list[dict]) -> ContextPacket:
        v = View(
            selection=list(view.get("selection", [])),
            params=dict(view.get("params", {})),
            gaze=view.get("gaze"),
            position=tuple(view.get("position", (0.0, 0.0, 0.0))),
            region=view.get("region"),
        )
        branch = view.get("branch") or self._main_branch_id() or ""
        head = ""
        row = self.store.get_row("branches", {"id": branch}) if branch else None
        if row is not None:
            head = row["payload"].get("head", "")
            # referents resolved through the node registry at the branch head
            v.referents = [r.model_dump(mode="json") for r in
                           self.core.registry.resolve(branch, v.selection)]
        packet = ContextPacket(
            id=new_id("packet"), actor=actor.id, view=v,
            history=self._history(), project=self._project_state(branch, head),
            conversation=[ConvLabel(**c) for c in conversation],
        )
        packet = enforce_packet_bounds(packet)
        return packet

    def _history(self) -> History:
        changes = [
            {"ver": e.payload.get("id", e.subject_id), "actor": e.actor.get("id", ""),
             "line": e.payload.get("note", "recipe change")}
            for e in self.store.events_since(0, types=["version.committed"])[-10:]
        ]
        renders = [
            (e.artifact or {}).get("sha256", "") for e in
            self.store.events_since(0, types=["render.completed"])[-3:]
        ]
        critic_notes = [
            {"at": e.at, "node": e.payload.get("node", ""),
             "reason_code": e.payload.get("reason_code", ""),
             "line": e.payload.get("line", "")}
            for e in self.store.events_since(0, types=["critic.verdict"])[-5:]
        ]
        open_wos = [
            {"id": w["id"], "title": w["payload"].get("title", ""), "state": w.get("state")}
            for w in self.store.scan("work_orders")
            if w.get("state") in ("draft", "queued", "building", "testing", "parked")
        ][-8:]
        landed = [
            {"id": w["id"], "title": w["payload"].get("title", ""),
             "outcome": w.get("state"), "touched": w["payload"].get("targets", [])}
            for w in self.store.scan("work_orders") if w.get("state") in ("kept",)
        ][-3:]
        return History(recipe_changes=changes, renders=renders, critic_notes=critic_notes,
                       work_orders_open=open_wos, landed_work_orders=landed)

    def _project_state(self, branch: str, head: str) -> ProjectState:
        gaps = [w["word"] for w in self.store.scan("vocab_words")
                if w.get("status") == "coming-soon"][:8]
        budget = {"gpu_minutes": 360, "hosted_cents": 0, "wall_minutes": 560}
        running = [n for n in self.store.scan("nights") if n.get("state") == "running"]
        if running:
            budget = running[0]["payload"].get("rails", budget)
        return ProjectState(
            branch=branch, head=head, budget_left_tonight=Rail(**budget),
            vocabulary_gaps=gaps, engine_pin={}, world_time=now_utc()[11:16],
        )

    def _main_branch_id(self) -> str | None:
        mains = [b for b in self.store.scan("branches") if b.get("purpose") == "main"]
        return mains[0]["id"] if mains else None

    # ------------------------------------------------------------- chips (kid path)

    def _handle_chips(self, actor: Actor, packet: ContextPacket, chips: list[str],
                      intent: dict) -> dict:
        from .tasks import TasksService
        from .work_orders import WorkOrdersService

        landed: list[dict] = []
        wos = WorkOrdersService(self.core)
        for chip in chips:
            if chip.startswith("computer:"):
                # "ask the Computer": Magnus proposes, Casey confirms (X C8/D4)
                wo = wos.file(
                    actor, Origin(channel="chip", packet=packet.id,
                                  character_line=None),
                    title=chip.removeprefix("computer:")[:80],
                    goal=intent.get("goal", chip.removeprefix("computer:")),
                    targets=[r["node_id"] for r in packet.view.referents],
                )
                landed.append({"kind": "work_order", "id": wo.id,
                               "addressed_to": "casey", "state": wo.state})
            else:
                task = TasksService(self.core).create(
                    author=actor.id, intention=chip, owner_character="companion",
                    ends_at=intent.get("kid_lane_ends_at"),
                )
                landed.append({"kind": "task", "id": task.id, "state": task.state,
                               "author": actor.id})
        return {"packet": packet.model_dump(mode="json"), "chips": landed}

    # ------------------------------------------------------------- compile (§3.1)

    def compile(self, actor: Actor, packet: ContextPacket, utterance: str,
                intent: dict, *, idem_key: str | None = None) -> dict:
        """1. resolve referents; 2. ambiguity → question, never guess;
        3. draft with goal/targets/acceptance/estimate; 4. the confirm line
        carries the ≤ 25-word spec sentence + BOTH price lines."""
        from .questions import QuestionsService
        from .work_orders import WorkOrdersService

        wos = WorkOrdersService(self.core)
        packet_artifact = self.store.artifacts.put(
            canonical_bytes(packet.model_dump(mode="json")), "context.packet")
        origin = Origin(channel="voice" if actor.kind == "owner" else "text",
                        packet=packet.id, utterance=utterance
                        if actor.kind == "owner" else None)
        wo = wos.file(
            actor, origin, (intent.get("title") or utterance)[:80],
            goal=intent.get("goal", utterance), targets=[],
            acceptance=intent.get("acceptance"),
            budget=Budget(**intent["budget"]) if intent.get("budget") else Budget(),
            vocabulary_gap=intent.get("vocabulary_gap"),
            packet_snapshot=packet.model_dump(mode="json"),
            packet_artifact=packet_artifact,
        )
        candidates = self._referent_candidates(packet)
        if len(candidates) >= 2 and not intent.get("force_draft"):
            q = QuestionsService(self.core).park(
                core_actor(), name=self._ambiguity_question(candidates),
                branch=packet.project.branch, wo=wo.id,
                options=[c["label"] for c in candidates[:2]],
            )
            response = {"packet": packet.id, "work_order": wo.id,
                        "question": q.model_dump(mode="json")}
            wos.question(wo.id, q.id, candidates[:2],
                         idem_key=idem_key, response_builder=lambda e: response)
            return response
        # single plausible referent set → draft
        targets = candidates[0]["nodes"] if candidates else packet.view.selection
        estimate = self._estimate(intent)
        confirm_line = self._confirm_line(wo, targets, estimate, intent, packet)

        def build_response(e) -> dict:
            return {"packet": packet.id, "work_order": e.subject_id,
                    "draft": wos.get(e.subject_id).model_dump(mode="json")}

        draft = wos.compile_draft(
            wo.id, title=(intent.get("title") or utterance)[:80],
            goal=intent.get("goal", utterance), targets=targets,
            acceptance=intent.get("acceptance") or [
                {"kind": "test_suite", "spec": {"suite": "default"}}],
            budget=Budget(**intent["budget"]) if intent.get("budget") else None,
            estimate=estimate, confirm_line=confirm_line,
            vocabulary_gap=intent.get("vocabulary_gap"),
            promote=intent.get("promote"),
            idem_key=idem_key, response_builder=build_response,
        )
        return {"packet": packet.id, "work_order": draft.id,
                "draft": draft.model_dump(mode="json")}

    def _referent_candidates(self, packet: ContextPacket) -> list[dict]:
        """Deterministic: candidate referent sets from selection ∪ region,
        grouped by region — if selection spans two groups, both {group} and
        {whole selection} are plausible and the core asks."""
        selection = packet.view.selection
        if not selection:
            return []
        referents = {r["node_id"]: r for r in packet.view.referents}
        groups: dict[str, list[str]] = {}
        for nid in selection:
            ref = referents.get(nid)
            region = (ref.get("entry_path", "").split(".")[0] if ref else "") or \
                (packet.view.region or "")
            groups.setdefault(region, []).append(nid)
        if len(groups) <= 1:
            return [{"label": self._group_label(selection, referents), "nodes": selection}]
        whole = [{"label": self._group_label(selection, referents), "nodes": selection}]
        parts = [{"label": self._group_label(nodes, referents), "nodes": nodes}
                 for _, nodes in sorted(groups.items())]
        return parts + whole

    @staticmethod
    def _group_label(nodes: list[str], referents: dict) -> str:
        if not nodes:
            return "nothing selected"
        first = nodes[0]
        ref = referents.get(first)
        if ref:
            return f"the {ref.get('entry_path', first).split('.')[-1]} ({first})"
        return f"the selection starting at {first}"

    def _ambiguity_question(self, candidates: list[dict]) -> str:
        a, b = candidates[0]["label"], candidates[1]["label"]
        return f"{a.capitalize()}, or {b}?"

    def _estimate(self, intent: dict) -> Estimate:
        est = intent.get("estimate") or {}
        return Estimate(
            build_verify=Rail(**est.get("build_verify", {"gpu_minutes": 0, "wall_minutes": 30})),
            generate_test=Rail(**est.get("generate_test", {"gpu_minutes": 0, "wall_minutes": 60})),
            basis=est.get("basis", "estimate"),
        )

    def _confirm_line(self, wo, targets: list[str], estimate: Estimate,
                      intent: dict, packet: ContextPacket) -> str:
        spec = intent.get("spec_sentence") or (wo.goal or wo.title)
        reverse = f"reversible at {packet.project.head or 'head'}"
        return (
            f"CONFIRM: {spec}; "
            f"build/verify: {self._fmt_rail(estimate.build_verify)} · "
            f"generate/test: {self._fmt_rail(estimate.generate_test)} · "
            f"{reverse}. Go?"
        )

    @staticmethod
    def _fmt_rail(rail: Rail) -> str:
        if rail.gpu_minutes > 0:
            return f"~{rail.gpu_minutes / 60:.1f} GPU-h [e]"
        return f"~{rail.wall_minutes:.0f} min [e]"
