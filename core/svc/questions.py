"""Parked questions (§1.8 questions group, §3.2.6): the night cannot ask;
it parks a named question attached to a branch (or an order), at most 3
blocking — the fourth parks the *task* instead. The conservative-reading
alternative is assumption.recorded, attached to the branch/card it
replaced."""
from __future__ import annotations

from ..canon import new_id
from ..errors import NotFound, Refused
from ..events import Actor, core_actor
from ..models import Question

MAX_BLOCKING_OPEN = 3


class QuestionsService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    def park(self, asked_by: Actor, name: str, options: list[str], *,
             branch: str | None = None, wo: str | None = None,
             blocking: bool = True) -> Question:
        if len(options) != 2:
            raise Refused("a parked question is a two-option choice (§4.2)", name=name)
        if blocking:
            open_blocking = [q for q in self.store.scan("questions")
                             if q.get("open") and q.get("blocking")]
            if len(open_blocking) >= MAX_BLOCKING_OPEN:
                raise Refused(
                    f"at most {MAX_BLOCKING_OPEN} blocking questions may exist; park the "
                    "task instead (§3.2.6)", open=[q["id"] for q in open_blocking])
        q = Question(id=new_id("question"), name=name, branch=branch, wo=wo,
                     options=options, blocking=blocking, asked_by=asked_by)
        ev = self.store.new_event(
            "question.parked", asked_by, {"entity_kind": "question", "entity_id": q.id},
            q.model_dump(mode="json"),
        )
        self.store.append(ev)
        return self.get(q.id)

    def get(self, q_id: str) -> Question:
        row = self.store.get_row("questions", {"id": q_id})
        if row is None:
            raise NotFound(f"question {q_id} not found", entity=q_id)
        return Question(**row["payload"])

    def list(self, open_only: bool = False) -> list[Question]:
        out = []
        for row in self.store.scan("questions"):
            if open_only and not row.get("open"):
                continue
            out.append(Question(**row["payload"]))
        return out

    def answer(self, q_id: str, answer: str, actor: Actor, *,
               idem_key: str | None = None) -> Question:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return Question(**cached["body"])
        q = self.get(q_id)
        row = self.store.get_row("questions", {"id": q_id})
        if row is None:
            raise NotFound(f"question {q_id} not found", entity=q_id)
        if not row.get("open"):
            raise Refused(f"question {q_id} is already answered", entity=q_id)
        if answer not in q.options:
            raise Refused(
                f"answer must be one of the two options {q.options!r} — one tap, no free "
                "text (§4.2)", entity=q_id)
        payload = {"answer": answer, "wo": q.wo} if q.wo else {"answer": answer}
        ev = self.store.new_event(
            "question.answered", actor, {"entity_kind": "question", "entity_id": q_id},
            payload,
        )
        _, resp = self.store.append(
            ev, idem_key=idem_key,
            response_builder=lambda e: self.get(q_id).model_dump(mode="json"))
        if resp and resp.get("__replay__"):
            return Question(**resp["body"])
        return self.get(q_id)

    def record_assumption(self, q_id: str, assumption: dict) -> None:
        """The conservative reading taken at night, attached to the branch/
        card it replaced — not merely mentioned in the report (RV patch 2)."""
        ev = self.store.new_event(
            "assumption.recorded", core_actor(),
            {"entity_kind": "question", "entity_id": q_id},
            {"question": q_id, "assumption": assumption},
        )
        self.store.append(ev)
