"""A skill is a tile: the world's own words for builder-ide's capability record.

The world's library and builder-ide's tile library are the same discipline
with different nouns — content addressed, versioned per family, retired
rather than deleted, held to a closed vocabulary, and played with the
context attached. This module is the seam between the two nouns, so a
skill and a capability are **one record** rather than two that have to be
kept in step by hand.

What maps, field for field:

============  ==========================  ==========================
world         builder-ide                 what the mapping is
============  ==========================  ==========================
``id``        ``id``                      the **same** id, and it is a
                                            content address in both
``family``    ``family``                  the same
``version``   ``version``                 the same
``kind``      ``kind``                    ``behaviour`` / ``build_step``
                                            are tile kinds too
``title``     ``title``                   the same
``api``       ``steps``                   one step per world word the
                                            skill calls; the tile's
                                            ``words`` are then exactly
                                            the skill's ``api``
``preconditions`` ``preconditions``        the same shape
``author``    ``author``                  the same fields
``status``    ``status``                  the same
============  ==========================  ==========================

Two things do **not** map, and they are said out loud rather than faked:

* **the body.** A tile's body is a list of typed steps; a skill's body is
  a small JavaScript function. The script stays in the world's skill file.
  What travels is the script's **content hash**, in the tile's
  ``provenance``, so the two records are provably the same source.
* **the prediction.** A tile has no prediction of its own — the
  prediction is the *measure* of the play, not of the capability. It
  travels in the ``provenance`` too, and the world's own
  ``Outcome.measure`` is already one of builder-ide's four
  (``sealed_prediction``, ``owner_keep``, ``owner_undo``, ``critic``).

The id is the same id on purpose. It is what lets the judge's answer join
to the play: the judge answers with a **skill id**, and the calibration
cell reads ``payload["tile_id"]``. One id, one join, no translation table.
"""

from __future__ import annotations

from typing import Any, Mapping

from core.canon import content_hash, is_content_hash
from core.tiles.models import (
    Precondition as TilePrecondition,
    Tile,
    TileAuthor,
    TileStep,
)

from .models import Skill

__all__ = [
    "skill_to_tile",
    "tile_to_skill_spec",
    "skill_body",
    "tile_prompt_hash",
    "scope_of",
    "authored_payload",
    "retired_payload",
    "played_payload",
    "WorldVocabulary",
    "DEFAULT_FEATURE_KEYS",
]

#: The context features the world's chooser branches on. The bucket they
#: make is the world's ``scope`` — the join key builder-ide's judge
#: calibration uses to pair a judgment with the play it answered.
DEFAULT_FEATURE_KEYS: tuple[str, ...] = ("role", "phase")


def skill_body(skill: Skill) -> dict[str, Any]:
    """The body a skill's id is computed over.

    This is :func:`agent_world_reflex.library.build_skill`'s hash, spelled
    out — the same fields, in the same order of meaning — so a skill read
    back from disk hashes to the same id it was admitted with.
    """
    return {
        "family": skill.family,
        "kind": skill.kind,
        "role": skill.role,
        "title": skill.title,
        "body": skill.body,
        "api": list(skill.api),
        "preconditions": [dict(p) for p in skill.preconditions],
        "predict": dict(skill.predict.model_dump()),
    }


def tile_prompt_hash(skill: Skill) -> str:
    """The tile author's ``prompt_hash`` for this skill.

    builder-ide's :class:`~core.tiles.models.TileAuthor` holds a content
    hash there, and it is the thing that makes two tiles comparable: two
    tiles written by the same model from the same prompt are the same
    tile.

    A skill that was written by a cloud model carries that model's prompt
    hash and it is kept. A **seed** skill was written by hand, so it has
    no prompt — and its ``prompt_hash`` is the word ``"seed"``, which is
    not a hash. Inventing one would be a fabrication, so the hash is
    derived from the **script itself**: the prompt that produced a seeded
    skill *is* the script. The derivation is recorded in the tile's
    ``provenance`` under ``prompt_hash_origin`` so nobody has to guess
    which of the two it is.
    """
    given = skill.author.prompt_hash
    if is_content_hash(given):
        return given
    return content_hash(skill_body(skill))


