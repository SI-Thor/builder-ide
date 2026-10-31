"""The spec's client surface (§4.2), and the door the resident core owns.

Two adapters live here, and they are the only places that know how today's
core is actually served:

* **`SpecClient`** — the spec v2 endpoints as one class, over HTTP. Today the
  HTTP is `core-api`'s FastAPI app driven in-process through Starlette's
  `TestClient` (branch `core-api`, materialized by `siblings.py`); the day
  the seats merge onto `main`, this class alone changes — `base_url` and a
  real socket instead of the in-process app — and the session script does
  not.

* **`CoreDoor`** — the operations the *resident core process* owns, which the
  spec deliberately does not expose as owner/panel HTTP: heartbeat ticks,
  scheduler job events, critic verdicts, vocabulary seeding, character-filed
  work orders, the engineer attempt loop. Today the door drives core-api's
  service layer in-process (that is what the resident process would call);
  after the merge it is the same calls over the service seam.

Token classes carry an actor (§4.1): `casey` (adult owner), `magnus` (kid
owner), the panel, and the two characters the slice has. The dev tokens are
core-api's documented LAN development credentials (config.py).
"""

from __future__ import annotations

import json
from typing import Any

from siblings import Seats

OWNER = {"Authorization": "Bearer dev-token-casey"}
KID = {"Authorization": "Bearer dev-token-magnus"}
PANEL = {"Authorization": "Bearer dev-token-panel"}
PROP = {"Authorization": "Bearer dev-token-propmaker"}
COMPANION = {"Authorization": "Bearer dev-token-companion"}

_ROLES = {
    "owner": OWNER,
    "kid": KID,
    "panel": PANEL,
    "propmaker": PROP,
    "companion": COMPANION,
}


class SpecError(RuntimeError):
    """A §4.2 call failed."""

    def __init__(self, status: int, body: Any, path: str) -> None:
        code = body.get("error", {}).get("code") if isinstance(body, dict) else body
        super().__init__(f"{path} -> {status} {code}: {body}")
        self.status = status
        self.body = body
        self.code = code


