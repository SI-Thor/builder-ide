"""The taste ledger (§1.7).

Three rules, all of them load-bearing:

  * **One writer.** A taste note is written by the owner's verdict event and
    nothing else. The night's automated keeps are verdict writes, never
    taste writes — otherwise the taste model trains on its own output and
    the sealed bets become unfalsifiable.
  * **Author-scoped, forever.** Casey's rows and Magnus's rows never merge.
    Magnus's rows are never in a slice a model reads.
  * **Erase is a mechanism, not a promise.** One owner action, one
    transaction: redact the author's payloads and append the compensating
    event; the fold then excludes them from every projection.
"""
from __future__ import annotations

import pytest

from core.errors import NotFound, Refused
from core.events import Actor, core_actor, owner_actor
from core.svc.taste import TasteService


def note(core, author="casey", actor=None, **overrides):
    payload = {
        "subject": {"node_id": "span_south", "param_path": "material", "value": "tarred"},
        "artifact_ref": "br_main@ver_1",
        "verdict": "keep",
        "reason_code": "too_busy",
    }
    payload.update(overrides)
    return TasteService(core).append_note(actor or owner_actor(author), author=author, **payload)


# ------------------------------------------------------------- one writer

def test_only_the_owner_writes_taste_notes(core):
    """The critic never sees the taste ledger, and the night's automated
    keeps are verdict writes, not taste writes."""
    with pytest.raises(Refused) as e:
        TasteService(core).append_note(
            core_actor(), author="casey", subject={"node_id": "n"},
            artifact_ref="br@ver", verdict="keep", reason_code="too_busy")
    assert "single writer" in e.value.message


def test_a_reason_code_outside_the_closed_dozen_is_refused(core):
    with pytest.raises(Refused) as e:
        note(core, reason_code="felt_wrong")
    assert "closed dozen" in e.value.message


def test_the_closed_dozen_is_exactly_twelve(core):
    from core.svc.taste import REASON_CODES

    assert len(REASON_CODES) == 12
    assert "too_busy" in REASON_CODES and "no_focus" in REASON_CODES


def test_a_note_needs_an_artifact_reference(core):
    """A taste note is a claim about a thing, never a conversation."""
    with pytest.raises(Refused) as e:
        note(core, artifact_ref="")
    assert "never a conversation" in e.value.message


def test_a_note_carries_the_author_and_the_reason(core):
    n = note(core, author="casey")
    assert n.author == "casey"
    assert n.reason_code == "too_busy"
    assert n.status == "active"


# ------------------------------------------------------------- author scoping

def test_the_authors_rows_never_merge(core):
    note(core, author="casey")
    note(core, author="magnus", actor=owner_actor("magnus"))
    svc = TasteService(core)
    assert len(svc.list("casey")) == 1
    assert len(svc.list("magnus")) == 1


def test_a_kids_rows_are_never_in_a_slice(core):
    """§7.6: Magnus's rows never go into a model prompt."""
    note(core, author="casey")
    note(core, author="magnus", actor=owner_actor("magnus"))
    svc = TasteService(core)
    assert len(svc.list()) == 2
    assert len(svc.list(slice_for_model=True)) == 1
    assert svc.list(slice_for_model=True)[0]["author"] == "casey"


def test_a_kids_keeps_are_pending_and_inert_until_ratified(core):
    """§1.7: Magnus's first keeps are pending_ratification and INERT."""
    n = note(core, author="magnus", actor=owner_actor("magnus"))
    assert n.status == "pending_ratification"
    svc = TasteService(core)
    assert len(svc.list("magnus", include_pending=False)) == 0
    assert len(svc.list("magnus")) == 1


def test_ratifying_a_kid_activates_their_pending_rows(core):
    note(core, author="magnus", actor=owner_actor("magnus"))
    out = TasteService(core).ratify("magnus", owner_actor("casey"))
    assert out["ratified"] is True
    svc = TasteService(core)
    assert len(svc.list("magnus", include_pending=False)) == 1
    assert svc.list("magnus")[0]["status"] == "active"


def test_ratifying_twice_is_harmless(core):
    svc = TasteService(core)
    svc.ratify("magnus", owner_actor("casey"), idem_key="r1")
    again = svc.ratify("magnus", owner_actor("casey"), idem_key="r2")
    assert again["already"] is True
    # and the same key replays the original result
    replay = svc.ratify("magnus", owner_actor("casey"), idem_key="r1")
    assert replay["ratified"] is True


def test_ratifying_is_an_owner_action(core):
    with pytest.raises(Refused):
        TasteService(core).ratify("magnus", core_actor())


# ------------------------------------------------------------- export

def test_the_export_is_one_bundle_of_the_authors_rows(core):
    note(core, author="casey")
    note(core, author="casey", reason_code="too_dark")
    out = TasteService(core).export("casey")
    assert out["author"] == "casey"
    assert len(out["rows"]) == 2
    assert out["reason_codes"] == {"too_busy": 1, "too_dark": 1}
    assert out["artifact_refs"] == ["br_main@ver_1"]


def test_exporting_an_author_with_no_rows_is_a_404(core):
    with pytest.raises(NotFound):
        TasteService(core).export("nobody")


# ------------------------------------------------------------- erase

def test_erasing_redacts_the_rows_and_appends_the_compensation(core):
    """One transaction: the author's payloads are redacted and a
    taste.erased event says so."""
    note(core, author="magnus", actor=owner_actor("magnus"))
    assert len(TasteService(core).list("magnus")) == 1

    out = TasteService(core).erase("magnus", owner_actor("casey"))
    assert out["erased"] is True
    assert TasteService(core).list("magnus") == []

    erased = core.store.events_since(0, types=["taste.erased"])
    assert len(erased) == 1
    # the compensation names who was erased and how much
    assert erased[0].payload["author"] == "magnus"
    assert erased[0].payload["redacted_rows"] == 1


def test_the_erased_payloads_are_redacted_in_place(core):
    """§1.0's one immutability exception: the payload is rewritten, not
    deleted — the log stays append-only in shape."""
    note(core, author="magnus", actor=owner_actor("magnus"))
    TasteService(core).erase("magnus", owner_actor("casey"))
    for ev in core.store.events_since(0, types=["taste.note.appended"]):
        assert ev.payload.get("redacted") is True
        assert "subject" not in ev.payload.get("row", {})


def test_erasing_is_idempotent(core):
    svc = TasteService(core)
    note(core, author="magnus", actor=owner_actor("magnus"))
    svc.erase("magnus", owner_actor("casey"), idem_key="e1")
    again = svc.erase("magnus", owner_actor("casey"), idem_key="e1")
    assert again["erased"] is True
    assert len(core.store.events_since(0, types=["taste.erased"])) == 1


def test_erasing_leaves_the_other_authors_rows_alone(core):
    note(core, author="casey")
    note(core, author="magnus", actor=owner_actor("magnus"))
    TasteService(core).erase("magnus", owner_actor("casey"))
    svc = TasteService(core)
    assert len(svc.list("casey")) == 1
    assert svc.list("magnus") == []


def test_erasing_is_an_owner_action(core):
    with pytest.raises(Refused):
        TasteService(core).erase("magnus", core_actor())


def test_the_projection_rebuild_also_excludes_the_erased_rows(core):
    """The fold excludes a redacted note, so a rebuild cannot resurrect it."""
    from core.fold import fold_all

    note(core, author="magnus", actor=owner_actor("magnus"))
    TasteService(core).erase("magnus", owner_actor("casey"))
    shadow = fold_all(core.store.events_since(0), core.store.ctx)
    assert shadow.scan("taste_notes") == []
