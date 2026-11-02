"""Byte-identical verdicts: the same proposal gets the same bytes.

The claim under test (docs/lab/exp-precedent-store.md): a verdict is a
function of (store, rules, proposal keys) and nothing else — not the
order the keys arrive in, not the order the store was filled, not the
process that computes it. ``Verdict.canonical()`` is the payload a
caller would commit to a ledger; two runs that disagree on one byte of
it would be two worlds, so this file compares bytes, not semantics.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

from core.precedent import (
    Precedent,
    PrecedentStatus,
    PrecedentStore,
    Rule,
    RuleEffect,
    Validator,
    seed_precedents,
    seed_store,
    seed_validator,
)

REPO = Path(__file__).resolve().parents[2]

KEYS = ["proposal.upload", "default.allow_upload", "scan.clean"]


def filled_store() -> PrecedentStore:
    store = seed_store()
    store.append(
        Precedent(
            id="prec-upload",
            gap_id="gap-upload",
            decision="deny",
            rationale="not scanned",
            author="casey",
            created_at=datetime.datetime(2026, 11, 2, 8, 0),
            status=PrecedentStatus.ADJUDICATED,
            rule_override="default.allow_upload",
            keys=["proposal.upload", "scan.clean"],
        )
    )
    return store


def rules():
    return {
        "default.allow_upload": "uploads are allowed",
        "scan.clean": Rule(
            key="scan.clean", text="ask the scanner", effect=RuleEffect.ASK_HUMAN
        ),
        "nogrief.attack_player": Rule(
            key="nogrief.attack_player",
            text="never attack a player",
            effect=RuleEffect.DENY,
            hard=True,
        ),
    }


def test_the_same_question_twice_is_the_same_bytes() -> None:
    validator = Validator(filled_store(), rules())
    first = validator.validate("upload the log", KEYS)
    for _ in range(50):
        again = validator.validate("upload the log", KEYS)
        assert again.canonical().encode("utf-8") == first.canonical().encode("utf-8")
        assert again.digest() == first.digest()


def test_key_order_does_not_move_the_verdict() -> None:
    validator = Validator(filled_store(), rules())
    forwards = validator.validate("upload the log", KEYS)
    backwards = validator.validate("upload the log", list(reversed(KEYS)))
    shuffled = validator.validate("upload the log", ["scan.clean", "proposal.upload", "default.allow_upload"])
    assert forwards.canonical() == backwards.canonical() == shuffled.canonical()


def test_store_insertion_order_does_not_move_the_verdict() -> None:
    a = filled_store()
    # the same cases, appended in the opposite order
    c = PrecedentStore()
    c.append(a.get("prec-upload"))
    for precedent in seed_precedents():
        c.append(precedent)
    assert [p.id for p in a.all()] != [p.id for p in c.all()]
    one = Validator(a, rules()).validate("upload the log", KEYS)
    two = Validator(c, rules()).validate("upload the log", KEYS)
    assert one.canonical() == two.canonical()


def test_a_markdown_round_trip_preserves_the_verdict_bytes(tmp_path) -> None:
    store = filled_store()
    path = tmp_path / "board.md"
    store.save_markdown(path)
    back = PrecedentStore()
    back.load_markdown(path)

    keys = ["proposal.upload", "scan.clean"]
    before = Validator(store, rules()).validate("upload the log", keys)
    after = Validator(back, rules()).validate("upload the log", keys)
    assert before.canonical() == after.canonical()
    assert before.digest() == after.digest()


def test_two_processes_produce_the_same_bytes() -> None:
    program = (
        "import sys; sys.path.insert(0, %r);"
        "from core.precedent import seed_validator;"
        "v = seed_validator();"
        "print(v.validate('Pebble wants to apply this branch', ['recipe.apply']).canonical());"
        "print(v.validate('Pebble wants to commit to main', ['ladder.p1', 'ladder.p1.commit_main']).digest())"
    ) % str(REPO)
    in_process = seed_validator()
    expected = [
        in_process.validate("Pebble wants to apply this branch", ["recipe.apply"]).canonical(),
        in_process.validate(
            "Pebble wants to commit to main", ["ladder.p1", "ladder.p1.commit_main"]
        ).digest(),
    ]

    runs = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
        )
        runs.append(result.stdout)
    assert runs[0] == runs[1]
    assert runs[0].splitlines() == expected


def test_the_digest_is_a_sha256_hex() -> None:
    verdict = seed_validator().validate("nothing here", ["unknown.action"])
    assert verdict.digest().startswith("sha256:")
    assert len(verdict.digest()) == len("sha256:") + 64
    assert all(c in "0123456789abcdef" for c in verdict.digest()[7:])
