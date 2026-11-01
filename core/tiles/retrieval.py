"""The retrieval front: find the tiles that *mean* the right thing, first.

**The gap this closes.** The chooser (:mod:`core.tiles.chooser`) is a
contextual bandit: it learns which tile wins in which bucket, and it picks
well *among the tiles it was handed*. With a library of six tiles that is
enough. With a library of six hundred it is not — the bandit's estimate is
one number per (bucket, tile), and it can only ever act on what it is given.
The retrieval front is the missing half. It embeds the game's state, takes
the K tiles whose meaning matches it, and hands those to the bandit, which
then does what it is good at: learning from outcomes.

    retrieve (by meaning)  →  shortlist of K  →  choose (by reward)

**The front narrows; it does not decide.** That split is the whole design.
The bandit is the only thing that knows what *wins*; the front only knows
what *fits*. A front that decided would throw away the learning, and a
bandit that saw the whole library would drown in options it has no estimate
for.

**Eligibility comes before scoring.** A tile whose preconditions do not hold
in this context is not an option — not a low-scoring option, not an option at
all (§4 of the design). So the front filters first and scores second: an
ineligible tile never reaches the ranking, and the K that come back are K
that could actually have been played.

**An embedder is a parameter, and the record says which one.** A similarity
number is meaningless without the model that produced it — two embedders
rank the same library differently and put their scores on different scales.
So every result carries the embedder's record (kind, model, licence,
dimensions), and :func:`default_embedder` is the one place that decides
which embedder the seat uses. The floor is :class:`HashingEmbedder`: no
model, no download, no licence, and a record that says exactly that. The
ceiling is a local static model (model2vec's ``potion-base-8M``, MIT), which
is CPU-only and costs a couple of seconds to load.

**The numbers travel with the propensity.** A choice made through the front
is a choice made by *two* mechanisms, so its probability is the product of
both draws: the retrieval's own draw (the chance the tile was in the
shortlist at all) times the chooser's draw inside the shortlist. That product
is what the importance weight divides by, and the shortlist travels with the
play record so a target policy normalises over the same set. See
:class:`RetrievalChooser` and :mod:`core.tiles.ope`.
"""

from __future__ import annotations

import functools
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from .chooser import Choice, TileChooser
from .models import PlayRecord, Tile, TileRefusal

__all__ = [
    "DEFAULT_MODEL",
    "HASHING_DIMENSIONS",
    "MODEL_LICENCES",
    "Embedder",
    "EmbedderUnavailable",
    "HashingEmbedder",
    "Hit",
    "RetrievalChooser",
    "RetrievalFront",
    "RetrievalResult",
    "StaticEmbedder",
    "TileIndex",
    "context_key",
    "context_text",
    "default_embedder",
    "describe_tile",
    "embedder_record",
]


#: The local static model the seat uses when it can. 256 dimensions, CPU
#: only, MIT — checked against the model's card, not assumed.
DEFAULT_MODEL = "minishlab/potion-base-8M"

#: The hashing fallback's width. 4096 buckets over the vocabulary's own
#: features: enough that two unrelated tile titles almost never collide.
HASHING_DIMENSIONS = 4096

#: The models whose licence has been checked, and what it is. A model that
#: is not in here is reported as unchecked rather than assumed to be free:
#: some image and text models are non-commercial, and a bundle that carries
#: an embedding has to carry the embedding's licence with it.
MODEL_LICENCES: dict[str, str] = {
    "minishlab/potion-base-8M": "MIT",
    "minishlab/potion-multilingual-128M": "MIT",
    "sentence-transformers/all-MiniLM-L6-v2": "Apache-2.0",
}

#: What an unchecked model's licence is reported as.
UNKNOWN_LICENCE = "unchecked (see the model's card)"


class EmbedderUnavailable(Exception):
    """A model that is not here, refused by name.

    Named rather than empty: a front that quietly indexes nothing because
    the model would not load looks exactly like a front that found nothing
    worth finding, and the two have opposite meanings.
    """

    def __init__(self, model: str, detail: str = "") -> None:
        super().__init__(f"{model}: {detail or 'the model is not available'}")
        self.model = model
        self.detail = detail


