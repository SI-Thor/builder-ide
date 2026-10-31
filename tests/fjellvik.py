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
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.api import Actor, Asset, Task, WorkOrder
from core.justification import ProjectRecords
from core.recipe import Branch, RecipeEntry, RecipeVersion
from core.vocab import VocabularyEntry

AS_OF = "2026-10-31"

EAST_TASK = "task_8801"


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
                   created_by=Actor("core", "core"), protected=True),
            Branch(id="br_east", name="night-2026-10-30.east",
                   recipe="rcp_fjellvik", head="ver_0201", purpose="night",
                   created_by=Actor("character", "landscaper")),
            Branch(id="br_north", name="night-2026-08-01.north",
                   recipe="rcp_fjellvik", head="ver_0104", purpose="night"),
            Branch(id="br_wild", name="B-wild-wood", recipe="rcp_fjellvik",
                   head="ver_0188", purpose="rejected"),
        ],
        versions=[
            RecipeVersion(id="ver_0192", recipe="rcp_fjellvik", entries={
                "harbor.crates": RecipeEntry(
                    path="harbor.crates", kind="prop_set", assets=["ast_0207"],
                    origin="wo_14"),
                "structure.south_span": RecipeEntry(
                    path="structure.south_span", kind="structure"),
            }),
            RecipeVersion(id="ver_0201", recipe="rcp_fjellvik", entries={
                "forest.east_slope": RecipeEntry(
                    path="forest.east_slope", kind="terrain"),
                "props.felled_timber": RecipeEntry(
                    path="props.felled_timber", kind="prop_set",
                    assets=["ast_0231", "ast_0232"], origin="wo_15"),
            }),
            RecipeVersion(id="ver_0104", recipe="rcp_fjellvik", entries={
                "lights.north": RecipeEntry(
                    path="lights.north", kind="light", assets=["ast_0251"]),
            }),
            RecipeVersion(id="ver_0188", recipe="rcp_fjellvik", entries={
                "forest.wild_wood": RecipeEntry(
                    path="forest.wild_wood", kind="terrain",
                    assets=["ast_0244"]),
            }),
        ],
        work_orders=[
            WorkOrder(id="wo_14", at="2026-10-29T21:08:39Z",
                      filed_by=Actor("owner", "casey"),
                      title="Rope bridge, south span", state="kept",
                      serves="task_8701",
                      vocabulary_gap={"word": "bridge.rope"}),
            WorkOrder(id="wo_15", at="2026-10-30T22:41:02Z",
                      filed_by=Actor("character", "prop_maker"),
                      title="Felled-timber prop set", state="landed",
                      serves=EAST_TASK,
                      vocabulary_gap={"word": "props.timber.pile"}),
            WorkOrder(id="wo_11", at="2026-08-01T21:30:00Z",
                      filed_by=Actor("owner", "casey"),
                      title="North lantern fixtures", state="failed",
                      serves="task_8702"),
        ],
        vocabulary=[
            VocabularyEntry(word="bridge.rope", kind="structure",
                            owner_character="architect", status="active",
                            provenance={"origin": "wo_14"}),
            VocabularyEntry(word="props.timber.pile", kind="prop",
                            owner_character="prop_maker",
                            status="coming-soon", provenance={}),
            VocabularyEntry(word="props.harbor.crates", kind="prop",
                            owner_character="prop_maker", status="active",
                            provenance={"origin": "builtin"}),
            VocabularyEntry(word="material.wood.weathering", kind="material",
                            owner_character="prop_maker", status="active",
                            provenance={"origin": "builtin"}),
        ],
        assets=[
            Asset(id="ast_0207", kind="mesh"),      # crates, kept on main
            Asset(id="ast_0231", kind="mesh"),      # timber pile, east slope
            Asset(id="ast_0232", kind="texture"),   # timber maps, east slope
            Asset(id="ast_0251", kind="mesh"),      # north lantern (stale goal)
            Asset(id="ast_0244", kind="mesh"),      # wild wood (rejected branch)
            Asset(id="ast_0999", kind="mesh"),      # in the library, serves nothing
        ],
    )
