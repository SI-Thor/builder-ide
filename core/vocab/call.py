"""The door: a character's typed call, validated and refused at the threshold.

Spec §1.5: *"A character's call is `POST /v1/vocab/call {word, node | region,
params}` → the core validates against the schema, binds the acceptance
template, and produces a `RecipeEdit` authored `{kind: character, id: …,
via: word}`. Anything outside the schema is refused at the door — that
refusal, said in character, is the 'I can't do rope yet' moment."*

So a call either produces a typed edit or produces a **refusal with a reason
code** — never a silent repair, never a best guess. The refusal is audited as
a `vocab.call` event (§1.8: "refused calls included — the edges are the
story"), because the refusals are where the vocabulary's edges show up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .hashing import short_hash
from .models import AcceptanceCheck, Actor, AuditEvent, Op, RecipeEdit, VocabularyEntry
from .registry import VocabularyRegistry, entry_path_for
from .schema import ParamsError, SchemaError

__all__ = [
    "CallRefusal",
    "VocabularyService",
    "bind_acceptance_template",
    "REFUSAL_REASONS",
]

#: The closed set of refusal reasons a door can produce.
REFUSAL_REASONS: tuple[str, ...] = (
    "unknown_word",
    "word_not_active",
    "no_referent",
    "no_base",
    "params_not_an_object",
    "unknown_property",
    "missing_property",
    "type_mismatch",
    "out_of_range",
    "not_in_enum",
    "cross_field_violation",
    "params_too_large",
    "word_schema_broken",
)


@dataclass(frozen=True)
class CallRefusal:
    """A refused call, with the reason and the line the character says."""

    reason: str
    detail: str
    word: str
    line: str

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return False


class VocabularyService:
    """Turns a character's typed call into a validated `RecipeEdit` — or a refusal."""

    def __init__(
        self,
        *,
        registry: VocabularyRegistry,
        ledger: Any,
        clock: Any,
        recipes: Any | None = None,
    ) -> None:
        self._registry = registry
        self._ledger = ledger
        self._clock = clock
        self._recipes = recipes

    # -- the call --------------------------------------------------------------

    def call(
        self,
        *,
        word: str,
        params: Mapping[str, Any],
        actor: Actor,
        node: str | None = None,
        region: str | None = None,
        base: str | None = None,
        branch: str | None = None,
    ) -> RecipeEdit | CallRefusal:
        """Validate a call at the door and produce a typed edit."""
        entry = self._registry.get(word)
        if entry is None:
            return self._refuse(
                reason="unknown_word",
                detail=f"{word!r} is not a word in this vocabulary",
                word=word,
                line=f"I don't have {word} in my hands yet.",
                node=node,
                region=region,
                actor=actor,
            )

        if entry.status != "active":
            return self._refuse(
                reason="word_not_active",
                detail=f"{word} is {entry.status}",
                word=word,
                line=f"{word} isn't in my hands yet — {entry.status}.",
                node=node,
                region=region,
                actor=actor,
            )

        if not node and not region:
            return self._refuse(
                reason="no_referent",
                detail="a call names a node or a region",
                word=word,
                line="Which one? I need to know where.",
                node=node,
                region=region,
                actor=actor,
            )

        try:
            self._registry.validate_params(word, params)
        except ParamsError as error:
            return self._refuse(
                reason=error.reason,
                detail=error.detail,
                word=word,
                line=self._line_for(entry, error),
                node=node,
                region=region,
                actor=actor,
            )
        except SchemaError as error:  # a core fault, not the caller's
            return self._refuse(
                reason="word_schema_broken",
                detail=error.detail,
                word=word,
                line=f"{word} is miswritten on my side — I can't call it.",
                node=node,
                region=region,
                actor=actor,
            )

        resolved_base = base
        if resolved_base is None and branch is not None and self._recipes is not None:
            resolved_base = self._recipes.head(branch)
        if not resolved_base:
            return self._refuse(
                reason="no_base",
                detail="a call needs the version it starts from",
                word=word,
                line="I don't know what I'm editing.",
                node=node,
                region=region,
                actor=actor,
            )

        edit = self._build_edit(
            entry=entry,
            params=params,
            actor=actor,
            base=resolved_base,
            node=node,
            region=region,
        )

        self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'vocab.call', 'edit': edit.id})}",
                at=self._clock.now(),
                actor=actor,
                type="vocab.call",
                subject={"entity_kind": "vocabulary", "entity_id": word},
                payload={
                    "word": word,
                    "node": node,
                    "region": region,
                    "params": dict(params),
                    "refused": False,
                    "edit_id": edit.id,
                },
            )
        )
        return edit

    # -- internals -------------------------------------------------------------

    def _build_edit(
        self,
        *,
        entry: VocabularyEntry,
        params: Mapping[str, Any],
        actor: Actor,
        base: str,
        node: str | None,
        region: str | None,
    ) -> RecipeEdit:
        entry_path = entry_path_for(entry.word)
        ops = [
            Op(op="set", path=f"{entry_path}.params.{name}", value=params[name])
            for name in params
        ]
        author = Actor(kind=actor.kind, id=actor.id, via="word")
        message = self._message_for(entry, params)
        return RecipeEdit(
            id=f"ed_{short_hash({'base': base, 'ops': [op.model_dump() for op in ops]})}",
            base=base,
            ops=ops,
            author=author,
            message=message,
        )

    def _message_for(self, entry: VocabularyEntry, params: Mapping[str, Any]) -> str:
        """The one line a card shows (§1.1: ≤ 80 chars, one line)."""
        summary = ", ".join(f"{name} {params[name]}" for name in sorted(params))
        message = f"{entry.word}: {summary}"
        return message[:80]

    def _line_for(self, entry: VocabularyEntry, error: ParamsError) -> str:
        """The refusal, said in character."""
        names = ", ".join(sorted(entry.params.get("properties", {})))
        if error.reason == "unknown_property":
            return f"{entry.word} takes {names} — nothing else."
        if error.reason == "missing_property":
            return f"{entry.word} needs {names}."
        if error.reason == "not_in_enum":
            return f"{entry.word} takes only the values it lists — not that one."
        if error.reason == "out_of_range":
            return f"{entry.word} stays inside its bounds — that is outside them."
        if error.reason == "cross_field_violation":
            return f"{entry.word} counts those against each other — that pair doesn't hold."
        if error.reason == "params_too_large":
            return f"{entry.word} takes a smaller set than that."
        return f"{entry.word} takes {names}."

    def _refuse(
        self,
        *,
        reason: str,
        detail: str,
        word: str,
        line: str,
        node: str | None,
        region: str | None,
        actor: Actor,
    ) -> CallRefusal:
        self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'vocab.call', 'refused': reason, 'word': word, 'n': node, 'r': region})}",
                at=self._clock.now(),
                actor=actor,
                type="vocab.call",
                subject={"entity_kind": "vocabulary", "entity_id": word},
                payload={
                    "word": word,
                    "node": node,
                    "region": region,
                    "refused": True,
                    "reason": reason,
                    "detail": detail,
                },
            )
        )
        return CallRefusal(reason=reason, detail=detail, word=word, line=line)


def bind_acceptance_template(
    entry: VocabularyEntry, node: str | None
) -> AcceptanceCheck | None:
    """Bind a word's acceptance template to the node that was called (§1.5).

    The template carries `{node}` placeholders; at call time they are bound to
    the node the character pointed at, so the check that lands on the board
    names a real thing.
    """
    if entry.acceptance_template is None:
        return None
    spec = {
        key: (value.replace("{node}", node) if isinstance(value, str) else value)
        for key, value in entry.acceptance_template.spec.items()
    }
    return AcceptanceCheck(kind=entry.acceptance_template.kind, spec=spec)
