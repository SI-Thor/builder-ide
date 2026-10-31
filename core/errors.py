"""Error hierarchy. Every domain refusal is one of these; the API maps them
to HTTP statuses. A *refusal* (domain rule said no) is distinct from a
*stale transition* (compare-and-swap failed, §5.3) and from *other half
unavailable* (a seam the sibling branch implements)."""
from __future__ import annotations


class CoreError(Exception):
    status = 500
    code = "core_error"

    def __init__(self, message: str, **detail):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_json(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.detail}}


class ValidationError(CoreError):
    """Request/entity does not satisfy the spec's schema rules."""

    status = 422
    code = "validation"


class Refused(CoreError):
    """A domain rule refused the action at the door (spec: refusals are
    audited — the edges are the story)."""

    status = 422
    code = "refused"


class StaleTransition(CoreError):
    """Compare-and-swap on (entity, expected_state, seq) failed (§5.3);
    fails closed."""

    status = 409
    code = "stale_transition"


class NotFound(CoreError):
    status = 404
    code = "not_found"


class OtherHalfUnavailable(CoreError):
    """A seam owned by the sibling half (core-recipe: recipe store, compiler,
    engineer adapter). Stubs raise this; the API answers 501 naming the seam."""

    status = 501
    code = "other_half_unavailable"


class Overflow(CoreError):
    """A hard bound was exceeded and could not be resolved by dropping
    (e.g. a context packet still over 16 KiB after the drop order)."""

    status = 422
    code = "overflow"


class IntegrityFailure(CoreError):
    status = 500
    code = "integrity"