class SpecClient:
    """`docs/design/core-spec.md` §4.2 as a Python surface."""

    def __init__(self, http) -> None:
        self._http = http

    # -- transport -------------------------------------------------------------

    def _req(
        self,
        method: str,
        path: str,
        *,
        by: str = "owner",
        body: dict | None = None,
        idem: str | None = None,
        params: dict | None = None,
    ) -> Any:
        headers = dict(_ROLES[by])
        if idem:
            headers["Idempotency-Key"] = idem
        r = self._http.request(method, path, headers=headers, json=body, params=params)
        if r.status_code >= 300:
            try:
                payload = r.json()
            except Exception:  # noqa: BLE001 — the body may be text (SSE, html)
                payload = r.text
            raise SpecError(r.status_code, payload, path)
        if not r.content:
            return None
        ctype = r.headers.get("content-type", "")
        return r.json() if "json" in ctype else r.text

    # -- §4.2 ------------------------------------------------------------------

    def call(
        self,
        *,
        utterance: str | None = None,
        chips: list[str] | None = None,
        view: dict | None = None,
        conversation: list[dict] | None = None,
        intent: dict | None = None,
        by: str = "owner",
        idem: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"view": view or {}}
        if utterance is not None:
            body["utterance"] = utterance
        if chips is not None:
            body["chips"] = chips
        if conversation is not None:
            body["conversation"] = conversation
        if intent is not None:
            body["intent"] = intent
        return self._req("POST", "/v1/call", by=by, body=body, idem=idem)

    def work_orders(self, state: str | None = None) -> list[dict]:
        out = self._req(
            "GET", "/v1/work-orders", by="panel", params={"state": state} if state else None
        )
        return out["work_orders"]

    def confirm(self, wo_id: str, *, answer: str = "go", idem: str | None = None) -> dict:
        return self._req(
            "POST", f"/v1/work-orders/{wo_id}/confirm", body={"answer": answer}, idem=idem
        )

    def keep(self, wo_id: str, *, reason_code: str | None = None, idem: str | None = None) -> dict:
        body = {"reason_code": reason_code} if reason_code else {}
        return self._req("POST", f"/v1/work-orders/{wo_id}/keep", body=body, idem=idem)

    def park_question(
        self,
        name: str,
        options: list[str],
        *,
        branch: str | None = None,
        wo: str | None = None,
        by: str = "propmaker",
    ) -> dict:
        return self._req(
            "POST",
            "/v1/questions",
            by=by,
            body={"name": name, "options": options, "branch": branch, "wo": wo},
        )

    def answer_question(self, q_id: str, answer: str, *, idem: str | None = None) -> dict:
        return self._req(
            "POST", f"/v1/questions/{q_id}/answer", body={"answer": answer}, idem=idem
        )

    def slate(self) -> dict:
        return self._req("GET", "/v1/slate", by="owner")

    def file_task(
        self,
        intention: str,
        *,
        owner_character: str = "",
        recipe_scope: list[str] | None = None,
        cost_estimate: dict | None = None,
        by: str = "companion",
    ) -> dict:
        body: dict[str, Any] = {"intention": intention, "owner_character": owner_character}
        if recipe_scope:
            body["recipe_scope"] = recipe_scope
        if cost_estimate:
            body["cost_estimate"] = cost_estimate
        return self._req("POST", "/v1/tasks", by=by, body=body)

    def start_night(
        self,
        *,
        rails: dict | None = None,
        detach_after_min: int = 30,
        load_budget: dict[str, int] | None = None,
        idem: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"detach_after_min": detach_after_min}
        if rails:
            body["rails"] = rails
        if load_budget:
            body["load_budget"] = load_budget
        return self._req("POST", "/v1/night", body=body, idem=idem)

    def stop_night(self, night_id: str, *, reason: str = "owner stop", idem: str | None = None) -> dict:
        return self._req(
            "POST", f"/v1/night/{night_id}/stop", body={"reason": reason}, idem=idem
        )

    def report(self, night_id: str, mode: str = "json") -> Any:
        return self._req(
            "GET", f"/v1/nights/{night_id}/report", by="panel", params={"mode": mode}
        )

    def branches(self) -> dict:
        return self._req("GET", "/v1/branches", by="owner")

    def apply_branch(self, branch_id: str, *, to_version: str | None = None) -> dict:
        body = {"to_version": to_version} if to_version else {}
        return self._req("POST", f"/v1/branches/{branch_id}/apply", body=body)

    def budget(self, night: str | None = None) -> dict:
        return self._req("GET", "/v1/budget", by="panel", params={"night": night} if night else None)

    def vocab(self, by: str = "propmaker") -> dict:
        return self._req("GET", "/v1/vocab", by=by)

    def vocab_call(
        self,
        word: str,
        params: dict,
        *,
        node: str | None = None,
        region: str | None = None,
        by: str = "propmaker",
        idem: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"word": word, "params": params}
        if node:
            body["node"] = node
        if region:
            body["region"] = region
        return self._req("POST", "/v1/vocab/call", by=by, body=body, idem=idem)

    def seal(
        self,
        *,
        branch_ref: str,
        claim: str,
        claim_type: str,
        confidence: str,
        basis: str = "0 observations",
        render_spec: dict | None = None,
        builder: str | None = None,
        idem: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "branch_ref": branch_ref,
            "claim": claim,
            "claim_type": claim_type,
            "confidence": confidence,
            "basis": basis,
        }
        if render_spec is not None:
            body["render_spec"] = render_spec
        if builder is not None:
            body["builder"] = builder
        return self._req("POST", "/v1/predictions/seal", by="propmaker", body=body, idem=idem)

    def tally(self, builder: str | None = None, claim_type: str | None = None) -> dict:
        params = {k: v for k, v in (("builder", builder), ("claim_type", claim_type)) if v}
        return self._req("GET", "/v1/predictions/tally", by="panel", params=params or None)

    def taste(self, author: str | None = None) -> dict:
        return self._req(
            "GET", "/v1/ledger/taste", by="panel", params={"author": author} if author else None
        )

    def taste_export(self, author: str) -> dict:
        return self._req("GET", "/v1/ledger/taste/export", params={"author": author})

    def assets(self) -> dict:
        return self._req("GET", "/v1/assets", by="panel")

    def create_asset(self, *, kind: str, provenance: dict, licence: dict,
                     files: list[dict] | None = None) -> dict:
        return self._req(
            "POST",
            "/v1/assets",
            by="panel",
            body={"kind": kind, "provenance": provenance, "licence": licence,
                  "files": files or []},
        )

    def world_scene(self, *, branch: str | None = None, lod: str | None = None,
                    since_version: str | None = None) -> dict:
        params = {k: v for k, v in
                  (("branch", branch), ("lod", lod), ("since_version", since_version)) if v}
        return self._req("GET", "/v1/world/scene", by="panel", params=params or None)

    # -- §4.3: the stream --------------------------------------------------------

    def events(self, since_seq: int = 0, types: list[str] | None = None,
               until_seq: int | None = None, limit: int = 1000) -> list[dict]:
        """Read the feed over SSE until the replay drains.

        The feed is the log (D §02:07): `since_seq` makes reconnects and
        rewinds the same operation. The read stops when the ledger's head
        (`until_seq`) has been seen — the SSE heartbeat only fires every
        15 s, and a cold join should not wait on silence.
        """
        params: dict[str, Any] = {"since_seq": since_seq}
        if types:
            params["types"] = ",".join(types)
        collected: list[dict] = []
        with self._http.stream(
            "GET", "/v1/events", headers=dict(PANEL), params=params
        ) as r:
            if r.status_code >= 300:
                raise SpecError(r.status_code, "stream failed", "/v1/events")
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith(":"):
                    break  # heartbeat: nothing newer exists
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload:
                        event = json.loads(payload)
                        collected.append(event)
                        if until_seq is not None and int(event.get("seq", 0)) >= until_seq:
                            break
                if len(collected) >= limit:
                    break
        return collected


