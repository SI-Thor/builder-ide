"""Sealed predictions: the bet that cannot be edited after the fact.

Spec §1.7 and §5.1:

* A `Prediction` is **sealed** — hashed into the ledger *before* any render
  exists — and cannot be edited after (D §23:04 step 2; §5.1: "the
  `prediction.sealed` (committed, fsynced) **before** the render
  `job.enqueued` is committed — that ordering is what makes a sealed bet
  unforgeable").
* The seal hash covers the whole payload including `render_spec`, so a verdict
  is re-scorable against the same inputs (X R7; RV patch 16).
* Three record types, three writers (X C5/D1/D2): a `prediction` is the
  builder's, sealed; a `taste_note` is the owner's; a `verdict` is the
  Critic's. **Self-scoring is refused.**

This module owns the record and the write path for it. The ledger itself is
`core-api`'s (branch `core-api`); this service writes through the
`LedgerPort` seam so the two merge without either seat owning the other's
tables.
"""

from __future__ import annotations

from typing import Any, Mapping

from .hashing import content_hash, short_hash
from .models import Actor, AuditEvent, Prediction

__all__ = [
    "SEALED_FIELDS",
    "seal_hash_for",
    "build_prediction",
    "verify_seal",
    "PredictionRefusal",
    "PredictionService",
]

#: §1.7 — "sha256 over canonical {builder, at, branch_ref, claim, claim_type,
#: confidence, basis, render_spec}".
SEALED_FIELDS: tuple[str, ...] = (
    "builder",
    "at",
    "branch_ref",
    "claim",
    "claim_type",
    "confidence",
    "basis",
    "render_spec",
)


def seal_hash_for(payload: Mapping[str, Any]) -> str:
    """The seal hash of a prediction payload: `sha256:` over the canonical JSON."""
    return content_hash({field: payload.get(field) for field in SEALED_FIELDS})


def build_prediction(
    *,
    id: str,
    builder: str,
    at: str,
    sealed_at: str,
    branch_ref: str,
    claim: str,
    claim_type: str,
    confidence: str,
    basis: str,
    render_spec: Mapping[str, Any] | None = None,
) -> Prediction:
    """Build a sealed `Prediction`, hashing the payload as §1.7 requires.

    `at` and `sealed_at` are equal at seal time ("equal at seal time;
    `sealed_at` is immutable").
    """
    payload = {
        "builder": builder,
        "at": at,
        "branch_ref": branch_ref,
        "claim": claim,
        "claim_type": claim_type,
        "confidence": confidence,
        "basis": basis,
        "render_spec": dict(render_spec) if render_spec is not None else None,
    }
    return Prediction(
        id=id,
        builder=builder,
        at=at,
        sealed_at=sealed_at,
        branch_ref=branch_ref,
        claim=claim,
        claim_type=claim_type,  # type: ignore[arg-type]
        namespace="taste" if claim_type == "taste_keep" else "world",
        confidence=confidence,  # type: ignore[arg-type]
        basis=basis,
        render_spec=dict(render_spec) if render_spec is not None else None,
        seal_hash=seal_hash_for(payload),
    )


def verify_seal(prediction: Prediction) -> bool:
    """True when the record still hashes to its own seal hash."""
    return prediction.seal_hash == seal_hash_for(prediction.model_dump())


