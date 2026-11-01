#!/usr/bin/env python
"""night-v3 — the first integrated night, driven end to end.

The owner goal: "a small courtyard with three props: a weathered crate, a
brass lantern, an iron anvil; make it feel lived-in."

One ledger, one runner, every layer real:

  plan        priced by core/night/cost, admitted under the rails
  decisions   tiles chosen through core/judge: local d1-2B first, escalating
              to Jev in the cloud below the calibrated tau, held by the
              standing gate, bounded by never-wait; every judgment a row
  world       Infinigen 2.0 through the engine seam (the v2 venv); the
              splice measured at the seam; Warp stages are NOT wired here,
              so the CPU path runs and is recorded
  props       TRELLIS.2 through core.genbatch: image, mesh, repair,
              measurement, the scripted critic (no VLM delegate: B2)
  memory      every heavy step takes ~/lm-wt/heavy.lock, with >= 25 GB free
  live view   the night's recipe changes compile to world-stream deltas;
              delta sizes recorded; a Playwright screenshot of the end state
  the band    the chorus: a loop rising fast is granted another round, taken
              from a loop gone flat; each cue and its effect recorded
  flow        the mediator (a cloud LLM) is counted in and out of flow;
              V-JEPA 2's prediction error is logged if the service answers

Run on the Thor, from the night-v3 worktree, in the propmaker-batch venv:

  PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
      docs/lab/night-v3-scripts/run_night.py --out artifacts/night-v3
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from core.canon import content_hash, now_utc  # noqa: E402
from core.engine.contract import PreviewRequest, StageRequest  # noqa: E402
from core.engine.registry import open_engine  # noqa: E402
from core.genbatch.comfy import ComfyClient  # noqa: E402
from core.genbatch.critic import PropCritic  # noqa: E402
from core.genbatch.executor import PropExecutor, Templates  # noqa: E402
from core.genbatch.models import PropRequest  # noqa: E402
from core.genbatch.night import MeasuredClock, _winners  # noqa: E402
from core.genbatch.schedule import NightPlan  # noqa: E402
from core.genbatch.store import PropStore  # noqa: E402
from core.genbatch.workflow import load_template  # noqa: E402
from core.judge.backends import D1Backend, JevBackend  # noqa: E402
from core.judge.gate import (  # noqa: E402
    ConfidencePolicy,
    EscalationLadder,
    StandingGate,
)
from core.judge.judge import Judge  # noqa: E402
from core.judge.models import Question  # noqa: E402
from core.night.cost.admission import PlannedJob, admission_check  # noqa: E402
from core.night.cost.estimates import owner_estimate  # noqa: E402
from core.night.cost.pricing import price_job  # noqa: E402
from core.night.ledger import SQLiteLedger  # noqa: E402
from core.night.models import IterationPolicy, Rail  # noqa: E402
from core.night.report import build_report, render_html, render_text  # noqa: E402
from core.night.runner import NightRunner  # noqa: E402
from core.records import Actor, GeneratorRef, Recipe, RecipeEntry, Task  # noqa: E402
from core.tiles.library import TileLibrary  # noqa: E402
from core.tiles.models import Outcome, TileStep, build_tile  # noqa: E402
from core.tiles.models import TileAuthor  # noqa: E402
from core.tiles.plays import record_play  # noqa: E402
from core.vocab.registry import VocabularyRegistry  # noqa: E402
from core.vocab.words import default_entries  # noqa: E402

# ---------------------------------------------------------------- constants --

NIGHT_ID = "night-v3"
PORT_D1 = 8295
D1_MODEL = Path.home() / "models" / "d1-2B" / "d1-2B-Q8_0.gguf"
LLAMA_SERVER = Path.home() / "llama.cpp-upstream" / "build-up" / "bin" / "llama-server"
TRELLIS_ROOT = Path.home() / "lm-wt" / "trellis"
COMFY_URL = "http://127.0.0.1:8188"
HEAVY_LOCK = Path.home() / "lm-wt" / "heavy.lock"
V2_HOME = Path.home() / "lm-wt" / "v2-thor"
SCRATCH = Path.home() / "lm-wt" / "world-stream-scratch"
VIEWER = Path.home() / "lm-tools" / "viewer"
SHOT = Path.home() / "lm-tools" / "playwright" / "shot.mjs"
GQ = Path.home() / "lm-tools" / "gq.py"
MIN_FREE_GB = 25.0
NEVER_WAIT_SECONDS = 8.0

#: The generator resolution for this box, in the seam's own shape: the
#: entry's generator name -> the v2 CLI's chain (the M1 table's way; each
#: chain renders and traces clean — v2-thor-experiment).
GENERATORS = {
    "room_livingroom_rand": "room_livingroom_rand",
    "storage_cabinet_with_door_rand": "storage_cabinet_with_door_rand",
    "storage_cell_shelf_rand": "storage_cell_shelf_rand",
    "wood_scratched_rand": "wood_scratched_rand material_cube",
}

CORE_ACTOR = Actor(kind="core", id="night-v3", via="word")
SCHEDULER_ACTOR = Actor(kind="core", id="night-v3", via="word")

WORLD_SEED = 42

# ----------------------------------------------------------------- helpers --


def log(msg: str) -> None:
    print(f"[night] {datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


def load_secrets() -> None:
    """GROQ_API_KEY and TYPESAFE_API_KEY into the environment, never printed."""
    secrets = Path.home() / ".config" / "last-mile" / "secrets.env"
    if not secrets.exists():
        return
    for line in secrets.read_text().splitlines():
        m = re.match(r"^(?:export )?([A-Z_]+)=['\"]?([^'\"]+)['\"]?", line)
        if m and m.group(1) in ("GROQ_API_KEY", "TYPESAFE_API_KEY"):
            os.environ.setdefault(m.group(1), m.group(2))


def box_state() -> dict:
    state: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "load1": round(os.getloadavg()[0], 2),
    }
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(("MemTotal", "MemAvailable")):
                key, val = line.split(":")
                state[key] = round(int(val.strip().split()[0]) / 1048576, 1)
    except OSError:
        pass
    try:
        micro = int(
            Path("/sys/class/hwmon/hwmon4/power1_input").read_text().strip()
        )
        state["vin_w"] = round(micro / 1e6, 1)
    except (OSError, ValueError):
        pass
    return state


def ram_free_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable"):
            return int(line.split()[1]) / 1048576.0
    return 0.0


class Heavy:
    """The house lease: one heavy step at a time, >= 25 GB free after a load."""

    def __init__(self, ledger: SQLiteLedger | None = None, *,
                 enabled: bool = True) -> None:
        self._ledger = ledger
        self.enabled = enabled
        self.waits = 0

    @contextmanager
    def hold(self, reason: str, *, check_ram: bool = False):
        if not self.enabled:
            log(f"(dry run: the heavy lease is a no-op — {reason})")
            yield
            return
        log(f"queueing for the heavy lock ({reason})")
        started = time.monotonic()
        with open(HEAVY_LOCK, "a+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.waits += 1
                log("the lock is held (another seat's heavy step); waiting")
                fcntl.flock(fh, fcntl.LOCK_EX)
            waited = time.monotonic() - started
            log(f"got the heavy lock after {waited:.0f} s ({reason})")
            if self._ledger is not None:
                self._ledger.append(
                    type="night.heavy_lease",
                    actor=CORE_ACTOR,
                    subject={"entity_kind": "night", "entity_id": NIGHT_ID},
                    payload={"reason": reason, "waited_s": round(waited, 1),
                             "free_gb": round(ram_free_gb(), 1)},
                )
            try:
                yield
                if check_ram:
                    free = ram_free_gb()
                    if free < MIN_FREE_GB:
                        raise RuntimeError(
                            f"only {free:.1f} GB free after {reason} "
                            f"(the bar is {MIN_FREE_GB}); refusing"
                        )
                    log(f"free after {reason}: {free:.1f} GB")
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def run_cmd(argv: Sequence[str], *, cwd: Path | None = None,
            env: dict | None = None, timeout: float = 3600.0) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(a) for a in argv[:8]) + (" ..." if len(argv) > 8 else ""))
    return subprocess.run(
        [str(a) for a in argv], cwd=cwd, env=env, timeout=timeout,
        check=False, capture_output=True, text=True,
    )


# --------------------------------------------------------------- the tiles ---

FAKE_AUTHOR = TileAuthor(
    model="scripted/night-v3-tiles-v1", provider="local",
    prompt_hash="sha256:" + "0" * 64, cost_cents=0,
)

#: What each tile implies beyond its word: the note the builder wrote and
#: the placement it means on the live wire (a move of a matching instance).
#: The wire's vocabulary is transforms-only today; the bridge is recorded,
#: never hidden.
TILES_META: dict[str, dict] = {}


def author_tiles(library: TileLibrary) -> list:
    """The cloud author's six tiles for the courtyard, in the M1 words."""
    specs = [
        ("crates.weathered.corner", "props.harbor.crates",
         {"count": 3, "style": "weathered", "from_library": 0}, 4021,
         "the crate corner reads weathered; the crates move toward the wall",
         {"match": r"table|crate|box|shelf|cabinet", "move": (0.8, 0.0, 0.3)}),
        ("crates.stained.stack", "props.harbor.crates",
         {"count": 5, "style": "stained", "from_library": 0}, 4022,
         "a stained stack of crates; the stack moves to open a path",
         {"match": r"table|crate|box|shelf|cabinet", "move": (-0.6, 0.0, 0.5)}),
        ("weathering.gray.worn", "material.wood.weathering",
         {"wear": 4, "tone": "gray"}, 4023,
         "the wood wears gray; a chair shifts to catch the light",
         {"match": r"chair|stool|seat|bench", "move": (0.4, 0.0, -0.4)}),
        ("weathering.pale.faded", "material.wood.weathering",
         {"wear": 2, "tone": "pale"}, 4024,
         "faded pale wood; a small table drifts to the courtyard's edge",
         {"match": r"table|desk|stand", "move": (-0.4, 0.0, -0.6)}),
        ("racks.tool.wall", "props.harbor.racks",
         {"count": 2, "length_m": 1.5}, 4025,
         "tool racks on the wall; the rack line moves off the walking path",
         {"match": r"shelf|rack|cabinet|unit", "move": (0.5, 0.0, 0.6)}),
        ("weathering.dark.lived", "material.wood.weathering",
         {"wear": 5, "tone": "dark"}, 4026,
         "dark, much-handled wood; the lamp table moves near the door",
         {"match": r"table|lamp|stand", "move": (0.2, 0.0, 0.7)}),
    ]
    tiles = []
    for title, word, params, seed, note, placement in specs:
        TILES_META[title] = {"note": note, "placement": placement,
                             "engine_seed": seed}
        # only the crates word's schema carries a seed; the other words'
        # variation lands on the recipe entry's seed, which the driver's
        # side table holds — the door validates every word's params.
        step_params = dict(params)
        if word == "props.harbor.crates":
            step_params["seed"] = seed
        tiles.append(build_tile(
            family=f"courtyard.{word}",
            kind="recipe_edit",
            title=title,
            steps=(TileStep(word=word, path=word, params=step_params),),
            author=FAKE_AUTHOR,
        ))
    for tile in tiles:
        library.add(tile)
    return tiles


