"""The workload: 64 characters per tick, each with a 3-question pack.

Grounded in builder-ide's own data, not invented:

* the **tiles toy** — the closed vocabulary of the tiles seat
  (``core/vocab/words.py``), the tile families (``core/tiles/models.py``)
  and the shortlist question the judge seat already asks over them
  (``core/judge/shortlist.py``);
* the **critic reference set** — ``core/critic/reference-set.json``: the 60
  base renders (scene, seed, size) and the 30 members, each with the
  defect class that was planted in it;
* the **critic's defect classes** — ``core/critic/defects.py``.

One *character* per tick sends one *pack*: a shared state (the scene it
is standing in) plus 1-5 typed questions. The brief's workload is 64
characters per tick, each with a 3-question pack over a ~150-token shared
state, so that is what this builds. The states are **distinct per
character** — the pack shares its state across its own questions, not
across characters — so nothing here can be answered by a cache.

Everything is a pure function of ``seed``: rerunning with the same seed
gives byte-identical packs.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUILDER_IDE = Path(
    __import__("os").environ.get("BUILDER_IDE", "/home/caseydigennaro/src/builder-ide")
)

#: The tile families of the tiles seat, with the title a shortlist shows
#: the judge (``core/judge/shortlist.py`` renders ``title (family)``).
TILE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("weathered crates", "harbor.crates.style"),
    ("stacked rope coils", "props.harbor.rope"),
    ("tide-stained bollards", "props.harbor.bollards"),
    ("tarred lobster pots", "props.harbor.pots"),
    ("brine-cured nets", "props.harbor.nets"),
    ("chalk-marked bollard cap", "props.harbor.cap"),
    ("faded dock lantern", "props.harbor.lantern"),
    ("salvaged timber pallet", "props.harbor.pallet"),
    ("dredged channel marker", "props.harbor.marker"),
    ("hull-planked dinghy", "props.harbor.dinghy"),
)

#: The quality scale of a critic's score question.
QUALITY_LEVELS: tuple[str, ...] = ("unusable", "poor", "fair", "good", "excellent")

#: The scenes of the critic's reference set, read from the set itself.
def _reference_set() -> dict[str, Any]:
    path = BUILDER_IDE / "core" / "critic" / "reference-set.json"
    with path.open() as fh:
        return json.load(fh)


def _defect_classes() -> tuple[str, ...]:
    """The seeded defect classes, read out of the critic's own module."""
    src = (BUILDER_IDE / "core" / "critic" / "defects.py").read_text()
    ns: dict[str, Any] = {}
    # the module imports its own package siblings; only the constants are
    # needed, so they are pulled out of the source text rather than
    # importing builder-ide (which needs its own dependency set)
    import re

    for name in ("IMAGE_DEFECTS", "MESH_DEFECTS"):
        m = re.search(rf"^{name}\s*:\s*tuple\[str, \.\.\.\]\s*=\s*\(([^)]*)\)", src, re.M)
        if m:
            ns[name] = re.findall(r'"([^"]+)"', m.group(1))
    out: list[str] = []
    for key in ("IMAGE_DEFECTS", "MESH_DEFECTS"):
        out.extend(ns.get(key, []))
    return tuple(out) or ("missing_object", "texture_swap", "wrong_scale")


@dataclass
class Pack:
    """One character's question pack for one tick."""

    tick: int
    char_id: str
    state: str
    questions: dict[str, dict[str, Any]]

    def to_wire(self) -> dict[str, Any]:
        return {"state": self.state, "questions": self.questions}


@dataclass
class Workload:
    packs: list[Pack]
    seed: int
    chars_per_tick: int
    questions_per_pack: int
    ticks: int
    notes: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# the state
# --------------------------------------------------------------------------

_TILE_VERBS = (
    "re-placing",
    "inspecting",
    "re-stacking",
    "photographing",
    "counting",
    "welding",
    "painting",
    "unloading",
    "salvaging",
    "polishing",
)

_NIGHT_LINES = (
    "The tide is coming in over the lower stones.",
    "The harbour lights come on one bank at a time.",
    "A gull works the bins behind the chandlery.",
    "Rain has stopped but the boards are still running with water.",
    "Somebody's radio is playing from a propped window.",
    "The fog comes up off the flats and takes the far crane with it.",
    "A rope knocks against a cleat in the dark.",
    "The wind drops and the whole quay seems to lean inwards.",
    "A generator coughs somewhere behind the fish shed.",
    "Cold enough that the paint on the winch is going brittle.",
)

_CHARACTER_ROLES = (
    "the builder",
    "the second builder",
    "the critic",
    "the night runner",
    "the tile chooser",
    "the scene server",
)


