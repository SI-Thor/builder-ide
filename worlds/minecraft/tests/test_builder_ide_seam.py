"""The seam between the Minecraft world and builder-ide.

Two claims are tested here, and both are about the same seam:

1. **One ledger.** The world's rows land in builder-ide's log of record
   — the core store — with their type, their actor, their payload and
   their subject intact. The rows the world wrote *before* the move are
   still read.

2. **A skill and a capability are one record.** The world's 65 seeded
   skills are builder-ide's tiles, and the rows the world writes fold
   back into builder-ide's own tile library.

Run them:

    pytest worlds/minecraft/tests/test_builder_ide_seam.py -q
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORLD = HERE.parent
REPO = WORLD.parent.parent
for _part in (str(REPO), str(WORLD), str(WORLD / "reflex")):
    if _part not in sys.path:
        sys.path.insert(0, _part)

import pytest  # noqa: E402

from agent_world_reflex.library import build_skill  # noqa: E402
from agent_world_reflex.ledger import WorldLedger  # noqa: E402
from agent_world_reflex.models import (  # noqa: E402
    Outcome,
    PlayCost,
    PlayRecord,
    SkillAuthor,
)
from agent_world_reflex.tiles import (  # noqa: E402
    WorldVocabulary,
    scope_of,
    skill_to_tile,
)
from builder_ide.ledger import CoreStoreLedger, read_core_store_ledger  # noqa: E402
from builder_ide.skills import fold_world_library, load_skills, load_tiles  # noqa: E402
from core.artifacts import ArtifactStore  # noqa: E402
from core.records import EVENT_TYPES, Actor  # noqa: E402
from core.store import LedgerStore  # noqa: E402
from core.tiles.library import TileLibrary, fold_library  # noqa: E402
from core.tiles.models import Tile, TileStep  # noqa: E402

SEED_DIR = WORLD / "reflex" / "skills" / "seed"


# --------------------------------------------------------------- the fixtures


@pytest.fixture()
def store(tmp_path: Path) -> LedgerStore:
    """builder-ide's store of record, on a temporary file."""
    return LedgerStore(tmp_path / "core.db", ArtifactStore(tmp_path / "artifacts"))


@pytest.fixture()
def sample_skill():
    """A small skill, built through the world's own door."""
    return build_skill(
        family="builder.pillar",
        role="builder",
        title="raise a three block pillar",
        body="const here = position();\nawait place('cobblestone', here.x, here.y + 1, here.z);",
        author=SkillAuthor(model="seed", provider="seed", prompt_hash="seed"),
        kind="behaviour",
        preconditions=[],
        predict={"kind": "block_placed", "min": 1},
        provenance={"origin": "seed"},
    )


@pytest.fixture()
def sample_play(sample_skill):
    """A play of that skill, as the world records it."""
    return PlayRecord(
        id="play_abc123",
        at="2026-11-24T09:00:00Z",
        skill_id=sample_skill.id,
        skill_version=1,
        context={"bot": "Pebble", "role": "builder", "phase": "day", "health": 20},
        outcome=Outcome(result="win", measure="sealed_prediction", score=1.0),
        cost=PlayCost(wall_seconds=12.5),
        chooser="bandit",
        chooser_version="0.1",
        propensity=0.75,
        candidates=(sample_skill.id,),
    )


# ------------------------------------------------------------- goal 1: one ledger


def test_the_world_writes_into_the_core_store(store, sample_skill, sample_play):
    """The world's rows are in builder-ide's log of record."""
    ledger = WorldLedger(Path(store.db_path).parent / "world.db", ledger=CoreStoreLedger(store))
    ledger.authored(sample_skill)
    ledger.played(sample_play)

    rows = store.events_since(0)
    kinds = [row.type for row in rows]
    assert "tile.authored" in kinds
    assert "tile.played" in kinds


