"""The two ledgers, prediction half (§1.7): sealed bets and their scoring.

Only sealed predictions count, anywhere. The seal is committed BEFORE the
render job exists (§5.1) — this service refuses to seal anything that
names an already-enqueued render job, and the seal includes render_spec so
a verdict is re-scorable against the same inputs (X R7).

Two gates, two namespaces: the world gate is per claim_type with a
denominator; the taste gate is per reason code with ≥ 2 prior observations.
Both gates govern *utterances* (lines.py); sealed records with confidence
"guess" are always permitted — the gate forbids pretending to a view, not
betting (§3.5).
"""
from __future__ import annotations

from ..canon import new_id
from ..errors import NotFound, Refused
from ..events import Actor, core_actor
from ..models import CLAIM_TYPES, CONFIDENCE_LEVELS, Prediction, prediction_seal_hash
from ..store import LedgerStore

# recency weighting: weight decays by half every 10 scored observations
RECENCY_HALF_LIFE = 10.0


class PredictionsService:
    def __init__(self, core) -> None:
        self.core = core
        self.store: LedgerStore = core.store

    # ------------------------------------------------------------- seal

    def seal(self, builder: Actor, branch_ref: str, claim: str, claim_type: str,
             confidence: str, basis: str = "0 observations",
             render_spec: dict | None = None, *, idem_key: str | None = None) -> Prediction:
        if idem_key is not None:
            cached = self.store.idem_get(idem_key)
            if cached:
                return Prediction(**cached["body"])
        if claim_type not in CLAIM_TYPES:
            raise Refused(
                f"claim_type must be one of the closed set {sorted(CLAIM_TYPES)} (§1.7)",
                claim_type=claim_type)
        if confidence not in CONFIDENCE_LEVELS:
            raise Refused(f"confidence must be one of {sorted(CONFIDENCE_LEVELS)}")
        if len(claim) > 120:
            raise Refused("claim is ≤ 120 chars, the spoken claim verbatim (§1.7)")
        if not render_spec:
            raise Refused(
                "render_spec {rung, resolution, seed} is required inside the sealed "
                "payload — a verdict must be re-scorable against the same inputs (X R7)")
        for key in ("rung", "resolution", "seed"):
            if key not in render_spec:
                raise Refused(f"render_spec.{key} is required (§1.7)", render_spec=render_spec)
        # §5.1: the seal must precede its render job — refuse a seal that
        # arrives after a render job for this branch_ref exists.
        for ev in self.store.events_since(0, types=["job.enqueued"]):
            req = ev.payload.get("request", {})
            if req.get("branch_ref") == branch_ref or ev.payload.get("branch_ref") == branch_ref:
                raise Refused(
                    "a render job for this branch_ref is already enqueued; the seal must "
                    "be committed before the render job exists (§5.1)", branch_ref=branch_ref)
        p = Prediction(
            id=new_id("prediction"), builder=builder.id, branch_ref=branch_ref,
            claim=claim, claim_type=claim_type,
            namespace="taste" if claim_type == "taste_keep" else "world",
            confidence=confidence, basis=basis, render_spec=render_spec,
        )
        p.sealed_at = p.at
        p.seal_hash = prediction_seal_hash(p)
        ev = self.store.new_event(
            "prediction.sealed", builder,
            {"entity_kind": "prediction", "entity_id": p.id},
            {"prediction": p.model_dump(mode="json")},
        )
        _, resp = self.store.append(
            ev, idem_key=idem_key,
            response_builder=lambda e: p.model_dump(mode="json"))
        if resp and resp.get("__replay__"):
            return Prediction(**resp["body"])
        return p

    # ------------------------------------------------------------- score

    def score(self, pr_id: str, verdict: str, scored_by: Actor,
              *, artifact_refs: list[str] | None = None) -> Prediction:
        if verdict not in ("hit", "miss", "partial"):
            raise Refused("verdict must be hit|miss|partial; never self-scored (§1.7)")
        row = self.store.get_row("predictions", {"id": pr_id})
        if row is None:
            raise NotFound(f"prediction {pr_id} not found", entity=pr_id)
        if row.get("verdict") is not None:
            raise Refused(f"prediction {pr_id} is already scored", entity=pr_id)
        ev = self.store.new_event(
            "prediction.scored", scored_by,
            {"entity_kind": "prediction", "entity_id": pr_id},
            {"verdict": verdict, "scored_by": scored_by.id,
             "artifact_refs": artifact_refs or []},
        )
        self.store.append(ev)
        return self.get(pr_id)

    def get(self, pr_id: str) -> Prediction:
        row = self.store.get_row("predictions", {"id": pr_id})
        if row is None:
            raise NotFound(f"prediction {pr_id} not found", entity=pr_id)
        return Prediction(**row["payload"])

    def score_taste_keep_on_branch(self, branch_ref: str, owner: Actor,
                                   owner_verdict: str) -> list[str]:
        """The owner's keep/apply/reject is the ONLY event that scores a
        taste_keep prediction (§1.7) — a critic keep does not."""
        mapping = {"keep": "hit", "keep_with_caveat": "partial", "reject": "miss",
                   "apply": "hit"}
        verdict = mapping.get(owner_verdict)
        if verdict is None:
            raise Refused(f"owner verdict {owner_verdict!r} cannot score taste_keep")
        scored: list[str] = []
        for row in self.store.scan("predictions"):
            doc = row["payload"]
            if doc.get("claim_type") != "taste_keep" or doc.get("verdict") is not None:
                continue
            # branch_ref is "br_xxx@ver_yyy" or a plain branch/work-order ref
            if not (doc.get("branch_ref") == branch_ref
                    or doc.get("branch_ref", "").split("@")[0] == branch_ref):
                continue
            self.score(doc["id"], verdict, owner)
            scored.append(doc["id"])
        return scored

    def score_world_from_critic(self, pr_id: str, critic_verdict: str) -> Prediction:
        """World-claim predictions are scored by the Critic only."""
        return self.score(pr_id, critic_verdict, core_actor())

    # ------------------------------------------------------------- gates

    def observations_for(self, builder: str, claim_type: str) -> int:
        n = 0
        for row in self.store.scan("predictions"):
            doc = row["payload"]
            if doc.get("builder") == builder and doc.get("claim_type") == claim_type \
                    and doc.get("verdict") is not None:
                n += 1
        return n

    def may_speak_claim(self, builder: str, claim_type: str) -> bool:
        """The two-observation gate on *utterances* (not sealed records):
        a builder may not SAY a taste claim below two observations."""
        if claim_type != "taste_keep":
            return True
        return self.observations_for(builder, claim_type) >= 2

    # ------------------------------------------------------------- tally (RV patch 20)

    def tally(self, builder: str | None = None, claim_type: str | None = None) -> dict:
        """Per builder × claim_type with denominators, recency-weighted; no
        single score is ever produced (X C2)."""
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in self.store.scan("predictions"):
            doc = dict(row["payload"])
            if builder and doc.get("builder") != builder:
                continue
            if claim_type and doc.get("claim_type") != claim_type:
                continue
            groups.setdefault((doc.get("builder", ""), doc.get("claim_type", "")), []).append(doc)
        out = []
        for (b, ct), docs in sorted(groups.items()):
            scored = sorted(
                (d for d in docs if d.get("verdict") is not None),
                key=lambda d: d.get("scored_at", ""), reverse=True)
            hits = sum(1 for d in scored if d["verdict"] == "hit")
            misses = sum(1 for d in scored if d["verdict"] == "miss")
            partials = sum(1 for d in scored if d["verdict"] == "partial")
            weights, weighted = [], []
            for age, d in enumerate(scored):
                w = 0.5 ** (age / RECENCY_HALF_LIFE)
                weights.append(w)
                weighted.append(w * {"hit": 1.0, "partial": 0.5, "miss": 0.0}[d["verdict"]])
            recency = round(sum(weighted) / sum(weights), 3) if weights else None
            out.append({
                "builder": b, "claim_type": ct,
                "sealed": len(docs), "scored": len(scored),
                "hits": hits, "misses": misses, "partials": partials,
                "denominator": len(scored),
                "recency_weighted": recency,
                "line": self._tally_line(b, ct, len(scored), hits, len(docs)),
            })
        return {"tally": out}

    @staticmethod
    def _tally_line(builder: str, claim_type: str, scored: int, hits: int,
                    sealed: int) -> str:
        if scored == 0:
            return f"{builder}: 0 of 0 on {claim_type} — not taste yet; that is a start"
        return f"{builder}: {hits} of {scored} on {claim_type} ({sealed} sealed)"
