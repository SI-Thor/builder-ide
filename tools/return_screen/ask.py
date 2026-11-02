"""ask.py — "what happened to X?" as active perception, not a full replay.

The idea is borrowed from OmniAgent's active perception
(docs/research/omniagent.md on main): an agent that answers questions about
a long log by *choosing what to look at* — ``get_clip(t0, t1)`` maps onto
ledger ranges here — instead of replaying everything. This module is the
look-choosing half: a deterministic planner turns a free-text question into
one ``core.rewind`` selection expression, runs it, and reports what it
pulled (and how little of the ledger that was). No model, no guesswork:
every extraction rule is below, and the expression the planner built is
returned with the answer so the human can see exactly what was read.
"""

from __future__ import annotations

import re
from typing import Any

from worldview import CHARACTERS, _iso, parse_at

KIND_WORDS: dict[str, str] = {
    "play": "tile.played", "played": "tile.played", "plays": "tile.played",
    "skill": "tile.played", "decision": "tile.played", "decisions": "tile.played",
    "verdict": "judge.verdict", "verdicts": "judge.verdict", "judge": "judge.verdict",
    "refusal": "judge.verdict", "refused": "judge.verdict", "refusals": "judge.verdict",
    "authored": "tile.authored", "admitted": "tile.authored", "new skill": "tile.authored",
    "new skills": "tile.authored", "retired": "tile.retired", "rejected": "tile.retired",
}

ID_RE = re.compile(r"skill_[0-9a-f]{6,}")
LAST_RE = re.compile(r"last (\d+) ?(h|hour|hours|m|minute|minutes|d|day|days)")
SINCE_RE = re.compile(r"since (\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?Z?)")


def _actors_in(question: str) -> list[str]:
    lowered = question.lower()
    found = [c for c in CHARACTERS if c.lower() in lowered]
    if "judge" in lowered or "verdict" in lowered:
        found.append("judge@d1:d1-2B")
    if "seed" in lowered:
        found.append("seed")
    if "mediator" in lowered or "retired" in lowered:
        found.append("mediator")
    return found


def _kinds_in(question: str) -> list[str]:
    lowered = question.lower()
    kinds: list[str] = []
    for word, kind in KIND_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered) and kind not in kinds:
            kinds.append(kind)
    return kinds


def _window(question: str, since_epoch: float, now: float) -> tuple[float, float] | None:
    """The time window the question names; None means the default."""
    m = LAST_RE.search(question.lower())
    if m:
        n, unit = int(m.group(1)), m.group(2)[0]
        seconds = n * {"h": 3600, "m": 60, "d": 86400}[unit]
        return (now - seconds, now)
    m = SINCE_RE.search(question)
    if m:
        start = parse_at(m.group(1) if m.group(1).endswith("Z") else m.group(1) + "Z")
        return (start, now)
    if "since i left" in question.lower() or "while i was away" in question.lower():
        return (since_epoch, now)
    return None


def plan_expression(question: str, since_epoch: float, now: float) -> dict[str, Any]:
    """One selection expression answering the question, plus its reading."""
    actors = _actors_in(question)
    kinds = _kinds_in(question)
    window = _window(question, since_epoch, now)
    ids = ID_RE.findall(question)
    clauses: list[str] = []
    if window:
        clauses.append(f"at >= {window[0]:.0f} and at < {window[1]:.0f}")
    if ids:
        clauses.append(" or ".join(f"id = {i}" for i in ids))
    elif actors and kinds:
        clauses.append(f"actor in ({', '.join(actors)}) and kind in ({', '.join(kinds)})")
    elif actors:
        clauses.append(f"actor in ({', '.join(actors)})")
    elif kinds:
        clauses.append(f"kind in ({', '.join(kinds)})")
    expression = " and ".join(f"({c})" for c in clauses) if clauses else "at >= 0"
    return {"expression": expression, "actors": actors, "kinds": kinds,
            "ids": ids, "window": window, "defaulted": not clauses}


