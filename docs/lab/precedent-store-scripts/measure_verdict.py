#!/usr/bin/env python3
"""The numbers in docs/lab/exp-precedent-store.md, measured on this box.

Run from the repository root:

    ~/lm-tools/thor-admit run --tier live --peak 1G \\
        --label precedent-store.latency -- \\
        .venv/bin/python docs/lab/precedent-store-scripts/measure_verdict.py

What it prints:

- **the seed counts** — how many rule rows the three sources carry
  (``core/precedent/seeds.py``) and how many seeded precedents;
- **the seed scenarios' verdicts** — the same rows
  ``tests/precedent/test_seeds.py`` asserts, so the numbers and the test
  cannot drift apart silently;
- **verdict latency** in microseconds, at p50 / p90 / p99 / max, over a
  mixed workload: the scenarios above, round-robin, in one process, on
  one validator built once (store + rules are built before the clock
  starts — what is measured is ``validate()`` itself);
- **the digests** — two runs of the same two verdicts; these are
  content hashes and are *not* machine-dependent, unlike latency.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.precedent import seed_rules, seed_precedents, seed_validator

SCENARIOS = [
    ("Pebble commits to main", ["ladder.p1", "ladder.p1.commit_main", "recipe.commit.main"]),
    ("Pebble pre-flights on the fork", ["ladder.p1", "ladder.p1.preflight"]),
    ("Timber commits in scope", ["ladder.p2", "ladder.p2.supervised"]),
    ("Timber widens its own scope", ["ladder.p2", "ladder.p2.widen_own_scope"]),
    ("Casey commits to main", ["ladder.p3", "ladder.p3.owner"]),
    ("Kite breaks a human block", ["nogrief.break_human_block", "world.break_block"]),
    ("Sprout empties a human chest", ["nogrief.take_from_human_chest"]),
    ("Pebble attacks TestHuman", ["nogrief.attack_player"]),
    ("Kite builds 3 blocks from a human build", ["nogrief.keep_out_radius", "world.place_block"]),
    ("Log what TestHuman said", ["nogrief.privacy"]),
    ("Turn TestHuman's request into a proposal", ["world.human_request", "board.propose"]),
    ("Apply Magnus's branch", ["recipe.apply"]),
    ("Something nobody has ruled on", ["unknown.action"]),
]

ITERATIONS = 20_000


def percentiles(samples_ns: list[int]) -> tuple[float, ...]:
    ordered = sorted(samples_ns)
    pick = lambda q: ordered[int(len(ordered) * q)] / 1_000.0  # noqa: E731
    return pick(0.50), pick(0.90), pick(0.99), ordered[-1] / 1_000.0


def main() -> None:
    rules = seed_rules()
    precedents = seed_precedents()
    hard = sum(1 for rule in rules.values() if rule.hard)
    print(f"rule rows seeded      : {len(rules)} "
          f"({hard} hard deny, {len(rules) - hard} soft)")
    print(f"seeded precedents     : {len(precedents)}")

    validator = seed_validator()
    print("seed scenarios        :")
    for proposal, keys in SCENARIOS:
        verdict = validator.validate(proposal, keys)
        print(f"    {verdict.type.value:<10} {proposal}")

    # -- latency: validate() only, store and rules built before the clock
    rungs = [(p, k) for p, k in SCENARIOS]
    samples: list[int] = []
    for i in range(ITERATIONS):
        proposal, keys = rungs[i % len(rungs)]
        started = time.perf_counter_ns()
        validator.validate(proposal, keys)
        samples.append(time.perf_counter_ns() - started)
    p50, p90, p99, worst = percentiles(samples)
    print(f"verdict latency, us   : p50 {p50:.1f}  p90 {p90:.1f}  "
          f"p99 {p99:.1f}  max {worst:.1f}  ({ITERATIONS} verdicts, one process)")

    again = seed_validator()
    for proposal, keys in SCENARIOS[:2]:
        one = validator.validate(proposal, keys).digest()
        two = again.validate(proposal, keys).digest()
        assert one == two
        print(f"digest, twice         : {one}")
    print("determinism           : the two runs' digests matched")


if __name__ == "__main__":
    main()
