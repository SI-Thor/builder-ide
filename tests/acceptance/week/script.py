"""The seven nights, as scripted facts.

This is the week the driver plays — one `NightSpec` per evening→night→morning
cycle. Everything a night *does* is here as data; everything the night
*means* (the melt, the gates, the rails, the budget) is the seats' code and
the spine's. The script fixes only what the mechanisms cannot decide for
themselves: which word the builder called with which params, which bets it
sealed, what the scripted critic found, what the night's flaw was, and how
much the night would have asked had the queue not been allowed to cut.

The shape follows gaps §1.9's first-week table (`docs/research/gaps.md`):
questions 6 → 0, guesses → claims per code as denominators pass two, one
night that would ask too much (cut at the queue), and evening seven
arriving with the ledger the corrected return line needs.

Two melt tracks run side by side, and the script keeps them separable on
purpose (the per-builder rule is load-bearing):

* the **asked track** — the eight bank codes, fed by the Companion's
  two-chip questions; they melt the *Companion* (a row written by
  answering a question is attributed to the builder that asked it);
* the **unprompted track** — the four codes the bank does not cover
  (`too_busy`, `too_messy`, `too_dark`, `no_focus`), fed by the owner's
  unprompted morning verdicts; those rows carry no attribution, so they
  melt *every* builder — including the prop-maker, whose sealed taste
  bets therefore ride this track: night 1 a guess at zero observations,
  night 2 a guess at one (the true count in the basis), night 3 the first
  real claim at two — G §1.9's own arc, on one code (`too_busy`), with the
  other flaw codes following a night later each.

Dates follow the continuity note (G §0): night one is Saturday 2026-10-24,
evening seven is Friday 2026-10-30 — the day `ux-day` describes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bet:
    """One sealed bet the builder makes in the night.

    `code` is the taste axis (a reason code) or the world axis (a claim
    type); the confidence is never chosen here — the cold-start sealer
    computes it from the ledger (decision 13a), and the driver asserts it
    matches the gate's decision.
    """

    axis: str                 # "taste" | "world"
    code: str                 # taste: a reason code · world: a claim type
    claim: str


@dataclass(frozen=True)
class NightEdit:
    """The night's one recipe edit: a typed vocabulary call on the night branch."""

    word: str                 # e.g. "props.harbor.crates"
    node: str                 # node id in the registry
    params: dict
    value: str                # the label the owner's table judges (rule 1)
    message: str


@dataclass(frozen=True)
class WorkOrderSpec:
    """The evening's one honest work order (two-line estimate, by construction)."""

    title: str
    goal: str
    utterance: str
    value: str                # what the landed order carries; rule 1 rules on it
    estimate: dict            # the two halves (X R16: both lines, always)
    promote: str | None = None          # word the keep promotes (the growth beat)
    promote_props: dict | None = None   # params the promoted word gains (v2)


@dataclass(frozen=True)
class NightSpec:
    n: int
    date: str
    edit: NightEdit
    taste_bets: tuple[Bet, ...]
    world_bet: Bet
    critic: str               # the scripted critic's word: keep | hold
    flaw: str                 # the night's flaw class (rule 4; a non-bank code)
    wo: WorkOrderSpec
    # the night's questions-to-the-owner load, before the queue's rules bite
    blocking_questions: tuple[str, ...] = ()
    fourth_blocking: bool = False   # the dam: the 4th parks the task (§3.2.6)
    ask_cards: int = 0              # candidate decision cards for the morning
    parked_question: str | None = None  # a plain parked question (no dam beat)
    assumes: bool = False           # record assumptions instead of parking


def _bet(axis: str, code: str, claim: str) -> Bet:
    return Bet(axis=axis, code=code, claim=claim)


_WO_ESTIMATE = {
    "build_verify": {"gpu_minutes": 5.0, "wall_minutes": 40.0},
    "generate_test": {"gpu_minutes": 15.0, "wall_minutes": 50.0},
}

#: The params the two promoted words gain (M1's crates-v2 shape; the week's
#: second growth beat is racks v2 on night 7).
_CRATES_V2_PROPS = {
    "lids": {"type": "boolean", "default": False},
    "handles": {"type": "string", "enum": ["none", "rope"], "default": "none"},
}
_RACKS_V2_PROPS = {"lids": {"type": "boolean", "default": False}}