def scope_of(context: Mapping[str, Any], *, keys: tuple[str, ...] = DEFAULT_FEATURE_KEYS) -> str:
    """The world's context bucket — the judge's join key.

    The same arithmetic builder-ide's own chooser uses to bucket a context
    (``role=scout|phase=day``): one ``key=value`` per feature, in the
    order the features are named, and a key the context does not have is
    ``<none>`` rather than an empty value.
    """
    parts = []
    for key in keys:
        if key not in context:
            parts.append(f"{key}=<none>")
        else:
            parts.append(f"{key}={context[key]}")
    return "|".join(parts)


def skill_to_tile(skill: Skill) -> Tile:
    """The skill as a builder-ide tile.

    The id is the skill's own id — both are content addresses over the
    same source, and sharing the id is what makes the two records one.
    """
    steps = tuple(
        TileStep(word=word, path=word, op="set", params={})
        for word in skill.api
    )
    if not steps:
        # A tile has at least one step, and a skill that calls no word of
        # the world's vocabulary has no capability to offer. The world's
        # door admits such a skill (it is a valid script), so this is
        # raised here rather than silently dropped: a skill that cannot
        # be a tile is a finding, not a detail.
        raise ValueError(
            f"skill {skill.id} calls no word of the world's vocabulary, so it "
            "is not a capability"
        )
    provenance = dict(skill.provenance)
    provenance.update(
        {
            "skill_id": skill.id,
            "role": skill.role,
            "api": list(skill.api),
            "predict": skill.predict.model_dump(),
            "source_hash": content_hash(skill.body),
            "prompt_hash_origin": (
                "skill" if is_content_hash(skill.author.prompt_hash) else "derived_from_skill_body"
            ),
        }
    )
    return Tile(
        id=skill.id,
        family=skill.family,
        version=skill.version,
        kind=skill.kind,
        title=skill.title,
        steps=steps,
        preconditions=tuple(
            TilePrecondition(key=p.key, op=p.op, value=p.value) for p in skill.preconditions
        ),
        author=TileAuthor(
            model=skill.author.model,
            provider=skill.author.provider,
            prompt_hash=tile_prompt_hash(skill),
            cost_cents=skill.author.cost_cents,
            temperature=skill.author.temperature,
        ),
        provenance=provenance,
        created_at=skill.created_at,
        status=skill.status,
        retired_at=skill.retired_at,
        retire_reason=skill.retire_reason,
    )


def tile_to_skill_spec(tile: Tile) -> dict[str, Any]:
    """The tile back as the world's own spec of a skill.

    The round trip is what makes "one record" a claim rather than a
    slogan: a tile read back out of builder-ide's log carries the world's
    family, role, words and prediction, and points at the skill id the
    world's own library holds.
    """
    provenance = dict(tile.provenance or {})
    return {
        "skill_id": str(provenance.get("skill_id") or tile.id),
        "family": tile.family,
        "kind": tile.kind,
        "role": str(provenance.get("role") or ""),
        "title": tile.title,
        "api": list(provenance.get("api") or tile.words),
        "preconditions": [dict(p.model_dump()) for p in tile.preconditions],
        "predict": dict(provenance.get("predict") or {"kind": "none"}),
        "version": tile.version,
        "status": tile.status,
        "retired_at": tile.retired_at,
        "retire_reason": tile.retire_reason,
    }


class WorldVocabulary:
    """builder-ide's :class:`~core.tiles.ports.VocabularyPort` over the world's words.

    The tile seat asks the vocabulary two questions: does this word exist,
    and are these parameters in its schema. The world's door answers the
    first — its vocabulary is closed and its words are the world's — and
    the second is **not** a question this world asks: the world's door
    checks the *names* a script calls, not the shape of their arguments.

    So the honest answer here is that the world's words have no parameter
    schema, and a call that carries parameters is refused rather than
    passed through unchecked. The world says so in its own words: a skill
    that reaches for a word the world does not have is not a skill.
    """

    def __init__(self, vocabulary: Mapping[str, str] | None = None) -> None:
        if vocabulary is None:
            from .door import VOCABULARY

            vocabulary = VOCABULARY
        self._words = dict(vocabulary)

    def require(self, word: str) -> str:
        """The word's meaning, or ``KeyError`` — the tiles seat's contract."""
        try:
            return self._words[word]
        except KeyError:
            raise KeyError(word) from None

    def validate_params(self, word: str, params: Mapping[str, Any]) -> None:
        """Refuse parameters: the world's words carry no parameter schema.

        The refusal carries a ``reason`` attribute, because the tiles seat
        re-states the vocabulary's own reason code
        (:func:`core.tiles.door.validate_tile`).
        """
        self.require(word)
        if params:
            raise _ParamsRefusal(
                "params_unknown",
                f"the world's word {word!r} has no parameter schema; the "
                "world's door checks the names a script calls, not their arguments",
            )

    def words(self) -> tuple[str, ...]:
        """Every word of the world's vocabulary, in order."""
        return tuple(self._words)