def tile_state(context: dict, tiles: list) -> str:
    """What the judge sees: the courtyard, the round, what lived-in means."""
    return (
        f"A small courtyard is being built at night. The owner asked for a "
        f"weathered crate, a brass lantern and an iron anvil, and for the "
        f"place to feel lived-in. Round {context['round']} of the edits. So "
        f"far the courtyard has: {context.get('history', 'nothing yet')}. "
        f"Which single change would make it feel most lived-in next?"
    )


def tile_text(tile) -> str:
    step = tile.steps[0]
    meta = TILES_META.get(tile.title, {})
    note = meta.get("note", "")
    return f"{tile.title}: sets {step.word} with {step.params}. {note}"


# ---------------------------------------------------------- the world seat ---

class WorldState:
    """The engine seam's state for one night: the recipe, its versions, the
    renders each variant produced, and the splice's measurements."""

    def __init__(self, engine, out: Path) -> None:
        self.engine = engine
        self.out = out
        self.pin = engine.describe().pin
        self.renders: dict[tuple[str, str], dict] = {}
        self.splice: list[dict] = []
        self.versions: dict[str, Recipe] = {}
        self.cpu_generation_s = 0.0  # the procfunc/trace wall the seam reported

    def base_recipe(self) -> Recipe:
        commit = self.pin.commit[:7]
        entries = {
            "courtyard.room": RecipeEntry(
                path="courtyard.room", kind="structure",
                generator=GeneratorRef(
                    module="infinigen2.scenes.room",
                    func="room_livingroom_rand", variant=None, rev=commit),
                seed=WORLD_SEED,
            ),
            "courtyard.crates": RecipeEntry(
                path="courtyard.crates", kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen2.objects",
                    func="storage_cabinet_with_door_rand", variant=None,
                    rev=commit),
                params={"count": 3, "style": "weathered"}, seed=4021,
            ),
            "courtyard.weathering": RecipeEntry(
                path="courtyard.weathering", kind="material",
                generator=GeneratorRef(
                    module="infinigen2.shaders",
                    func="wood_scratched_rand", variant=None, rev=commit),
                params={"wear": 1, "tone": "pale"}, seed=4023,
            ),
        }
        return Recipe(id="courtyard", name="the courtyard",
                      engine_pin=self.pin, seeds={"global": WORLD_SEED},
                      entries=entries)

    def apply_tile(self, base: Recipe, tile_step_word: str, params: dict,
                   seed: int) -> tuple[Recipe, list[str]]:
        """One tile's word as a recipe edit; returns (head recipe, notes)."""
        head = base.model_copy(deep=True)
        notes: list[str] = []
        if tile_step_word == "props.harbor.crates":
            entry = head.entries["courtyard.crates"]
            head.entries["courtyard.crates"] = entry.model_copy(
                update={"params": {**entry.params,
                                   "count": params.get("count", 3),
                                   "style": params.get("style", "weathered")},
                        "seed": seed})
            notes.append("crates.params <- the tile's word")
        elif tile_step_word == "material.wood.weathering":
            entry = head.entries["courtyard.weathering"]
            head.entries["courtyard.weathering"] = entry.model_copy(
                update={"params": {**entry.params,
                                   "wear": params.get("wear", 1),
                                   "tone": params.get("tone", "pale")},
                        "seed": seed})
            notes.append("weathering.params <- the tile's word")
        elif tile_step_word == "props.harbor.racks":
            entry = head.entries["courtyard.crates"]
            head.entries["courtyard.crates"] = entry.model_copy(
                update={"seed": seed})
            notes.append("racks word has no entry on this box (no racks "
                         "generator resolution was measured); the crates "
                         "entry's seed moved instead — recorded, not hidden")
        return head, notes

    @staticmethod
    def _vh(recipe: Recipe) -> str:
        """The version hash: the recipe's canonical form, hashed."""
        return content_hash(recipe.model_dump(mode="json"))

    def render(self, recipe: Recipe, subject: str, variant_id: str,
               heavy: Heavy) -> dict:
        started = time.monotonic()
        with heavy.hold(f"engine render {subject} ({variant_id})"):
            result = self.engine.render_preview(PreviewRequest(
                recipe=recipe,
                version_hash=self._vh(recipe),
                subject=subject,
                rung=2,
                seed=recipe.seeds.get("global", WORLD_SEED),
            ))
        png = self.out / "world" / f"{variant_id}_{subject.replace('.', '_')}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(result.data)
        record = {
            "variant_id": variant_id, "subject": subject,
            "bytes": len(result.data), "sha256": result.artifact["sha256"],
            "wall_ms": result.wall_ms,
            "wall_s": round(time.monotonic() - started, 2),
            "resolution": result.resolution, "rung": result.rung,
            "path": str(png),
        }
        self.renders[(variant_id, subject)] = record
        return record

    def splice_measure(self, base: Recipe, head: Recipe, dirty: list[str],
                       label: str, heavy: Heavy) -> dict:
        """The splice, measured at the seam: reexecute (the venv boundary
        refuses it, and the refusal is the record), then the scoped stage
        (the dirty entries only) against the full stage."""
        row: dict[str, Any] = {"label": label, "dirty": dirty}
        full_started = time.monotonic()
        with heavy.hold(f"full stage trace ({label})"):
            full = self.engine.generate_stage(StageRequest(
                recipe=head, version_hash=self._vh(head), stage="objects"))
        full_s = time.monotonic() - full_started
        row["full_stage_s"] = round(full_s, 2)
        row["full_stage_bytes"] = len(full.data)

        scoped_started = time.monotonic()
        with heavy.hold(f"scoped stage trace ({label})"):
            scoped = self.engine.generate_stage(StageRequest(
                recipe=head, version_hash=self._vh(head), stage="objects",
                entries=dirty))
        scoped_s = time.monotonic() - scoped_started
        row["scoped_stage_s"] = round(scoped_s, 2)
        row["scoped_stage_bytes"] = len(scoped.data)
        row["ratio"] = round(full_s / max(scoped_s, 1e-6), 2)
        self.splice.append(row)
        return row