@runtime_checkable
class Embedder(Protocol):
    """The seam: text in, vectors out, and a record of who made them."""

    @property
    def dimensions(self) -> int:
        """How many numbers a vector has."""
        ...

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Embed a batch of texts into a ``(len(texts), dimensions)`` array."""
        ...

    def record(self) -> dict[str, Any]:
        """The record that travels with every number this embedder makes."""
        ...


def embedder_record(embedder: Embedder) -> dict[str, Any]:
    """The record of an embedder, as a plain dict.

    Kind, model, licence and width. This is what a score is read against:
    a similarity of 0.62 means one thing under one model and another thing
    under another, and a record that says which is the difference between a
    measurement and a rumour.
    """
    record = embedder.record()
    return {
        "kind": str(record.get("kind", "unknown")),
        "model": str(record.get("model", "")),
        "licence": str(record.get("licence", UNKNOWN_LICENCE)),
        "dimensions": int(record.get("dimensions", 0)),
    }


# --- the hashing fallback -----------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9]+")


def _features(text: str) -> dict[str, int]:
    """The features of a text: its words and its word pairs, with counts.

    Counts, not a set: a word said twice is a stronger signal than a word
    said once, and dropping the count would make "weathered crates" and
    "stained crates" with a ``style: weathered`` parameter indistinguishable
    in the one place where the difference is the answer.
    """
    tokens = _TOKEN.findall(text.lower())
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    for first, second in zip(tokens, tokens[1:]):
        bigram = f"{first} {second}"
        counts[bigram] = counts.get(bigram, 0) + 1
    return counts


def _bucket(feature: str, dimensions: int) -> int:
    """Which bucket a feature hashes into. Stable across runs and machines."""
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dimensions


class HashingEmbedder:
    """The floor: an embedder with no model behind it.

    Feature hashing — every word and word pair is hashed into a fixed
    number of buckets and the counts are the vector, normalised. It is not a
    sentence embedding and it does not pretend to be one: it has no notion
    of synonymy, it matches on words, and it says so in its record
    (``kind="hashing"``, ``model=""``).

    What it is good for is being *there*: the front runs with no download, no
    licence question and no GPU, so the mechanism can be tested and measured
    before a model is chosen. What it is not good for is ranking two
    paraphrases of the same request — that is the difference the static model
    buys, and it is measured in ``docs/lab/exp-tiles-retrieval.md``.
    """

    kind = "hashing"

    def __init__(self, dimensions: int = HASHING_DIMENSIONS) -> None:
        if dimensions < 16:
            raise ValueError("a hashing embedder needs enough buckets to be useful")
        self._dimensions = int(dimensions)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Embed a batch of texts. The same text gives the same vector."""
        vectors = np.zeros((len(texts), self._dimensions), dtype=float)
        for row, text in enumerate(texts):
            for feature, count in _features(text).items():
                vectors[row, _bucket(feature, self._dimensions)] += count
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # An empty text has no direction; leave it at zero rather than
        # dividing by zero into a NaN that poisons every dot product after.
        norms[norms == 0.0] = 1.0
        return vectors / norms

    def record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "model": "",
            "licence": "none (ours)",
            "dimensions": self._dimensions,
        }


# --- the static model ---------------------------------------------------------


class StaticEmbedder:
    """A local static embedding model — CPU only, no API, no marginal cost.

    Model2vec's static models are distilled sentence embeddings: the whole
    model is a token-embedding table plus a tokenizer, so a query costs one
    matrix lookup per token and no forward pass. That is what makes the fast
    path free, which is the point of the front.

    The licence is looked up in :data:`MODEL_LICENCES` — a checked list, not
    an assumption — and an unchecked model is reported as unchecked.
    """

    kind = "static"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        allow_download: bool = True,
        licence: str | None = None,
    ) -> None:
        self.model = model
        self.licence = licence or MODEL_LICENCES.get(model, UNKNOWN_LICENCE)
        self._model = self._load(model, allow_download=allow_download)
        self._dimensions = int(self._model.dim)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self._model.encode(list(texts))
        array = np.asarray(vectors, dtype=float)
        if array.ndim == 1:  # a single text comes back as one vector
            array = array.reshape(1, -1)
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return array / norms

    def record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "model": self.model,
            "licence": self.licence,
            "dimensions": self._dimensions,
        }

    # -- internals -------------------------------------------------------------

    def _load(self, model: str, *, allow_download: bool):
        """Load the model, or refuse it by name."""
        try:
            from model2vec import StaticModel
        except ImportError as exc:  # the extra is not installed
            raise EmbedderUnavailable(
                model,
                "model2vec is not installed; install the 'embed' extra or use "
                "the hashing fallback",
            ) from exc

        if not allow_download and not _is_cached(model):
            raise EmbedderUnavailable(
                model,
                "the model is not in the local cache and downloads are not allowed",
            )

        try:
            # force_download=False: the cache is used when it is there, and
            # the model is fetched when it is not. The flag exists to skip a
            # re-download of something already on the disk.
            return StaticModel.from_pretrained(model, force_download=False)
        except Exception as exc:
            raise EmbedderUnavailable(model, f"{type(exc).__name__}: {exc}") from exc


