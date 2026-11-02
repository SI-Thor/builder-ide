"""The markdown round-trip: what a human writes is what the store reads.

The claim under test (docs/lab/exp-precedent-store.md): a precedent is a
markdown document a person can open and edit, and ``save -> load`` is
exactly the identity — for every field, including the awkward ones
(the ``None`` author, a decision that itself holds a fenced block, a
body with ``## `` lines in it, unicode, empty metadata).
"""

from __future__ import annotations

import datetime

import pytest

from core.precedent import (
    Precedent,
    PrecedentStatus,
    PrecedentStore,
    parse_precedents,
)


def make(**over) -> Precedent:
    fields = dict(
        id="prec-1",
        gap_id="gap-1",
        decision="deny",
        rationale="the file was not scanned before the upload",
        author="casey",
        created_at=datetime.datetime(2026, 11, 2, 9, 30),
        status=PrecedentStatus.ADJUDICATED,
        rule_override="default.allow_upload",
        keys=["proposal.upload", "scan.clean"],
        metadata={"source": "run 42", "tickets": 3},
    )
    fields.update(over)
    return Precedent(**fields)


ROUND_TRIP_CASES = {
    "the full form": {},
    "no author": {"author": None},
    "no rule override": {"rule_override": None},
    "no keys": {"keys": []},
    "no metadata": {"metadata": {}},
    "a proposed case": {"status": PrecedentStatus.PROPOSED},
    "every status": {"status": PrecedentStatus.ABANDONED},
    "an empty decision": {"decision": ""},
    "unicode": {"rationale": "ceci n'est pas une entrée — 中文 — ✓"},
    "a fenced block inside a body": {
        "decision": "allow\n\nfor example:\n\n```python\nprint('hi')\n```"
    },
    "long backtick runs in a body": {"rationale": "use ````four```` and ```three```"},
    "headings inside a body": {
        "rationale": "## This looked like a heading\n\nbut it is body text"
    },
    "a title inside a body": {
        "decision": "# Precedent not-really-a-title\n\nstill body text"
    },
    "blank lines at both ends": {"rationale": "\n\nthe point\n\n"},
    "newlines in a body": {"decision": "ask\nbut only after the scan"},
}


@pytest.mark.parametrize("over", ROUND_TRIP_CASES.values(), ids=ROUND_TRIP_CASES.keys())
def test_render_then_parse_is_exact(over) -> None:
    precedent = make(**over)
    assert Precedent.from_markdown(precedent.as_markdown()) == precedent


def test_the_rendered_document_is_readable_markdown() -> None:
    text = make().as_markdown()
    assert text.startswith("# Precedent prec-1\n")
    assert "- **Gap:** gap-1\n" in text
    assert "- **Status:** adjudicated\n" in text
    assert "## Decision\n" in text
    assert "## Rationale\n" in text
    # None round-trips as absent, never as the word "None".
    rendered = make(author=None, rule_override=None).as_markdown()
    assert "Author" not in rendered
    assert "Rule override" not in rendered


def test_a_store_round_trips_through_one_file(tmp_path) -> None:
    store = PrecedentStore()
    store.append(make(id="prec-a", keys=["a.one"]))
    store.append(make(id="prec-b", decision="ask", keys=[], author=None))
    path = tmp_path / "board.md"
    store.save_markdown(path)

    back = PrecedentStore()
    assert back.load_markdown(path) == 2
    assert back.all() == store.all()
    assert [p.id for p in back.all()] == ["prec-a", "prec-b"]


def test_a_store_round_trips_through_one_file_per_case(tmp_path) -> None:
    store = PrecedentStore()
    store.append(make(id="prec-a"))
    store.append(make(id="prec-b", decision="ask"))
    directory = tmp_path / "cases"
    written = store.save_files(directory)
    assert [p.name for p in sorted(written)] == ["prec-a.md", "prec-b.md"]

    back = PrecedentStore()
    assert back.load_files(directory) == 2
    assert back.all() == store.all()


def test_a_human_edits_the_body_by_hand() -> None:
    """Hand-written prose, unfenced bodies, a private note — all legal."""
    hand_written = """# Precedent magnus-chest-depot

note to self: Magnus asked about this at standup.

- **Gap:** where may the depot go
- **Status:** closed
- **Created:** 2026-11-02T10:00:00
- **Author:** casey
- **Keys:** board.depot, board.spawn

## Decision

allow, but only as a chest room

## Rationale

The pile on the ground lost four stacks overnight. A chest room keeps
what the crew gathers, and the tester can walk it.

## Scratch

ignored
"""
    precedent = Precedent.from_markdown(hand_written)
    assert precedent.id == "magnus-chest-depot"
    assert precedent.decision == "allow, but only as a chest room"
    assert precedent.keys == ["board.depot", "board.spawn"]
    assert precedent.metadata == {}
    # ... and it still round-trips once loaded.
    assert Precedent.from_markdown(precedent.as_markdown()) == precedent


def test_a_file_of_documents_parses_in_file_order() -> None:
    text = (
        make(id="zeta").as_markdown()
        + "\n"
        + make(id="alpha", decision="ask").as_markdown()
    )
    parsed = parse_precedents(text)
    assert [p.id for p in parsed] == ["zeta", "alpha"]


def test_an_unknown_field_is_an_error_not_a_comment() -> None:
    text = make().as_markdown().replace("**Gap:**", "**Gapp:**")
    with pytest.raises(ValueError, match="unknown field"):
        Precedent.from_markdown(text)


def test_a_key_with_a_comma_is_refused() -> None:
    with pytest.raises(ValueError, match="comma"):
        make(keys=["a,b"]).as_markdown()


def test_a_missing_section_is_an_error() -> None:
    text = make().as_markdown().replace("## Rationale", "## Reason")
    with pytest.raises(ValueError, match="rationale"):
        Precedent.from_markdown(text)


def test_an_unknown_status_names_the_good_ones() -> None:
    text = make().as_markdown().replace("**Status:** adjudicated", "**Status:** done")
    with pytest.raises(ValueError, match="proposed"):
        Precedent.from_markdown(text)


def test_a_duplicate_id_is_refused_on_load(tmp_path) -> None:
    path = tmp_path / "board.md"
    path.write_text(make(id="same").as_markdown() + make(id="same").as_markdown())
    store = PrecedentStore()
    with pytest.raises(ValueError, match="already exists"):
        store.load_markdown(path)


def test_an_unsafe_id_for_a_file_name_is_refused(tmp_path) -> None:
    store = PrecedentStore()
    store.append(make(id="../escape"))
    with pytest.raises(ValueError, match="file name"):
        store.save_files(tmp_path)


def test_the_hash_covers_every_field() -> None:
    base = make()
    assert base.hash() == make().hash()
    for changed in (
        make(id="prec-2"),
        make(gap_id="gap-2"),
        make(decision="allow"),
        make(rationale="other"),
        make(author=None),
        make(created_at=datetime.datetime(2026, 11, 3, 9, 30)),
        make(status=PrecedentStatus.CLOSED),
        make(rule_override=None),
        make(keys=[]),
        make(metadata={}),
    ):
        assert changed.hash() != base.hash(), changed
    # ... and the hash survives the round trip.
    assert Precedent.from_markdown(base.as_markdown()).hash() == base.hash()
