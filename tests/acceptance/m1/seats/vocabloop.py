"""The vocabulary seat (branch `vocab`): the Prop-maker's loop, in full.

This is the M1 night's reference implementation — D §23:04's fish-crate
bet, scripted, with every rule the future LLM will have to obey already in
code: the typed call at the door, the seal before the render job exists,
the confidence gate, the scripted critic wearing `verdict@scripted`, and
keep-or-revert as a verdict write, never a taste write (§1.7; X C5).

The session runs it once, on the **cold** world (night one: nothing in the
ledger), because that is the M1 night — and asserts the cold-start shape
the gate forces:

* the world bet seals with `confidence: "guess"` and `basis: "0
  observations"` (sealing is always legal; pretending to a view is not);
* the taste claim is **refused** by the two-observation gate — with no
  priors the builder may bet but may not claim taste;
* the hollow crates (7, 11 at the known seed) fall back to the library;
* the gate blocks the branch move the same way it blocked the claim, so the
  builder **parks the question** instead of deciding alone;
* the ledger refuses a `job.enqueued` whose prediction was never sealed —
  the §5.1 ordering, enforced where the ordering happens.

It runs on the seat's own in-memory world (its `conftest` wiring, cold
variant) — the same honest seam as the recipe seat: one more ledger until
the seats merge.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LoopWorld:
    """Everything one cold night needs, wired to the seat's seams."""

    registry: object
    ledger: object
    clock: object
    recipes: object
    scheduler: object
    predictions: object
    maker: object


def build_cold_world(seats) -> LoopWorld:
    """The vocab seat's own wiring, night one (nothing in the ledger)."""
    v = seats.vocab
    registry = v.VocabularyRegistry(v.default_entries())
    ledger = v.InMemoryLedger()          # cold: no seed_audit_events()
    clock = v.SteppingClock("2026-10-30T23:04:00Z")
    recipes = v.InMemoryRecipeStore(
        document=v.seed.RECIPE_DOCUMENT,
        branches=[
            v.models.Branch(
                id="br_main", name="main", recipe="rcp_fjellvik", head="ver_root",
                purpose="main", created_by=v.models.Actor(kind="owner", id="casey"),
            )
        ],
        validator=registry.validate_document,
        clock=clock,
    )
    scheduler = v.InMemoryScheduler(ledger=ledger, clock=clock)
    predictions = v.PredictionService(ledger=ledger, clock=clock)
    maker = v.PropMaker(
        registry=registry, ledger=ledger, recipes=recipes, scheduler=scheduler,
        clock=clock, predictions=predictions,
    )
    return LoopWorld(
        registry=registry, ledger=ledger, clock=clock, recipes=recipes,
        scheduler=scheduler, predictions=predictions, maker=maker,
    )


def run_cold_night(seats, world: LoopWorld, bet=None):
    """One night of the loop, exactly as the seat plays it (D §23:04)."""
    return world.maker.run(bet or seats.vocab.CrateBet())


def sealed_before_render(world: LoopWorld) -> bool:
    """§5.1, read off the seat's own ledger: the seal's seq precedes the
    enqueue's seq, for the bet the render tests."""
    events = world.ledger.events()
    sealed = next(e for e in events if e.type == "prediction.sealed")
    enqueued = next(e for e in events if e.type == "job.enqueued")
    return sealed.seq < enqueued.seq
