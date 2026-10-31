"""The FastAPI service: core-spec v2 §4.2's endpoints and the SSE stream.

This module is the *door*, not the brain. Every endpoint is a thin shell over
a service in ``core/svc``; the service speaks to the ledger through audit
events and the ledger is the only source of truth. Nothing here holds state
that is not derivable from the log — that is what makes the kill -9 test
pass: reopen the service and the feed renders from the ledger alone
(§5.4).

Three rules the door has to keep:

  * **A token is an identity, not a permission** (§4.1). Owner tokens are per
    actor (``casey``, ``magnus``) and the actor gates the actor-scoped
    endpoints. A kid actor cannot submit free text — refused at the schema
    and audited as ``call.refused``.
  * **Side effects happen only after commit** (§5.1). The service calls the
    ledger first; the ledger commits (WAL + ``synchronous=FULL``) before
    anything observable happens.
  * **Idempotency-Key on every owner POST** (§5.3). The key maps to the
    committed event; a replay returns the original result and never a second
    state change. A doubled "Go" cannot start two attempts.

The endpoints owned by the other half — the recipe store, the compiler, the
engineer adapter — are answered with 501 ``other_half_unavailable``, naming
the seam, rather than faked.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .auth import (
    CHARACTER,
    OWNER,
    PANEL,
    Principal,
    current_principal,
    require,
    require_adult_owner,
)
from .boot import Boot
from .canon import canonical_json
from .config import Settings, default_settings
from .errors import (
    CoreError,
    NotFound,
    OtherHalfUnavailable,
    Refused,
    ValidationError,
)
from .events import Actor, character_actor, owner_actor
from .models import Asset, Rail
from .svc import Core
from .svc.budget import BudgetService
from .svc.call import CallService
from .svc.nights import NightsService
from .svc.predictions import PredictionsService
from .svc.questions import QuestionsService
from .svc.report import ReportBuilder
from .svc.tasks import TasksService
from .svc.taste import TasteService
from .svc.vocab import VocabService
from .svc.work_orders import WorkOrdersService

SSE_HEARTBEAT_SECONDS = 15.0
SSE_POLL_SECONDS = 0.25
SSE_MAX_SECONDS = 3600.0


# ------------------------------------------------------------------ bodies


class CallBody(BaseModel):
    """The owner's call: an utterance plus the client's view."""

    model_config = ConfigDict(extra="forbid")

    utterance: str = Field(min_length=1)
    chips: list[str] | None = None
    view: dict | None = None
    conversation: list[dict] = Field(default_factory=list)
    intent: dict | None = None


class ChipBody(BaseModel):
    """The kid's call: chips only. There is no ``utterance`` field — the
    privacy rule is structure, not policy (§4.1)."""

    model_config = ConfigDict(extra="forbid")

    chips: list[str] = Field(min_length=1)
    view: dict | None = None
    conversation: list[dict] = Field(default_factory=list)
    intent: dict | None = None


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Literal["go", "no", "edit"]
    amendments: dict | None = None


class VerdictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str | None = None
    words: str | None = None


class AnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)


class ParkQuestionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    options: list[str] = Field(min_length=2, max_length=2)
    branch: str | None = None
    wo: str | None = None
    blocking: bool = True


class TaskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intention: str = Field(min_length=1)
    owner_character: str = ""
    recipe_scope: list[str] = Field(default_factory=list)
    #: The cost model's job kind this goal is — what the core prices it from.
    #: Empty means the default kind (one owner's goal, as the box measures it).
    kind: str = ""
    #: The owner's own ask. It overrides the model's price, and is recorded
    #: and shown as an override.
    cost_estimate: dict | None = None
    ends_at: str | None = None
    night: str | None = None


class NightBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rails: dict | None = None
    detach_after_min: int = 30
    load_budget: dict[str, int] | None = None
    power_mode: int | None = None


class StopBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "owner stop"


class VocabCallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1)
    node: str | None = None
    region: str | None = None
    params: dict = Field(default_factory=dict)


class SealBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_ref: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    confidence: Literal["guess", "low", "medium", "high"]
    basis: str = "0 observations"
    render_spec: dict | None = None
    builder: str | None = None


class TasteAuthorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: str = Field(min_length=1)


class ApplyBranchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_version: str | None = None


class BranchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    base: str | None = None
    head: str | None = None
    purpose: Literal["main", "night", "work-order", "morning-option", "standing",
                     "rejected"] = "morning-option"


class AssetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    kind: Literal["mesh", "texture", "material", "cad_part", "motion_clip", "audio"]
    files: list[dict] = Field(default_factory=list)
    provenance: dict
    licence: dict
    critic: dict | None = None


# ------------------------------------------------------------------ helpers


def actor_for(principal: Principal) -> Actor:
    """The audit actor for a caller (§4.1: the actor is a fact in every event)."""
    if principal.token_class == OWNER:
        return owner_actor(principal.actor)
    if principal.token_class == CHARACTER:
        return character_actor(principal.actor)
    return Actor(kind="core", id=principal.actor)


def scoped_key(scope: str, key: str | None) -> str | None:
    """Namespace an Idempotency-Key so two endpoints cannot collide."""
    return f"{scope}:{key}" if key else None


def _wo_board_view(wo) -> dict:
    """The board row: state, confirm line, budget, estimate, evidence (§4.2)."""
    return {
        "id": wo.id,
        "state": wo.state,
        "title": wo.title,
        "goal": wo.goal,
        "confirm_line": wo.confirm_line,
        "budget": wo.budget.model_dump(mode="json"),
        "estimate": wo.estimate.model_dump(mode="json") if wo.estimate else None,
        "evidence": [e.model_dump(mode="json") for e in wo.evidence],
        "preview": wo.preview,
        "attempts": [a.model_dump(mode="json") for a in wo.attempts],
        "targets": wo.targets,
        "filed_by": wo.filed_by.model_dump(mode="json"),
        "branch": wo.branch,
        "promotion": wo.promotion,
    }


# ------------------------------------------------------------------ the app


def create_app(settings: Settings | None = None, *, core: Core | None = None,
               run_boot: bool = True) -> FastAPI:
    """Build the service. ``core`` may be injected (tests, or a host that
    already owns the ledger); otherwise one is opened on ``settings``."""
    settings = settings or default_settings()
    if core is None:
        core = Core.open(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # §5.2: the boot sequence — projections caught up or rebuilt, artifact
        # integrity verified, expired leases requeued, running nights resumed
        # or stopped cleanly with a computed status line.
        if run_boot:
            app.state.boot_report = Boot(core, settings).run()
        yield

    app = FastAPI(
        title="builder-ide core",
        version=__version__,
        description="core-spec v2 half A: the audit ledger, the API and the event stream.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.core = core
    app.state.boot_report = None
    app.state.active_streams = 0

    @app.exception_handler(CoreError)
    async def _core_error(request: Request, exc: CoreError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_json())

    # ------------------------------------------------------------- health

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        """Not in the spec: a LAN service needs one door that says 'I am
        alive and my ledger is at seq N' without touching a write path."""
        return {
            "ok": True,
            "version": __version__,
            "seq": core.store.max_seq(),
            "fold_seq": core.store.fold_seq(),
            "streams": app.state.active_streams,
            "boot": app.state.boot_report,
        }

    # ------------------------------------------------------------- /v1/call

    @app.post("/v1/call", tags=["call"])
    async def post_call(request: Request,
                        principal: Principal = Depends(current_principal),
                        idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """Utterance + client view → pkt → a question XOR a draft (§3.1).

        A kid actor may not submit free text: the request is refused at the
        schema and the refusal is audited as ``call.refused`` — there is
        nothing of his to retain, by structure (§4.1).
        """
        raw = await request.json()
        if principal.kid:
            if isinstance(raw, dict) and "utterance" in raw:
                # The privacy rule is structure, not policy (§4.1): the field
                # is not in a kid's schema, and the refusal is audited.
                core.store.append_refused(core.store.new_event(
                    "call.refused", actor_for(principal),
                    {"entity_kind": "call", "entity_id": principal.actor},
                    {"reason": "kid actor class cannot submit free text (§4.1)",
                     "utterance_present": True, "fields": sorted(raw.keys())},
                ))
                raise Refused(
                    "kid actors cannot submit free text — the privacy rule is structure, "
                    "not policy (§4.1); chips only")
            try:
                body = ChipBody(**raw)
            except Exception as exc:
                raise ValidationError(f"request is not schema-valid: {exc}") from exc
            utterance, chips = None, body.chips
        else:
            try:
                body = CallBody(**raw)
            except Exception as exc:
                raise ValidationError(f"request is not schema-valid: {exc}") from exc
            utterance, chips = body.utterance, body.chips

        result = CallService(core).handle(
            actor_for(principal),
            utterance=utterance,
            chips=chips,
            view=body.view,
            conversation=body.conversation,
            intent=body.intent,
            idem_key=scoped_key("call", idem_key),
        )
        return result

    # ------------------------------------------------------------- work orders

    @app.get("/v1/work-orders", tags=["work-orders"])
    def list_work_orders(state: str | None = None,
                         principal: Principal = Depends(require(OWNER, PANEL, CHARACTER))):
        """The board view: state, confirm line, budget, estimate, evidence."""
        wos = WorkOrdersService(core)
        rows = [_wo_board_view(w) for w in wos.list(state or None)]
        return {"work_orders": rows, "count": len(rows)}

    @app.post("/v1/work-orders/{wo_id}/confirm", tags=["work-orders"])
    def confirm_work_order(wo_id: str, body: ConfirmBody,
                           principal: Principal = Depends(require_adult_owner()),
                           idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """``go`` | ``no`` | ``edit``. The confirm carries both price lines."""
        return WorkOrdersService(core).confirm(
            wo_id, actor_for(principal), body.answer,
            idem_key=scoped_key(f"wo:{wo_id}:confirm", idem_key),
            amendments=body.amendments,
        )

    @app.post("/v1/work-orders/{wo_id}/keep", tags=["work-orders"])
    def keep_work_order(wo_id: str, body: VerdictBody,
                        principal: Principal = Depends(require(OWNER)),
                        idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """The owner's keep: the terminal decision, and the only event that
        scores an outstanding ``taste_keep`` prediction (§1.7)."""
        return WorkOrdersService(core).keep(
            wo_id, actor_for(principal),
            idem_key=scoped_key(f"wo:{wo_id}:keep", idem_key),
            reason_code=body.reason_code,
        )

    @app.post("/v1/work-orders/{wo_id}/reject", tags=["work-orders"])
    def reject_work_order(wo_id: str, body: VerdictBody,
                          principal: Principal = Depends(require(OWNER)),
                          idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """The owner's reject: the branch is retained, the word is not promoted."""
        return WorkOrdersService(core).reject(
            wo_id, actor_for(principal),
            idem_key=scoped_key(f"wo:{wo_id}:reject", idem_key),
            reason_code=body.reason_code,
        )

    # ------------------------------------------------------------- questions

    @app.post("/v1/questions", tags=["questions"])
    def park_question(body: ParkQuestionBody,
                      principal: Principal = Depends(require(CHARACTER))):
        """Park a named question with two options — one tap, no free text."""
        q = QuestionsService(core).park(
            actor_for(principal), name=body.name, options=body.options,
            branch=body.branch, wo=body.wo, blocking=body.blocking,
        )
        return {"question": q.model_dump(mode="json")}

    @app.post("/v1/questions/{q_id}/answer", tags=["questions"])
    def answer_question(q_id: str, body: AnswerBody,
                        principal: Principal = Depends(require(OWNER)),
                        idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """One-tap answer to a parked question."""
        q = QuestionsService(core).answer(
            q_id, body.answer, actor_for(principal),
            idem_key=scoped_key(f"question:{q_id}", idem_key),
        )
        return {"question": q.model_dump(mode="json")}

    # ------------------------------------------------------------- slate & tasks

    @app.get("/v1/slate", tags=["night"])
    def get_slate(principal: Principal = Depends(require(OWNER, PANEL))):
        """The pre-night slate: slated tasks, asks, capability rows, the WO
        line and the bar."""
        return TasksService(core).slate()

    @app.post("/v1/tasks", tags=["night"])
    def file_task(body: TaskBody,
                  principal: Principal = Depends(require(CHARACTER, OWNER))):
        """File a chip/intention as a pre-night Task row (state slated).

        The ask is priced from the cost model unless the caller files its own
        number, which becomes an override.
        """
        estimate = Rail(**body.cost_estimate) if body.cost_estimate else None
        task = TasksService(core).create(
            author=principal.actor, intention=body.intention,
            owner_character=body.owner_character,
            recipe_scope=body.recipe_scope, cost_estimate=estimate,
            kind=body.kind,
            ends_at=body.ends_at, night=body.night,
        )
        return {"task": task.model_dump(mode="json")}

    @app.post("/v1/night/{night_id}/tasks", tags=["night"])
    def file_night_tasks(night_id: str,
                         principal: Principal = Depends(require(CHARACTER, OWNER))):
        """File the slate's tasks into the night (the slate becomes the queue)."""
        svc = NightsService(core, settings)
        svc.get(night_id)  # 404 if the night does not exist
        attached = TasksService(core).attach_slate_to_night(night_id)
        return {"night": night_id, "attached": attached}

    # ------------------------------------------------------------- night

    @app.post("/v1/night", tags=["night"])
    def start_night(body: NightBody,
                    principal: Principal = Depends(require_adult_owner()),
                    idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """Start the night (slate → queue). The response carries the
        pre-flight line: the pre-flight proposes, the owner decides (§3.2.2)."""
        rails = Rail(**body.rails) if body.rails else None
        return NightsService(core, settings).start(
            actor_for(principal), rails=rails,
            detach_after_min=body.detach_after_min,
            load_budget=body.load_budget, power_mode=body.power_mode or 0,
            idem_key=scoped_key("night:start", idem_key),
        )

    @app.post("/v1/night/{night_id}/stop", tags=["night"])
    def stop_night(night_id: str, body: StopBody,
                   principal: Principal = Depends(require_adult_owner()),
                   idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """The kill switch: stop all, commit branches, write the report now."""
        return NightsService(core, settings).stop(
            night_id, actor_for(principal), reason=body.reason,
            idem_key=scoped_key(f"night:{night_id}:stop", idem_key),
        )

    @app.get("/v1/nights/{night_id}/report", tags=["night"])
    def night_report(night_id: str,
                     mode: Literal["html", "json", "text"] = "html",
                     principal: Principal = Depends(require(OWNER, PANEL, CHARACTER))):
        """The static morning report, regenerable from the log at any time
        (§3.2.8). First paint ≤ 3 s; the text mode is the same ledger read."""
        built = ReportBuilder(core).build(night_id)
        doc = built["doc"]
        if mode == "json":
            return {"report": doc}
        if mode == "text":
            return PlainTextResponse(built["text_bytes"].decode("utf-8"))
        return HTMLResponse(ReportBuilder(core).render_html(doc))

    # ------------------------------------------------------------- branches

    @app.get("/v1/branches", tags=["branches"])
    def list_branches(principal: Principal = Depends(require(OWNER, PANEL))):
        """Morning A/B/C plus the standing options.

        Actor-scoped: a kid owner sees the shared branches and the ones he
        created, not another actor's in-flight proposals.
        """
        out = []
        for row in core.store.scan("branches"):
            doc = row["payload"]
            created = doc.get("created_by")
            created_id = created.get("id") if isinstance(created, dict) else created
            if principal.kid and created_id not in (None, principal.actor):
                continue
            out.append({
                "id": row["id"], "name": doc.get("name", ""), "head": doc.get("head"),
                "purpose": row.get("purpose"), "base": doc.get("base"),
                "protected": bool(row.get("protected")),
                "created_by": created, "proposed_pending": doc.get("proposed_pending"),
            })
        standing = [
            {"name": "keep yesterday", "kind": "main-unchanged"},
            {"name": "back to the plan", "kind": "standing branch from the slate's base"},
        ]
        return {"branches": out, "standing": standing}

    @app.post("/v1/branches", tags=["branches"])
    def create_branch(body: BranchBody,
                      principal: Principal = Depends(require_adult_owner())):
        """Open a branch: a morning option, a standing branch, or a
        work-order's own line.

        The branch is created from a base version and carries its creator,
        so the kid's branches are his and the owner's are the owner's. The
        branches are the owner's morning — a kid proposes, the owner opens
        (§7.15).
        """
        from .canon import new_id

        taken = {r["id"] for r in core.store.scan("branches")}
        br_id = new_id("branch")
        if br_id in taken:  # pragma: no cover - 12 hex chars of entropy
            raise ValidationError("branch id collision; retry")
        ev = core.store.new_event(
            "branch.created", owner_actor(principal.actor),
            {"entity_kind": "branch", "entity_id": br_id},
            {"branch": {"id": br_id, "name": body.name, "base": body.base,
                        "head": body.head, "purpose": body.purpose,
                        "protected": body.purpose == "main",
                        "created_by": {"kind": "owner", "id": principal.actor}}},
        )
        core.store.append(ev)
        row = core.store.get_row("branches", {"id": br_id})
        return {"branch": {"id": br_id, **(row or {}).get("payload", {})}}

    @app.post("/v1/branches/{branch_id}/apply", tags=["branches"])
    def apply_branch(branch_id: str, body: ApplyBranchBody,
                     principal: Principal = Depends(require(OWNER))):
        """Apply = a head move.

        A kid actor's apply creates ``branch.proposed`` and waits for the
        owner's confirmation (X C8/D4): a branch apply is a real edit, and his
        authority is structural.
        """
        row = core.store.get_row("branches", {"id": branch_id})
        if row is None:
            raise NotFound(f"branch {branch_id} not found", entity=branch_id)
        head = row["payload"].get("head")
        to = body.to_version or head
        if principal.kid:
            ev = core.store.new_event(
                "branch.proposed", owner_actor(principal.actor),
                {"entity_kind": "branch", "entity_id": branch_id},
                {"by": principal.actor, "from_head": head, "to": to,
                 "note": "a kid actor proposes; the owner confirms (§7.15)"},
            )
            core.store.append(ev)
            return {"proposed": True, "branch": branch_id, "to": to,
                    "pending_owner": True}
        # the owner's apply: the head move is a ledger event with a
        # compare-and-swap on the expected head (§5.3).
        ev = core.store.new_event(
            "branch.head.moved", owner_actor(principal.actor),
            {"entity_kind": "branch", "entity_id": branch_id},
            {"from_head": head, "to": to, "via": "owner apply"},
        )
        core.store.append(ev)
        # §1.7 — the owner's apply is *the* event that scores the night's
        # taste bets on that branch (a critic keep never does). Found by the
        # rewired melt week, which had to bridge this call in by hand.
        taste_scored = PredictionsService(core).score_taste_keep_on_branch(
            branch_id, owner_actor(principal.actor), "apply")
        recipe_sync = "ok"
        try:
            # §1.2 — applying a branch moves *the world*: the store's main
            # follows the applied head (the branch itself is already there;
            # fast-forwarding it was a pointer no-op that forced the callers
            # to move main by hand). The store's move rides a core actor —
            # one owner decision, one transaction, not two decisions.
            core.recipes.fast_forward("br_main", to)
        except CoreError:
            recipe_sync = "unavailable"  # the ledger event is the record
        fresh = core.store.get_row("branches", {"id": branch_id})
        return {"branch": branch_id, "head": (fresh or {}).get("payload", {}).get("head"),
                "recipe_sync": recipe_sync, "taste_bets_scored": taste_scored}

    # ------------------------------------------------------------- budget

    @app.get("/v1/budget", tags=["budget"])
    def get_budget(night: str | None = None,
                   principal: Principal = Depends(require(OWNER, PANEL, CHARACTER))):
        """The rail snapshot, the bar state and the load-cap counters."""
        return BudgetService(core).snapshot(night)

    # ------------------------------------------------------------- vocabulary

    @app.get("/v1/vocab", tags=["vocabulary"])
    def get_vocab(principal: Principal = Depends(require(CHARACTER, PANEL, OWNER))):
        """Words (including ``coming-soon`` edges), the taste notes (read-only)
        and the capability view (§1.5)."""
        svc = VocabService(core)
        words = [w.model_dump(mode="json") for w in svc.list()]
        taste = TasteService(core).list(slice_for_model=principal.is_kid)
        capability = TasksService(core).capability_rows()
        return {"words": words, "taste_notes": taste, "capability_rows": capability}

    @app.post("/v1/vocab/call", tags=["vocabulary"])
    def vocab_call(body: VocabCallBody,
                   principal: Principal = Depends(require(CHARACTER)),
                   idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """A typed word call → a validated RecipeEdit. Refusals are audited."""
        return VocabService(core).call(
            principal.actor, body.word, body.params, body.node, body.region,
            idem_key=scoped_key(f"vocab:{body.word}", idem_key),
        )

    # ------------------------------------------------------------- predictions

    @app.post("/v1/predictions/seal", tags=["predictions"])
    def seal_prediction(body: SealBody,
                        principal: Principal = Depends(require(CHARACTER)),
                        idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """Seal a bet BEFORE the render job exists; the confidence gate and
        ``render_spec`` are enforced (X R7)."""
        builder = actor_for(principal)
        if body.builder and not principal.is_kid:
            # An owner may record a seal on a builder's behalf (the critic's
            # own doors are not HTTP); a kid may not seal as anyone else.
            builder = Actor(kind="character", id=body.builder)
        p = PredictionsService(core).seal(
            builder, body.branch_ref, body.claim, body.claim_type, body.confidence,
            basis=body.basis, render_spec=body.render_spec,
            idem_key=scoped_key("prediction:seal", idem_key),
        )
        return {"prediction": p.model_dump(mode="json")}

    @app.get("/v1/predictions/tally", tags=["predictions"])
    def prediction_tally(builder: str | None = None, claim_type: str | None = None,
                         principal: Principal = Depends(require(OWNER, PANEL, CHARACTER))):
        """Per builder × claim_type, with denominators — never a single score."""
        return PredictionsService(core).tally(builder, claim_type)

    # ------------------------------------------------------------- taste ledger

    @app.get("/v1/ledger/taste", tags=["taste"])
    def read_taste(author: str | None = None,
                   principal: Principal = Depends(require(CHARACTER, PANEL, OWNER))):
        """Author-scoped read. Never writable through this path."""
        svc = TasteService(core)
        if principal.is_owner:
            rows = svc.list(author)
        else:
            rows = svc.list(author or principal.actor, slice_for_model=True)
        return {"rows": rows, "count": len(rows)}

    @app.get("/v1/ledger/taste/export", tags=["taste"])
    def export_taste(author: str = Query(min_length=1),
                     principal: Principal = Depends(require(OWNER))):
        """One-action export: the author's rows, their reason codes and their
        artifact refs."""
        return TasteService(core).export(author)

    @app.post("/v1/ledger/taste/erase", tags=["taste"])
    def erase_taste(body: TasteAuthorBody,
                    principal: Principal = Depends(require_adult_owner()),
                    idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """One-action erase: redaction plus the compensating event, in ONE
        transaction (§1.7, §7.16)."""
        # the service namespaces its own keys ("taste:erase:"), so the raw
        # key is passed through
        return TasteService(core).erase(
            body.author, actor_for(principal), idem_key=idem_key,
        )

    @app.post("/v1/ledger/taste/ratify", tags=["taste"])
    def ratify_taste(body: TasteAuthorBody,
                     principal: Principal = Depends(require_adult_owner()),
                     idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        """Ratify a kid actor's keeps — asked once, in the report, in one line."""
        return TasteService(core).ratify(
            body.author, actor_for(principal), idem_key=idem_key,
        )

    # ------------------------------------------------------------- assets

    @app.get("/v1/assets", tags=["assets"])
    def list_assets(principal: Principal = Depends(require(OWNER, PANEL, CHARACTER))):
        """The library, with its licence and dependency-terms columns (§1.6)."""
        rows = []
        for row in core.store.scan("assets"):
            doc = row["payload"]
            rows.append({
                "id": row["id"], "kind": doc.get("kind"),
                "licence": doc.get("licence"),
                "licence_check": doc.get("licence_check"),
                "provenance": doc.get("provenance"),
                "files": doc.get("files", []),
                "critic": doc.get("critic"),
            })
        return {"assets": rows, "count": len(rows)}

    @app.post("/v1/assets", tags=["assets"])
    def create_asset(body: AssetBody,
                     principal: Principal = Depends(require(OWNER, PANEL))):
        """Register an asset. A re-run with a different model is labelled
        "reinterpreted", never silently swapped."""
        from .canon import new_id

        raw = body.model_dump()
        raw["id"] = raw.get("id") or new_id("asset")
        try:
            asset = Asset(**raw)
        except Exception as exc:
            raise ValidationError(f"asset is not schema-valid: {exc}") from exc
        ev = core.store.new_event(
            "asset.created", actor_for(principal),
            {"entity_kind": "asset", "entity_id": asset.id},
            {"asset": asset.model_dump(mode="json")},
        )
        core.store.append(ev)
        return {"asset": asset.model_dump(mode="json")}

    # ------------------------------------------------------------- world scene

    @app.get("/v1/world/scene", tags=["world"])
    def world_scene(branch: str | None = None, lod: str | None = None,
                    since_version: str | None = None,
                    principal: Principal = Depends(require(OWNER, PANEL, CHARACTER))):
        """The compiled scene manifest — the compiler's door (item 4 of the
        build order). This half owns the endpoint and the registry it reads;
        the compiled glTF/USD is the other half's.

        Answered 501 with the seam named, rather than faked: a manifest that
        was not compiled is not a manifest.
        """
        raise OtherHalfUnavailable(
            "the scene compiler (recipe half) produces the compiled glTF/USD "
            "manifest; this half owns the endpoint and the node registry it reads",
            branch=branch, lod=lod, since_version=since_version,
        )

    # ------------------------------------------------------------- acp proxy

    @app.get("/acp/proxy/{attempt}", tags=["other-half"])
    def acp_proxy(attempt: str,
                  principal: Principal = Depends(require(OWNER, PANEL))):
        """The front-end proxy onto an engineer session (§2.4).

        The engineer adapter is the other half's door: this half owns the
        attempt's ledger and the event stream, but the session it would
        proxy onto does not exist here. Answered 501 with the seam named.
        """
        raise OtherHalfUnavailable(
            "the ACP engineer adapter (the other half) owns the session this "
            "proxy would re-broadcast; this half owns the attempt's ledger "
            "and the /v1/events stream",
            attempt=attempt,
        )

    # ------------------------------------------------------------- SSE

    @app.get("/v1/events", tags=["events"])
    async def events(request: Request,
                     since_seq: int = 0,
                     types: str = Query(default=""),
                     last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                     principal: Principal = Depends(current_principal)):
        """The stream (§4.3).

        ``since_seq`` makes reconnects and rewinds the same operation — the
        feed is the log. ``Last-Event-ID`` is honoured as the SSE-standard
        spelling of the same thing. The ledger is the source of truth; the
        event bus is only a wake-up hint, so the stream stays correct across
        processes and restarts.
        """
        start = since_seq
        if start == 0 and last_event_id:
            try:
                start = int(last_event_id)
            except ValueError:
                start = 0
        wanted = [t.strip() for t in types.split(",") if t.strip()]

        async def generator():
            seq = start
            begun = time.monotonic()
            last_beat = begun
            heartbeat = settings.sse_heartbeat_seconds
            poll = settings.sse_poll_seconds
            app.state.active_streams += 1
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    if time.monotonic() - begun > settings.sse_max_seconds:
                        return
                    batch = await asyncio.to_thread(core.store.events_since, seq,
                                                   wanted or None, 500)
                    for ev in batch:
                        seq = ev.seq
                        yield _sse_event(ev)
                    now = time.monotonic()
                    if now - last_beat >= heartbeat:
                        last_beat = now
                        yield ": heartbeat\n\n"
                    # Sleep rather than block a worker thread on the event
                    # bus: a client that walks away must not hold a pool
                    # thread for as long as its stream lives, or enough
                    # abandoned streams will starve the pool the ledger reads
                    # run on.
                    await asyncio.sleep(poll)
            finally:
                app.state.active_streams -= 1

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                     "Connection": "keep-alive"},
        )

    return app


def _sse_event(ev) -> str:
    """One SSE frame: the event's seq as the id, so a reconnect can rewind."""
    data = canonical_json({
        "seq": ev.seq, "id": ev.id, "at": ev.at, "type": ev.type,
        "actor": ev.actor.model_dump(mode="json"), "subject": ev.subject,
        "payload": ev.payload, "artifact": ev.artifact, "refused": ev.refused,
    })
    return f"id: {ev.seq}\nevent: {ev.type}\ndata: {data}\n\n"


class _LazyApp:
    """``uvicorn core.api:app`` without touching ``$BUILDER_HOME`` at import
    time. The ledger is opened on the first call, so importing the module (in
    a test, or in a tool that only wants the schema) has no side effects."""

    def __init__(self) -> None:
        self._app: FastAPI | None = None

    def build(self) -> FastAPI:
        if self._app is None:
            self._app = create_app()
        return self._app

    async def __call__(self, scope, receive, send):
        await self.build()(scope, receive, send)


# The ASGI entry point: `uvicorn core.api:app` (or the factory form
# `uvicorn core.api:create_app --factory`).
app = _LazyApp()