class PredictionRefusal(Exception):
    """A prediction write that is refused. Carries a closed reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class PredictionService:
    """Writes sealed predictions and their verdicts through the ledger seam."""

    def __init__(self, *, ledger: Any, clock: Any) -> None:
        self._ledger = ledger
        self._clock = clock

    # -- sealing ----------------------------------------------------------------

    def seal(
        self,
        *,
        builder: str,
        claim: str,
        claim_type: str,
        confidence: str,
        basis: str,
        branch_ref: str,
        render_spec: Mapping[str, Any] | None = None,
        reason_code: str | None = None,
        actor: Actor | None = None,
        at: str | None = None,
    ) -> Prediction:
        """Seal a bet and commit it to the ledger.

        The commit happens **here**, before any render job exists; the caller
        is responsible for only enqueuing a render after this returns.

        `reason_code` is not part of the `Prediction` record (§1.7 does not
        have the field). It rides in the audit payload because the taste gate
        is *per reason code* and the ledger is where the gate reads its
        denominators from.
        """
        if claim_type not in _CLAIM_TYPES:
            raise PredictionRefusal("claim_type_unknown", f"{claim_type!r} is not a claim type")
        if confidence not in _CONFIDENCES:
            raise PredictionRefusal("confidence_unknown", f"{confidence!r} is not a confidence")

        now = at or self._clock.now()
        payload = {
            "builder": builder,
            "at": now,
            "branch_ref": branch_ref,
            "claim": claim,
            "claim_type": claim_type,
            "confidence": confidence,
            "basis": basis,
            "render_spec": dict(render_spec) if render_spec is not None else None,
        }
        prediction = build_prediction(
            id=f"pr_{short_hash(payload)}",
            builder=builder,
            at=now,
            sealed_at=now,
            branch_ref=branch_ref,
            claim=claim,
            claim_type=claim_type,
            confidence=confidence,
            basis=basis,
            render_spec=render_spec,
        )

        event_payload = {
            "prediction_id": prediction.id,
            "seal_hash": prediction.seal_hash,
            "claim_type": prediction.claim_type,
            "namespace": prediction.namespace,
            "sealed_payload": payload,
        }
        if reason_code is not None:
            event_payload["reason_code"] = reason_code

        self._ledger.append(
            AuditEvent(
                seq=0,  # the ledger assigns the sequence
                id=f"aud_{short_hash({'type': 'prediction.sealed', 'pid': prediction.id})}",
                at=now,
                actor=actor or Actor(kind="character", id=builder, via="word"),
                type="prediction.sealed",
                subject={"entity_kind": "prediction", "entity_id": prediction.id},
                payload=event_payload,
            )
        )
        return prediction

    # -- scoring ----------------------------------------------------------------

    def score(
        self,
        prediction: Prediction,
        *,
        verdict: str,
        actor: Actor,
    ) -> Prediction:
        """Record a verdict against a sealed prediction.

        The three-writer rule (X C5/D1/D2; spec §1.7) is enforced here, in
        code, not in a prompt:

        * a **world** prediction is scored by the Critic;
        * a **taste** prediction is scored by the owner (keep/apply/reject);
        * nobody scores their own bet.
        """
        if prediction.verdict is not None:
            raise PredictionRefusal("already_scored", "a sealed prediction is scored once")
        already = self._ledger.find(
            "prediction.scored", prediction_id=prediction.id
        )
        if already is not None:
            # The record is immutable, so the log is where "already scored"
            # lives — a replay must not score a bet twice.
            raise PredictionRefusal("already_scored", "a sealed prediction is scored once")
        if verdict not in ("hit", "miss", "partial"):
            raise PredictionRefusal("verdict_unknown", f"{verdict!r} is not a verdict")
        if actor.id == prediction.builder:
            raise PredictionRefusal(
                "self_scored", "a builder never scores their own bet (spec §1.7)"
            )
        if prediction.namespace == "world" and actor.kind != "critic":
            raise PredictionRefusal(
                "not_the_critic", "a world prediction is scored by the Critic"
            )
        if prediction.namespace == "taste" and actor.kind != "owner":
            raise PredictionRefusal(
                "not_the_owner", "a taste prediction is scored by the owner's keep/apply/reject"
            )

        self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'prediction.scored', 'pid': prediction.id, 'v': verdict})}",
                at=self._clock.now(),
                actor=actor,
                type="prediction.scored",
                subject={"entity_kind": "prediction", "entity_id": prediction.id},
                payload={
                    "prediction_id": prediction.id,
                    "verdict": verdict,
                    "seal_hash": prediction.seal_hash,
                    "claim_type": prediction.claim_type,
                    "builder": prediction.builder,
                },
            )
        )
        return prediction.model_copy(update={"verdict": verdict})


_CLAIM_TYPES = (
    "shadow_count",
    "scale_read",
    "clutter_density",
    "material_read",
    "era_read",
    "light_read",
    "weather_read",
    "taste_keep",
)

_CONFIDENCES = ("guess", "low", "medium", "high")
