"""Tasks and the plan slate (§1.9 Task, RV patch 11): chips and intentions
are Task rows BEFORE any night exists (state slated, night None); the ask
(cost_estimate) is stored at slate time so the morning can name what was
cut. The slate view carries capability rows derived from the vocab.call
log — no new record type (RV patch 18)."""
from __future__ import annotations

from ..canon import new_id
from ..errors import NotFound, Refused
from ..events import Actor
from ..models import Rail, Task


class TasksService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    def create(self, author: str, intention: str, *, owner_character: str = "",
               recipe_scope: list[str] | None = None, cost_estimate: Rail | None = None,
               rail: Rail | None = None, night: str | None = None,
               ends_at: str | None = None, idem_key: str | None = None) -> Task:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return Task(**cached["body"])
        if night is not None and self.store.get_row("nights", {"id": night}) is None:
            raise NotFound(f"night {night} not found", entity=night)
        task = Task(
            id=new_id("task"), night=night, author=author, ends_at=ends_at,
            owner_character=owner_character, intention=intention,
            recipe_scope=recipe_scope or [], cost_estimate=cost_estimate or Rail(),
            rail=rail or Rail(),
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
        """Start-the-night moves the slate to the queue (§3.2.1→2)."""
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

    def slate(self) -> dict:
        tasks = [t for t in self.store.scan("tasks") if t.get("state") == "slated"]
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
        from ..models import Rail as R

        bar = {"gpu_minutes": 360, "hosted_cents": 0, "wall_minutes": 560}
        running = [n for n in self.store.scan("nights") if n.get("state") == "running"]
        if running:
            bar = running[0]["payload"].get("rails", bar)
        return {
            "tasks": [t["payload"] for t in tasks],
            "ask": {"gpu_minutes": ask_gpu, "wall_minutes": ask_wall},
            "bar": bar,
            "work_order_line": wo_line,
            "capability_rows": capability_rows,
            "money": "$0.00 (local) — hosted spend is off by default",
        }

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
