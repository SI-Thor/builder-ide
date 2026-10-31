"""The Fjellvik morning fixture — spec v2's own examples, assembled.

State: the morning of 2026-10-31, after the night of 2026-10-30.

- task_8701 "Harbor hamlet, seed 4471" — kept yesterday; its outcome is
  ``br_main`` (protected, purpose main), carrying the crates entry that
  consumes ast_0207. WO-14 (rope bridge, kept) promoted ``bridge.rope``.
- task_8801 "Forest the east slope, keep the oak" — ran last night
  (br_east); its timber props consume ast_0231/ast_0232; WO-15 is landed
  with ``props.timber.pile`` pinned coming-soon. THE GOAL THIS FIXTURE
  EXISTS TO KILL.
- task_8702 "North lantern line" — slated 2026-08-01 with review-by
  2026-08-15: stale at any as_of past the 30-day grace. Its lantern asset
  must already read questionable. WO-11 under it failed terminally.
- br_wild "B-wild-wood" — a rejected morning option (retained, visitable);
  its wild-wood asset is the certified-dead arm.

Shared by tests/test_justification.py and tests/test_morning_report.py.

The records here are the *real* ones — ``core.models``' Task/Branch/
WorkOrder/Asset, the recipe store's RecipeVersion/RecipeEntry and the
vocabulary's VocabularyEntry. The why-kernel seat's stub packages are gone,
so the fixture carries the fields those stubs invented and the spec does
not name: ``Task.slated_at``/``Task.review_by`` (the goal horizon) and
``WorkOrder.serves`` (the order's goal). See INTEGRATION.md, decisions 2
and 4.
"""

from __future__ import annotations

from core.recipe.models import RecipeEntry, RecipeVersion
from core.events import Actor
from core.models import Asset, Branch, FileRef, Licence, Provenance, Task, WorkOrder
from core.models import Origin
from core.vocab.models import VocabularyEntry

from core.justification import ProjectRecords

AS_OF = "2026-10-31"

EAST_TASK = "task_8801"


def _asset(asset_id: str, kind: str, licence: str = "CC0-1.0") -> Asset:
    """A library asset with the files/provenance/licence §1.6 requires."""
    return Asset(
        id=asset_id,
        kind=kind,
        files=[FileRef(role=kind, path=f"library/{asset_id}.glb",
                       sha256=asset_id * 8, bytes=1024)],
        provenance=Provenance(source="library"),
        licence=Licence(spdx=licence, commercial_ok=True),
    )


def _version(version_id: str, actor: Actor | None = None) -> RecipeVersion:
    """A committed version. Its entries ride in ``version_entries``: §1.0
    keeps recipe documents as content-addressed blobs, so a version record
    carries provenance, not the materialized document."""
    return RecipeVersion(
        id=version_id,
        recipe="rcp_fjellvik",
        parent=None,
        edit=None,
        root_hash=version_id * 8,
        at="2026-10-30T06:00:00Z",
        actor=actor or Actor(kind="core", id="core"),
    )