def _is_cached(model: str) -> bool:
    """True when the model is already in the local Hugging Face cache."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    try:
        return try_to_load_from_cache(model, "config.json") is not None
    except Exception:
        return False


@functools.lru_cache(maxsize=4)
def _static_embedder(model: str, allow_download: bool) -> "StaticEmbedder":
    """One loaded model per (model, download policy) — the load is the cost."""
    return StaticEmbedder(model, allow_download=allow_download)


def default_embedder(
    model: str | None = None,
    *,
    allow_download: bool = True,
) -> Embedder:
    """The embedder the seat uses when nobody names one.

    With no ``model``: the checked static model if it can be loaded, and the
    hashing fallback if it cannot. The front runs either way and says which
    one it used.

    With an explicit ``model``: that model, and nothing else. A model that
    cannot be loaded is refused by name
    (:class:`EmbedderUnavailable`) rather than silently swapped — a caller
    that asked for a specific model and got a different one has been misled
    by a default.
    """
    if model is None:
        try:
            return _static_embedder(DEFAULT_MODEL, allow_download)
        except EmbedderUnavailable:
            return HashingEmbedder()
    if model in ("", "hashing"):
        return HashingEmbedder()
    return _static_embedder(model, allow_download)


# --- describing a tile --------------------------------------------------------


def describe_tile(tile: Tile) -> str:
    """A tile in words: what it is called, what it is for, what it says.

    The title alone is too thin (two tiles can share a name across families)
    and the whole body is too noisy (every crates tile says ``count 12``).
    So the description is the title, the family, the vocabulary words it
    uses, and its parameters — the things that make *this* tile the right one
    for *this* request.
    """
    parts: list[str] = [tile.title, tile.family]
    parts.extend(tile.words)
    for step in tile.steps:
        parts.extend(f"{key} {value}" for key, value in sorted(step.params.items()))
    return " ".join(part for part in parts if part)


def context_text(context: Mapping[str, Any]) -> str:
    """The game state as a query: the context's keys and values, in order.

    Sorted, so the same context always makes the same query and a replay
    gives the same answer.
    """
    return " ".join(
        f"{key} {context[key]}" for key in sorted(context) if key in context
    )


def context_key(context: Mapping[str, Any]) -> str:
    """The context as a bucket key: ``key=value|key=value``, sorted.

    The one the record carries when the chooser does not bucket on anything
    of its own — so a play can still be grouped by the context it was made
    in.
    """
    return "|".join(
        f"{key}={context[key] if key in context else '<none>'}"
        for key in sorted(context)
    )


# --- the index ----------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """One tile the index found, and how close it was."""

    tile: Tile
    score: float


class TileIndex:
    """The library, embedded once, searchable by meaning.

    The embedding of a tile is made when it is added and never again: a
    tile's body never changes (§2), so its vector never changes either, and
    the cost of indexing a library is paid once.
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder if embedder is not None else default_embedder()
        self._tiles: dict[str, Tile] = {}
        self._vectors: dict[str, np.ndarray] = {}
        #: How many embeddings this index has made — the cost of the index,
        #: counted.
        self.embeddings_made = 0

    @property
    def size(self) -> int:
        """How many tiles are indexed."""
        return len(self._tiles)

    def add(self, tile: Tile) -> None:
        """Index a tile. Adding the same tile again is a no-op."""
        if tile.id in self._tiles:
            return
        self._tiles[tile.id] = tile
        self._vectors[tile.id] = self.embedder.embed([describe_tile(tile)])[0]
        self.embeddings_made += 1

    def remove(self, tile_id: str) -> None:
        """Take a tile out of the index — a retired tile is not an option."""
        self._tiles.pop(tile_id, None)
        self._vectors.pop(tile_id, None)

    def tiles(self) -> tuple[Tile, ...]:
        """Every indexed tile."""
        return tuple(self._tiles.values())

    def get(self, tile_id: str) -> Tile | None:
        return self._tiles.get(tile_id)

    def search(
        self,
        text: str,
        k: int = 5,
        *,
        tiles: Sequence[Tile] | None = None,
    ) -> tuple[Hit, ...]:
        """The K tiles whose meaning is closest to ``text``.

        ``tiles`` restricts the pool — the front uses it to score only the
        eligible tiles, because eligibility comes before scoring.

        Ties are broken by tile id, so the same query on the same library
        always returns the same order: a front that reorders itself between
        two runs cannot be replayed.
        """
        if k <= 0 or not self._vectors:
            return ()
        pool = None
        if tiles is not None:
            allowed = {tile.id for tile in tiles}
            pool = {
                tile_id: vector
                for tile_id, vector in self._vectors.items()
                if tile_id in allowed
            }
            if not pool:
                return ()
        else:
            pool = self._vectors

        query = self.embedder.embed([text])[0]
        scored = [(float(query @ vector), tile_id) for tile_id, vector in pool.items()]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            Hit(tile=self._tiles[tile_id], score=score)
            for score, tile_id in scored[:k]
        )


