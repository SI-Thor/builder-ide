"""The mediator: the cloud writes the options.

Casey's frame (from ``docs/design/three-minds.md``): the mediator is the
reflective mind. It watches the running system and improves it while it
runs — but **it observes during flow and steps in only when the sign
fades** (failures rising, confidence sliding) or when a human joins.

So this module has two halves:

* **The observer.** It reads the log — the play records — and computes
  the sign: the failure rate over the recent window, and the slope of
  the decision model's confidence. It makes **no model calls** while the
  sign holds. That is the rule: intervening during flow would add
  latency, cost and second-guessing to a groove that is working.
* **The author.** When the sign fades, it builds a feedback packet per
  losing family ("write a better one; here is why it lost") and asks a
  cloud model for a new skill. The new skill is held to the **door** —
  the same door the builders are held to — and the refusal reason goes
  back to the author, so the next attempt is a better one.

The cloud call is Groq's ``gpt-oss-120b`` through ``~/lm-tools/gq.py``.
The cost is recorded with the skill.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from .door import VOCABULARY, vocabulary_text
from .library import SkillLibrary, build_skill
from .ledger import WorldLedger
from .models import FeedbackPacket, PlayRecord, Skill, SkillAuthor

__all__ = ["Mediator", "sign_of", "feedback_packets"]

#: The cloud client. It is a parameter with a default, like every door here.
GROQ_TOOLS = Path(os.environ.get("AW_GQ_DIR", str(Path.home() / "lm-tools")))


def _gq_ask(model: str, instruction: str, text: str = "") -> tuple[str, dict[str, Any]]:
    """One cloud call. The key is read from the environment and never printed."""
    if str(GROQ_TOOLS) not in sys.path:
        sys.path.insert(0, str(GROQ_TOOLS))
    from gq import ask  # type: ignore

    return ask(model, instruction, text)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model's answer."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    body = fenced.group(1) if fenced else text
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("the answer had no JSON object in it")
    return json.loads(body[start : end + 1])


def sign_of(records: Sequence[PlayRecord], *, window: int = 20) -> dict[str, Any]:
    """The sign: is the world in flow, or is it fading?

    Two readings, both from the recent window:

    * **failures rising** — the share of recent plays that lost;
    * **confidence sliding** — the slope of the decision model's
      confidence on those plays.

    The sign holds when the failures are low and not rising. It fades
    when the failure rate is above ``fail_threshold`` or climbing by
    more than ``rise_threshold`` across the window, or when the mean
    confidence is falling.
    """
    recent = list(records)[-window:]
    if not recent:
        return {
            "plays": 0,
            "failure_rate": 0.0,
            "confidence": None,
            "confidence_slope": 0.0,
            "fading": False,
            "reason": "no plays yet",
        }

    failures = [r for r in recent if r.outcome.result == "lose"]
    failure_rate = len(failures) / len(recent)

    confidences = [
        r.context.get("confidence")
        for r in recent
        if isinstance(r.context.get("confidence"), (int, float))
    ]
    slope = 0.0
    mean_conf = None
    if len(confidences) >= 4:
        half = len(confidences) // 2
        older = sum(confidences[:half]) / half
        newer = sum(confidences[half:]) / (len(confidences) - half)
        slope = newer - older
        mean_conf = sum(confidences) / len(confidences)

    # The failure trend: the first half against the second half.
    half = len(recent) // 2
    older_rate = len([r for r in recent[:half] if r.outcome.result == "lose"]) / max(1, half)
    newer_rate = (
        len([r for r in recent[half:] if r.outcome.result == "lose"])
        / max(1, len(recent) - half)
    )
    rise = newer_rate - older_rate

    fading = False
    reasons: list[str] = []
    if failure_rate >= 0.5:
        fading = True
        reasons.append(f"failure rate {failure_rate:.0%}")
    if rise >= 0.25:
        fading = True
        reasons.append(f"failures rising ({older_rate:.0%} -> {newer_rate:.0%})")
    if mean_conf is not None and slope <= -0.1:
        fading = True
        reasons.append(f"confidence sliding ({slope:+.2f})")

    return {
        "plays": len(recent),
        "failure_rate": round(failure_rate, 3),
        "failure_rise": round(rise, 3),
        "confidence": round(mean_conf, 3) if mean_conf is not None else None,
        "confidence_slope": round(slope, 3),
        "fading": fading,
        "reason": "; ".join(reasons) if reasons else "the sign holds",
    }


def feedback_packets(
    records: Sequence[PlayRecord],
    library: SkillLibrary,
    *,
    min_plays: int = 3,
) -> list[FeedbackPacket]:
    """One packet per family that is losing.

    The packet is deliberately blunt: what it lost, where it lost, how
    many times, and what it used.
    """
    by_skill: dict[str, list[PlayRecord]] = {}
    for record in records:
        by_skill.setdefault(record.skill_id, []).append(record)

    packets: list[FeedbackPacket] = []
    families: dict[str, list[PlayRecord]] = {}
    for skill_id, plays in by_skill.items():
        skill = library.get(skill_id)
        if skill is None:
            continue
        families.setdefault(skill.family, []).extend(plays)

    for family, plays in sorted(families.items()):
        wins = [p for p in plays if p.outcome.result == "win"]
        losses = [p for p in plays if p.outcome.result == "lose"]
        if len(plays) < min_plays or not losses or len(wins) >= len(losses):
            continue
        api: set[str] = set()
        for play in plays:
            skill = library.get(play.skill_id)
            if skill:
                api.update(skill.api)
        contexts = sorted({p.context.get("phase", "?") for p in losses})
        packets.append(
            FeedbackPacket(
                skill_id=losses[0].skill_id,
                family=family,
                kind="behaviour",
                api=tuple(sorted(api)),
                plays=len(plays),
                wins=len(wins),
                win_rate=round(len(wins) / len(plays), 3),
                measure=losses[0].outcome.measure,
                contexts=tuple(contexts),
                request=(
                    f"write a better skill for the family '{family}'; "
                    f"here is why it lost ({len(wins)} won, {len(losses)} lost, "
                    f"in contexts: {', '.join(contexts)})"
                ),
            )
        )
    return packets


class Mediator:
    """The reflective mind: observes, and steps in only when it must."""

    def __init__(
        self,
        *,
        library: SkillLibrary,
        ledger: WorldLedger,
        model: str = "120b",
        max_calls: int = 4,
        dry_run: bool = False,
    ) -> None:
        self.library = library
        self.ledger = ledger
        self.model = model
        self.max_calls = max_calls
        self.dry_run = dry_run
        self.calls = 0
        self.cost_cents = 0

    # -- the observer ----------------------------------------------------------

    def observe(self) -> dict[str, Any]:
        """Read the sign. No model call happens here."""
        records = self.ledger.plays()
        sign = sign_of(records)
        human = any(
            bool(r.context.get("human_present"))
            for r in records[-40:]
        )
        sign["human_present"] = human
        sign["should_step_in"] = bool(sign["fading"] or human)
        sign["trigger"] = (
            "the sign faded" if sign["fading"] else ("a human joined" if human else "")
        )
        return sign

    # -- the author ------------------------------------------------------------

    def _prompt(self, packet: FeedbackPacket, refused: str = "") -> tuple[str, str]:
        instruction = (
            "You write one small JavaScript skill for a Minecraft agent. "
            "The agent runs your skill; you never run it yourself.\n\n"
            "Rules:\n"
            "- Use only the words listed. Any other word is refused.\n"
            "- The skill is a sequence of statements. `await` an action before "
            "using its result.\n"
            "- The skill returns {done: true|false, detail: '...'}.\n"
            "- Do not use `say`, chat, or any way to speak to a player.\n"
            "- Keep it under 40 lines.\n\n"
            "The words:\n"
            + vocabulary_text()
            + "\n\nAnswer with JSON only, of the shape:\n"
            '{"title": "...", "body": "...", "predict": {"kind": "inventory_delta", '
            '"item": "oak_log", "min": 1}}\n'
            "The predict block is what the world checks to decide whether the "
            "skill won: inventory_delta (the agent's bag gains at least `min` "
            "of `item`), block_placed (a block was placed), block_broken (a "
            "block was mined), moved_to (the agent got within 2 blocks of a "
            "target), none (no measurable effect)."
        )
        text = (
            f"Family: {packet.family}\n"
            f"Plays: {packet.plays}, won: {packet.wins} (win rate {packet.win_rate:.0%})\n"
            f"Contexts where it lost: {', '.join(packet.contexts) or 'unknown'}\n"
            f"Words it used: {', '.join(packet.api) or 'none'}\n"
            f"{packet.request}\n"
        )
        if refused:
            text += f"\nYour last attempt was refused: {refused}\nDo it differently.\n"
        return instruction, text

    def author_for(self, packet: FeedbackPacket) -> Skill | None:
        """Ask the cloud for a better skill, and hold it to the door."""
        instruction, text = self._prompt(packet)
        answer, usage = _gq_ask(self.model, instruction, text)
        cost_cents = int(round(float(usage.get("cost_usd", 0.0)) * 100))
        self.calls += 1
        self.cost_cents += cost_cents
        try:
            parsed = _extract_json(answer)
        except (ValueError, json.JSONDecodeError) as exc:
            self.ledger.retrained(
                summary={
                    "chooser": "mediator",
                    "refused": f"the cloud's answer was not JSON: {exc}",
                    "family": packet.family,
                }
            )
            return None

        author = SkillAuthor(
            model=usage.get("model", self.model),
            provider="groq",
            prompt_hash=SkillAuthor(model=usage.get("model", self.model), provider="groq").prompt_hash
            or _hash(text),
            cost_cents=cost_cents,
            temperature=None,
        )
        author = author.model_copy(update={"prompt_hash": _hash(text)})
        try:
            skill = build_skill(
                family=packet.family,
                role=_role_of(packet),
                title=str(parsed.get("title", "a new skill"))[:120],
                body=str(parsed.get("body", "")),
                author=author,
                predict=parsed.get("predict") or {"kind": "none"},
                provenance={"written_because": packet.skill_id, "request": packet.request},
            )
        except Exception as exc:
            reason = getattr(exc, "reason", "refused")
            detail = getattr(exc, "detail", str(exc))
            self.ledger.retrained(
                summary={
                    "chooser": "mediator",
                    "refused": f"{reason}: {detail}",
                    "family": packet.family,
                }
            )
            return None

        admitted = self.library.add(skill)
        self.ledger.authored(admitted, cost_cents=cost_cents)
        return admitted

    # -- the loop --------------------------------------------------------------

    def step_in(self) -> dict[str, Any]:
        """Observe, and act only if the sign faded or a human joined."""
        sign = self.observe()
        if not sign["should_step_in"]:
            return {"acted": False, "sign": sign}
        if self.calls >= self.max_calls:
            return {"acted": False, "sign": sign, "detail": "the cloud call budget is spent"}
        if self.dry_run:
            return {"acted": False, "sign": sign, "detail": "dry run"}

        records = self.ledger.plays()
        packets = feedback_packets(records, self.library)
        written: list[str] = []
        for packet in packets[: max(0, self.max_calls - self.calls)]:
            skill = self.author_for(packet)
            if skill is not None:
                written.append(skill.id)
        return {"acted": bool(written), "sign": sign, "written": written}


def _role_of(packet: FeedbackPacket) -> str:
    """The role a family belongs to, carried in the family's name."""
    return packet.family.split(".")[0]


def _hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