def test_the_subject_survives_the_core_store(store, sample_skill, sample_play):
    """The row can be found again by its id.

    The core store keeps a subject as two columns — ``entity_kind`` and
    ``entity_id`` — and drops every other key. The world's old subject
    shape (``{"skill": ..., "family": ...}``) would have lost the skill
    id silently, and the row would have come back with an empty subject.
    """
    ledger = WorldLedger(Path(store.db_path).parent / "world.db", ledger=CoreStoreLedger(store))
    ledger.authored(sample_skill)
    ledger.played(sample_play)

    found = store.events_for("tile", sample_skill.id)
    assert [row.type for row in found] == ["tile.authored", "tile.played"]
    assert all(row.subject["entity_kind"] == "tile" for row in found)
    assert all(row.subject["entity_id"] == sample_skill.id for row in found)


def test_the_judges_rows_land_in_the_same_log(store, sample_skill, sample_play):
    """The decision model's verdicts and the world's plays share a log.

    They are joined on the play's ``scope``, which is what the morning
    report's calibration card reads.
    """
    from core.records import Actor

    ledger = WorldLedger(Path(store.db_path).parent / "world.db", ledger=CoreStoreLedger(store))
    ledger.played(sample_play)
    ledger.append(
        type="judge.verdict",
        actor=Actor(kind="core", id="judge@d1", via="d1"),
        subject={"entity_kind": "judgment", "entity_id": "qh1"},
        payload={
            "judgments": [
                {"qid": "qh1", "answer": sample_skill.id, "confidence": 0.8}
            ]
        },
    )
    kinds = [row.type for row in store.events_since(0)]
    assert kinds == ["tile.played", "judge.verdict"]


def test_the_worlds_event_types_are_in_the_closed_set():
    """The core store refuses a type it does not know; the world's are known."""
    for kind in (
        "tile.authored",
        "tile.played",
        "tile.retired",
        "tile.retrained",
        "drift.yield",
        "judge.verdict",
    ):
        assert kind in EVENT_TYPES


def test_the_worlds_own_file_still_works(tmp_path, sample_skill, sample_play):
    """The file the world has always written is still written and read."""
    path = tmp_path / "world-ledger.sqlite3"
    ledger = WorldLedger(path)
    ledger.authored(sample_skill)
    ledger.played(sample_play)

    again = WorldLedger(path)
    assert again.authored_skills() == [sample_skill.id]
    records = again.plays()
    assert [r.skill_id for r in records] == [sample_skill.id]
    assert records[0].outcome.result == "win"


def test_a_row_written_before_the_move_still_reads(tmp_path, sample_skill, sample_play):
    """The old shape — the world's own subject and payload — still reads.

    This is the file the Thor has been writing since the world was its
    own repository: the subject is ``{"skill": ..., "family": ...}`` and
    the payload is the world's own play record. Nothing migrates it; it
    is simply still readable.
    """
    from core.night.ledger import SQLiteLedger

    path = tmp_path / "old-world-ledger.sqlite3"
    old = SQLiteLedger(path)
    old.append(
        type="tile.played",
        actor=Actor(kind="character", id="Pebble", via="reflex"),
        subject={"skill": sample_skill.id, "family": sample_skill.family},
        payload=sample_play.model_dump(mode="json"),
    )
    old.close()

    again = WorldLedger(path)
    records = again.plays()
    assert [r.skill_id for r in records] == [sample_skill.id]
    assert records[0].context["bot"] == "Pebble"


def test_the_core_store_reads_back_as_a_ledger(store, sample_skill, sample_play):
    """The "why" door's row shape, read off the core store.

    ``core.rewind`` explains a row; it reads a ledger. The core store's
    own schema holds the subject in two columns, so the reader here
    rejoins them into the row the rewind seat takes.
    """
    ledger = WorldLedger(Path(store.db_path).parent / "world.db", ledger=CoreStoreLedger(store))
    ledger.played(sample_play)

    read = read_core_store_ledger(store.db_path)
    assert [row.kind for row in read.rows] == ["tile.played"]
    row = read.rows[0]
    assert row.entity_id == sample_skill.id
    assert row.agent == "Pebble"
    assert row.verdict == "win"


