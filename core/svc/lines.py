"""Interruption and narration budgets, enforced in the core, not the
prompt (§5.6): narrations ≤ 6 per builder per hour, state-change only, no
repeats within a session; interruptions ≤ 1 per builder per 20 minutes,
only for a blocked decision, a rail event, or a hard failure. The
line.spoken event is emitted only after the budget check passes.

Also the two-observation gate on taste CLAIMS (§1.7): a builder may not
say a taste claim below two observations; below three the uncertainty
leads the sentence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..canon import now_utc
from ..errors import Refused
from ..events import character_actor

NARRATIONS_PER_HOUR = 6
INTERRUPTION_COOLDOWN_MIN = 20
TASTE_GATE_OBSERVATIONS = 2


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


class LinesService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    def speak(self, builder: str, text: str, *, kind: str = "narration",
              state_change: bool = True, claim_type: str | None = None,
              reason: str | None = None) -> dict:
        if kind not in ("narration", "interruption"):
            raise Refused("line kind must be narration|interrupt")
        if kind == "narration" and not state_change:
            raise Refused("narrations are state-change only (§5.6)")
        actor = character_actor(builder)
        cutoff = (_parse(now_utc()) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        recent = [
            e for e in self.store.events_since(0, types=["line.spoken"])
            if e.actor.id == builder and e.at >= cutoff and not e.refused
        ]
        if kind == "narration":
            narrations = [e for e in recent
                          if e.payload.get("kind") == "narration"]
            if len(narrations) >= NARRATIONS_PER_HOUR:
                raise Refused(
                    f"narration budget spent ({NARRATIONS_PER_HOUR}/builder/hour) — the "
                    "check is code, because prompt instructions are not enforcement")
            if any(e.payload.get("text") == text for e in narrations):
                raise Refused("no repeats within a session (§5.6)")
        else:  # interruption
            interruptions = [
                e for e in self.store.events_since(0, types=["line.spoken"])
                if e.actor.id == builder
                and e.payload.get("kind") == "interruption" and not e.refused
            ]
            if interruptions:
                last = _parse(sorted(e.at for e in interruptions)[-1])
                if _parse(now_utc()) - last < timedelta(minutes=INTERRUPTION_COOLDOWN_MIN):
                    raise Refused(
                        f"at most one interruption per builder per {INTERRUPTION_COOLDOWN_MIN} "
                        "minutes (§5.6)")
            if reason not in ("blocked decision", "rail event", "hard failure"):
                raise Refused(
                    "a builder may interrupt only for a blocked decision, a rail event, "
                    "or a hard failure (§5.6)")
        # the taste-claim gate on utterances (§1.7) — sealed guesses stay legal
        if claim_type == "taste_keep":
            from .predictions import PredictionsService

            obs = PredictionsService(self.core).observations_for(builder, "taste_keep")
            if obs < TASTE_GATE_OBSERVATIONS:
                raise Refused(
                    f"a builder may not SAY a taste claim below {TASTE_GATE_OBSERVATIONS} "
                    f"observations ({builder} has {obs}) — seal it as confidence 'guess' "
                    "instead; the gate forbids pretending to a view, not betting")
        ev = self.store.new_event(
            "line.spoken", actor, {"entity_kind": "character", "entity_id": builder},
            {"kind": kind, "text": text, "state_change": state_change,
             "claim_type": claim_type, "reason": reason},
        )
        self.store.append(ev)
        return {"spoken": True, "builder": builder, "text": text}
