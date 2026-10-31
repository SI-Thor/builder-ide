"""The registry: the words, their schemas, and what a builder may say about them.

Spec §1.5: *"A character's call is `POST /v1/vocab/call {word, node | region,
params}` → the core validates against the schema, binds the acceptance
template, and produces a `RecipeEdit`."*

The registry also owns two derived views the panels read:

* the **entry path** of a word — how a word names a place in the recipe;
* the **capability view** — "Swing isn't in my hands yet — 0 built" is a view
  over the call log, not a new record type (X C12; RV patch 18).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .models import VocabularyEntry
from .schema import ParamsError, validate_params, validate_schema

__all__ = [
    "VocabularyRegistry",
    "CapabilityRow",
    "entry_path_for",
    "NAMESPACE_SEGMENTS",
]

#: A word's leading segment may be a namespace ("props", "material", …). The
#: entry path is the word without it: `props.harbor.crates` → `harbor.crates`.
NAMESPACE_SEGMENTS: frozenset[str] = frozenset(
    {
        "prop",
        "props",
        "material",
        "materials",
        "terrain",
        "weather",
        "motion",
        "light",
        "structure",
        "structures",
        "character",
        "characters",
        "constraint",
        "constraints",
    }
)


def entry_path_for(word: str) -> str:
    """The recipe entry path a word writes into.

    `props.harbor.crates` → `harbor.crates`; `bridge.rope` → `bridge.rope`
    (the spec's own example: the word *is* the path when it carries no
    namespace segment).
    """
    head, _, tail = word.partition(".")
    if tail and head in NAMESPACE_SEGMENTS:
        return tail
    return word


@dataclass(frozen=True)
class CapabilityRow:
    """What a character can honestly say about a word."""

    word: str
    calls: int
    refused: int
    built: int

    @property
    def line(self) -> str:
        """The capability row as it is spoken (plan moment 7)."""
        return f"{self.word}: {self.calls} calls · {self.built} built"


class VocabularyRegistry:
    """The closed vocabulary: the words, and the rules about calling them."""

    def __init__(self, entries: Iterable[VocabularyEntry] = ()) -> None:
        self._entries: dict[str, VocabularyEntry] = {}
        for entry in entries:
            self.add(entry)

    # -- the words -------------------------------------------------------------

    def add(self, entry: VocabularyEntry) -> VocabularyEntry:
        """Add a word. The schema is checked on the way in.

        A word that breaks the §1.5 subset never reaches the registry: it
        would be a word nobody could call safely.
        """
        validate_schema(entry.params)
        if entry.word in self._entries:
            raise ValueError(f"{entry.word} is already in the registry")
        self._entries[entry.word] = entry
        return entry

    def get(self, word: str) -> VocabularyEntry | None:
        return self._entries.get(word)

    def require(self, word: str) -> VocabularyEntry:
        entry = self._entries.get(word)
        if entry is None:
            raise KeyError(f"unknown word {word!r}")
        return entry

    def words(self) -> tuple[VocabularyEntry, ...]:
        return tuple(self._entries.values())

    def active_words(self) -> tuple[VocabularyEntry, ...]:
        return tuple(
            entry for entry in self._entries.values() if entry.status == "active"
        )

    def set_status(
        self,
        word: str,
        status: str,
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> VocabularyEntry:
        """Flip a word's status — the promotion transaction's write (§2.3).

        *"Keep ⇒ promotion, in one core transaction: … the word's `status`
        flips `coming-soon → active` with provenance pointing at the WO and
        commit."*
        """
        if status not in ("active", "coming-soon", "retired"):
            raise ValueError(f"{status!r} is not a word status")
        entry = self.require(word)
        merged = dict(entry.provenance)
        if provenance:
            merged.update(provenance)
        updated = entry.model_copy(update={"status": status, "provenance": merged})
        self._entries[word] = updated
        return updated

    def entry_path(self, word: str) -> str:
        """The recipe entry path of a word."""
        return entry_path_for(word)

    def word_for_entry_path(self, entry_path: str) -> VocabularyEntry | None:
        """The word that owns a recipe entry path, if any."""
        for entry in self._entries.values():
            if entry_path_for(entry.word) == entry_path:
                return entry
        return None

    # -- validation ------------------------------------------------------------

    def validate_params(self, word: str, params: Mapping[str, Any]) -> None:
        """Validate a call's params against a word's schema.

        Raises `ParamsError` — the refusal that happens at the door.
        """
        entry = self.require(word)
        validate_params(entry.params, params)

    def validate_document(self, document: Mapping[str, Any]) -> None:
        """Validate every entry of a recipe document that a word owns.

        This is the check `core-recipe` calls before it admits an edit
        (§1.1: "an edit is admitted only if the resulting document passes
        every touched entry's vocabulary param schema"). The vocabulary
        validates the params it owns; the engine owns the rest.
        """
        entries = document.get("entries", {})
        if not isinstance(entries, Mapping):
            return
        for entry_path, recipe_entry in entries.items():
            if not isinstance(recipe_entry, Mapping):
                continue
            word = self.word_for_entry_path(str(entry_path))
            if word is None:
                continue
            params = recipe_entry.get("params", {})
            if not isinstance(params, Mapping):
                raise ParamsError(
                    "params_not_an_object", f"{entry_path} carries a params object"
                )
            owned = {
                name: value
                for name, value in params.items()
                if name in word.params.get("properties", {})
            }
            validate_params(word.params, owned)

    # -- derived views ---------------------------------------------------------

    def capability_view(self, events: Sequence[Any]) -> dict[str, CapabilityRow]:
        """The capability rows, derived from the call log.

        "Swing isn't in my hands yet — 0 built" is a view over `vocab.call`
        counts and kept work orders (X C12; RV patch 18) — not a record type.
        """
        calls: dict[str, int] = {}
        refused: dict[str, int] = {}
        built: dict[str, int] = {}
        for event in events:
            event_type = getattr(event, "type", None)
            payload: Mapping[str, Any] = getattr(event, "payload", {}) or {}
            if event_type == "vocab.call":
                word = str(payload.get("word", ""))
                if not word:
                    continue
                if payload.get("refused"):
                    refused[word] = refused.get(word, 0) + 1
                else:
                    calls[word] = calls.get(word, 0) + 1
            elif event_type == "wo.kept":
                word = str(payload.get("word", ""))
                if word:
                    built[word] = built.get(word, 0) + 1

        rows: dict[str, CapabilityRow] = {}
        for word in self._entries:
            rows[word] = CapabilityRow(
                word=word,
                calls=calls.get(word, 0),
                refused=refused.get(word, 0),
                built=built.get(word, 0),
            )
        return rows