def test_the_gyms_reader_reads_the_old_file(tmp_path, sample_play):
    """The gym's reader still reads the file the world wrote before.

    The gym reads the world's plays with their own keys (``skill_id``),
    and those keys are still written — the core's keys were added beside
    them, not in place of them.
    """
    pytest.importorskip("gymnasium")
    sys.path.insert(0, str(WORLD / "gym"))
    from agent_world_gym.ledger import WorldLedgerReader

    path = tmp_path / "world-ledger.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, at TEXT,"
        " actor TEXT, type TEXT, subject TEXT, payload TEXT, artifact TEXT)"
    )
    connection.execute(
        "INSERT INTO audit (id, at, actor, type, subject, payload) VALUES (?,?,?,?,?,?)",
        (
            "aud_0001",
            "2026-11-24T09:00:00Z",
            json.dumps({"kind": "character", "id": "Pebble"}),
            "tile.played",
            json.dumps({"skill": sample_play.skill_id, "family": ""}),
            json.dumps(sample_play.model_dump(mode="json")),
        ),
    )
    connection.commit()
    connection.close()

    plays = WorldLedgerReader(path).plays()
    assert [p.skill_id for p in plays] == [sample_play.skill_id]
    assert plays[0].bot == "Pebble"


def test_the_gyms_reader_reads_the_core_store(store, sample_skill, sample_play):
    """And it reads the core store's log too — the one ledger, two readers."""
    pytest.importorskip("gymnasium")
    sys.path.insert(0, str(WORLD / "gym"))
    from agent_world_gym.ledger import WorldLedgerReader

    ledger = WorldLedger(Path(store.db_path).parent / "world.db", ledger=CoreStoreLedger(store))
    ledger.played(sample_play)

    plays = WorldLedgerReader(store.db_path).plays()
    assert [p.skill_id for p in plays] == [sample_skill.id]
    assert plays[0].result == "win"


# ------------------------------------------------- goal 2: a skill is a capability


def test_every_seeded_skill_is_a_tile():
    """All 65 of the world's starting skills are builder-ide's tiles."""
    skills = load_skills(SEED_DIR)
    assert len(skills) == 65
    tiles = load_tiles(SEED_DIR)
    assert len(tiles) == 65


def test_the_tiles_id_is_the_skills_id():
    """One record, one id — which is what lets the judge join to the play."""
    for skill in load_skills(SEED_DIR):
        tile = skill_to_tile(skill)
        assert tile.id == skill.id
        assert tile.family == skill.family
        assert tile.title == skill.title
        assert tile.kind == skill.kind


def test_the_tiles_words_are_the_skills_api():
    """The tile's words are exactly the world's words the skill calls."""
    for skill in load_skills(SEED_DIR):
        tile = skill_to_tile(skill)
        assert tile.words == tuple(skill.api)
        assert tile.words, f"{skill.id} calls no word of the vocabulary"


def test_the_mapping_is_deterministic():
    """The same script is the same tile, whoever asks."""
    first = load_tiles(SEED_DIR)
    second = load_tiles(SEED_DIR)
    assert [t.id for t in first] == [t.id for t in second]
    assert [t.content_hash for t in first] == [t.content_hash for t in second]


def test_the_worlds_rows_fold_into_builders_ide_library(store, sample_skill):
    """The round trip: the world's rows read back as builder-ide's tiles.

    ``core.tiles.library.fold_library`` is builder-ide's own fold. It
    reads the rows the world wrote and gives back a library — which is
    the statement that a skill and a capability are one record.
    """
    ledger = WorldLedger(Path(store.db_path).parent / "world.db", ledger=CoreStoreLedger(store))
    ledger.authored(sample_skill)

    events = store.events_since(0, types=["tile.authored"])
    library = fold_library(events, registry=WorldVocabulary())
    tile = library.get(sample_skill.id)
    assert tile is not None
    assert tile.family == sample_skill.family
    assert tile.title == sample_skill.title
    assert tile.words == tuple(sample_skill.api)
    assert tile.provenance["skill_id"] == sample_skill.id