class WorldCritic:
    """The calibrated scripted checks, on the night's own renders: the same
    analytic image checks the reference set measures (black frame, fireflies,
    flat patch, dark holes, patch seams), plus the render-level facts a
    preview owes — it decoded, it is not black or blown out, it carries
    contrast, and the tile's edit actually changed the bytes. No model, no
    VLM (B2); the verdict row says which critic made it."""

    def __init__(self, world: WorldState, ledger: SQLiteLedger) -> None:
        self.world = world
        self.ledger = ledger

    def score(self, task: Task, variant):
        import io

        import numpy as np
        from PIL import Image
        from core.critic.checks import run_image_checks

        from core.night.iterate import CriticScore

        edits = variant.edit or {}
        subject = edits.get("subject", "courtyard.room")
        record = self.world.renders.get((variant.id, subject))
        if record is None:
            return CriticScore(score=0.0, reason="no render was produced",
                               degraded=True)
        png = Path(record["path"]).read_bytes()
        score, checks = 1.0, []
        try:
            arr = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
        except Exception as exc:
            self._row(task, variant, record, 0.0,
                      [[f"decode failed: {exc}"[:80]]])
            return CriticScore(score=0.0, reason=f"decode failed: {exc}"[:80],
                               degraded=True)
        checks.append(["decodes", "ok", 0.0])
        lum = arr.mean()
        contrast = arr.std()
        checks.append(["luminance", f"{lum:.1f}", 0.0 if 12 <= lum <= 242 else -0.3])
        checks.append(["contrast", f"{contrast:.1f}", 0.0 if contrast >= 6 else -0.2])
        for outcome in run_image_checks(arr):
            if not outcome.applicable:
                continue
            penalty = -0.15 if outcome.fired else 0.0
            checks.append([outcome.check,
                           "FIRED" if outcome.fired else "clean", penalty])
            score += penalty
        score += checks[1][2] + checks[2][2]
        # the tile's prediction: an edit that changes the seed must change
        # the bytes — a hash identical to the parent's render of the same
        # subject means the edit did nothing the picture can see
        parent_key = (variant.parent_id, subject)
        parent_sha = (self.world.renders.get(parent_key) or {}).get("sha256")
        if parent_sha is not None:
            changed = parent_sha != record["sha256"]
            checks.append(["edit_changed_bytes",
                           "yes" if changed else "NO", 0.0 if changed else -0.3])
            score += 0.0 if changed else -0.3
        score = max(0.0, min(1.0, score))
        reason = "; ".join(f"{n}={v}{f" ({p:+.2f})" if p else ""}"
                           for n, v, p in checks)
        self._row(task, variant, record, score, checks)
        return CriticScore(score=score, reason=reason)

    def _row(self, task, variant, record, score, checks) -> None:
        self.ledger.append(
            type="judge.verdict",
            actor=Actor(kind="critic", id="scripted", via="night"),
            subject={"entity_kind": "variant", "entity_id": variant.id},
            payload={"critic": "scripted", "task": task.id, "score": score,
                     "checks": checks, "subject": record["subject"],
                     "render_sha": record["sha256"],
                     "render_bytes": record["bytes"]},
        )


# --------------------------------------------------------- the night seat ----

class CompositeExecutor:
    """One executor, two workshops: the engine seam (world) and the
    generative batch (props). The runner sees one seam."""

    def __init__(self, world: WorldState, prop_exec: PropExecutor,
                 heavy: Heavy, ledger: SQLiteLedger, judge_seat: "JudgeSeat",
                 wires: list[dict]) -> None:
        self.world = world
        self.props = prop_exec
        self.heavy = heavy
        self.ledger = ledger
        self.judge = judge_seat
        self.wires = wires  # live-view rows: what each applied tile did

    def _is_prop(self, task_id: str) -> bool:
        return task_id.startswith(("img:", "prop:"))

    def plan(self, task: Task, variant=None):
        if self._is_prop(task.id):
            return self.props.plan(task, variant)
        from core.genbatch.executor import ExecutionPlan

        if task.id == "world.base":
            return ExecutionPlan(gpu_minutes=0.4, wall_minutes=6.0)
        return ExecutionPlan(gpu_minutes=0.4, wall_minutes=6.0)

    def run(self, task: Task, variant=None):
        from core.genbatch.executor import ExecutionPlan

        if self._is_prop(task.id):
            return self.props.run(task, variant)

        started = time.monotonic()
        edits = (variant.edit if variant is not None else None) or {}
        if task.id == "world.base":
            recipe = self.world.base_recipe()
            self.world.versions["v1"] = recipe
            rows = []
            for subject in ("courtyard.room", "courtyard.crates",
                            "courtyard.weathering"):
                rows.append(self.world.render(recipe, subject, "v1", self.heavy))
            wall = time.monotonic() - started
            return ExecutionPlan(
                outcome="kept", reason="the courtyard's baseline: room, "
                "crates and weathering, rendered at rung 2",
                artifact=rows[0]["path"],
                gpu_minutes=0.0, wall_minutes=wall / 60.0,
            )

        # world.edit: the chosen tile becomes a recipe edit, then a render.
        round_no = variant.round if variant is not None else 1
        base = self.world.versions.get(
            "v1", self.world.base_recipe())
        word = edits.get("word", "")
        params = edits.get("params", {})
        seed = int(edits.get("seed", 4000 + round_no))
        head, notes = self.world.apply_tile(base, word, params, seed)
        head_key = f"v{round_no + 1}"
        self.world.versions[head_key] = head

        subject = {
            "props.harbor.crates": "courtyard.crates",
            "material.wood.weathering": "courtyard.weathering",
            "props.harbor.racks": "courtyard.crates",
        }.get(word, "courtyard.room")
        render = self.world.render(head, subject, variant.id, self.heavy)

        # the splice, measured where an edit actually lands
        self.world.splice_measure(
            base, head, [subject.split(".")[-1]], f"round-{round_no} {word}",
            self.heavy)

        # the live wire: the tile's placement as the wire's transform edit
        self.wires.append({
            "round": round_no, "tile": edits.get("tile_id"),
            "word": word, "placement": edits.get("placement"),
            "note": edits.get("note", ""), "head": head_key,
        })

        wall = time.monotonic() - started
        return ExecutionPlan(
            outcome="kept",
            reason=f"round {round_no}: applied {edits.get('tile_id')} "
                   f"({word}); " + "; ".join(notes),
            artifact=render["path"],
            gpu_minutes=0.0, wall_minutes=wall / 60.0,
        )