def answer(question: str, view, human: str | None = None) -> dict[str, Any]:
    """Pull only the slice that answers `question`, from the cached ledger."""
    import time as _time
    from core.rewind import parse, select  # the same language the rewind uses

    now = _time.time()
    since_epoch = view.last_seen(human or (view.humans()[0]["name"]
                                           if view.humans() else "Casey")) or now
    plan = plan_expression(question, since_epoch, now)
    rows = view.rows()
    ledger = _as_rewind_ledger(rows)
    result = select(ledger, parse(plan["expression"]))

    kept = set(result.kept_seqs)
    matched = [r for r in rows if r["seq"] in kept]
    by_kind: dict[str, int] = {}
    by_actor: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    refused = 0
    first_at = last_at = None
    for r in matched:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        by_actor[r["actor"]] = by_actor.get(r["actor"], 0) + 1
        if r["kind"] == "tile.played":
            outcomes[r["verdict"]] = outcomes.get(r["verdict"], 0) + 1
        if r.get("refused"):
            refused += 1
        if first_at is None:
            first_at = r["at_iso"]
        last_at = r["at_iso"]
    summary = _summarise(question, plan, matched, by_kind, by_actor, outcomes, refused)
    return {
        "question": question,
        "expression": plan["expression"],
        "planner": {k: v for k, v in plan.items() if k != "window"},
        "window": ([_iso(plan["window"][0]), _iso(plan["window"][1])]
                   if plan["window"] else None),
        "matched": len(matched),
        "of_total_rows": len(rows),
        "fraction_of_ledger": round(len(matched) / len(rows), 4) if rows else 0.0,
        "by_kind": by_kind, "by_actor": by_actor,
        "outcomes": outcomes, "refused": refused,
        "first_at": first_at, "last_at": last_at,
        "summary": summary,
        "sample": [_sample_row(r) for r in matched[-25:]],
    }


def _sample_row(r: dict) -> dict:
    out = {"at": r["at_iso"], "seq": r["seq"], "kind": r["kind"], "actor": r["actor"]}
    if r["kind"] == "tile.played":
        out["verdict"] = r["verdict"]
        out["skill"] = r.get("skill")
        out["detail"] = (r["payload"].get("outcome") or {}).get("detail")
    elif r["kind"] == "judge.verdict":
        out["refused"] = bool(r.get("refused"))
    elif r["kind"] == "tile.authored":
        out["title"] = r["payload"].get("title")
        out["family"] = r["payload"].get("family")
    elif r["kind"] == "tile.retired":
        out["family"] = r["payload"].get("family")
        out["reason"] = r["payload"].get("reason")
    return out


def _summarise(question: str, plan: dict, matched: list[dict], by_kind: dict,
               by_actor: dict, outcomes: dict, refused: int) -> str:
    if not matched:
        return ("Nothing in the ledger answers that — the selection the planner built "
                f"(`{plan['expression']}`) matched no rows.")
    who = ", ".join(f"{a} ({n})" for a, n in sorted(by_actor.items(), key=lambda kv: -kv[1])[:4])
    what = ", ".join(f"{k} ({n})" for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1]))
    parts = [f"The slice that answers it holds {len(matched)} rows: {what}; by actor: {who}."]
    if outcomes:
        total = sum(outcomes.values())
        parts.append(f"Play outcomes: {outcomes.get('win', 0)} win / "
                     f"{outcomes.get('partial', 0)} partial / {outcomes.get('lose', 0)} lose "
                     f"of {total}.")
    if refused:
        parts.append(f"{refused} of them are refusals.")
    return " ".join(parts)


def _as_rewind_ledger(rows: list[dict]):
    """Adapt the cached fold into a core.rewind Ledger (no second sqlite read)."""
    from core.rewind.ledger import LedgerRow, ledger_from_rows

    adapted = []
    for r in rows:
        payload = r["payload"]
        if r["kind"] == "tile.played":
            entity_id = payload.get("skill_id", "")
        elif r["kind"] in ("tile.authored",):
            entity_id = payload.get("skill", "")
        else:
            subject = payload.get("subject") or {}
            entity_id = subject.get("skill", "") if isinstance(subject, dict) else ""
        adapted.append(LedgerRow(
            seq=r["seq"], at=r["at"], actor=r["actor"], agent=r.get("agent") or "",
            kind=r["kind"], entity_id=entity_id, verdict=r.get("verdict") or "",
            payload=payload))
    return ledger_from_rows(adapted, source="world-ledger.sqlite3 (cached fold)")