# --- the front ----------------------------------------------------------------


def empty_embedder_record() -> dict[str, Any]:
    """The empty record — used when a result is built without an embedder."""
    return {"kind": "unknown", "model": "", "licence": UNKNOWN_LICENCE, "dimensions": 0}


@dataclass(frozen=True)
class RetrievalResult:
    """What the front found, and the numbers that say so."""

    #: The shortlist, best first. The chooser's option set.
    candidates: tuple[Tile, ...] = ()
    #: The similarity of the best candidate — 0.0 when there is none.
    top_score: float = 0.0
    #: Each candidate's similarity, in the same order as ``candidates``.
    #: The band reads these: a score is a number about *a tile*, not about
    #: the shortlist.
    scores: tuple[float, ...] = ()
    #: The embedder that made the numbers.
    embedder: dict[str, Any] = field(default_factory=empty_embedder_record)
    #: The query the front asked.
    query: str = ""


class RetrievalFront:
    """The retrieval front: the game's state in, a shortlist out.

    ``k`` is how many tiles the front hands over. Small is the point: the
    chooser behind it is a bandit with one estimate per (bucket, tile), and
    a shortlist of three gives it three estimates to maintain instead of six
    hundred.
    """

    def __init__(
        self,
        index: TileIndex | None = None,
        *,
        k: int = 3,
        embedder: Embedder | None = None,
    ) -> None:
        if k <= 0:
            raise ValueError("the shortlist has at least one tile in it")
        self.index = index if index is not None else TileIndex(embedder)
        self.k = int(k)

    def retrieve(self, context: Mapping[str, Any]) -> RetrievalResult:
        """The shortlist for this context, and the numbers behind it.

        Eligibility first: a tile that is retired, or whose preconditions do
        not hold, is not an option and is not scored. Then the query, then
        the top K by meaning.
        """
        eligible = [
            tile
            for tile in self.index.tiles()
            if tile.status == "active" and tile.is_eligible(context)
        ]
        query = context_text(context)
        hits = self.index.search(query, k=self.k, tiles=eligible)
        return RetrievalResult(
            candidates=tuple(hit.tile for hit in hits),
            top_score=hits[0].score if hits else 0.0,
            scores=tuple(hit.score for hit in hits),
            embedder=embedder_record(self.index.embedder),
            query=query,
        )

    def draw_probability(self, tile_id: str, shortlist: Sequence[Tile]) -> float:
        """The probability that the front's own draw produced this tile.

        The front is deterministic — the top K by meaning, every time — so a
        tile it returned was drawn with probability 1, and a tile it did not
        return with probability 0. This is the place where a front that
        draws at random would return *its* probability: the whole-policy
        propensity multiplies by whatever comes back here, so the
        arithmetic does not change when the front does.
        """
        return 1.0 if any(tile.id == tile_id for tile in shortlist) else 0.0