class CompositeVariants:
    """Where variants come from: seeds for props; the judge's chosen tile
    for the world's edit rounds."""

    def __init__(self, plan: NightPlan, judge_seat: "JudgeSeat",
                 ledger: SQLiteLedger) -> None:
        self.plan = plan
        self.judge = judge_seat
        self.ledger = ledger
        #: the chorus rounds seed past everything wave 1 used
        self.seed_offset = 0

    def variants(self, task: Task, *, round: int, parent, count: int):
        from core.night.iterate import Variant

        if task.id == "world.base":
            if round > 1:
                return []
            return [Variant(id=f"{task.id}_r{round}_v1", label="baseline",
                            round=round, seed=WORLD_SEED)]
        if task.id == "world.edit":
            if round > 2:
                return []
            choice = self.judge.choose_tile(round, parent)
            return [Variant(
                id=f"{task.id}_r{round}_v1",
                label=choice["tile"].title,
                seed=int(choice["edit"]["seed"]),
                round=round,
                parent_id=parent.id if parent is not None else None,
                edit=choice["edit"],
            )]
        request = self.plan.request(task.id)
        if request is None:
            return []
        base = getattr(request, "base_seed", 0) or 0
        return [
            Variant(
                id=f"{task.id}_r{round}_v{index + 1}",
                label=f"seed {base + self.seed_offset + 1000 * (round - 1) + index + 1}",
                seed=base + self.seed_offset + 1000 * (round - 1) + index + 1,
                round=round,
            )
            for index in range(count)
        ]


class CompositeCritic:
    """The scripted critics, dispatched: the prop critic the seat merged,
    the render checks for the world. No 30B VLM anywhere (B2)."""

    def __init__(self, prop_critic: PropCritic, world_critic: WorldCritic,
                 plan: NightPlan) -> None:
        self.props = prop_critic
        self.world = world_critic
        self.plan = plan

    def score(self, task: Task, variant):
        if task.id.startswith(("img:", "prop:")):
            return self.props.score(task, variant)
        return self.world.score(task, variant)


class JudgeSeat:
    """The decision seam: d1-2B first, Jev below tau, standing gate,
    never-wait. Every judgment is a ledger row (the judge's own writes);
    this seat adds the night's decisions and the flow state."""

    def __init__(self, ledger: SQLiteLedger, tiles: list, library: TileLibrary,
                 d1_port: int, *, fake: bool = False) -> None:
        from core.judge.backends import FakeBackend

        self.ledger = ledger
        self.tiles = tiles
        self.library = library
        self.fake = fake
        self.judge = Judge(
            backend=FakeBackend() if fake else D1Backend(port=d1_port),
            ladder=None if fake else EscalationLadder([("jev", JevBackend())]),
            policy=ConfidencePolicy(),
            standing=StandingGate(),
            ledger=ledger,
        )
        self.tick = 0
        self.decisions: list[dict] = []
        self.mediator_calls: list[dict] = []
        self.last_confidence: float | None = None
        self.last_word: str | None = None
        self.words: list[str | None] = []
        self.critic_slope = 0.0

    # -- flow ------------------------------------------------------------------

    def in_flow(self) -> bool:
        """The knower's sign, as the night can measure it: the decision
        models confident, the standing steady, the critic's quality not
        falling. Low prediction error itself is V-JEPA's job (logged beside,
        never built on)."""
        steady = (
            self.last_confidence is not None
            and self.last_confidence >= 0.5
            and len(set(self.words[-3:])) <= 1
        )
        return bool(steady and self.critic_slope >= 0.0)

    def mediator(self, why: str, context: str) -> dict:
        """The mediator, consulted only outside flow. One Groq call; its
        cost rides the row."""
        flow = self.in_flow()
        call: dict[str, Any] = {"why": why, "in_flow": flow, "at": now_utc()}
        if self.fake:
            call.update({"ok": False, "skipped": "dry run", "wall_s": 0.0})
            self.mediator_calls.append(call)
            return call
        started = time.monotonic()
        try:
            sys.path.insert(0, str(GQ.parent))
            import gq  # noqa: PLC0415

            answer, usage = gq.ask(
                "20b",
                "One short paragraph, plain words, no praise:",
                f"{why}\n\n{context}",
            )
            call["answer"] = answer[:800]
            call["ok"] = True
            call["usage"] = usage
        except Exception as exc:  # the mediator is never load-bearing
            call["ok"] = False
            call["error"] = str(exc)[:200]
        call["wall_s"] = round(time.monotonic() - started, 2)
        self.mediator_calls.append(call)
        self.ledger.append(
            type="night.mediator_call",
            actor=CORE_ACTOR,
            subject={"entity_kind": "night", "entity_id": NIGHT_ID},
            payload=call,
        )
        return call

    # -- the decisions ---------------------------------------------------------

    def _record(self, kind: str, answer, extra: dict) -> dict:
        self.tick += 1
        judgment = answer.judgment("tile") if kind == "tile" else answer.judgments[0]
        row = {
            "decision": kind,
            "tick": self.tick,
            "confidence": judgment.confidence,
            "tau": judgment.tau,
            "gate": judgment.gate,
            "author": judgment.author,
            "backend_model": f"{judgment.backend}:{judgment.model}",
            "latency_s": answer.latency_seconds,
            "surfaced": answer.surfaced,
            "attempts": answer.attempts,
            "cost": answer.cost.model_dump(),
            "standing": answer.standing_words,
            **extra,
        }
        self.decisions.append(row)
        self.last_confidence = judgment.confidence
        self.last_word = (answer.standing_words or {}).get("tile") or judgment.gate
        self.words.append(self.last_word)
        return row

    def choose_tile(self, round_no: int, parent) -> dict:
        """The builder's decision: which tile lands next. Through the judge,
        under the standing gate, bounded by never-wait."""
        history = "; ".join(
            f"r{d['decision_round']}: {d['chosen']}" for d in self.decisions
            if d["decision"] == "tile"
        ) or "nothing yet"
        context = {"round": round_no, "history": history}
        question = Question(
            qid="tile",
            kind="choice",
            instructions=(
                "Which single change would make this courtyard feel most "
                "lived-in next? Answer with one option id."
            ),
            criteria={tile.id: tile_text(tile) for tile in self.tiles},
        )
        answer = self.judge.judge(
            "courtyard.tile.v1",
            tile_state(context, self.tiles),
            (question,),
            now=float(self.tick + 1),
            deadline_seconds=NEVER_WAIT_SECONDS,
        )
        judgment = answer.judgment("tile")
        distribution = judgment.distribution or {}
        pick = max(distribution, key=lambda k: distribution[k]) if distribution \
            else self.tiles[0].id
        tile = next(t for t in self.tiles if t.id == pick)
        row = self._record("tile", answer, {
            "decision_round": round_no,
            "chosen": tile.title,
            "distribution": distribution,
        })
        if answer.surfaced:
            self.mediator(
                "A courtyard edit decision was surfaced below tau after the "
                "whole ladder; the night needs a note on what to do with it.",
                tile_state(context, self.tiles) +
                f"\n\nThe surfaced pick was {tile.title}.")
        step = tile.steps[0]
        meta = TILES_META.get(tile.title, {})
        return {
            "tile": tile, "step": step,
            "edit": {
                "tile_id": tile.id, "word": step.word, "params": step.params,
                "seed": meta.get("engine_seed", 4000),
                "note": meta.get("note", ""),
                "placement": meta.get("placement"),
                "subject": {
                    "props.harbor.crates": "courtyard.crates",
                    "material.wood.weathering": "courtyard.weathering",
                    "props.harbor.racks": "courtyard.crates",
                }.get(step.word, "courtyard.room"),
                "predict": {"note": f"the tile's own prediction: "
                            f"{meta.get('note', '')}"},
            },
            "row": row,
        }

    def verify_concept(self, request_id: str, prompt: str) -> dict:
        """Is this prop's concept on-brief? A verify judgment per prop, over
        the prompt text (the d1 server runs text-only tonight; the row says
        so)."""
        question = Question(
            qid="on_brief",
            kind="verify",
            claim=(
                f'The concept prompt "{prompt}" serves the owner goal "a '
                f'small courtyard ... make it feel lived-in" for the '
                f'{request_id} prop.'
            ),
            evidence=(
                "the owner goal's three props are a weathered crate, a "
                "brass lantern and an iron anvil"
            ),
            instructions="Answer whether the claim holds.",
        )
        answer = self.judge.judge(
            "courtyard.prop.brief.v1",
            f"The courtyard night judges its prop concept for {request_id}.",
            (question,),
            now=float(self.tick + 1),
            deadline_seconds=NEVER_WAIT_SECONDS,
        )
        judgment = answer.judgments[0]
        row = self._record("prop_brief", answer, {
            "request_id": request_id,
            "distribution": judgment.distribution,
            "text_only": True,
        })
        return row