def test_the_whole_seed_library_folds_into_a_library():
    """Every seeded skill survives the fold.

    The seed directory holds **65 files and 56 skills**: five of the
    scripts are written more than once (the ``g3-``/``g7-``/``g11-``
    generations of the same body), and a skill is content addressed, so
    the same script written twice is the same skill. That is the world's
    own rule, not a collapse this seam invented — the world's ``seed``
    command admits the same 56.
    """
    skills = load_skills(SEED_DIR)
    tiles = load_tiles(SEED_DIR)
    distinct = {skill.id for skill in skills}
    assert len(skills) == 65
    assert len(distinct) == 56
    assert len(tiles) == 65  # the loader reads every file
    assert len({tile.id for tile in tiles}) == 56  # content addressing

    library = TileLibrary(registry=WorldVocabulary(), tiles=tiles)
    assert len(library.tiles()) == len(distinct)
    assert len(library.active()) == len(distinct)
    assert set(library.families()) == {s.family for s in skills}


def test_the_tile_door_refuses_a_word_the_world_does_not_have():
    """The two doors are one door: an unknown word is refused, not repaired."""
    from core.tiles.models import TileRefusal

    tile = Tile(
        id="skill_nope",
        family="builder.pillar",
        kind="behaviour",
        title="reach for a word the world does not have",
        steps=(TileStep(word="teleport", path="teleport"),),
        author=sample_author(),
    )
    library = TileLibrary(registry=WorldVocabulary())
    with pytest.raises(TileRefusal) as caught:
        library.add(tile)
    assert caught.value.reason == "word_unknown"


def sample_author():
    from core.tiles.models import TileAuthor
    from core.canon import content_hash

    return TileAuthor(
        model="seed",
        provider="seed",
        prompt_hash=content_hash({"a": "b"}),
    )


def test_a_seed_skills_prompt_hash_becomes_a_content_hash(sample_skill):
    """A seeded skill has no prompt, so the hash is derived from the script.

    The seed files say ``prompt_hash: "seed"``, which is not a hash.
    Inventing one would be a fabrication, so the script's own hash is
    used and the derivation is recorded.
    """
    from core.canon import is_content_hash

    tile = skill_to_tile(sample_skill)
    assert is_content_hash(tile.author.prompt_hash)
    assert tile.provenance["prompt_hash_origin"] == "derived_from_skill_body"


def test_a_real_prompt_hash_is_kept():
    """A skill a model wrote keeps that model's prompt hash."""
    from core.canon import content_hash, is_content_hash

    prompt_hash = content_hash({"prompt": "raise a pillar"})
    skill = build_skill(
        family="builder.pillar",
        role="builder",
        title="raise a three block pillar",
        body="const here = position();\nawait place('cobblestone', here.x, here.y + 1, here.z);",
        author=SkillAuthor(model="gpt-oss-120b", provider="groq", prompt_hash=prompt_hash),
        predict={"kind": "block_placed", "min": 1},
    )
    tile = skill_to_tile(skill)
    assert tile.author.prompt_hash == prompt_hash
    assert tile.provenance["prompt_hash_origin"] == "skill"


def test_the_play_row_carries_the_judges_join_key(sample_play):
    """The play's ``scope`` is the world's context bucket.

    It is the key builder-ide's judge calibration pairs a judgment with
    the play it answered, so the morning report can read the Minecraft
    builders' calibration.
    """
    from agent_world_reflex.tiles import played_payload

    payload = played_payload(sample_play)
    assert payload["scope"] == scope_of(sample_play.context)
    assert payload["scope"] == "role=builder|phase=day"
    assert payload["tile_id"] == sample_play.skill_id
    assert payload["skill_id"] == sample_play.skill_id


def test_the_worlds_play_rows_read_back_as_builder_ide_plays(store, sample_skill, sample_play):
    """builder-ide's own play fold reads the world's rows."""
    from core.tiles.plays import fold_plays

    ledger = WorldLedger(Path(store.db_path).parent / "world.db", ledger=CoreStoreLedger(store))
    ledger.played(sample_play)

    records = fold_plays(store.events_since(0, types=["tile.played"]))
    assert len(records) == 1
    assert records[0].tile_id == sample_skill.id
    assert records[0].outcome.result == "win"
    assert records[0].scope == "role=builder|phase=day"
