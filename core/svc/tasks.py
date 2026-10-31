"""Tasks and the plan slate (§1.9 Task, RV patch 11): chips and intentions
are Task rows BEFORE any night exists (state slated, night None); the ask
(cost_estimate) is stored at slate time so the morning can name what was
cut. The slate view carries capability rows derived from the vocab.call
log — no new record type (RV patch 18).

**The ask is priced, not typed.** A task names the job kind it is
(``kind``) and the **cost model** (``core/night/cost``) says what that kind
costs on this box: the p50 is the ask, the p95 is the rail the task is held
to. A client may still file its own number — that becomes an **override**,
recorded on the task and shown on the slate, not silently replaced by the
model's."""
from __future__ import annotations

from typing import Sequence

from ..canon import new_id
from ..errors import NotFound, Refused
from ..events import Actor
from ..models import Rail, Task
from ..night.cost.admission import NightPlan, PlannedJob, admission_check
from ..night.cost.estimates import owner_estimate
from ..night.cost.model import get_model
from ..night.cost.pricing import DEFAULT_KIND, PricedAsk, hold_to, known_kinds, price_job


class TasksService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    def create(self, author: str, intention: str, *, owner_character: str = "",
               recipe_scope: list[str] | None = None, cost_estimate: Rail | None = None,
               rail: Rail | None = None, kind: str = "", night: str | None = None,
               ends_at: str | None = None, idem_key: str | None = None) -> Task:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return Task(**cached["body"])
        if night is not None and self.store.get_row("nights", {"id": night}) is None:
            raise NotFound(f"night {night} not found", entity=night)
        job_kind = kind or DEFAULT_KIND
        priced = self.price(job_kind)
        if cost_estimate is not None:
            # the owner's own number. It is kept, not overwritten: the ask the
            # owner filed is the ask the night is held to, and it is recorded
            # as an override so the slate can show it.
            ask = cost_estimate
            ask_source = "override"
            ask_basis = "estimate"
        else:
            ask = priced.ask
            ask_source = "model"
            ask_basis = priced.basis
        task = Task(
            id=new_id("task"), night=night, author=author, ends_at=ends_at,
            owner_character=owner_character, intention=intention,
            recipe_scope=recipe_scope or [], cost_estimate=ask,
            rail=rail or hold_to(ask, priced),
            kind=job_kind, ask_source=ask_source, ask_basis=ask_basis,
        )
        ev = self.store.new_event(
            "night.task.created", Actor(kind="character", id=owner_character or "companion")
            if owner_character else Actor(kind="owner", id=author),
            {"entity_kind": "task", "entity_id": task.id},
            {"task": task.model_dump(mode="json"), "night": night},
        )
        _, resp = self.store.append(
            ev, idem_key=idem_key,
            response_builder=lambda e: task.model_dump(mode="json"))
        if resp and resp.get("__replay__"):
            return Task(**resp["body"])
        return task

    def price(self, kind: str) -> PricedAsk:
        """What the cost model says a job of this kind costs.

        The ask is the band's p50 and the rail its p95; the basis and source
        come along so the slate can say where the number came from.
        """
        try:
            return price_job(kind)
        except KeyError:
            raise Refused(
                f"the cost model has no price for {kind!r}; it knows "
                f"{', '.join(known_kinds())}"
            ) from None

    def get(self, task_id: str) -> Task:
        row = self.store.get_row("tasks", {"id": task_id})
        if row is None:
            raise NotFound(f"task {task_id} not found", entity=task_id)
        return Task(**row["payload"])

    def set_state(self, task_id: str, to: str, *, reason: str | None = None) -> Task:
        task = self.get(task_id)
        valid = {"slated", "queued", "running", "kept", "reverted", "parked", "cut"}
        if to not in valid:
            raise Refused(f"task state must be one of {sorted(valid)}")
        ev = self.store.new_event(
            "night.task.state", Actor(kind="core", id="core"),
            {"entity_kind": "task", "entity_id": task_id},
            {"from_state": task.state, "to": to, "reason": reason},
        )
        self.store.append(ev)
        return self.get(task_id)

    def attach_slate_to_night(self, night_id: str) -> list[str]:
        """Start-the-night moves the slate to the queue (§3.2.1→2).

        The slate is checked against the night's rails **first**: a plan that
        does not fit is refused, and the refusal names what falls off the
        end. The owner reads that this evening, not at 3 a.m. — and the
        slate stays as it was, so the recovery is a trim and a try again.
        """
        night = self.store.get_row("nights", {"id": night_id})
        if night is None:
            raise NotFound(f"night {night_id} not found", entity=night_id)
        rails = Rail(**(night["payload"].get("rails") or {}))
        plan = self.plan()
        check = admission_check(plan, rails)
        if not check.fits:
            estimate = owner_estimate(plan, rails, check=check)
            reason = "; ".join(line.reason for line in check.cut)
            raise Refused(
                f"the slate does not fit tonight's rails — {reason}",
                night=night_id,
                cut=check.cut_names,
                estimate=estimate.model_dump(mode="json"),
            )
        attached = []
        for row in self.store.scan("tasks"):
            if row.get("state") != "slated":
                continue
            ev = self.store.new_event(
                "night.task.state", Actor(kind="core", id="core"),
                {"entity_kind": "task", "entity_id": row["id"]},
                {"from_state": "slated", "to": "queued",
                 "reason": f"night {night_id} started", "night": night_id},
            )
            self.store.append(ev)
            attached.append(row["id"])
        return attached

    # ------------------------------------------------------------- the slate (§4.2)

    def rails(self) -> Rail:
        """The bar the slate is measured against: the running night's rails,
        or the model's default (the spec's 360 GPU-min / 560 wall-min).

        The number comes from the cost model, so the code and the document
        cannot drift apart.
        """
        running = [n for n in self.store.scan("nights") if n.get("state") == "running"]
        if running:
            payload = running[0]["payload"].get("rails") or {}
            if payload:
                return Rail(**payload)
        return get_model().default_night_rails()

    def plan(self, tasks: Sequence[Task] | None = None) -> NightPlan:
        """Tonight's plan, in the cost model's shape: the asks as filed.

        The ask is the one stored on the task — the model's price, or the
        owner's own number when they filed one.
        """
        rows = tasks if tasks is not None else self.slated_tasks()
        return NightPlan(
            jobs=[
                PlannedJob(
                    id=task.id,
                    intention=task.intention,
                    ask=task.cost_estimate,
                    kind=task.kind,
                )
                for task in rows
            ]
        )

    def slated_tasks(self) -> list[Task]:
        """The tasks on the slate right now, in the order they were filed."""
        return [
            Task(**row["payload"])
            for row in self.store.scan("tasks")
            if row.get("state") == "slated"
        ]

    def slate(self) -> dict:
        """The plan slate: what tonight would cost, and whether it fits.

        The asks are the model's (or the owner's own, marked as overrides),
        the bar is the night's rails, and the two lines are the owner's
        answer before the night starts.
        """
        tasks = [t for t in self.store.scan("tasks") if t.get("state") == "slated"]
        rows = self.slated_tasks()
        plan = self.plan(rows)
        rails = self.rails()
        check = admission_check(plan, rails)
        estimate = owner_estimate(plan, rails, check=check)
        asks = [t["payload"].get("cost_estimate", {}) for t in tasks]
        ask_gpu = sum(float(a.get("gpu_minutes", 0)) for a in asks)
        ask_wall = sum(float(a.get("wall_minutes", 0)) for a in asks)
        # the work-order ask as its own line — on night one it exists to say
        # it is empty (X C11)
        open_wos = [w for w in self.store.scan("work_orders")
                    if w.get("state") in ("draft", "queued", "building", "testing", "parked")]
        wo_minutes = 0.0
        for w in open_wos:
            est = w["payload"].get("estimate") or {}
            for half in ("build_verify", "generate_test"):
                wo_minutes += float((est.get(half) or {}).get("wall_minutes", 0))
        wo_line = (f"Work orders: {wo_minutes / 60:.1f} h — approved separately"
                   if wo_minutes else "Work orders: none — the line exists from night one")
        capability_rows = self._capability_rows()
        return {
            "tasks": [t["payload"] for t in tasks],
            "rows": [self._row(task) for task in rows],
            "ask": {"gpu_minutes": ask_gpu, "wall_minutes": ask_wall},
            "bar": rails.model_dump(),
            "estimate": estimate.as_dict(),
            "work_order_line": wo_line,
            "capability_rows": capability_rows,
            "money": f"${estimate.ask.hosted_cents / 100:.2f} (local) — hosted spend is off by default",
        }

    def _row(self, task: Task) -> dict:
        """One row of the slate: the ask, and where it came from.

        An override shows the model's own price beside it, so the owner can
        see what the box says the work costs next to the number they filed.
        """
        priced = None
        if task.kind:
            try:
                priced = self.price(task.kind)
            except Refused:  # pragma: no cover - a kind the model knows
                priced = None
        return {
            "id": task.id,
            "intention": task.intention,
            "owner_character": task.owner_character,
            "kind": task.kind,
            "ask": task.cost_estimate.model_dump(),
            "rail": task.rail.model_dump(),
            "ask_source": task.ask_source,
            "ask_basis": task.ask_basis,
            # every estimate is marked until it is measured (§3.2.1)
            "marked": "[e]" if task.ask_basis == "estimate" else "",
            "model_ask": priced.ask.model_dump() if priced else None,
            "model_basis": priced.basis if priced else "",
            "overridden": task.ask_source == "override",
        }

    def capability_rows(self) -> list[dict]:
        """The capability view: what has actually been built, per word."""
        return self._capability_rows()

    def _capability_rows(self) -> list[dict]:
        """Derived from vocab.call counts and kept work orders — claims are
        records, not decoration (X C12)."""
        rows = []
        for w in self.store.scan("vocab_words"):
            doc = w["payload"]
            calls = int(doc.get("calls", 0))
            kept = self.store.count_events(["vocab.word.added"],
                                           payload_where="payload->>'word' = ?",
                                           payload_args=(doc.get("word", ""),))
            if calls == 0:
                line = "No record — built 0 of these for you"
            else:
                line = f"built {calls} for you"
            rows.append({"word": doc.get("word"), "calls": calls, "kept_promotions": kept,
                         "line": line})
        return rows