# ---------------------------------------------------------------- services ---


def serve_d1(heavy: Heavy, out: Path) -> dict:
    """The night's d1-2B, under the heavy lease, free-RAM bar checked."""
    import urllib.request

    health = f"http://127.0.0.1:{PORT_D1}/health"
    try:
        with urllib.request.urlopen(health, timeout=1):
            log(f"d1-2B already answers on :{PORT_D1}")
            return {"started": False, "port": PORT_D1}
    except Exception:
        pass
    logpath = out / "d1-server.log"
    with heavy.hold("start d1-2B llama-server", check_ram=True):
        proc = subprocess.Popen(
            [str(LLAMA_SERVER), "-m", str(D1_MODEL),
             "--host", "127.0.0.1", "--port", str(PORT_D1),
             "-ngl", "99", "--flash-attn", "on", "--ctx-size", "8192",
             "-ub", "4096", "--alias", "d1-2B-Q8"],
            stdout=open(logpath, "w"), stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for _ in range(360):
            try:
                with urllib.request.urlopen(health, timeout=1):
                    break
            except Exception:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"llama-server died during load; see {logpath}")
                time.sleep(1)
        else:
            raise RuntimeError("llama-server did not become healthy")
    rss_kb = int(Path(f"/proc/{proc.pid}/status").read_text()
                 .split("VmHWM:")[1].split("kB")[0].strip())
    log(f"d1-2B serving on :{PORT_D1} (pid {proc.pid}, peak RSS {rss_kb/1024:.0f} MB)")
    return {"started": True, "port": PORT_D1, "pid": proc.pid,
            "peak_rss_mb": round(rss_kb / 1024)}


def stop_d1(handle: dict) -> None:
    if not handle.get("started"):
        return
    import signal

    try:
        os.kill(handle["pid"], signal.SIGTERM)
        log("d1-2B server stopped")
    except ProcessLookupError:
        pass


