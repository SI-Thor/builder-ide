"""The metrics — the numbers the report quotes.

Four of them, and each one has a denominator or it is not a number:

* **unique items** — the count of distinct item types obtained over the
  whole run. The Voyager benchmark reports this as "unique items
  collected", and it is the number a world-time comparison is made
  against.
* **tech-tree milestones** — the rungs reached (wood, stone, iron), and
  the moment each was first reached.
* **skills admitted** — and, beside it, how many were rejected and how
  many were superseded, because a library that admits everything admits
  nothing.
* **token cost per milestone** — the tokens spent **before** each
  milestone was first reached. It is a cumulative number, not a
  per-step one: the cost of reaching iron is everything spent up to
  iron, and a per-step average would hide the search that cost.

Every count here comes from the run's own records, so the report's
numbers can be recomputed from the log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .models import RunReport, StepRecord

__all__ = ["Metrics"]


@dataclass
class Metrics:
    """The run's tally."""

    world: str = ""
    started_at: str = ""
    finished_at: str = ""
    wall_seconds: float = 0.0
    #: The item types seen so far, with the largest count seen for each.
    items: dict[str, int] = field(default_factory=dict)
    #: The milestones reached, in the order they were reached.
    reached: list[str] = field(default_factory=list)
    #: The wall-clock second at which each milestone was first reached.
    milestone_seconds: dict[str, float] = field(default_factory=dict)
    #: The tokens spent before each milestone was first reached.
    milestone_tokens: dict[str, int] = field(default_factory=dict)
    tokens_by_role: dict[str, int] = field(default_factory=dict)
    total_tokens: int = 0
    steps: list[StepRecord] = field(default_factory=list)

    # -- the writes ------------------------------------------------------------

    def note_step(self, record: StepRecord) -> None:
        """Take one step into the tally."""
        self.steps.append(record)
        self.total_tokens += record.total_tokens
        for usage in record.usage:
            self.tokens_by_role[usage.role] = (
                self.tokens_by_role.get(usage.role, 0) + usage.total_tokens
            )

    def note_items(self, items: Mapping[str, int]) -> None:
        """Fold a snapshot of the inventory into the unique-item count."""
        for name, count in items.items():
            if count <= 0:
                continue
            if name not in self.items:
                self.items[name] = count
            else:
                self.items[name] = max(self.items[name], count)

    def note_milestone(
        self, key: str, *, at_seconds: float, tokens: int
    ) -> None:
        """Note that a milestone was reached, once."""
        if key in self.milestone_seconds:
            return
        self.reached.append(key)
        self.milestone_seconds[key] = at_seconds
        self.milestone_tokens[key] = tokens

    # -- the reads -------------------------------------------------------------

    @property
    def unique_items(self) -> int:
        """The number of distinct item types obtained."""
        return len(self.items)

    def cost_per_milestone(self) -> float | None:
        """The tokens spent per milestone reached, or ``None`` for none.

        The denominator is the number of milestones reached, so the
        number is "tokens per rung of the tech tree" and not a rate with
        no denominator.
        """
        if not self.reached:
            return None
        return self.total_tokens / len(self.reached)

    def tokens_to_reach(self, key: str) -> int | None:
        """The tokens spent before a milestone was reached."""
        return self.milestone_tokens.get(key)

    def report(
        self,
        *,
        skills_admitted: int = 0,
        skills_rejected: int = 0,
        skills_superseded: int = 0,
        cost_cents: int | None = None,
    ) -> RunReport:
        """The run's report."""
        return RunReport(
            world=self.world,
            started_at=self.started_at,
            finished_at=self.finished_at,
            wall_seconds=self.wall_seconds,
            steps=list(self.steps),
            unique_items=self.unique_items,
            items=dict(sorted(self.items.items())),
            milestones_reached=tuple(self.reached),
            milestone_seconds=dict(self.milestone_seconds),
            milestone_tokens=dict(self.milestone_tokens),
            skills_admitted=skills_admitted,
            skills_rejected=skills_rejected,
            skills_superseded=skills_superseded,
            tokens_by_role=dict(self.tokens_by_role),
            total_tokens=self.total_tokens,
            cost_cents=cost_cents,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "world": self.world,
            "unique_items": self.unique_items,
            "milestones_reached": list(self.reached),
            "milestone_seconds": dict(self.milestone_seconds),
            "milestone_tokens": dict(self.milestone_tokens),
            "tokens_by_role": dict(self.tokens_by_role),
            "total_tokens": self.total_tokens,
            "tokens_per_milestone": self.cost_per_milestone(),
        }
