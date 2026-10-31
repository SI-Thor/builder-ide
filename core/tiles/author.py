"""The cloud author — the seam the cloud writes tiles through (§1, §5, §8).

The cloud is slow and smart; the Thor is fast and learns. The two meet
here, and only here: **the author is a seam**, so the rest of the seat
never knows whether a tile came from a cloud model or from a script.

Two implementations:

* :class:`ScriptedAuthor` — the **fake**. Deterministic, no network, no
  model, no money. Every test that needs tiles uses this one, and the
  acceptance run is entirely this one.
* :class:`CloudAuthor` — the real seam: one hosted call per request, the
  request carrying the goal, the words the tile may use and the feedback
  from the tiles that lost. The HTTP transport is injectable, so the seam
  can be exercised without a network.

**No LLM is hosted on the Thor** (Casey's B2). The author runs in the
cloud; what lands on the Thor is a tile — data, in the closed vocabulary —
and the cost of the call, which is recorded on the tile.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from core.canon import canonical_bytes, content_hash, now_utc

from .door import validate_tile
from .models import FeedbackPacket, Json, Tile, TileAuthor, TileRefusal, TileStep, Precondition, build_tile
from .ports import VocabularyPort

__all__ = [
    "AuthorRequest",
    "TileAuthorProtocol",
    "ScriptedAuthor",
    "CloudAuthor",
    "DEFAULT_PROMPT",
]


#: The instruction the cloud author is given. It says the same thing the
#: door enforces: the tile is a list of steps in the closed vocabulary, and
#: anything else is refused.
DEFAULT_PROMPT = (
    "You write tiles for a world builder. A tile is a list of steps; each "
    "step names a vocabulary word and its parameters. Use only the words "
    "given. Do not write code, do not write prose. Return JSON."
)


@dataclass(frozen=True)
class AuthorRequest:
    """What the author is asked for.

    ``feedback`` is the heart of it: the tiles that lost, with the reason
    they lost, so the cloud can write a better one (§5).
    """

    goal: str
    words: tuple[str, ...] = ()
    context: Mapping[str, Json] = field(default_factory=dict)
    feedback: tuple[FeedbackPacket, ...] = ()
    budget_cents: int = 0
    attempt: int = 1

    def payload(self) -> dict[str, Any]:
        """The canonical form of the request — what is hashed and sent."""
        return {
            "goal": self.goal,
            "words": list(self.words),
            "context": dict(self.context),
            "feedback": [packet.model_dump() for packet in self.feedback],
            "budget_cents": self.budget_cents,
            "attempt": self.attempt,
        }


@runtime_checkable
class TileAuthorProtocol(Protocol):
    """The author seam: in a request, out a list of tiles."""

    def write(self, request: AuthorRequest) -> list[Tile]:
        """Write tiles for this request."""
        ...


# --- the fake ----------------------------------------------------------------


class ScriptedAuthor:
    """The fake cloud author — deterministic tiles from a script.

    ``script`` is either a callable (it takes the request and returns tile
    specs) or a sequence of specs. It is the author used by every test, and
    the acceptance run: **no real LLM call is made anywhere in this seat's
    suite.**
    """

    def __init__(
        self,
        script: Sequence[Mapping[str, Any]] | Callable[[AuthorRequest], Sequence[Mapping[str, Any]]],
        *,
        model: str = "fake/scripted-v1",
        provider: str = "fake",
        prompt_hash: str | None = None,
        registry: VocabularyPort | None = None,
    ) -> None:
        self._script = script
        self._model = model
        self._provider = provider
        self._registry = registry
        self._prompt_hash = prompt_hash
        #: every request the author was asked, so a test can assert on what
        #: the cloud was actually told.
        self.calls: list[AuthorRequest] = []

    @property
    def model(self) -> str:
        return self._model

    def write(self, request: AuthorRequest) -> list[Tile]:
        self.calls.append(request)
        specs = self._script(request) if callable(self._script) else self._script
        author = TileAuthor(
            model=self._model,
            provider=self._provider,
            prompt_hash=self._prompt_hash
            or content_hash({"model": self._model, "goal": request.goal}),
            cost_cents=0,
        )
        tiles = [_tile_from_spec(spec, author) for spec in specs]
        if self._registry is not None:
            for tile in tiles:
                validate_tile(tile, self._registry)
        return tiles


# --- the real seam -----------------------------------------------------------


class CloudAuthor:
    """The cloud author: one hosted call per request.

    The transport is injectable so the seam can be tested without a
    network — and so the *shape* of the call (what the cloud is told, and
    what comes back) is a thing a test can assert on. The default
    transport posts JSON over HTTP; it is the only place in this seat that
    touches the network, and nothing in the test suite reaches it.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        provider: str,
        registry: VocabularyPort | None = None,
        transport: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        prompt: str = DEFAULT_PROMPT,
        temperature: float | None = None,
        clock: Callable[[], str] = now_utc,
        timeout: float = 120.0,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.provider = provider
        self._registry = registry
        self._transport = transport or _http_transport(endpoint, timeout)
        self._prompt = prompt
        self._temperature = temperature
        self._clock = clock

    def write(self, request: AuthorRequest) -> list[Tile]:
        """Ask the cloud for tiles, and check what comes back.

        The tiles are validated against the same door every other tile
        goes through: a cloud model that names an unknown word gets a
        refusal, not a tile.
        """
        prompt = self._build_prompt(request)
        response = self._transport(
            {
                "prompt": prompt,
                "model": self.model,
                "provider": self.provider,
                "temperature": self._temperature,
                "request": request.payload(),
            }
        )
        specs = response.get("tiles")
        if not isinstance(specs, list):
            raise TileRefusal(
                "author_response_malformed", "the author did not return a list of tiles"
            )
        author = TileAuthor(
            model=self.model,
            provider=self.provider,
            prompt_hash=content_hash({"prompt": prompt}),
            cost_cents=int(response.get("cost_cents", 0)),
            temperature=self._temperature,
        )
        tiles = [_tile_from_spec(spec, author) for spec in specs]
        if self._registry is not None:
            for tile in tiles:
                validate_tile(tile, self._registry)
        return tiles

    def _build_prompt(self, request: AuthorRequest) -> str:
        """The prompt, and therefore the prompt hash."""
        lines = [
            self._prompt,
            f"Goal: {request.goal}",
            f"Words you may use: {', '.join(request.words) or '(none given)'}",
        ]
        for packet in request.feedback:
            lines.append(
                "A previous tile lost: "
                f"{packet.tile_id} ({packet.wins}/{packet.plays} won by {packet.measure}). "
                f"{packet.request}"
            )
        return "\n".join(lines)


# --- internals ---------------------------------------------------------------


def _tile_from_spec(spec: Mapping[str, Any], author: TileAuthor) -> Tile:
    """Build a tile from the shape the author returns."""
    try:
        steps = tuple(
            TileStep.model_validate(step) for step in spec.get("steps", [])
        )
        preconditions = tuple(
            Precondition.model_validate(p) for p in spec.get("preconditions", [])
        )
        return build_tile(
            family=str(spec["family"]),
            kind=str(spec.get("kind", "recipe_edit")),
            title=str(spec.get("title", spec["family"])),
            steps=steps,
            preconditions=preconditions,
            author=author,
            provenance=dict(spec.get("provenance") or {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TileRefusal(
            "author_tile_malformed", f"the author returned a tile that does not read: {exc}"
        ) from exc


def _http_transport(endpoint: str, timeout: float) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """The default transport: one JSON POST to the configured endpoint."""

    def _post(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = canonical_bytes(payload)
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            raise TileRefusal("author_unreachable", f"{endpoint}: {exc}") from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TileRefusal(
                "author_response_malformed", f"the author did not answer with JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise TileRefusal(
                "author_response_malformed", "the author did not answer with an object"
            )
        return parsed

    return _post