def serve_comfy(heavy: Heavy) -> bool:
    """The TRELLIS.2 environment's ComfyUI, under the heavy lease."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{COMFY_URL}/system_stats", timeout=2):
            log("ComfyUI already up")
            return False
    except Exception:
        pass
    with heavy.hold("start ComfyUI (TRELLIS.2)", check_ram=True):
        result = run_cmd([TRELLIS_ROOT / "scripts" / "serve.sh", "start",
                          "--cache-none"])
        if result.returncode != 0:
            raise RuntimeError(f"serve.sh start failed: {result.stderr[-400:]}")
    for _ in range(240):
        try:
            with urllib.request.urlopen(f"{COMFY_URL}/system_stats", timeout=2):
                log("ComfyUI ready")
                return True
        except Exception:
            time.sleep(2)
    raise RuntimeError("ComfyUI did not become ready")


def stop_comfy(started: bool) -> None:
    if not started:
        return
    run_cmd([TRELLIS_ROOT / "scripts" / "serve.sh", "stop"])
    log("ComfyUI stopped")


# --------------------------------------------------------------- live view ---


def world_stream(wires: list[dict], heavy: Heavy, out: Path) -> dict:
    """The night's recipe changes compile to world-stream deltas.

    The source scene is a real Infinigen 2.0 generation, exported to glTF by
    the world-stream team's tool; the recipe is compiled, then each applied
    tile's placement lands as the wire's transform edit. Delta sizes are the
    record. Props do not ride this wire today: instance.add with new
    geometry is the fragment-GLB delta, designed but not implemented.
    """
    rows: dict[str, Any] = {"export": {}, "compile": [], "deltas": [],
                            "screenshot": {}}
    export_dir = out / "worldstream" / "export"
    compiler = SCRATCH / "compiler"

    with heavy.hold("Infinigen 2.0 scene export (CPU generation + glTF)"):
        started = time.monotonic()
        result = run_cmd(
            [V2_HOME / ".venv" / "bin" / "python",
             SCRATCH / "export_scene.py",
             "--generator", "room_livingroom_rand", "--seed", str(WORLD_SEED),
             "--outdir", export_dir],
            cwd=SCRATCH, timeout=3600)
    if result.returncode != 0 or not (export_dir / "source.glb").exists():
        rows["export"]["error"] = (result.stderr or result.stdout)[-800:]
        log(f"scene export failed; the live view carries what compiled: "
            f"{rows['export']['error'][:200]}")
        return rows
    rows["export"] = {
        "wall_s": round(time.monotonic() - started, 1),
        "stats": json.loads((export_dir / "source.export_stats.json").read_text()),
    }

    build = out / "worldstream" / "build"
    v1 = out / "worldstream" / "v1.json"

    def node(*argv: str) -> subprocess.CompletedProcess:
        return run_cmd(["node", "worldc.mjs", *argv], cwd=compiler,
                       timeout=1800)

    result = node("recipe", "--source", export_dir / "source.glb",
                  "--world", "courtyard", "--branch", "main", "--version", "1",
                  "--meta", "generator=room_livingroom_rand",
                  "--meta", f"seed={WORLD_SEED}",
                  "--meta", "engine=infinigen@2.0.0a3+bpy4.2",
                  "--out", v1)
    if result.returncode != 0:
        rows["compile"].append({"step": "recipe", "error": result.stderr[-500:]})
        return rows
    result = node("build", "--recipe", v1, "--source", export_dir / "source.glb",
                  "--out", build, "--jobs", "14")
    if result.returncode != 0:
        rows["compile"].append({"step": "build", "error": result.stderr[-500:]})
        return rows
    rows["compile"].append({
        "step": "v1", "glb_bytes": (build / "world@1.glb").stat().st_size,
    })

    # each applied tile's placement, as the wire's transform edit
    prev = v1
    version = 1
    recipe = json.loads(v1.read_text())
    for wire in wires:
        placement = wire.get("placement")
        if not placement:
            rows["deltas"].append({
                "round": wire["round"], "tile": wire["tile"], "word": wire["word"],
                "delta_bytes": 0,
                "note": "the wire's vocabulary is transforms-only today; the "
                        "word's params ride the engine recipe, not the wire",
            })
            continue
        ids = sorted(e["id"] for e in recipe["entries"])
        pick = next((i for i in ids
                     if re.search(placement["match"], i.lower())), None)
        if pick is None:
            rows["deltas"].append({
                "round": wire["round"], "tile": wire["tile"],
                "error": f"no instance matches {placement['match']!r}",
            })
            continue
        move = placement["move"]
        version += 1
        new_recipe = out / "worldstream" / f"v{version}.json"
        result = node("edit", "--in", prev, "--id", pick,
                      "--move", ",".join(str(m) for m in move),
                      "--author", "Architect",
                      "--note", (wire.get("note") or "night-v3 edit")[:80],
                      "--out", new_recipe)
        if result.returncode != 0:
            rows["deltas"].append({"round": wire["round"],
                                   "error": result.stderr[-400:]})
            continue
        result = node("delta", "--old", prev, "--new", new_recipe,
                      "--out", build)
        delta_file = build / f"world@{version}.since{version - 1}.json"
        row = {
            "round": wire["round"], "tile": wire["tile"], "word": wire["word"],
            "instance": pick, "move": move,
            "delta_bytes": delta_file.stat().st_size if delta_file.exists() else None,
        }
        rows["deltas"].append(row)
        recipe = json.loads(new_recipe.read_text())
        prev = new_recipe

    rows["head_version"] = version
    return rows


def shoot(build: Path, out: Path) -> dict:
    """The viewer at the night's end state, screenshotted by Playwright."""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, DEMO_DELAY_MS="0")
    server = subprocess.Popen(
        ["node", "server.mjs", str(build), "--port", str(port)],
        cwd=VIEWER, env=env, stdout=open(out / "viewer.log", "w"),
        stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(2)
    try:
        result = run_cmd(["node", str(SHOT), f"http://127.0.0.1:{port}/",
                          str(out / "night-end-state.png")], timeout=120)
        body = result.stdout.strip()
        try:
            return json.loads(body.splitlines()[-1])
        except Exception:
            return {"raw": body[-400:], "returncode": result.returncode}
    finally:
        server.terminate()


# --------------------------------------------------------------- the band ----


def fold_attempts(ledger: SQLiteLedger) -> dict[str, list[dict]]:
    """Per-task attempts with their scores, in round order."""
    by_task: dict[str, list[dict]] = {}
    for event in ledger.events():
        if event.type != "task.attempt":
            continue
        payload = event.payload
        by_task.setdefault(payload.get("task_id", ""), []).append(payload)
    return by_task


def round_scores(attempts: list[dict]) -> dict[int, float]:
    best: dict[int, float] = {}
    for attempt in attempts:
        rnd = attempt.get("round", 1)
        best[rnd] = max(best.get(rnd, 0.0), attempt.get("score", 0.0))
    return best


def the_band(ledger: SQLiteLedger, slopes: dict[str, float],
             rails_left: Rail) -> dict:
    """The chorus: the loop rising fastest is granted another round, taken
    from the loop gone flat. Each cue, its grant and its funding are rows."""
    if not slopes:
        return {"cues": []}
    rising = max(slopes, key=slopes.get)
    flat = min(slopes, key=slopes.get)
    cue = {
        "rising": rising, "rising_slope": round(slopes[rising], 4),
        "flat": flat, "flat_slope": round(slopes[flat], 4),
    }
    if rising == flat or slopes[rising] <= 0.001:
        cue["granted"] = False
        cue["why"] = "no loop is rising fast enough to take a chorus from"
        ledger.append(
            type="band.cue", actor=SCHEDULER_ACTOR,
            subject={"entity_kind": "night", "entity_id": NIGHT_ID},
            payload=cue)
        return {"cues": [cue]}
    cue["granted"] = True
    cue["grant"] = f"one more round for {rising} (the chorus)"
    cue["funded_by"] = (
        f"{flat}'s unspent rail: {rails_left.gpu_minutes:.2f} GPU-min, "
        f"{rails_left.wall_minutes:.1f} wall-min"
    )
    ledger.append(
        type="band.cue", actor=SCHEDULER_ACTOR,
        subject={"entity_kind": "night", "entity_id": NIGHT_ID},
        payload=cue)
    log(f"the band: {rising} is rising ({slopes[rising]:.4f}); it takes "
        f"another chorus from {flat} ({slopes[flat]:.4f})")
    return {"cues": [cue], "rising": rising, "flat": flat}


# --------------------------------------------------------------- the night ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_night.py")
    parser.add_argument("--out", type=Path, default=REPO / "artifacts" / NIGHT_ID)
    parser.add_argument("--dry-run", action="store_true",
                        help="the whole wiring on the fake engine and the "
                             "fake judge: no services, no props, no live view")
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "world").mkdir(exist_ok=True)
    load_secrets()

    t0 = time.monotonic()
    state_before = box_state()
    log(f"the night begins; box: {state_before}")

    ledger = SQLiteLedger(out / "ledger.db")
    heavy = Heavy(ledger, enabled=not args.dry_run)
    ledger.append(
        type="night.box_state", actor=CORE_ACTOR,
        subject={"entity_kind": "night", "entity_id": NIGHT_ID},
        payload={"phase": "before", **state_before})

    d1_handle: dict = {}
    comfy_started = False
    try:
        # -- services ---------------------------------------------------------
        if not args.dry_run:
            d1_handle = serve_d1(heavy, out)
            comfy_started = serve_comfy(heavy)

        # -- the pieces -------------------------------------------------------
        if args.dry_run:
            requests, plan = [], None
        else:
            requests = [
                PropRequest.model_validate(row) for row in json.loads(
                    (Path(__file__).parent / "courtyard_requests.json").read_text())
            ]
            plan = NightPlan(list(requests))
        store = PropStore()
        registry = VocabularyRegistry(default_entries())
        library = TileLibrary(registry=registry, ledger=ledger)
        tiles = author_tiles(library)

        if args.dry_run:
            engine = open_engine({"flavour": "fake"})
        else:
            engine_spec = {
                "flavour": "infinigen-2-procfunc", "runtime": "venv",
                "python": str(V2_HOME / ".venv" / "bin" / "python"),
                "repo": str(V2_HOME / "src" / "infinigen-upstream"),
                "repo_name": "princeton-vl/infinigen",
                "generators": dict(GENERATORS),
                "output_dir": str(out / "world" / "engine"),
            }
            engine = open_engine(engine_spec)
        world = WorldState(engine, out)

        if args.dry_run:
            templates = client = prop_exec = None
        else:
            templates = Templates(
                image=load_template(TRELLIS_ROOT / "workflows" / "text2image.api.json"),
                trellis=load_template(TRELLIS_ROOT / "workflows" / "trellis2_512.api.json"),
            )
            client = ComfyClient(COMFY_URL, output_root=TRELLIS_ROOT / "out")
            prop_exec = PropExecutor(client=client, plan=plan, store=store,
                                     templates=templates)

        judge_seat = JudgeSeat(ledger, tiles, library, PORT_D1,
                               fake=args.dry_run)

        # -- the plan, priced and admitted ------------------------------------
        prop_jobs: list[PlannedJob] = []
        priced_rows = []
        if plan is not None:
            prop_jobs = [
                PlannedJob(id=task.id, intention=task.intention,
                           ask=task.cost_estimate,
                           model=plan.model_for(task.id))
                for task in plan.tasks
            ]
        world_jobs = []
        for task_id, intention in (
            ("world.base", "the courtyard's baseline: room, crates and "
                          "weathering through the engine seam, rung 2"),
            ("world.edit", "two edit rounds: the judge's chosen tile applied "
                           "to the recipe, rendered, and the splice measured"),
        ):
            priced = price_job("rung.2")
            world_jobs.append(PlannedJob(
                id=task_id, intention=intention, ask=priced.ask, kind="rung.2"))
            priced_rows.append({
                "task_id": task_id, "kind": "rung.2", "basis": priced.basis,
                "source": priced.source, "ask": priced.ask.model_dump(),
                "rail": priced.rail.model_dump(), "intention": intention})

        # the prop concepts, verified on-brief through the judge
        for request in requests:
            judge_seat.verify_concept(request.id, request.prompt)

        rails = Rail(gpu_minutes=60.0, wall_minutes=240.0, hosted_cents=100)
        jobs = world_jobs + prop_jobs
        check = admission_check(jobs, rails)
        estimate = owner_estimate(jobs, rails, check=check)
        pricing = {
            "two_lines": estimate.lines(), "fits": estimate.fits,
            "cut": estimate.cut, "parked": estimate.parked,
            "joules": estimate.joules,
            "ask": estimate.ask.model_dump(), "rails": rails.model_dump(),
            "owner_goal": "a small courtyard with three props: a weathered "
                          "crate, a brass lantern, an iron anvil; make it "
                          "feel lived-in",
            "world_tasks": priced_rows,
            "prop_tasks": [
                {"task_id": t.id, "kind": t.kind, "basis": t.ask_basis,
                 "ask": t.cost_estimate.model_dump()} for t in (plan.tasks if plan else [])
            ],
        }
        (out / "pricing.json").write_text(json.dumps(pricing, indent=2))
        ledger.append(
            type="night.preflight", actor=CORE_ACTOR,
            subject={"entity_kind": "night", "entity_id": NIGHT_ID},
            payload={
                "box": state_before,
                "services": {"d1": d1_handle.get("port"),
                             "comfy_started": comfy_started},
                "two_lines": estimate.lines(),
                "admission": {"fits": check.fits, "cut": check.cut,
                              "parked": check.parked},
                "pricing_file": "pricing.json",
            })
        log("the owner's two lines:")
        for line in estimate.lines():
            log(f"  {line}")

        # -- the critics and sources ------------------------------------------
        by_task = {task.id: plan.request(task.id) for task in plan.tasks} \
            if plan is not None else {}
        prop_critic = PropCritic(requests=by_task, store=store, plan=plan)
        world_critic = WorldCritic(world, ledger)
        critic = CompositeCritic(prop_critic, world_critic, plan)
        sources = CompositeVariants(plan, judge_seat, ledger)
        wires: list[dict] = []
        executor = CompositeExecutor(world, prop_exec, heavy, ledger,
                                     judge_seat, wires)

        # -- wave 1: the whole plan through the one runner ---------------------
        iteration = IterationPolicy(variants_per_round=3, max_rounds=2,
                                    min_gain=0.02)
        runner = NightRunner(
            ledger, executor, night_id=NIGHT_ID, rails=rails,
            clock=MeasuredClock(), load_budget={"sd_xl_base_1.0": 1,
                                                "trellis2": 1},
            variant_source=sources, critic=critic, iteration=iteration,
        )
        tasks = [
            Task(id="world.base", night=NIGHT_ID, author="casey",
                 intention=world_jobs[0].intention,
                 cost_estimate=world_jobs[0].ask, kind="rung.2",
                 ask_source="model", ask_basis="measured"),
            Task(id="world.edit", night=NIGHT_ID, author="casey",
                 intention=world_jobs[1].intention,
                 cost_estimate=world_jobs[1].ask, kind="rung.2",
                 ask_source="model", ask_basis="measured"),
        ] + (list(plan.tasks) if plan is not None else [])
        runner.start(tasks)
        runner.run()
        runner.stop()
        log(f"wave 1 done: {runner.status.first_line if runner.status else '?'}")

        # -- the band: the chorus ----------------------------------------------
        attempts = fold_attempts(ledger)
        slopes: dict[str, float] = {}
        for task_id, rows in attempts.items():
            scores = round_scores(rows)
            rounds = sorted(scores)
            if len(rounds) >= 2:
                slopes[task_id] = scores[rounds[-1]] - scores[rounds[-2]]
        left = runner.budget.remaining
        band = the_band(ledger, slopes, left)

        chorus_effect: dict[str, Any] = {"cues": band.get("cues", [])}
        if band.get("granted"):
            rising = band["rising"]
            scores_before = round_scores(attempts[rising])
            prev_best = max(scores_before.values()) if scores_before else 0.0
            jobs_done_before = sum(
                1 for e in ledger.events() if e.type == "job.done")
            sources.seed_offset = 2000
            chorus_runner = NightRunner(
                ledger, executor, night_id=f"{NIGHT_ID}-chorus", rails=left,
                clock=MeasuredClock(),
                load_budget={"sd_xl_base_1.0": 1, "trellis2": 1},
                variant_source=sources, critic=critic,
                iteration=IterationPolicy(variants_per_round=3, max_rounds=1,
                                          min_gain=0.0),
            )
            chorus_task = next(t for t in tasks if t.id == rising)
            chorus_task = chorus_task.model_copy(update={
                "night": f"{NIGHT_ID}-chorus",
                "state": "slated",
            })
            chorus_runner.start([chorus_task])
            chorus_runner.run()
            chorus_runner.stop()
            fresh = [
                e.payload for e in ledger.events()[jobs_done_before:]
                if e.type == "job.done" and e.payload.get("task_id") == rising
            ]
            after = round_scores(fresh)
            new_best = max(after.values()) if after else 0.0
            chorus_effect[rising] = {
                "best_before": round(prev_best, 4),
                "best_after": round(new_best, 4),
                "improved": new_best > prev_best,
                "fresh_round_scores": {str(k): round(v, 4)
                                       for k, v in after.items()},
            }
            ledger.append(
                type="band.effect", actor=SCHEDULER_ACTOR,
                subject={"entity_kind": "night", "entity_id": NIGHT_ID},
                payload={"loop": rising, **{
                    k: v for k, v in chorus_effect[rising].items()
                    if k != "fresh_round_scores"}})

        # -- the live view ------------------------------------------------------
        ws: dict[str, Any] = {"skipped": "dry run"}
        if not args.dry_run:
            log("compiling the night's recipe changes to world-stream deltas")
            ws = world_stream(wires, heavy, out)
            if ws.get("head_version"):
                ws["screenshot"] = shoot(out / "worldstream" / "build", out)
            (out / "live-view.json").write_text(json.dumps(ws, indent=2))
            ledger.append(
                type="night.live_view", actor=CORE_ACTOR,
                subject={"entity_kind": "night", "entity_id": NIGHT_ID},
                payload={
                    "export_wall_s": ws.get("export", {}).get("wall_s"),
                    "head_version": ws.get("head_version"),
                    "deltas": [
                        {k: d.get(k) for k in
                         ("round", "tile", "word", "instance", "delta_bytes",
                          "error", "note")}
                        for d in ws.get("deltas", [])
                    ],
                    "screenshot_hud": (ws.get("screenshot") or {}).get("hud", "")[:200],
                    "full_file": "live-view.json",
                })

        # -- the critic's slope, for the flow ledger ---------------------------
        tile_rows = [d for d in judge_seat.decisions if d["decision"] == "tile"]
        if tile_rows:
            judge_seat.critic_slope = slopes.get("world.edit", 0.0)

        # -- the morning --------------------------------------------------------
        attempts_all = fold_attempts(ledger)
        core_report = build_report(ledger.events())
        status = core_report.status if hasattr(core_report, "status") else None
        winners = _winners(plan, store, core_report) if plan is not None else []
        props_summary = {
            "generated": sum(len(rows) for tid, rows in attempts_all.items()
                             if tid.startswith("img:")),
            "meshes": sum(len(rows) for tid, rows in attempts_all.items()
                          if tid.startswith("prop:")),
            "kept": len(winners),
            "winners": [
                {"request": w.request_id, "variant": w.variant_id,
                 "score": w.score, "watertight": w.watertight,
                 "triangles": w.triangles, "beat": w.beaten}
                for w in winners
            ],
        }
        decisions_summary = summarise_decisions(judge_seat)
        state_after = box_state()

        morning = {
            "night_id": NIGHT_ID,
            "generated_at": now_utc(),
            "owner_goal": "a small courtyard with three props: a weathered "
                          "crate, a brass lantern, an iron anvil; make it "
                          "feel lived-in",
            "status": (status.model_dump() if status is not None and
                       hasattr(status, "model_dump") else str(status)),
            "box_before": state_before,
            "box_after": state_after,
            "two_lines": estimate.lines(),
            "admission": {"fits": check.fits, "cut": check.cut,
                          "parked": check.parked},
            "props": props_summary,
            "decisions": decisions_summary,
            "band": chorus_effect,
            "splice": world.splice,
            "live_view": ws,
            "wall_minutes": round((time.monotonic() - t0) / 60.0, 2),
        }
        (out / "morning.json").write_text(json.dumps(morning, indent=2))
        (out / "report.json").write_text(core_report.model_dump_json(indent=2))
        (out / "report.txt").write_text(render_text(core_report) + "\n")
        (out / "report.html").write_text(render_html(core_report))
        (out / "morning.txt").write_text(render_morning_text(morning))
        spoken = what_happened(morning, judge_seat)
        (out / "what-happened.txt").write_text(spoken + "\n")
        ledger.append(
            type="line.spoken", actor=CORE_ACTOR,
            subject={"entity_kind": "night", "entity_id": NIGHT_ID},
            payload={"line": spoken})
        log(f"the night's morning is in {out}")
        log(spoken)
        return 0
    finally:
        stop_comfy(comfy_started)
        stop_d1(d1_handle)
        ledger.append(
            type="night.box_state", actor=CORE_ACTOR,
            subject={"entity_kind": "night", "entity_id": NIGHT_ID},
            payload={"phase": "after", **box_state()})
        ledger.close()


