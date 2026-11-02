# precedent-store-scripts — the validator's apparatus

The scripts behind [`docs/lab/exp-precedent-store.md`](../exp-precedent-store.md):
the measurements that say what a verdict costs and what the board is
made of.

## `measure_verdict.py`

Run from the repository root, through the memory lease (as every run on
the Thor is):

```bash
~/lm-tools/thor-admit run --tier live --peak 1G \
    --label precedent-store.latency -- \
    .venv/bin/python docs/lab/precedent-store-scripts/measure_verdict.py
```

It prints, in order: the seeded rule rows (22: 18 hard deny, 4 soft
allow, from `core/precedent/seeds.py`), the seeded precedents, the 13
seed scenarios' verdicts, the verdict latency at p50 / p90 / p99 / max
in microseconds over 20,000 mixed verdicts in one process, and the
`sha256:` digests of two separately-built validators over the same
proposals.

The latency numbers are **machine-dependent** (they are a property of
the Thor and of one process; nothing pins the CPU). The digests are
**content hashes** and must be identical on every machine and every run
— `tests/precedent/test_verdict_determinism.py` asserts exactly this,
including across fresh interpreters, so this script and the test suite
disagree loudly if the validator ever stops being deterministic.

The scenarios listed by the script are the same rows
`tests/precedent/test_seeds.py` asserts: the numbers in the write-up
cannot drift away from what the suite checks.