# --- the chooser in front of the chooser --------------------------------------


class RetrievalChooser:
    """Retrieve first, then choose — and record the whole policy's probability.

    Two mechanisms make the choice, so the probability of the choice is the
    product of both:

    * the **retrieval's draw** — the chance the tile was in the shortlist at
      all (:meth:`RetrievalFront.draw_probability`);
    * the **chooser's draw** — the inner chooser's own propensity, measured
      over the shortlist it chose from.

    The product is what an importance weight divides by, so it is what goes
    on the play record. Recording only the inner chooser's number would be
    wrong in a way that hides: the inner chooser's propensity is measured
    over a *shortlist*, and a reader who assumed it was measured over the
    whole library would divide by too small a number and get estimates that
    are too confident. The shortlist travels with the record
    (:attr:`core.tiles.models.PlayRecord.candidates`) so a target policy
    normalises over the same set.

    **The front narrows, so the pool the chooser sees shrinks, and the
    chooser's probability inside it grows.** That is not a free lunch and it
    is not claimed to be: a tile the front never returns is never played, so
    it is never learned from either. The front's K is the knob, and its
    cost is measured in ``docs/lab/exp-tiles-retrieval.md``.
    """

    name = "retrieval/bandit-v1"
    version = "1"

    def __init__(self, front: RetrievalFront, inner: TileChooser) -> None:
        self.front = front
        self.inner = inner

    # -- the choice ------------------------------------------------------------

    def choose(self, context: Mapping[str, Any], tiles: Sequence[Tile]) -> Choice:
        """Pick a tile: the front's shortlist, then the inner chooser's pick.

        The shortlist is the intersection of the front's K and the tiles the
        caller offered — the caller's pool is the ceiling, the front is the
        floor. A context with no eligible tile is a refusal with a named
        reason, never a fallback to some other tile.
        """
        pool = {tile.id for tile in tiles}
        result = self.front.retrieve(context)
        shortlist = [tile for tile in result.candidates if tile.id in pool]
        if not shortlist:
            raise TileRefusal(
                "no_eligible_tile",
                "the retrieval front found no eligible tile in this context",
            )

        inner_choice = self.inner.choose(context, shortlist)
        return Choice(
            tile_id=inner_choice.tile_id,
            reason=f"retrieved/{inner_choice.reason}",
            bucket=self.bucket(context),
            score=inner_choice.score,
            propensity=self.policy_probability(inner_choice, shortlist),
            candidates=tuple(tile.id for tile in shortlist),
        )

    def policy_probability(self, choice: Choice, shortlist: Sequence[Tile]) -> float | None:
        """The probability that this whole policy made this choice.

        The retrieval's own draw times the chooser's own draw. ``None``
        when the inner chooser does not measure its own propensity: a
        missing propensity is never defaulted to 1.0, because a log that
        claims certainty it did not have cannot be weighted honestly.
        """
        if choice.propensity is None:
            return None
        draw = self.front.draw_probability(choice.tile_id, shortlist)
        return draw * choice.propensity

    # -- the learning ----------------------------------------------------------

    def update(self, record: PlayRecord) -> None:
        """Learn from a play — the inner chooser's learning, unchanged."""
        self.inner.update(record)

    def fit(self, records: Sequence[PlayRecord]) -> None:
        """Refit from the log — the nightly loop, delegated."""
        fit = getattr(self.inner, "fit", None)
        if fit is not None:
            fit(records)

    def estimate(self, bucket: str, tile_id: str) -> float:
        """The inner chooser's estimate for a tile in a bucket."""
        return float(self.inner.estimate(bucket, tile_id))

    def bucket(self, context: Mapping[str, Any]) -> str:
        """The bucket on the record: the inner chooser's, when it has one.

        The inner chooser knows how it learns, so its bucket is the one that
        means something. When it does not branch at all, the record still
        says which context the choice was made in.
        """
        inner_bucket = getattr(self.inner, "bucket", None)
        if inner_bucket is not None:
            bucket = inner_bucket(context)
            if bucket:
                return bucket
        return context_key(context)
