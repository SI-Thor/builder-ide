"""Token classes carry an actor (§4.1).

The spec's rule is that a token is not a permission, it is an *identity*: an
``owner`` token is issued per person (``casey``, ``magnus``), and the actor
rides on every audit event and gates the actor-scoped endpoints. A ``panel``
token reads and streams; a ``character`` token is a character's own door; a
``seat`` token reaches only the MCP tools, which are the other half's door and
have no HTTP surface here.

The one privacy rule that matters in this half is structural, not policy: a
kid actor (``magnus``) cannot submit free text. The API refuses an
``utterance`` field from a kid token *at the schema* and audits the refusal
as ``call.refused`` — so there is nothing of his to retain, by construction
rather than by promise (§4.1, §7.10).

The token registry lives in ``$BUILDER_HOME/tokens.json`` (see
``config.Settings``); the dev defaults there are LAN-only development
credentials and are documented as such.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, Request

from .errors import AuthError, Forbidden

OWNER = "owner"
PANEL = "panel"
CHARACTER = "character"
SEAT = "seat"

TOKEN_CLASSES = frozenset({OWNER, PANEL, CHARACTER, SEAT})


@dataclass(frozen=True)
class Principal:
    """Who is calling. ``actor`` is the id that lands in the audit log.

    ``agent`` is the per-agent token's agent claim — one actor, many
    agents (the world-mcp round's extension of §4.1). It rides onto every
    audit row the caller writes and gates nothing (A1 is permissive).
    """

    token_class: str
    actor: str
    kid: bool = False
    agent: str | None = None

    @property
    def is_owner(self) -> bool:
        return self.token_class == OWNER

    @property
    def is_kid(self) -> bool:
        return self.kid

    @property
    def is_panel(self) -> bool:
        return self.token_class == PANEL

    @property
    def is_character(self) -> bool:
        return self.token_class == CHARACTER

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.token_class}:{self.actor}"


def registry(settings) -> dict[str, dict]:
    """The token registry: {token: {class, actor, kid?, agent?}}."""
    return settings.load_tokens()


def principal_for(token: str, settings) -> Principal:
    entry = registry(settings).get(token)
    if entry is None:
        raise AuthError("unknown token", token_class="unknown")
    token_class = entry.get("class", PANEL)
    if token_class not in TOKEN_CLASSES:
        raise AuthError(f"token class {token_class!r} is not one of {sorted(TOKEN_CLASSES)}",
                        token_class=token_class)
    actor = entry.get("actor") or token_class
    kid = bool(entry.get("kid")) or actor in settings.kid_actors
    agent = entry.get("agent") or None
    return Principal(token_class=token_class, actor=actor, kid=kid, agent=agent)


async def current_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency: resolve the bearer token to a Principal."""
    settings = request.app.state.settings
    if not authorization:
        raise AuthError("missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Authorization must be 'Bearer <token>'")
    return principal_for(parts[1].strip(), settings)


def require(*classes: str):
    """Dependency factory: the caller's token class must be one of ``classes``.

    A seat token has no HTTP door in this half (§2.5), so it is deliberately
    not in any allowed set.
    """
    allowed = frozenset(classes)

    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        return check_class(principal, allowed)

    return dependency


def require_adult_owner():
    """Owner class, and not a kid actor (§7.15).

    Magnus's authority is enumerated, not implied: chips in, free text
    refused structurally, preview-keeps and question-answers are his, branch
    applies are proposals pending the owner's confirm. The doors that belong
    to the adult owner alone — confirming a draft into a build, running a
    night, erasing or ratifying taste — are closed to him in code, not by
    policy.
    """
    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        check_class(principal, frozenset({OWNER}))
        if principal.kid:
            raise Forbidden(
                "this door is the adult owner's: a kid actor's authority is "
                "structural (§7.15) — chips, preview-keeps, question-answers, "
                "and branch proposals are his",
                token_class=principal.token_class, actor=principal.actor)
        return principal

    return dependency


def check_class(principal: Principal, classes: frozenset[str]) -> Principal:
    if principal.token_class not in classes:
        raise Forbidden(
            f"token class {principal.token_class!r} may not use this endpoint "
            f"(allowed: {sorted(classes)})",
            token_class=principal.token_class)
    return principal