NIGHTS: tuple[NightSpec, ...] = (
    NightSpec(
        n=1, date="2026-10-24",
        edit=NightEdit(
            word="props.harbor.crates", node="crates",
            params={"count": 12, "style": "weathered", "from_library": 6, "seed": 101},
            value="weathered", message="night 1: crate row on the quay, weathered",
        ),
        taste_bets=(
            _bet("taste", "too_busy",
                 "You keep the busy quay row over a shipshape one"),
            _bet("taste", "wrong_material",
                 "You keep rope-handled crates, not plain ones"),
        ),
        world_bet=_bet("world", "material_read",
                       "Weathered timber reads as weathered on all 12 crates"),
        critic="keep",
        flaw="too_busy",
        wo=WorkOrderSpec(
            title="Crates v2: lids and rope handles",
            goal=("props.harbor.crates gains {lids: bool, handles: enum[none, rope]} "
                  "with a deterministic rebuild and a watertight geometry check"),
            utterance="Computer — the crates gain lids and rope handles",
            value="rope-handled",
            estimate=_WO_ESTIMATE,
            promote="props.harbor.crates",
            promote_props=_CRATES_V2_PROPS,
        ),
        # the night that would ask too much: 3 blocking questions (the dam
        # refuses the fourth), plus 12 candidate decision cards the queue
        # must cut to the morning's budget of 10 (G §4.3)
        blocking_questions=(
            "The jetty lantern glass: warm amber, or clear?",
            "The second shed stands on stone, or on piles?",
            "The crate row runs north–south, or along the quay edge?",
        ),
        fourth_blocking=True,
        ask_cards=12,
    ),
    NightSpec(
        n=2, date="2026-10-25",
        edit=NightEdit(
            word="props.harbor.crates", node="crates",
            params={"count": 12, "style": "weathered", "from_library": 8, "seed": 102},
            value="weathered", message="night 2: more library crates in the row",
        ),
        taste_bets=(
            _bet("taste", "too_busy",
                 "You keep the denser row — eight library crates, not six"),
        ),
        world_bet=_bet("world", "material_read",
                       "The library crates blend with the generated ones at rung 2"),
        critic="keep",
        flaw="too_busy",
        wo=WorkOrderSpec(
            title="Racks: deeper bays for the nets",
            goal="props.harbor.racks length_m 3.0 → 4.5, same count",
            utterance="Computer — make the racks deeper",
            value="deep-racks",
            estimate=_WO_ESTIMATE,
        ),
        parked_question="The net racks face the water, or the shed wall?",
    ),
    NightSpec(
        n=3, date="2026-10-26",
        edit=NightEdit(
            word="material.wood.weathering", node="weathering",
            params={"wear": 4, "tone": "gray"},
            value="gray", message="night 3: gray weathering at high wear",
        ),
        taste_bets=(
            _bet("taste", "too_busy",
                 "You keep the grayer, older-looking wood over fresh-toned"),
        ),
        world_bet=_bet("world", "era_read",
                       "Wear 4 gray reads as decades old, not months"),
        critic="keep",
        flaw="too_messy",
        wo=WorkOrderSpec(
            title="Crates: a stained row for the market",
            goal="props.harbor.crates style weathered → stained, one row",
            utterance="Computer — stain the market crates",
            value="stained",
            estimate=_WO_ESTIMATE,
        ),
        assumes=True,
    ),
    NightSpec(
        n=4, date="2026-10-27",
        edit=NightEdit(
            word="props.harbor.crates", node="crates",
            params={"count": 16, "style": "plain", "from_library": 4, "seed": 104},
            value="plain", message="night 4: the plain crate experiment",
        ),
        taste_bets=(
            _bet("taste", "too_messy",
                 "You keep sixteen crates on the quay, not twelve"),
        ),
        world_bet=_bet("world", "material_read",
                       "Plain timber reads as freshly cut on all 16 crates"),
        critic="hold",  # the honest miss: the critic finds it reads as a fence
        flaw="too_messy",
        wo=WorkOrderSpec(
            title="Crates: plain boards for the market stalls",
            goal="props.harbor.crates style → plain, from_library 4",
            utterance="Computer — plain crates for the market",
            value="plain",
            estimate=_WO_ESTIMATE,
        ),
        assumes=True,
    ),
    NightSpec(
        n=5, date="2026-10-28",
        edit=NightEdit(
            word="material.wood.weathering", node="weathering",
            params={"wear": 2, "tone": "dark"},
            value="dark", message="night 5: dark tones under the lanterns",
        ),
        taste_bets=(
            _bet("taste", "too_messy",
                 "You keep lantern-lit dark wood over floodlit pale"),
        ),
        world_bet=_bet("world", "light_read",
                       "Dark tone at wear 2 reads as lantern-lit, not floodlit"),
        critic="keep",
        flaw="too_dark",
        wo=WorkOrderSpec(
            title="Weathering: darker tones on the sheds",
            goal="material.wood.weathering tone gray → dark on the shed row",
            utterance="Computer — darker tones on the sheds",
            value="dark",
            estimate=_WO_ESTIMATE,
        ),
        assumes=True,
    ),
    NightSpec(
        n=6, date="2026-10-29",
        edit=NightEdit(
            word="props.harbor.racks", node="racks",
            params={"count": 8, "length_m": 3.0},
            value="deep-racks", message="night 6: eight deep racks by the shed wall",
        ),
        taste_bets=(
            # too_dark's first observation landed this morning — the bet is a
            # guess with the true count, and the third flaw code's arc begins
            _bet("taste", "too_dark",
                 "You keep the darker racks against the lantern light"),
        ),
        world_bet=_bet("world", "clutter_density",
                       "Eight deep racks read as a shed wall, not a fence"),
        critic="keep",
        flaw="too_dark",
        wo=WorkOrderSpec(
            title="Racks: a second row on the north wall",
            goal="props.harbor.racks count 8 → 14, length 3.0 m",
            utterance="Computer — a second rack row, north wall",
            value="deep-racks",
            estimate=_WO_ESTIMATE,
        ),
        assumes=True,
    ),
    NightSpec(
        n=7, date="2026-10-30",
        edit=NightEdit(
            word="props.harbor.crates", node="crates",
            params={"count": 12, "style": "weathered", "from_library": 6, "seed": 107},
            value="weathered", message="night 7: the week's row, settled",
        ),
        taste_bets=(
            _bet("taste", "too_dark",
                 "You keep the settled, darker row under dawn mist"),
        ),
        world_bet=_bet("world", "material_read",
                       "The settled row reads as weathered on every crate"),
        critic="keep",
        flaw="no_focus",
        wo=WorkOrderSpec(
            title="Racks v2: lids for the top shelf",
            goal="props.harbor.racks gains {lids: bool} on the top shelf",
            utterance="Computer — lids on the top shelf of the racks",
            value="deep-racks",
            estimate=_WO_ESTIMATE,
            promote="props.harbor.racks",
            promote_props=_RACKS_V2_PROPS,
        ),
        assumes=True,
    ),
)

