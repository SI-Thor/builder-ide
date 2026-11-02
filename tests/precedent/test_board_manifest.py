"""The BoardManifest: a derived scope, a content fingerprint, a
markdown file a human can edit.
"""

from __future__ import annotations

import datetime

from core.precedent import (
    BoardManifest,
    Precedent,
    PrecedentStatus,
    PrecedentStore,
    seed_rules,
    seed_store,
)
from core.precedent.manifest import parse_manifest

STAMP = datetime.datetime(2026, 11, 2, 9, 0)


def board() -> PrecedentStore:
    store = seed_store()
    store.append(
        Precedent(
            id="prec-upload",
            gap_id="gap-upload",
            decision="ask",
            rationale="needs the scan first",
            author="casey",
            created_at=STAMP,
            status=PrecedentStatus.ADJUDICATED,
            keys=["proposal.upload"],
        )
    )
    store.append(
        Precedent(
            id="prec-dropped",
            gap_id="gap-dropped",
            decision="deny",
            rationale="we abandoned this branch",
            author="casey",
            created_at=STAMP,
            status=PrecedentStatus.ABANDONED,
            keys=["proposal.dropped"],
        )
    )
    return store


def test_the_manifest_projects_the_board() -> None:
    manifest = BoardManifest.from_store(
        board(), rules=seed_rules(), scope_boundary="the spawn island"
    )
    # three active cases (the abandoned one counts toward the version
    # but not toward the board's work)
    assert manifest.version == 4
    assert manifest.precedent_ids == [
        "prec-upload",
        "seed-human-request",
        "seed-kid-apply",
    ]
    keys = manifest.ratified_keys()
    assert "proposal.upload" in keys
    assert "recipe.apply" in keys
    assert "world.human_request" in keys
    assert "ladder.p1.commit_main" in keys
    assert "nogrief.break_human_block" in keys
    assert "proposal.dropped" not in keys
    assert manifest.scope_boundary == "the spawn island"
    assert manifest.rule_keys == sorted(manifest.rule_keys)


def test_the_fingerprint_is_content_not_clock() -> None:
    one = BoardManifest(version=1, precedent_ids=["a"], rule_keys=["k"], scope_boundary=None)
    same_clock = BoardManifest(
        version=1,
        precedent_ids=["a"],
        rule_keys=["k"],
        scope_boundary=None,
        created_at=datetime.datetime(2030, 1, 1),
    )
    assert one.fingerprint() == same_clock.fingerprint()
    assert one.fingerprint().startswith("manifest/1:")
    # ... and every kind of content moves it.
    for changed in (
        BoardManifest(version=2, precedent_ids=["a"], rule_keys=["k"]),
        BoardManifest(version=1, precedent_ids=["b"], rule_keys=["k"]),
        BoardManifest(version=1, precedent_ids=["a"], rule_keys=["l"]),
        BoardManifest(version=1, precedent_ids=["a"], rule_keys=["k"], scope_boundary="x"),
    ):
        assert changed.fingerprint() != one.fingerprint()


def test_the_manifest_round_trips_through_markdown(tmp_path) -> None:
    manifest = BoardManifest.from_store(board(), rules=seed_rules())
    path = tmp_path / "manifest.md"
    manifest.save(path)
    back = BoardManifest.load(path)
    assert back == manifest
    assert back.fingerprint() == manifest.fingerprint()
    # ... and the file is readable markdown.
    text = path.read_text(encoding="utf-8")
    assert text.startswith(f"# Board Manifest {manifest.fingerprint()}\n")
    assert "## Scope keys (" in text


def test_a_human_edit_reaches_the_fingerprint(tmp_path) -> None:
    manifest = BoardManifest.from_store(board(), rules=seed_rules())
    path = tmp_path / "manifest.md"
    manifest.save(path)
    text = path.read_text(encoding="utf-8")
    # widen the ratified scope by hand, the way a human with the
    # authority would: one more key on the list.
    text = text.replace("- recipe.apply\n", "- recipe.apply\n- recipe.squash\n")
    path.write_text(text, encoding="utf-8")

    widened = BoardManifest.load(path)
    assert "recipe.squash" in widened.ratified_keys()
    assert widened.fingerprint() != manifest.fingerprint()


def test_unrestricted_boundary_round_trips_as_none(tmp_path) -> None:
    manifest = BoardManifest(version=1, precedent_ids=[], rule_keys=[])
    path = tmp_path / "manifest.md"
    manifest.save(path)
    back = BoardManifest.load(path)
    assert back.scope_boundary is None
    assert back.fingerprint() == manifest.fingerprint()


def test_a_malformed_version_is_an_error() -> None:
    text = (
        "# Board Manifest manifest/1:abc\n"
        "- **Version:** not-a-number\n"
        "- **Created:** 2026-11-02T09:00:00\n"
    )
    try:
        parse_manifest(text)
    except ValueError:
        return
    raise AssertionError("a non-integer version must not parse")