class _ParamsRefusal(Exception):
    """The vocabulary's own refusal, with a reason code (like the core's)."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


# ==================================================================== payloads
#
# The rows the world writes, in a shape that is a **superset** of two
# vocabularies: builder-ide's tile seat (which folds them into a
# ``TileLibrary``) and the world's own readers (the gym's recorder, the
# drift seat, the rewind seat). A key is added, never removed, so a file
# written before this change still reads and a file written after it
# reads in both vocabularies.


def authored_payload(tile: Tile, *, cost_cents: int = 0) -> dict[str, Any]:
    """The ``tile.authored`` row: a skill enters the library.

    The first eight keys are builder-ide's own ``tile.authored`` payload,
    byte for byte — that is what :func:`core.tiles.library.fold_library`
    reads a tile back from. The rest are the world's own keys, kept so
    the rows the world wrote before this change still read the same way.
    """
    return {
        # --- builder-ide's shape ---
        "tile_id": tile.id,
        "family": tile.family,
        "version": tile.version,
        "kind": tile.kind,
        "title": tile.title,
        "body": tile.body(),
        "content_hash": tile.content_hash,
        "provenance": dict(tile.provenance),
        "created_at": tile.created_at,
        # --- the world's own keys ---
        "skill": tile.id,
        "role": str(tile.provenance.get("role") or ""),
        "api": list(tile.words),
        "author": tile.author.model,
        "provider": tile.author.provider,
        "cost_cents": int(cost_cents or tile.author.cost_cents),
        "prompt_hash": tile.author.prompt_hash,
    }


def retired_payload(
    tile: Tile, *, reason: str, plays: int = 0, wins: int = 0
) -> dict[str, Any]:
    """The ``tile.retired`` row: a skill leaves the eligible set."""
    return {
        # --- builder-ide's shape ---
        "tile_id": tile.id,
        "family": tile.family,
        "version": tile.version,
        "reason": reason,
        "retired_at": tile.retired_at,
        # --- the world's own keys ---
        "skill": tile.id,
        "plays": int(plays),
        "wins": int(wins),
    }


def played_payload(record: Any) -> dict[str, Any]:
    """The ``tile.played`` row: a skill was used, with its outcome.

    ``record`` is the world's own play record. The keys builder-ide's
    tiles seat reads are added (``play_id``, ``tile_id``, ``tile_version``,
    ``scope``); the world's keys are kept, so the drift seat (which reads
    ``skill_id``) and the rewind seat (which reads the subject) still see
    what they saw before.

    ``scope`` is the world's context bucket — the key builder-ide's judge
    calibration pairs a judgment with the play it answered.
    """
    context = dict(getattr(record, "context", {}) or {})
    outcome = getattr(record, "outcome", None)
    cost = getattr(record, "cost", None)
    return {
        # --- builder-ide's shape ---
        "play_id": getattr(record, "id", ""),
        "tile_id": getattr(record, "skill_id", ""),
        "tile_version": int(getattr(record, "skill_version", 1) or 1),
        "context": context,
        "outcome": outcome.model_dump() if hasattr(outcome, "model_dump") else dict(outcome or {}),
        "cost": cost.model_dump() if hasattr(cost, "model_dump") else dict(cost or {}),
        "chooser": getattr(record, "chooser", "") or "",
        "chooser_version": getattr(record, "chooser_version", "") or "",
        "night": getattr(record, "night", None),
        "propensity": getattr(record, "propensity", None),
        "candidates": list(getattr(record, "candidates", ()) or ()),
        "scope": scope_of(context),
        # --- the world's own keys ---
        "id": getattr(record, "id", ""),
        "at": getattr(record, "at", ""),
        "skill_id": getattr(record, "skill_id", ""),
        "skill_version": int(getattr(record, "skill_version", 1) or 1),
    }
