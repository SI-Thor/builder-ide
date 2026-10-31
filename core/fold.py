"""The fold: every projection row derives from audit events, in seq order,
and nothing else. Handlers are pure over (event, RowStore) so the same code
runs the live SQLite projections, the boot-time catch-up, the shadow
verification and a full rebuild (§5.2 step 1).

Compare-and-swap (§5.3): transition events carry ``from_state``; a mismatch
raises StaleTransition and the whole append transaction rolls back — a
stale transition fails closed. Domain refusals (out-of-schema params, kid
free text, over-budget asks) commit as events flagged ``refused: true``
(the vocab.call precedent: the edges are the story) and change no
projection.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .artifacts import ArtifactStore
from .errors import StaleTransition
from .events import AuditEvent
from .projections import FOLD_TABLES, MemoryRowStore, RowStore

# Allowed source states per work-order transition event (§1.3 table).
WO_FROM_STATES: dict[str, frozenset[str]] = {
    "wo.compiled": frozenset({"compiling"}),
    "wo.questioned": frozenset({"compiling"}),
    "wo.confirmed": frozenset({"draft"}),
    "wo.cancelled": frozenset({"draft"}),
    "wo.queued": frozenset({"draft", "queued"}),
    # §1.3's own diagram routes a failed gate to `building` (attempt n+1, if
    # the per_order rail allows), so an attempt may start from there.
    "wo.attempt.started": frozenset({"queued", "testing", "building"}),
    "wo.attempt.delivered": frozenset({"building"}),
    "wo.testing": frozenset({"building", "testing"}),
    "wo.landed": frozenset({"testing"}),
    "wo.kept": frozenset({"landed"}),
    "wo.rejected": frozenset({"landed"}),
    "wo.parked": frozenset({"queued", "building", "testing"}),
    "wo.resumed": frozenset({"parked"}),
    "wo.failed": frozenset({"testing", "building"}),
}


@dataclass
class FoldContext:
    artifacts: ArtifactStore
    kid_actors: frozenset[str]


def _load(row: dict | None) -> dict:
    if row is None:
        return {}
    payload = row.get("payload")
    if isinstance(payload, str):
        return json.loads(payload)
    return dict(payload or {})


def _dump(doc: dict) -> str:
    from .canon import canonical_json

    return canonical_json(doc)


def _wo_cas(rows: RowStore, ev: AuditEvent) -> tuple[dict, str]:
    wo_id = ev.subject_id or ev.payload.get("wo_id", "")
    row = rows.get("work_orders", {"id": wo_id})
    if row is None:
        raise StaleTransition(f"work order {wo_id} does not exist", entity=wo_id)
    doc = _load(row)
    current = doc.get("state")
    expected = ev.payload.get("from_state")
    if expected is not None and current != expected:
        raise StaleTransition(
            f"work order {wo_id}: expected state {expected!r}, found {current!r}",
            entity=wo_id, expected=expected, actual=current,
        )
    allowed = WO_FROM_STATES.get(ev.type)
    if allowed is not None and current not in allowed:
        raise StaleTransition(
            f"work order {wo_id}: {ev.type} not allowed from {current!r}",
            entity=wo_id, expected=sorted(allowed), actual=current,
        )
    return doc, wo_id


def _wo_save(rows: RowStore, wo_id: str, doc: dict, seq: int) -> None:
    rows.put(
        "work_orders",
        {"id": wo_id},
        {"id": wo_id, "state": doc["state"], "updated_seq": seq, "payload": _dump(doc)},
    )


def _task_cas(rows: RowStore, ev: AuditEvent) -> tuple[dict, str]:
    task_id = ev.subject_id or ev.payload.get("task_id", "")
    row = rows.get("tasks", {"id": task_id})
    if row is None:
        raise StaleTransition(f"task {task_id} does not exist", entity=task_id)
    doc = _load(row)
    expected = ev.payload.get("from_state")
    if expected is not None and doc.get("state") != expected:
        raise StaleTransition(
            f"task {task_id}: expected state {expected!r}, found {doc.get('state')!r}",
            entity=task_id,
        )
    return doc, task_id


# ---------------------------------------------------------------- work orders

def _h_wo_filed(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    doc = dict(ev.payload.get("work_order", {}))
    wo_id = doc.get("id") or ev.subject_id
    doc.setdefault("id", wo_id)
    doc.setdefault("state", "compiling")
    doc.setdefault("attempts", [])
    doc.setdefault("evidence", [])
    _wo_save(rows, wo_id, doc, ev.seq)
    packet = ev.payload.get("packet_snapshot")
    if packet:
        rows.put(
            "packets",
            {"id": packet["id"]},
            {"id": packet["id"], "sha256": ev.artifact.get("sha256") if ev.artifact else None,
             "updated_seq": ev.seq, "payload": _dump(packet)},
        )


def _wo_patch(rows: RowStore, ev: AuditEvent, ctx: FoldContext, state: str, fields: tuple[str, ...]) -> None:
    doc, wo_id = _wo_cas(rows, ev)
    for f in fields:
        if f in ev.payload:
            doc[f] = ev.payload[f]
    doc["state"] = state
    _wo_save(rows, wo_id, doc, ev.seq)


def _h_attempt_started(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    doc, wo_id = _wo_cas(rows, ev)
    attempts = list(doc.get("attempts", []))
    attempts.append(ev.payload["attempt"])
    doc["attempts"] = attempts
    doc["state"] = "building"
    _wo_save(rows, wo_id, doc, ev.seq)


def _h_attempt_delivered(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    doc, wo_id = _wo_cas(rows, ev)
    attempts = list(doc.get("attempts", []))
    n = ev.payload.get("attempt_n")
    for a in attempts:
        if a.get("n") == n:
            a["state"] = "delivered"
            a["ended_at"] = ev.payload.get("at", ev.at)
    doc["attempts"] = attempts
    if "deliverable" in ev.payload:
        doc["last_deliverable"] = ev.payload["deliverable"]
        # the deliverable's evidence is the work order's evidence — "no card
        # without an artifact": the owner sees the test run before deciding.
        doc["evidence"] = _merge_evidence(doc.get("evidence", []),
                                          ev.payload["deliverable"].get("evidence", []))
    doc["state"] = "testing"
    _wo_save(rows, wo_id, doc, ev.seq)


def _merge_evidence(existing: list, incoming: list) -> list:
    """Append evidence, keeping one copy of each artifact."""
    out = list(existing)
    seen = {(e.get("kind"), e.get("sha256"), e.get("ref")) for e in out}
    for e in incoming:
        key = (e.get("kind"), e.get("sha256"), e.get("ref"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _h_gate_result(ev: AuditEvent, rows: RowStore, ctx: FoldContext, state: str) -> None:
    doc, wo_id = _wo_cas(rows, ev)
    if "preview" in ev.payload:
        doc["preview"] = ev.payload["preview"]
    if "evidence" in ev.payload:
        doc["evidence"] = _merge_evidence(doc.get("evidence", []),
                                          ev.payload["evidence"])
    if "gate" in ev.payload:
        doc["last_gate"] = ev.payload["gate"]
    if "failed_attempt_n" in ev.payload:
        for a in doc.get("attempts", []):
            if a.get("n") == ev.payload["failed_attempt_n"]:
                a["state"] = ev.payload.get("attempt_outcome", "gate_failed")
    # §1.3: one wo.failed event, two possible targets — building (attempt
    # n+1, if the per_order rail allows) or failed (attempts or rail
    # exhausted). The service decides which; the event carries it.
    doc["state"] = ev.payload.get("to_state", state)
    _wo_save(rows, wo_id, doc, ev.seq)


def _h_terminal(ev: AuditEvent, rows: RowStore, ctx: FoldContext, state: str) -> None:
    _wo_patch(rows, ev, ctx, state, ("decided_by", "decided_at", "promotion", "kept_branch"))


def _h_question_answered(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    q_id = ev.subject_id
    row = rows.get("questions", {"id": q_id})
    if row is not None:
        doc = _load(row)
        doc["answer"] = ev.payload.get("answer")
        doc["answered_at"] = ev.at
        rows.put("questions", {"id": q_id}, {
            "id": q_id, "open": 0, "blocking": row.get("blocking", 1),
            "updated_seq": ev.seq, "payload": _dump(doc),
        })
    wo_id = ev.payload.get("wo")
    if wo_id:
        wrow = rows.get("work_orders", {"id": wo_id})
        if wrow is not None:
            doc = _load(wrow)
            if doc.get("state") == "questioned":
                doc["state"] = "compiling"
                doc["answered_questions"] = list(doc.get("answered_questions", [])) + [q_id]
                _wo_save(rows, wo_id, doc, ev.seq)


# ---------------------------------------------------------------- questions

def _h_question_parked(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    q_id = ev.subject_id or ev.payload.get("id")
    doc = dict(ev.payload)
    doc.setdefault("id", q_id)
    rows.put("questions", {"id": q_id}, {
        "id": q_id, "open": 1, "blocking": 1 if doc.get("blocking", True) else 0,
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_assumption(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    q_id = ev.payload.get("question")
    row = rows.get("questions", {"id": q_id})
    if row is not None:
        doc = _load(row)
        doc["assumption"] = ev.payload.get("assumption")
        rows.put("questions", {"id": q_id}, {
            "id": q_id, "open": row.get("open", 1), "blocking": row.get("blocking", 1),
            "updated_seq": ev.seq, "payload": _dump(doc),
        })


# ---------------------------------------------------------------- predictions

def _h_prediction_sealed(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    doc = dict(ev.payload.get("prediction", {}))
    pr_id = doc.get("id") or ev.subject_id
    doc.setdefault("id", pr_id)
    rows.put("predictions", {"id": pr_id}, {
        "id": pr_id, "verdict": None, "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_prediction_scored(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    pr_id = ev.subject_id
    row = rows.get("predictions", {"id": pr_id})
    if row is None:
        raise StaleTransition(f"prediction {pr_id} does not exist", entity=pr_id)
    doc = _load(row)
    if doc.get("verdict") is not None:
        raise StaleTransition(f"prediction {pr_id} already scored", entity=pr_id)
    doc["verdict"] = ev.payload.get("verdict")
    doc["scored_at"] = ev.at
    doc["scored_by"] = ev.payload.get("scored_by")
    rows.put("predictions", {"id": pr_id}, {
        "id": pr_id, "verdict": ev.payload.get("verdict"),
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


# ---------------------------------------------------------------- taste

def _ratified(rows: RowStore, author: str) -> bool:
    row = rows.get("taste_authors", {"author": author})
    return bool(row and row.get("ratified"))


def _h_taste_note(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    if ev.payload.get("redacted"):
        return  # erased in place (§1.0's one immutability exception)
    doc = dict(ev.payload.get("row", ev.payload))
    tn_id = doc.get("id") or ev.subject_id
    author = doc.get("author", "")
    status = "pending_ratification" if (author in ctx.kid_actors and not _ratified(rows, author)) else "active"
    doc.setdefault("id", tn_id)
    # the status is part of the note, not only a column on the row: a reader
    # that reads the note must see that it is still pending
    doc["status"] = status
    rows.put("taste_notes", {"id": tn_id}, {
        "id": tn_id, "author": author, "status": status,
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_taste_ratified(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    author = ev.payload.get("author", ev.subject_id)
    rows.put("taste_authors", {"author": author}, {
        "author": author, "ratified": 1, "updated_seq": ev.seq, "payload": _dump({"author": author}),
    })
    for row in rows.scan("taste_notes"):
        if row.get("author") == author and row.get("status") == "pending_ratification":
            doc = _load(row)
            rows.put("taste_notes", {"id": row["id"]}, {
                "id": row["id"], "author": author, "status": "active",
                "updated_seq": ev.seq, "payload": _dump({**doc, "status": "active"}),
            })


def _h_taste_erased(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    author = ev.payload.get("author", ev.subject_id)
    for row in rows.scan("taste_notes"):
        if row.get("author") == author:
            rows.delete("taste_notes", {"id": row["id"]})


# ---------------------------------------------------------------- vocabulary

def _h_vocab_word_added(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    word = ev.subject_id or ev.payload.get("word")
    doc = dict(ev.payload.get("entry", {}))
    doc.setdefault("word", word)
    doc.setdefault("status", ev.payload.get("status", "active"))
    doc.setdefault("version", 1)
    doc.setdefault("calls", 0)
    rows.put("vocab_words", {"word": word}, {
        "word": word, "status": doc["status"], "version": doc["version"],
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_vocab_word_status(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    word = ev.subject_id
    row = rows.get("vocab_words", {"word": word})
    if row is None:
        return
    doc = _load(row)
    if "status" in ev.payload:
        doc["status"] = ev.payload["status"]
    if "version" in ev.payload:
        doc["version"] = ev.payload["version"]
    for f in ("provenance", "params"):
        if f in ev.payload:
            doc[f] = ev.payload[f]
    rows.put("vocab_words", {"word": word}, {
        "word": word, "status": doc.get("status"), "version": doc.get("version"),
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_vocab_call(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    if ev.refused:
        return
    word = ev.payload.get("word")
    row = rows.get("vocab_words", {"word": word})
    if row is None:
        return
    doc = _load(row)
    doc["calls"] = int(doc.get("calls", 0)) + 1
    rows.put("vocab_words", {"word": word}, {
        "word": word, "status": doc.get("status"), "version": doc.get("version"),
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


# ---------------------------------------------------------------- night/task/budget

def _h_night_started(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    night = ev.subject_id
    doc = dict(ev.payload.get("night", {}))
    doc.setdefault("id", night)
    doc.setdefault("state", "running")
    rows.put("nights", {"id": night}, {
        "id": night, "state": doc["state"], "updated_seq": ev.seq, "payload": _dump(doc),
    })
    rows.put("budget", {"night": night}, {
        "night": night, "updated_seq": ev.seq,
        "payload": _dump({"night": night, "gpu_minutes": 0.0, "hosted_cents": 0,
                          "wall_minutes": 0.0, "loads": {}, "rails": doc.get("rails", {}),
                          "load_budget": doc.get("load_budget", {})}),
    })


def _h_night_event(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    night = ev.subject_id
    row = rows.get("nights", {"id": night})
    if row is None:
        return
    doc = _load(row)
    kind = ev.type
    if kind == "night.preflight":
        doc["preflight"] = ev.payload.get("preflight", {})
    elif kind == "night.tick":
        doc["tick_count"] = int(doc.get("tick_count", 0)) + 1
        doc["last_tick_at"] = ev.at
    elif kind == "night.stopped":
        doc["state"] = "stopped"
        doc["stopped_at"] = ev.payload.get("stopped_at", ev.at)
        doc["stop_reason"] = ev.payload.get("reason")
        doc["status"] = ev.payload.get("status")
        if "report" in ev.payload:
            rep = ev.payload["report"]
            # the model's `report` is a reference (the json artifact's hash);
            # the full descriptors stay alongside it
            doc["report_artifacts"] = rep
            if isinstance(rep, dict):
                doc["report"] = (rep.get("json") or {}).get("sha256")
            else:
                doc["report"] = rep
    elif kind == "kill.switch":
        doc["kill_switch"] = True
    elif kind == "power.mode.set":
        doc["power_mode"] = ev.payload.get("mode")
    rows.put("nights", {"id": night}, {
        "id": night, "state": doc.get("state"), "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_task_created(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    task_id = ev.subject_id or ev.payload.get("id")
    doc = dict(ev.payload.get("task", {}))
    doc.setdefault("id", task_id)
    night = doc.get("night") or ev.payload.get("night")
    doc.setdefault("state", "queued" if night else "slated")
    doc.setdefault("predictions", [])
    doc.setdefault("branches", [])
    rows.put("tasks", {"id": task_id}, {
        "id": task_id, "state": doc["state"], "night": night, "author": doc.get("author"),
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_task_state(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    doc, task_id = _task_cas(rows, ev)
    doc["state"] = ev.payload.get("to", ev.payload.get("state", doc.get("state")))
    if "night" in ev.payload and ev.payload["night"]:
        doc["night"] = ev.payload["night"]
    if "reason" in ev.payload:
        doc["last_reason"] = ev.payload["reason"]
    rows.put("tasks", {"id": task_id}, {
        "id": task_id, "state": doc["state"], "night": doc.get("night"),
        "author": doc.get("author"), "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_budget_spend(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    night = ev.payload.get("night") or ev.subject_id
    row = rows.get("budget", {"night": night}) if night else None
    if row is not None:
        doc = _load(row)
        spend = ev.payload.get("spend", {})
        doc["gpu_minutes"] = round(float(doc.get("gpu_minutes", 0)) + float(spend.get("gpu_minutes", 0)), 6)
        doc["hosted_cents"] = int(doc.get("hosted_cents", 0)) + int(spend.get("hosted_cents", 0))
        doc["wall_minutes"] = round(float(doc.get("wall_minutes", 0)) + float(spend.get("wall_minutes", 0)), 6)
        doc["last_spend"] = ev.payload.get("spend", {})
        if "job" in ev.payload:
            doc.setdefault("spend_events", []).append({"seq": ev.seq, "job": ev.payload["job"]})
        rows.put("budget", {"night": night}, {"night": night, "updated_seq": ev.seq, "payload": _dump(doc)})
    wo_id = ev.payload.get("wo")
    if wo_id:
        wrow = rows.get("work_orders", {"id": wo_id})
        if wrow is not None:
            doc = _load(wrow)
            cur = dict(doc.get("spend_so_far") or {})
            spend = ev.payload.get("spend", {})
            cur["gpu_minutes"] = round(float(cur.get("gpu_minutes", 0)) + float(spend.get("gpu_minutes", 0)), 6)
            cur["hosted_cents"] = int(cur.get("hosted_cents", 0)) + int(spend.get("hosted_cents", 0))
            cur["wall_minutes"] = round(float(cur.get("wall_minutes", 0)) + float(spend.get("wall_minutes", 0)), 6)
            doc["spend_so_far"] = cur
            _wo_save(rows, wo_id, doc, ev.seq)


def _h_model_load(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    night = ev.payload.get("night") or ev.subject_id
    row = rows.get("budget", {"night": night})
    if row is None:
        return
    doc = _load(row)
    model = ev.payload.get("model", "unknown")
    loads = dict(doc.get("loads", {}))
    loads[model] = int(loads.get(model, 0)) + 1
    doc["loads"] = loads
    rows.put("budget", {"night": night}, {"night": night, "updated_seq": ev.seq, "payload": _dump(doc)})


# ---------------------------------------------------------------- scheduler

def _h_job(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    job_id = ev.subject_id
    state_map = {
        "job.enqueued": "queued", "job.started": "running", "job.done": "done",
        "job.requeued": "requeued",
    }
    row = rows.get("jobs", {"id": job_id})
    doc = _load(row) if row else {"id": job_id}
    doc.setdefault("id", job_id)
    state = state_map[ev.type]
    if ev.type == "job.done" and ev.payload.get("outcome") == "failed":
        state = "failed"
    doc["state"] = state
    for f in ("outputs", "stage_cache", "power_mode", "model", "lane", "request", "lease_until"):
        if f in ev.payload:
            doc[f] = ev.payload[f]
    if ev.type == "job.requeued" and "reason" in ev.payload:
        doc["last_requeue_reason"] = ev.payload["reason"]
    rows.put("jobs", {"id": job_id}, {"id": job_id, "state": state, "updated_seq": ev.seq, "payload": _dump(doc)})


# ---------------------------------------------------------------- branches / nodes

def _h_branch_created(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    # Two spellings, one fact: the spine writes the branch doc under "branch"
    # (or bare "id"); the recipe store writes it flat with "branch" as the id.
    payload = ev.payload
    br_id = ev.subject_id or payload.get("id") or (
        payload.get("branch") if isinstance(payload.get("branch"), str) else None
    )
    if isinstance(payload.get("branch"), dict):
        doc = dict(payload["branch"])
    else:
        doc = {k: v for k, v in payload.items() if k != "branch"}
    doc.setdefault("name", payload.get("name"))
    doc.setdefault("id", br_id)
    doc.setdefault("head", ev.payload.get("head"))
    doc.setdefault("purpose", "main" if doc.get("name") == "main" else "work-order")
    doc.setdefault("protected", doc.get("name") == "main")
    rows.put("branches", {"id": br_id}, {
        "id": br_id, "head": doc.get("head"), "purpose": doc.get("purpose"),
        "protected": 1 if doc.get("protected") else 0,
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_branch_head_moved(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    br_id = ev.subject_id
    row = rows.get("branches", {"id": br_id})
    if row is None:
        return
    doc = _load(row)
    from_head = ev.payload.get("from_head", ev.payload.get("from"))
    if from_head is not None and doc.get("head") != from_head:
        raise StaleTransition(
            f"branch {br_id}: expected head {from_head!r}, found {doc.get('head')!r}",
            entity=br_id,
        )
    doc["head"] = ev.payload.get("to")
    rows.put("branches", {"id": br_id}, {
        "id": br_id, "head": doc["head"], "purpose": doc.get("purpose"),
        "protected": 1 if doc.get("protected") else 0,
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_branch_purpose(ev: AuditEvent, rows: RowStore, ctx: FoldContext, purpose: str | None = None) -> None:
    br_id = ev.subject_id
    row = rows.get("branches", {"id": br_id})
    if row is None:
        return
    doc = _load(row)
    if purpose:
        doc["purpose"] = purpose
    if ev.type == "branch.proposed":
        doc["proposed_pending"] = {"by": ev.payload.get("by"), "at": ev.at}
    rows.put("branches", {"id": br_id}, {
        "id": br_id, "head": doc.get("head"), "purpose": doc.get("purpose"),
        "protected": 1 if doc.get("protected") else 0,
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_version_committed(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    """The node-registry seam (§1.4.0): the recipe half's compiler publishes
    nodes.json as a content-addressed artifact on version.committed; the
    registry is the fold of those artifacts, keyed per branch head."""
    art = ev.artifact or {}
    if art.get("kind") != "nodes.json":
        return
    branch = ev.payload.get("branch") or ev.payload.get("br")
    if not branch:
        return
    nodes = json.loads(ctx.artifacts.get(art["sha256"]).decode("utf-8"))
    seen: set[str] = set()
    for node in nodes.get("nodes", []):
        node_id = node.get("node_id")
        seen.add(node_id)
        rows.put("node_refs", {"branch": branch, "node_id": node_id}, {
            "branch": branch, "node_id": node_id, "entry_path": node.get("entry_path"),
            "kind": node.get("kind"), "orphaned": 0, "updated_seq": ev.seq,
            "payload": _dump(node),
        })
    for row in rows.scan("node_refs"):
        if row.get("branch") == branch and row.get("node_id") not in seen and not row.get("orphaned"):
            doc = _load(row)
            rows.put("node_refs", {"branch": branch, "node_id": row["node_id"]}, {
                "branch": branch, "node_id": row["node_id"], "entry_path": row.get("entry_path"),
                "kind": row.get("kind"), "orphaned": 1, "updated_seq": ev.seq,
                "payload": _dump({**doc, "orphaned": True}),
            })


# ---------------------------------------------------------------- assets / critic / client

def _h_asset_created(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    ast_id = ev.subject_id or ev.payload.get("id")
    doc = dict(ev.payload.get("asset", {}))
    doc.setdefault("id", ast_id)
    rows.put("assets", {"id": ast_id}, {"id": ast_id, "updated_seq": ev.seq, "payload": _dump(doc)})


def _h_asset_licence(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    ast_id = ev.subject_id
    row = rows.get("assets", {"id": ast_id})
    if row is None:
        return
    doc = _load(row)
    doc["licence_check"] = ev.payload.get("check", {})
    rows.put("assets", {"id": ast_id}, {"id": ast_id, "updated_seq": ev.seq, "payload": _dump(doc)})


def _h_critic_verdict(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    vid = ev.payload.get("id") or ev.subject_id or f"cv_{ev.seq}"
    doc = dict(ev.payload)
    doc.setdefault("id", vid)
    doc.setdefault("at", ev.at)
    rows.put("critic_verdicts", {"id": vid}, {
        "id": vid, "night": doc.get("night"), "branch": doc.get("branch"),
        "verdict": doc.get("verdict"), "degraded": 1 if doc.get("degraded") else 0,
        "updated_seq": ev.seq, "payload": _dump(doc),
    })


def _h_client(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    actor = ev.payload.get("actor", ev.subject_id or "client")
    attached = 1 if ev.type == "client.attach" else 0
    rows.put("client_presence", {"actor": actor}, {
        "actor": actor, "attached": attached, "updated_seq": ev.seq,
        "payload": _dump({"actor": actor, "attached": bool(attached), "at": ev.at}),
    })


HANDLERS: dict[str, Callable[[AuditEvent, RowStore, FoldContext], None]] = {
    "wo.filed": _h_wo_filed,
    "wo.compiled": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="draft",
        fields=("title", "goal", "targets", "acceptance", "budget", "estimate", "confirm_line",
                "origin", "vocabulary_gap", "promote", "packet")),
    "wo.questioned": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="questioned",
        fields=("question", "question_id", "candidates")),
    "question.answered": _h_question_answered,
    "wo.confirmed": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="queued",
        fields=("budget", "estimate", "confirmed_by")),
    "wo.cancelled": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="cancelled", fields=("cancelled_by",)),
    "wo.queued": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="queued", fields=("night",)),
    "wo.attempt.started": _h_attempt_started,
    "wo.attempt.delivered": _h_attempt_delivered,
    "wo.testing": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="testing", fields=("gate_started",)),
    "wo.landed": lambda ev, r, c: _h_gate_result(ev, r, c, "landed"),
    "wo.failed": lambda ev, r, c: _h_gate_result(ev, r, c, "failed"),
    "wo.kept": lambda ev, r, c: _h_terminal(ev, r, c, "kept"),
    "wo.rejected": lambda ev, r, c: _h_terminal(ev, r, c, "rejected"),
    "wo.parked": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="parked", fields=("park_reason",)),
    "wo.resumed": lambda ev, r, c: _wo_patch(ev=ev, rows=r, ctx=c, state="queued", fields=("resumed_by",)),
    "question.parked": _h_question_parked,
    "assumption.recorded": _h_assumption,
    "prediction.sealed": _h_prediction_sealed,
    "prediction.scored": _h_prediction_scored,
    "taste.note.appended": _h_taste_note,
    "taste.erased": _h_taste_erased,
    "taste.ratified": _h_taste_ratified,
    "vocab.word.added": _h_vocab_word_added,
    "vocab.word.status": _h_vocab_word_status,
    "vocab.call": _h_vocab_call,
    "night.started": _h_night_started,
    "night.preflight": _h_night_event,
    "night.tick": _h_night_event,
    "night.stopped": _h_night_event,
    "kill.switch": _h_night_event,
    "power.mode.set": _h_night_event,
    "night.task.created": _h_task_created,
    "night.task.state": _h_task_state,
    "budget.spend": _h_budget_spend,
    "sched.model.load": _h_model_load,
    "job.enqueued": _h_job,
    "job.started": _h_job,
    "job.done": _h_job,
    "job.requeued": _h_job,
    "branch.created": _h_branch_created,
    "branch.head.moved": _h_branch_head_moved,
    "branch.rejected": lambda ev, r, c: _h_branch_purpose(ev, r, c, "rejected"),
    "branch.proposed": lambda ev, r, c: _h_branch_purpose(ev, r, c, None),
    "version.committed": _h_version_committed,
    "asset.created": _h_asset_created,
    "asset.licence.checked": _h_asset_licence,
    "critic.verdict": _h_critic_verdict,
    "client.attach": _h_client,
    "client.detach": _h_client,
}

# Events with no projection change: edit.proposed, edit.validated,
# constraint.failed, sched.model.unload, sched.demote, render.completed,
# scene.loaded/evicted, line.spoken, model.change.noticed, core.boot,
# core.recovered, projection.rebuilt, integrity.failure, call.refused —
# the audit row alone is the record; read paths query the log directly.


def apply_event(ev: AuditEvent, rows: RowStore, ctx: FoldContext) -> None:
    """Apply one committed event to a row store. Refused events (the
    vocab.call precedent) and redacted taste payloads change nothing."""
    if ev.refused:
        return
    if ev.type == "taste.note.appended" and isinstance(ev.payload, dict) and ev.payload.get("redacted"):
        return
    handler = HANDLERS.get(ev.type)
    if handler is not None:
        handler(ev, rows, ctx)


def fold_all(events: list[AuditEvent], ctx: FoldContext) -> MemoryRowStore:
    shadow = MemoryRowStore()
    for ev in events:
        apply_event(ev, shadow, ctx)
    return shadow


def stores_equal(a: RowStore, b: RowStore) -> list[str]:
    """Table-level diff used by boot verification."""
    diffs: list[str] = []
    for table in FOLD_TABLES:
        ra = {tuple(sorted((k, v) for k, v in r.items() if k != "payload")): r for r in a.scan(table)}
        rb = {tuple(sorted((k, v) for k, v in r.items() if k != "payload")): r for r in b.scan(table)}
        if ra.keys() != rb.keys():
            diffs.append(f"{table}: key sets differ")
            continue
        for key in ra:
            pa, pb = ra[key].get("payload"), rb[key].get("payload")
            if isinstance(pa, str):
                pa = json.loads(pa)
            if isinstance(pb, str):
                pb = json.loads(pb)
            if pa != pb:
                diffs.append(f"{table}[{key}]: payload differs")
    return diffs