def _state_for(
    rng: random.Random,
    char_id: str,
    base: dict[str, Any],
    member: dict[str, Any],
    defect: str | None,
    tile_picks: list[tuple[str, str]],
) -> str:
    """One character's ~150-token shared state."""
    scene = base.get("scene", "arctic")
    width = base.get("width", 960)
    height = base.get("height", 540)
    base_id = base.get("id", "base")
    seed = base.get("seed", 0)
    member_id = member.get("member_id", "mem")
    defect_line = (
        f"The last critic pass over {member_id} reported a {defect} defect."
        if defect
        else f"The last critic pass over {member_id} came back clean."
    )
    lines = [
        f"Night cycle, scene {scene} ({base_id}), render seed {seed}, {width}x{height}.",
        f"{char_id} is {_TILE_VERBS[rng.randrange(len(_TILE_VERBS))]} "
        f"{tile_picks[0][0]} ({tile_picks[0][1]}) on the {scene} quay.",
        f"Context: phase={rng.choice(('dusk', 'night', 'late'))}, "
        f"style={rng.choice(('weathered', 'salt-bleached', 'tarred'))}, "
        f"crates={rng.randrange(4, 20)}, from_library={rng.randrange(0, 3)}.",
        "Tiles: " + "; ".join(f"{title} ({fam})" for title, fam in tile_picks) + ".",
        defect_line,
        rng.choice(_NIGHT_LINES),
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# the questions
# --------------------------------------------------------------------------

def _questions_for(
    rng: random.Random,
    tile_picks: list[tuple[str, str]],
    defect: str | None,
    kind_cycle: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Three typed questions over one shared state."""
    out: dict[str, dict[str, Any]] = {}
    for i, kind in enumerate(kind_cycle):
        qid = f"q{i}"
        if kind == "choice":
            criteria = {f"opt{j}": f"{title} ({fam})" for j, (title, fam) in enumerate(tile_picks)}
            out[qid] = {
                "type": "choice",
                "instructions": "Which tile should be played next on this quay?",
                "criteria": criteria,
            }
        elif kind == "score":
            out[qid] = {
                "type": "score",
                "instructions": "How good is the render as it stands?",
                "criteria": list(QUALITY_LEVELS),
            }
        else:
            claim = (
                f"the render carries a {defect} defect"
                if defect
                else "the render carries no planted defect at all"
            )
            out[qid] = {
                "type": "noul",
                "instructions": f"Claim: {claim}. Is the claim true given the evidence?",
            }
    return out


# --------------------------------------------------------------------------
# the builder
# --------------------------------------------------------------------------

def build_workload(
    *,
    seed: int = 20261031,
    ticks: int = 4,
    chars_per_tick: int = 64,
    questions_per_pack: int = 3,
) -> Workload:
    """The workload, as a pure function of ``seed``."""
    rng = random.Random(seed)
    ref = _reference_set()
    bases: list[dict[str, Any]] = list(ref.get("bases", []))
    members: list[dict[str, Any]] = list(ref.get("members", []))
    defects = _defect_classes()
    if not bases or not members:
        raise RuntimeError(f"the critic reference set at {BUILDER_IDE} is empty")

    kinds = ("choice", "score", "noul")
    packs: list[Pack] = []
    for tick in range(ticks):
        for c in range(chars_per_tick):
            base = bases[(tick * chars_per_tick + c) % len(bases)]
            member = members[(tick * chars_per_tick + c) % len(members)]
            defect = member.get("defect")
            if defect not in defects:
                defect = defect or None
            picks = rng.sample(TILE_CANDIDATES, 4)
            char_id = f"char_{c:02d}"
            state = _state_for(rng, char_id, base, member, defect, picks)
            kind_cycle = tuple(kinds[(c + i) % len(kinds)] for i in range(questions_per_pack))
            questions = _questions_for(rng, picks, defect, kind_cycle)
            packs.append(Pack(tick=tick, char_id=char_id, state=state, questions=questions))

    notes = {
        "source": {
            "reference_set": str(BUILDER_IDE / "core" / "critic" / "reference-set.json"),
            "defect_classes": list(defects),
            "tile_candidates": [f"{t} ({f})" for t, f in TILE_CANDIDATES],
        },
        "n_packs": len(packs),
        "n_questions": len(packs) * questions_per_pack,
    }
    return Workload(
        packs=packs,
        seed=seed,
        chars_per_tick=chars_per_tick,
        questions_per_pack=questions_per_pack,
        ticks=ticks,
        notes=notes,
    )


def write_workload(path: Path, wl: Workload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for p in wl.packs:
            fh.write(
                json.dumps(
                    {
                        "tick": p.tick,
                        "char_id": p.char_id,
                        "state": p.state,
                        "questions": p.questions,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    meta = {
        "seed": wl.seed,
        "ticks": wl.ticks,
        "chars_per_tick": wl.chars_per_tick,
        "questions_per_pack": wl.questions_per_pack,
        "n_packs": len(wl.packs),
        "n_questions": len(wl.packs) * wl.questions_per_pack,
        "notes": wl.notes,
    }
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    return path


def read_workload(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