#: Night one's twelve candidate decision cards — what the night *would* ask
#: the morning if the queue had no budget. Each is a two-option choice (one
#: tap); the queue's admission (G §4.3) decides which survive.
ASK_CARDS: tuple[tuple[str, list[str]], ...] = (
    ("Move the second shed two meters east?", ["yes, east", "leave it"]),
    ("The slip gains a second lane?", ["two lanes", "one lane"]),
    ("Rope the north stacks?", ["rope them", "leave loose"]),
    ("Paint the marker posts?", ["paint them", "bare wood"]),
    ("The jetty gains a mid lamp?", ["mid lamp", "ends only"]),
    ("Stack the spare crates under the eave?", ["under the eave", "in the yard"]),
    ("Gravel the path to the sheds?", ["gravel", "bare ground"]),
    ("Raise the shed door lintels?", ["raise", "leave"]),
    ("The boat tarp: canvas, or hide?", ["canvas", "hide"]),
    ("A second rope on the far rail?", ["second rope", "single"]),
    ("The woodpile under a lean-to?", ["lean-to", "open air"]),
    ("Mark the tide line with a post?", ["a post", "unmarked"]),
)

#: The attention shape the script produces (the driver asserts the ledger
#: matches, never trusts this): evening questions fall 6 → 0 as each code's
#: denominator passes two (8 bank codes × 2 answers each, ≤ 6 a sitting),
#: and the mornings shrink with them.
EXPECTED_QUESTIONS: tuple[int, ...] = (6, 6, 2, 2, 0, 0, 0)

#: Decisions already committed by the night's structure on night 1 when the
#: queue admits the ask cards: the branch apply, the work-order keep, and
#: the three blocking questions the dam let stand.
NIGHT1_STRUCTURAL_DECISIONS = 5