def summarise_decisions(seat: JudgeSeat) -> dict:
    rows = seat.decisions
    latencies = [d["latency_s"] for d in rows if d.get("latency_s")]
    local = [d for d in rows if d["author"].startswith("judge@d1")]
    escalated = [d for d in rows if "jev" in d["author"] or "clef" in d["author"]]
    flickers = sum(
        1 for a, b in zip(seat.words, seat.words[1:]) if a != b)
    return {
        "count": len(rows),
        "local": len(local),
        "escalated": len(escalated),
        "surfaced": sum(1 for d in rows if d.get("surfaced")),
        "latency_p50_s": round(statistics.median(latencies), 3) if latencies else None,
        "latency_p95_s": (round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3)
                          if len(latencies) >= 2 else None),
        "standing_flickers": flickers,
        "never_wait_seconds": NEVER_WAIT_SECONDS,
        "rows": rows,
        "mediator_calls": seat.mediator_calls,
        "mediator_in_flow": sum(1 for c in seat.mediator_calls if c["in_flow"]),
        "mediator_out_flow": sum(1 for c in seat.mediator_calls if not c["in_flow"]),
    }


def render_morning_text(m: dict) -> str:
    lines = [f"=== {m['night_id']} — the morning", ""]
    lines.append(f"the owner's goal: {m['owner_goal']}")
    lines.append("")
    lines.append("the two lines, from before the night ran:")
    for line in m["two_lines"]:
        lines.append(f"  {line}")
    lines.append("")
    st = m.get("status")
    lines.append(f"status: {st}")
    lines.append(f"wall: {m['wall_minutes']} min")
    lines.append("")
    lines.append("the props:")
    p = m["props"]
    lines.append(f"  {p['generated']} concepts, {p['meshes']} meshes, "
                 f"{p['kept']} kept")
    for w in p["winners"]:
        lines.append(f"  · {w['request']}: {w['variant']} scored {w['score']:.3f} "
                     f"({'watertight' if w['watertight'] else 'NOT watertight'}, "
                     f"{w['triangles']:,} tris) beat {', '.join(w['beat'])}")
    lines.append("")
    d = m["decisions"]
    lines.append("the decisions:")
    lines.append(f"  {d['count']} judgments — {d['local']} local (d1), "
                 f"{d['escalated']} escalated, {d['surfaced']} surfaced; "
                 f"p50 {d['latency_p50_s']} s, standing flickers "
                 f"{d['standing_flickers']}")
    lines.append(f"  the mediator: {d['mediator_in_flow']} calls in flow, "
                 f"{d['mediator_out_flow']} out")
    lines.append("")
    lines.append("the band:")
    for cue in m["band"].get("cues", []):
        lines.append(f"  · rising {cue.get('rising')} ({cue.get('rising_slope')}), "
                     f"flat {cue.get('flat')} ({cue.get('flat_slope')}), "
                     f"granted: {cue.get('granted')}")
    for key, effect in m["band"].items():
        if key == "cues":
            continue
        lines.append(f"  · the chorus's effect on {key}: {effect}")
    lines.append("")
    lines.append("the splice (scoped vs full stage, at the seam):")
    for row in m["splice"]:
        lines.append(f"  · {row['label']}: full {row['full_stage_s']} s, "
                     f"scoped {row['scoped_stage_s']} s "
                     f"({row['ratio']}x)")
    lines.append("")
    lines.append("the live view:")
    ws = m["live_view"]
    if ws.get("export", {}).get("wall_s"):
        lines.append(f"  · the scene exported in {ws['export']['wall_s']} s "
                     f"({ws['export']['stats']['objects']} objects, "
                     f"{ws['export']['stats']['triangles_approx']:,} triangles)")
    for delta in ws.get("deltas", []):
        if "error" in delta:
            lines.append(f"  · round {delta.get('round')}: {delta['error']}")
        else:
            lines.append(f"  · round {delta.get('round')}: {delta.get('word')} "
                         f"→ {delta.get('instance')} moved "
                         f"{delta.get('move')}; delta {delta.get('delta_bytes')} B")
    if ws.get("screenshot"):
        lines.append(f"  · the end state: {ws['screenshot']}")
    return "\n".join(lines)