def fjellvik(east_state: str = "running") -> ProjectRecords:
    """The morning snapshot; ``east_state`` lets the caller kill the goal."""
    return ProjectRecords(
        tasks=[
            Task(id="task_8701", author="casey", owner_character="architect",
                 intention="Harbor hamlet, seed 4471", state="kept",
                 branches=["br_main"], slated_at="2026-10-29"),
            Task(id=EAST_TASK, author="casey", owner_character="landscaper",
                 intention="Forest the east slope, keep the oak",
                 state=east_state, branches=["br_east"],
                 slated_at="2026-10-30"),
            Task(id="task_8702", author="casey", owner_character="architect",
                 intention="North lantern line", state="slated",
                 branches=["br_north"], slated_at="2026-08-01",
                 review_by="2026-08-15"),
        ],
        branches=[
            Branch(id="br_main", name="main", recipe="rcp_fjellvik",
                   head="ver_0192", purpose="main",
                   created_by=Actor(kind="core", id="core"), protected=True),
            Branch(id="br_east", name="night-2026-10-30.east",
                   recipe="rcp_fjellvik", head="ver_0201", purpose="night",
                   created_by=Actor(kind="character", id="landscaper")),
            Branch(id="br_north", name="night-2026-08-01.north",
                   recipe="rcp_fjellvik", head="ver_0104", purpose="night"),
            Branch(id="br_wild", name="B-wild-wood", recipe="rcp_fjellvik",
                   head="ver_0188", purpose="rejected"),
        ],
        versions=[
            _version("ver_0192"),
            _version("ver_0201"),
            _version("ver_0104"),
            _version("ver_0188"),
        ],
        version_entries={
            "ver_0192": {
                "harbor.crates": RecipeEntry(
                    path="harbor.crates", kind="prop_set", assets=["ast_0207"],
                    origin="wo_14"),
                "structure.south_span": RecipeEntry(
                    path="structure.south_span", kind="structure"),
            },
            "ver_0201": {
                "forest.east_slope": RecipeEntry(
                    path="forest.east_slope", kind="terrain"),
                "props.felled_timber": RecipeEntry(
                    path="props.felled_timber", kind="prop_set",
                    assets=["ast_0231", "ast_0232"], origin="wo_15"),
            },
            "ver_0104": {
                "lights.north": RecipeEntry(
                    path="lights.north", kind="light", assets=["ast_0251"]),
            },
            "ver_0188": {
                "forest.wild_wood": RecipeEntry(
                    path="forest.wild_wood", kind="terrain",
                    assets=["ast_0244"]),
            },
        },
        work_orders=[
            WorkOrder(id="wo_14", at="2026-10-29T21:08:39Z",
                      filed_by=Actor(kind="owner", id="casey"),
                      origin=Origin(channel="voice", packet="pk_14"),
                      title="Rope bridge, south span", state="kept",
                      serves="task_8701",
                      vocabulary_gap={"word": "bridge.rope"}),
            WorkOrder(id="wo_15", at="2026-10-30T22:41:02Z",
                      filed_by=Actor(kind="character", id="prop_maker"),
                      origin=Origin(channel="character", packet="pk_15"),
                      title="Felled-timber prop set", state="landed",
                      serves=EAST_TASK,
                      vocabulary_gap={"word": "props.timber.pile"}),
            WorkOrder(id="wo_11", at="2026-08-01T21:30:00Z",
                      filed_by=Actor(kind="owner", id="casey"),
                      origin=Origin(channel="voice", packet="pk_11"),
                      title="North lantern fixtures", state="failed",
                      serves="task_8702"),
        ],
        vocabulary=[
            VocabularyEntry(word="bridge.rope", kind="structure",
                            owner_character="architect", status="active",
                            params={}, provenance={"origin": "wo_14"}),
            # Requested by WO-15 but never delivered: the word exists, pinned
            # coming-soon, and no order *promoted* it. Its origin says
            # "requested" so the graph does not claim a promotion that never
            # happened; the order's vocabulary_gap still wires it.
            VocabularyEntry(word="props.timber.pile", kind="prop",
                            owner_character="prop_maker",
                            status="coming-soon", params={},
                            provenance={"origin": "requested"}),
            VocabularyEntry(word="props.harbor.crates", kind="prop",
                            owner_character="prop_maker", status="active",
                            params={}, provenance={"origin": "builtin"}),
            VocabularyEntry(word="material.wood.weathering", kind="material",
                            owner_character="prop_maker", status="active",
                            params={}, provenance={"origin": "builtin"}),
        ],
        assets=[
            _asset("ast_0207", "mesh"),      # crates, kept on main
            _asset("ast_0231", "mesh"),      # timber pile, east slope
            _asset("ast_0232", "texture"),   # timber maps, east slope
            _asset("ast_0251", "mesh"),      # north lantern (stale goal)
            _asset("ast_0244", "mesh"),      # wild wood (rejected branch)
            _asset("ast_0999", "mesh"),      # in the library, serves nothing
        ],
    )