class CoreDoor:
    """The resident core's own hands (see the module docstring).

    Everything here is what the core process itself does while the owner is
    away or before the panels exist: heartbeats, scheduler job events,
    critic verdicts, seeding the vocabulary, filing a character's work
    order, running an engineer attempt through the gate. The HTTP surface
    (§4.2) deliberately has no door for these.
    """

    def __init__(self, seats: Seats, core, settings, engine=None) -> None:
        self.seats = seats
        self.api = seats.api
        self.core = core
        self.settings = settings
        # The engine behind the scheduler's renders (the seam, core/engine).
        # None keeps the door honest: a render ask without an engine raises
        # rather than inventing bytes.
        self.engine = engine

    # -- event helpers -----------------------------------------------------------

    _SERVICE_CLASS = {
        "nights": ("nights", "NightsService", True),    # (module, class, needs settings)
        "tasks": ("tasks", "TasksService", False),
        "work_orders": ("work_orders", "WorkOrdersService", False),
        "vocab": ("vocab", "VocabService", False),
        "predictions": ("predictions", "PredictionsService", False),
        "taste": ("taste", "TasteService", False),
        "budget": ("budget", "BudgetService", False),
        "questions": ("questions", "QuestionsService", False),
        "lines": ("lines", "LinesService", False),
        "report": ("report", "ReportBuilder", False),
    }

    def _svc(self, name: str):
        import importlib

        module, cls, needs_settings = self._SERVICE_CLASS[name]
        mod = importlib.import_module(f"core.svc.{module}")
        args = (self.core, self.settings) if needs_settings else (self.core,)
        return getattr(mod, cls)(*args)

    @property
    def store(self):
        return self.core.store

    def event(self, type_: str, actor, subject: dict, payload: dict, artifact: dict | None = None):
        ev = self.store.new_event(type_, actor, subject, payload, artifact)
        return self.store.append(ev)[0]

    # -- the night's own writes (§3.2, §3.4) --------------------------------------

    def tick(self, night_id: str, *, at: str | None = None, load: float | None = None) -> None:
        self._svc("nights").tick(night_id, at=at, load=load)

    def record_spend(self, night: str, spend: dict, *, job: str | None = None) -> None:
        self._svc("budget").record_spend(night, spend, job=job)

    def model_load(self, night: str, model: str) -> dict:
        return self._svc("budget").model_load(night, model)

    def set_task_state(self, task_id: str, to: str, *, reason: str | None = None):
        return self._svc("tasks").set_state(task_id, to, reason=reason)

    # -- the scheduler's job door (§1.9, §5.1) ------------------------------------

    def put_artifact(self, data: bytes, name: str) -> dict:
        """Store one content-addressed artifact; returns its descriptor."""
        return self.store.artifacts.put(data, name)

    def render_job(
        self,
        *,
        branch_ref: str,
        entry_paths: list[str],
        rung: int,
        seed: int,
        prediction_id: str | None,
        night: str,
        resolution: str = "480p",
    ) -> dict:
        """Enqueue, run and complete one render job — the scheduler's half.

        The bytes come from the engine behind the door (the seam,
        `core/engine`; the fake engine in this session — deterministic in
        the whole request, and labelled inside its own bytes). The ordering
        rules are the real ones: `job.enqueued` commits after the seal it
        tests (§5.1) and the artifact is content-addressed (§1.0).
        """
        preview = self._render(branch_ref, subject=",".join(entry_paths),
                               rung=rung, seed=seed, resolution=resolution)
        events = self.api.events
        job_id = f"job_{len(self.store.events_since(0, types=['job.enqueued'])) + 1:04d}"
        actor = events.core_actor()
        self.event(
            "job.enqueued", actor, {"entity_kind": "job", "entity_id": job_id},
            {"job_id": job_id, "branch_ref": branch_ref, "entry_paths": entry_paths,
             "rung": rung, "seed": seed, "prediction_id": prediction_id,
             "lane": "gpu", "worker": "thor", "night": night},
        )
        self.event(
            "job.started", actor, {"entity_kind": "job", "entity_id": job_id},
            {"job_id": job_id},
        )
        desc = self.put_artifact(preview.data, f"render-r{rung}-{seed}.png")
        completed = {
            "job_id": job_id, "rung": rung, "seed": seed,
            "engine": self.engine.describe().source,
            "engine_flavour": self.engine.describe().flavour,
            # the measured render wall (None only for the fake, which
            # measures nothing and says so by omitting it)
            "wall_ms": preview.wall_ms,
            "resolution": preview.resolution,
            "artifact": {"sha256": desc["sha256"], "kind": "render",
                         "bytes": desc["bytes"]},
        }
        if preview.wall_ms is not None:
            # the morning's box section quotes the measured render (G §1:
            # the [e] fields the slate marked are replaced by measurements)
            completed["timing"] = {
                "what": "render", "measured_ms": round(preview.wall_ms, 1),
                "label": f"measured (engine render, rung {rung})"}
        self.event(
            "render.completed", actor, {"entity_kind": "job", "entity_id": job_id},
            completed,
            artifact=desc,
        )
        self.event(
            "job.done", actor, {"entity_kind": "job", "entity_id": job_id},
            {"job_id": job_id, "outputs": [desc["sha256"]]},
        )
        return {"job_id": job_id, "artifact": desc}

    def _render(self, branch_ref: str, *, subject: str, rung: int, seed: int,
                resolution: str = "480p"):
        """One preview through the seam, at the recipe version named by the
        branch ref — the render is *of* the committed version, never of a
        hand-me-down byte string."""
        from core.engine.contract import PreviewRequest

        if self.engine is None:
            raise RuntimeError(
                "no engine is wired to the door (seats/engine.py); a render "
                "without an engine is a fabrication, not a default")
        version_id = branch_ref.split("@", 1)[1]
        store = self.core.recipes.store
        return self.engine.render_preview(PreviewRequest(
            recipe=store.get_document(version_id),
            version_hash=store.get_version(version_id).root_hash,
            subject=subject, rung=rung, resolution=resolution, seed=seed,
        ))

    def critic_verdict(
        self,
        *,
        job_id: str,
        verdict: str,
        code: str,
        summary: str,
        label: str = "verdict@scripted",
        extra: dict | None = None,
    ) -> None:
        """A scripted critic verdict — always `verdict@scripted` on its face
        until a critic model is chosen and calibrated (RV patch 15)."""
        payload = {"job_id": job_id, "verdict": verdict, "code": code,
                   "label": label, "degraded": True, "summary": summary}
        payload.update(extra or {})
        self.event(
            "critic.verdict", self.api.events.Actor(kind="critic", id="critic-scripted"),
            {"entity_kind": "job", "entity_id": job_id}, payload,
        )

    # -- predictions' critic half (§1.7) -------------------------------------------

    def score_world_bet(self, pr_id: str, critic_verdict: str):
        return self._svc("predictions").score_world_from_critic(pr_id, critic_verdict)

    # -- vocabulary and taste (§1.5, §1.7) -----------------------------------------

    def add_vocab_word(self, entry: dict):
        return self._svc("vocab").add_word(entry, self.api.events.core_actor())

    def set_vocab_status(self, word: str, status: str):
        return self._svc("vocab").set_status(word, status, self.api.events.core_actor())

    def append_taste_note(self, *, subject: dict, artifact_ref: str, verdict: str,
                          reason_code: str, words: str | None = None,
                          tags: list[str] | None = None, author: str = "casey"):
        return self._svc("taste").append_note(
            self.api.events.owner_actor(author), author=author, subject=subject,
            artifact_ref=artifact_ref, verdict=verdict, reason_code=reason_code,
            words=words, tags=tags,
        )

    # -- work orders' character and engineer halves (§1.3, §2) ----------------------

    def file_character_wo(
        self, *, title: str, goal: str, character_line: str, vocabulary_gap: dict | None,
        targets: list[str], acceptance: list[dict], estimate: dict | None = None,
        confirm_line: str = "", promote: dict | None = None,
    ):
        """A character hits a vocabulary edge and files the order (§3.1)."""
        models = self.api.models
        wos = self._svc("work_orders")
        origin = models.Origin(
            channel="character", packet="pkt_character",
            character_line=character_line,
        )
        wo = wos.file(
            self.api.events.character_actor("prop-maker", via=vocabulary_gap["word"] if vocabulary_gap else None),
            origin, title, goal=goal, targets=targets,
            acceptance=acceptance, vocabulary_gap=vocabulary_gap,
        )
        est = models.Estimate(**estimate) if estimate else None
        return wos.compile_draft(
            wo.id, title=title, goal=goal, targets=targets, acceptance=acceptance,
            estimate=est, confirm_line=confirm_line, promote=promote,
            vocabulary_gap=vocabulary_gap,
        )

    def run_engineer_attempt(self, wo_id: str, *, deliverable: dict,
                             night: str | None = None, subject: str | None = None,
                             rung: int = 2, seed: int = 42) -> dict:
        """The stub engineer (`aider-local`) + the merge gate over the engine.

        attempt → deliver (evidence must include a test_run) → gate → land
        with a preview artifact that exists before the owner is notified
        (D §4 moment 10). The gate's engine rungs and the preview both run
        on the seam (the fake engine in this session); the engineer and the
        verdict are still stubs and say so."""
        wos = self._svc("work_orders")
        wos.start_attempt(wo_id, "aider-local")
        wos.deliver(wo_id, deliverable)
        gate = wos.run_gate(wo_id)
        if not gate.get("passed"):
            raise RuntimeError(f"the merge gate refused {wo_id}: {gate}")
        # the preview is rendered at whatever the seam's branch is on —
        # the version the night has committed by now
        seam = self.core.recipes
        head = seam.head(seam.commit_branch)
        preview = self._render(f"{seam.commit_branch}@{head}",
                               subject=subject or wo_id, rung=rung, seed=seed)
        desc = self.put_artifact(preview.data, f"{wo_id}-preview.png")
        wall = (f"{preview.wall_ms / 1000.0:.1f} s wall"
                if preview.wall_ms is not None else "wall unmeasured (fake)")
        evidence = [
            {"kind": "render", "ref": desc["sha256"], "sha256": desc["sha256"],
             "summary": f"rung-{rung} preview · {self.engine.describe().flavour} "
                        f"· {wall} · verdict@scripted"},
        ]
        wos.land(wo_id, desc, evidence, gate=gate)
        if night:
            wos.record_spend(wo_id, night, deliverable.get("budget_spend") or {})
        return {**gate, "preview_wall_ms": preview.wall_ms}

    # -- the recipe half's publishing convention (§1.4.0, ports.py) -----------------

    def publish_branch(self, branch_id: str, *, name: str, purpose: str, head: str,
                       base: str | None = None) -> None:
        """A branch row, the way the recipe half creates one."""
        self.event(
            "branch.created", self.api.events.core_actor(),
            {"entity_kind": "branch", "entity_id": branch_id},
            {"id": branch_id, "name": name, "head": head, "purpose": purpose,
             "base": base, "protected": purpose == "main"},
        )

    def publish_nodes(self, branch: str, nodes: list[dict], *, head: str) -> None:
        """nodes.json, the compiler's publishing convention (ports.py).

        The artifact is content-addressed and attached to the
        version.committed event for the branch head; the core's node-registry
        projection folds it (§1.4.0).
        """
        desc = self.put_artifact(
            json.dumps({"nodes": nodes}).encode("utf-8"), "nodes.json"
        )
        self.event(
            "version.committed", self.api.events.core_actor(),
            {"entity_kind": "branch", "entity_id": branch},
            {"branch": branch, "head": head},
            artifact=desc,
        )

    def raw_events(self, since: int = 0, types: list[str] | None = None) -> list:
        return self.store.events_since(since, types or None)

    # -- durability (§5.2) -----------------------------------------------------------

    def kill(self) -> None:
        """Close the ledger — the honest kill -9 (core-api's own rule: an
        actual close, an actual reopen, the actual file)."""
        self.store.close()

    def reopen(self, **ports):
        core = self.api.svc.Core.open(self.settings, **ports)
        self.core = core
        return core