def what_happened(m: dict, seat: JudgeSeat) -> str:
    """The short answer to "what happened last night?", composed from the
    ledger — the first mile on the ProArt can speak this later."""
    p = m["props"]
    d = m["decisions"]
    parts = [f"Last night the crew built the courtyard: "
             f"{p['kept']} of {p['meshes']} props kept"]
    winners = ", ".join(f"the {w['request']} at {w['score']:.2f}"
                        for w in p["winners"])
    if winners:
        parts.append(f"({winners})")
    if m["band"].get("cues"):
        cue = m["band"]["cues"][0]
        if cue.get("granted"):
            parts.append(f"the band gave the {cue['rising']} loop another "
                         f"chorus because it was rising fastest")
    parts.append(f"{d['count']} decisions were made, {d['local']} answered "
                 f"locally in about {d['latency_p50_s']} s")
    ws = m["live_view"]
    deltas = [x for x in ws.get("deltas", []) if "delta_bytes" in x]
    if deltas:
        total = sum(x["delta_bytes"] for x in deltas)
        parts.append(f"{len(deltas)} changes went out to the live view as "
                     f"{total:,} bytes of deltas")
    if ws.get("screenshot", {}).get("hud"):
        parts.append("the end state is on screen")
    return ". ".join(parts) + "."


if __name__ == "__main__":
    sys.exit(main())
