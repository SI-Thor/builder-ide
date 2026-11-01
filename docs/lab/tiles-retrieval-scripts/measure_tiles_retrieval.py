#!/usr/bin/env python3
"""E1: the embedding fast path against the bandit, on the tiles acceptance rig.

**The question.** ``docs/research/pincher-fit.md`` §E1: *"offline replay
over the tiles logs. Embedding fast path at ≥ 0.80, falling back to the
bandit's logged choice. It beats the bandit if it covers ≥ 30 % of contexts,
its reward is within ε of the bandit's, and p95 is under 50 ms."*

And the settling experiment it belongs to: bandit only, pincher-style
similarity only, retrieval then bandit — *"measure win rate, latency, and
how fast each improves with use."*

**The rig** is the tiles acceptance rig's own
(``tests/tiles/test_acceptance_learning.py``), kept identical so the numbers
sit beside its published ones: six tiles in the M1 slice's crates word (two
per style), 600 plays over the same seeded context sequence, and a game
that pays 0.85 for the style the context asked for and 0.15 otherwise. The
draws are sha256-seeded by (tile, bucket, play index), so **every arm plays
the identical game** and a difference between arms is a difference between
the policies, not between the luck.

**Four arms, all on the same 600 contexts:**

* **bandit** — the contextual bandit from zero. The floor to beat.
* **retrieval-only** — pincher's similarity pick: the top tile by meaning,
  every time. No learning at all.
* **retrieval-bandit** — the front retrieves K, the bandit chooses among
  them. The learning stays.
* **fastpath** — E1's policy, replayed over the bandit's log: the
  retrieved tile when the score clears τ, the band's logged choice
  otherwise.

**And the bands.** The three bands (execute / confirm / compile) are read
from the same scores: at or above τ_hi the tile is executed outright, in the
gap it is played but marked confirmed, and below τ_lo **nothing is played**
and a request goes to the cloud author. The band distribution over the
rig's contexts is reported, and so is what the band does to the play count.

**Two readings of the same question, because they answer different ones.**

* The **direct replay** is exact. The rig's game is a seeded function, so
  any policy's win rate over the 600 contexts can be computed, not
  estimated. This is what settles E1 on this rig.
* The **OPE estimate** uses the log alone — the estimators in
  ``core.tiles.ope`` — which is what a real night would have. It is
  reported beside the direct value, and the gap between them is the
  quantity the log cannot recover: the plays where the logger and the
  target disagreed. On those plays the log holds the logger's outcome,
  not the target's, and no estimator can invent the missing one.

Run from the repo root::

    PYTHONPATH=. python docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py

It needs numpy, the repo's own ``core.tiles``, and (for the static
embedder) the ``embed`` extra. Without that extra it runs the hashing
fallback and says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from core.night.ledger import InMemoryLedger  # noqa: E402
from core.tiles.bands import BandConfig, BandGate  # noqa: E402
from core.tiles.chooser import ContextualBandit  # noqa: E402
from core.tiles.library import TileLibrary  # noqa: E402
from core.tiles.author import AuthorRequest, ScriptedAuthor  # noqa: E402
from core.tiles.models import Outcome  # noqa: E402
from core.tiles.ope import DeterministicTarget, evaluate  # noqa: E402
from core.tiles.plays import fold_plays, record_play  # noqa: E402
from core.tiles.retrieval import (  # noqa: E402
    HashingEmbedder,
    RetrievalChooser,
    RetrievalFront,
    TileIndex,
    default_embedder,
    embedder_record,
)
from core.tiles.stats import (  # noqa: E402
    newcombe_difference,
    two_proportion_z,
    wilson_interval,
)
from core.vocab.registry import VocabularyRegistry  # noqa: E402
from core.vocab.words import default_entries  # noqa: E402

#: The rig asks for a style by name. A real request does not: it says the
#: same thing in other words. These are the two sets the probe asks for —
#: the rig's own literal form, and a paraphrase of it — because the rig
#: cannot show the difference between an embedder that matches words and
#: one that matches meaning, and that difference is the whole reason the
#: static model exists.
LITERAL_REQUESTS = {
    "plain": "plain crates",
    "weathered": "weathered crates",
    "stained": "stained crates",
}

PARAPHRASE_REQUESTS = {
    "plain": "unpainted bare timber",
    "weathered": "worn and aged timber",
    "stained": "darkened with dye",
}


def paraphrase_probe(front, tiles_by_id):
    """How well the front separates the right style from the wrong ones.

    The measure is the **margin**: the best matching-style candidate's
    score minus the best mismatching candidate's score. A rank would be
    measured in six tiles and a half — the margin is a number, and it says
    the same thing for both embedders.

    A positive margin means the right style is on top; a negative one means
    the front would have handed back a tile of the wrong style.
    """
    rows = []
    for kind, requests in (
        ("literal", LITERAL_REQUESTS),
        ("paraphrase", PARAPHRASE_REQUESTS),
    ):
        for style, request in requests.items():
            result = front.retrieve({"phase": "dusk", "wanted_style": request})
            matching = [
                score
                for tile, score in zip(result.candidates, result.scores)
                if tiles_by_id[tile.id].steps[0].params["style"] == style
            ]
            other = [
                score
                for tile, score in zip(result.candidates, result.scores)
                if tiles_by_id[tile.id].steps[0].params["style"] != style
            ]
            best_match = max(matching) if matching else None
            best_other = max(other) if other else None
            margin = (
                best_match - best_other
                if best_match is not None and best_other is not None
                else None
            )
            rows.append(
                {
                    "kind": kind,
                    "style": style,
                    "request": request,
                    "best_matching_score": round(best_match, 6)
                    if best_match is not None
                    else None,
                    "best_mismatching_score": round(best_other, 6)
                    if best_other is not None
                    else None,
                    "margin": round(margin, 6) if margin is not None else None,
                    "right_style_on_top": bool(margin is not None and margin > 0),
                }
            )
    return rows


# ---------------------------------------------------------------- the rig ----

#: The acceptance rig's constants, kept identical so the numbers sit
#: beside its published ones.
STYLES = ("plain", "weathered", "stained")
P_MATCH, P_MISS = 0.85, 0.15

#: The number of plays the rig runs.
N_PLAYS = 600

#: The context seed the rig uses.
CONTEXT_SEED = 17

#: The bandit's seed — the judge's cold-start measurement uses the same one.
BANDIT_SEED = 7

#: E1's threshold: the fast path fires at or above this score.
TAU_HI = 0.80

#: The low line: below it, nothing is played and a new tile is compiled.
TAU_LO = 0.55

#: The shortlist the front hands the bandit.
K_SHORTLIST = 3

#: E1's bar for the fast path's coverage.
COVERAGE_BAR = 0.30

#: E1's bar for p95 latency, in milliseconds.
P95_BAR_MS = 50.0

#: E1's ε: how far the fast path's reward may sit below the bandit's.
EPSILON = 0.02

def author_tiles(library: TileLibrary, registry):
    """The scripted cloud author's six tiles — the acceptance rig's own.

    The rig uses ``ScriptedAuthor`` with the same specs, the same request
    and the same registry, so the tiles have the same ids, and the game's
    sha256 draw — which is keyed on the tile id — is the same game the
    acceptance run played. That is what makes the numbers in this note
    comparable with the published ones instead of merely similar.
    """
    specs = []
    for style in STYLES:
        for attempt in (1, 2):
            specs.append(
                {
                    "family": "harbor.crates.style",
                    "kind": "recipe_edit",
                    "title": f"{style} crates, take {attempt}",
                    "steps": [
                        {
                            "word": "props.harbor.crates",
                            "path": "harbor.crates",
                            "params": {"count": 12, "style": style, "from_library": 0},
                        }
                    ],
                }
            )
    author = ScriptedAuthor(specs, registry=registry)
    tiles = author.write(
        AuthorRequest(
            goal="make the crates read the way the builder wants them",
            words=("props.harbor.crates",),
        )
    )
    for tile in tiles:
        library.add(tile)
    return tiles


def contexts(n: int, seed: int = CONTEXT_SEED) -> list[dict]:
    """The night's contexts — the acceptance rig's own generator."""
    rng = random.Random(seed)
    styles = [STYLES[index % len(STYLES)] for index in range(n)]
    rng.shuffle(styles)
    return [{"phase": "dusk", "wanted_style": style} for style in styles]


def game_draw(tile_id: str, bucket: str, play_index: int) -> float:
    """A seeded draw in [0, 1) — reproducible, identical across arms."""
    digest = hashlib.sha256(f"{tile_id}|{bucket}|{play_index}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def play_outcome(tile, context: dict, bucket: str, play_index: int) -> Outcome:
    """The simulated game's verdict — the acceptance rig's, verbatim in shape."""
    style = tile.steps[0].params["style"]
    chance = P_MATCH if style == context["wanted_style"] else P_MISS
    won = game_draw(tile.id, bucket, play_index) < chance
    return Outcome(
        result="win" if won else "lose",
        measure="critic",
        detail="the crates read the way the context asked for"
        if won
        else "the crates read wrong",
    )


def bucket_of(context: dict) -> str:
    """The bucket the rig's bandit branches on."""
    return f"wanted_style={context['wanted_style']}"


# ------------------------------------------------------------ the box state --


def box_state() -> dict:
    """The machine the numbers were measured on."""
    state: dict[str, Any] = {
        "ts": time.time(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    try:
        state["load1"] = round(os.getloadavg()[0], 2)
        state["cpus"] = os.cpu_count()
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    state["mem_available_gb"] = round(int(line.split()[1]) / 1048576, 1)
                    break
    except OSError:
        pass
    try:
        with open("/proc/cpuinfo") as handle:
            for line in handle:
                if line.startswith("model name"):
                    state["cpu"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    try:
        import numpy

        state["numpy"] = numpy.__version__
    except ImportError:
        pass
    try:
        import model2vec

        state["model2vec"] = getattr(model2vec, "__version__", "unknown")
    except ImportError:
        state["model2vec"] = "not installed (the hashing fallback was used)"
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=8,
        ).stdout.strip()
        if out:
            state["gpu"] = out.splitlines()[0]
    except Exception:
        pass
    return state


# --------------------------------------------------------------- the arms ----


def _bandit(seed: int = BANDIT_SEED) -> ContextualBandit:
    """The rig's bandit: the acceptance rig's own chooser."""
    return ContextualBandit(
        feature_keys=("wanted_style",),
        epsilon=0.25,
        epsilon_decay=0.995,
        min_epsilon=0.02,
        seed=seed,
    )


def run_bandit(tiles, contexts_list, n_plays, library):
    """Arm A: the bandit from zero. The floor."""
    ledger = InMemoryLedger()
    chooser = _bandit()
    by_id = {tile.id: tile for tile in tiles}
    picks, wins, latencies = [], [], []
    for index, context in enumerate(contexts_list[:n_plays]):
        bucket = bucket_of(context)
        start = time.perf_counter()
        choice = chooser.choose(context, tiles)
        latencies.append((time.perf_counter() - start) * 1000.0)
        tile = by_id[choice.tile_id]
        outcome = play_outcome(tile, context, bucket, index)
        record = record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            chooser=chooser.name,
            chooser_version=chooser.version,
            propensity=choice.propensity,
            candidates=choice.candidates,
        )
        chooser.update(record)
        picks.append(choice.tile_id)
        wins.append(outcome.result == "win")
    return {
        "picks": picks,
        "wins": wins,
        "latencies_ms": latencies,
        "records": fold_plays(ledger.events()),
        "chooser": chooser.name,
    }


def run_retrieval_only(tiles, contexts_list, n_plays, library, front):
    """Arm B: pincher's similarity pick. The top tile by meaning, every time."""
    ledger = InMemoryLedger()
    by_id = {tile.id: tile for tile in tiles}
    picks, wins, latencies, scores = [], [], [], []
    for index, context in enumerate(contexts_list[:n_plays]):
        bucket = bucket_of(context)
        start = time.perf_counter()
        result = front.retrieve(context)
        latencies.append((time.perf_counter() - start) * 1000.0)
        scores.append(result.top_score)
        if not result.candidates:
            continue
        tile = result.candidates[0]
        outcome = play_outcome(tile, context, bucket, index)
        record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            chooser="retrieval-only/v1",
            chooser_version="1",
            propensity=1.0,
            candidates=tuple(candidate.id for candidate in result.candidates),
        )
        picks.append(tile.id)
        wins.append(outcome.result == "win")
    return {
        "picks": picks,
        "wins": wins,
        "latencies_ms": latencies,
        "scores": scores,
        "chooser": "retrieval-only/v1",
    }


def run_retrieval_bandit(tiles, contexts_list, n_plays, library, front):
    """Arm C: retrieve K, then the bandit chooses among them."""
    ledger = InMemoryLedger()
    chooser = RetrievalChooser(front=front, inner=_bandit())
    by_id = {tile.id: tile for tile in tiles}
    picks, wins, latencies, scores = [], [], [], []
    for index, context in enumerate(contexts_list[:n_plays]):
        bucket = bucket_of(context)
        start = time.perf_counter()
        choice = chooser.choose(context, tiles)
        latencies.append((time.perf_counter() - start) * 1000.0)
        result = front.retrieve(context)
        scores.append(result.top_score)
        tile = by_id[choice.tile_id]
        outcome = play_outcome(tile, context, bucket, index)
        record = record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            chooser=chooser.name,
            chooser_version=chooser.version,
            propensity=choice.propensity,
            candidates=choice.candidates,
        )
        chooser.update(record)
        picks.append(choice.tile_id)
        wins.append(outcome.result == "win")
    return {
        "picks": picks,
        "wins": wins,
        "latencies_ms": latencies,
        "scores": scores,
        "records": fold_plays(ledger.events()),
        "chooser": chooser.name,
    }


def run_always_matching(tiles, contexts_list, n_plays, by_id):
    """The reference: always play a tile of the style the context asked for.

    This is the best *class* of policy the game allows — the game pays
    0.85 for a matching style and 0.15 for anything else, so a policy that
    always matches is earning the top of the range.

    It is not a ceiling, and the difference matters: it always plays the
    *first* matching tile, and the two matching tiles have different seeded
    draws. So this is one draw of the always-matching class, and another
    always-matching policy can land a play or two away from it. It is here
    as the reference the arms are read against.
    """
    wins = []
    for index, context in enumerate(contexts_list[:n_plays]):
        wanted = context["wanted_style"]
        tile = next(
            tile for tile in tiles if tile.steps[0].params["style"] == wanted
        )
        outcome = play_outcome(tile, context, bucket_of(context), index)
        wins.append(outcome.result == "win")
    return {
        "picks": [],
        "wins": wins,
        "latencies_ms": [],
        "chooser": "always-matching/v1",
    }


def replay_fastpath(bandit_arm, contexts_list, n_plays, by_id, front, tau_hi):
    """Arm D: E1's policy, replayed over the bandit's log.

    Where the score clears τ the retrieved tile is played; otherwise the
    band's logged choice stands. The game's outcome for the tile that is
    actually played is recomputed from the seeded draw, so this arm plays
    the identical game as every other one.
    """
    picks, wins, fired, latencies = [], [], [], []
    for index, context in enumerate(contexts_list[:n_plays]):
        bucket = bucket_of(context)
        start = time.perf_counter()
        result = front.retrieve(context)
        latencies.append((time.perf_counter() - start) * 1000.0)
        use_fast = bool(result.candidates) and result.top_score >= tau_hi
        if use_fast:
            tile = result.candidates[0]
        else:
            tile = by_id[bandit_arm["picks"][index]]
        outcome = play_outcome(tile, context, bucket, index)
        picks.append(tile.id)
        wins.append(outcome.result == "win")
        fired.append(use_fast)
    return {
        "picks": picks,
        "wins": wins,
        "fired": fired,
        "latencies_ms": latencies,
        "chooser": "fastpath/v1",
    }


def replay_policy(pick: Callable[[dict], str], contexts_list, n_plays, by_id):
    """Any deterministic policy's exact value over the rig's contexts.

    The game is a seeded function, so a policy's reward on these contexts is
    computed, not estimated. This is the ground truth the OPE estimates are
    checked against.
    """
    wins = []
    for index, context in enumerate(contexts_list[:n_plays]):
        tile_id = pick(context)
        if not tile_id:
            continue
        outcome = play_outcome(by_id[tile_id], context, bucket_of(context), index)
        wins.append(outcome.result == "win")
    return wins


# ------------------------------------------------------------- the analysis ---


def curve(wins: list[bool], buckets: int = 12) -> list[dict]:
    """Win rate by play-index bucket — how fast the arm improves with use."""
    size = max(1, len(wins) // buckets)
    out = []
    for start in range(0, len(wins), size):
        chunk = wins[start : start + size]
        out.append(
            {
                "plays": f"{start + 1}-{start + len(chunk)}",
                "wins": sum(chunk),
                "n": len(chunk),
                "win_rate": round(sum(chunk) / len(chunk), 4) if chunk else None,
            }
        )
    return out


def agreement(a: list[str], b: list[str]) -> float:
    """The share of plays where two arms picked the same tile."""
    if not a:
        return 0.0
    return round(sum(1 for x, y in zip(a, b) if x == y) / len(a), 4)


def percentile(values: list[float], p: float) -> float:
    """The p-th percentile, nearest-rank."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * p / 100.0)))
    return ordered[index]


def rate(wins: list[bool]) -> tuple[int, int, float]:
    """(wins, plays, win rate) — the rate always with its denominator."""
    plays = len(wins)
    wins_count = sum(wins)
    return wins_count, plays, (wins_count / plays if plays else 0.0)


def band_distribution(contexts_list, front, tiles_by_id, n_plays, tau_hi, tau_lo):
    """What the three bands say over the rig's contexts.

    The gate is held per (tile, context): the same tile in a different
    context is a different subject, so one context's bad score does not
    drag another's band down.
    """
    gate = BandGate(config=BandConfig(tau_hi=tau_hi, tau_lo=tau_lo))
    bands: dict[str, int] = {"execute": 0, "confirm": 0, "compile": 0}
    per_context: dict[str, dict[str, Any]] = {}
    for context in contexts_list[:n_plays]:
        result = front.retrieve(context)
        if not result.candidates:
            continue
        tile = result.candidates[0]
        subject = f"{tile.id}|{context['wanted_style']}"
        decision = gate.step_for(subject, result.top_score, now=0.0)
        bands[decision.band] = bands.get(decision.band, 0) + 1
        per_context[subject] = {
            "band": decision.band,
            "score": round(decision.score, 6),
            "style": tiles_by_id[tile.id].steps[0].params["style"],
        }
    return bands, per_context


def score_calibration(contexts_list, front, tiles_by_id, n_plays):
    """What the scores actually look like, and what they are about.

    Two readings, and they are not the same thing:

    * **the shortlist's scores** — every candidate's score, split into the
      tiles whose style the context asked for and the ones that do not
      match. This is the separation the front has to achieve.
    * **the top-1's score** — the score the fast path actually reads, split
      by whether the top-1 was the tile the context asked for. This is the
      score a threshold has to be read against.

    The band thresholds are a measurement in somebody else's embedding
    space. This is ours.
    """
    matching: list[float] = []
    mismatching: list[float] = []
    top1: list[float] = []
    top1_matching: list[float] = []
    top1_wrong: list[float] = []
    for context in contexts_list[:n_plays]:
        result = front.retrieve(context)
        if not result.candidates:
            continue
        wanted = context["wanted_style"]
        for tile, score in zip(result.candidates, result.scores):
            style = tiles_by_id[tile.id].steps[0].params["style"]
            (matching if style == wanted else mismatching).append(score)
        top = result.candidates[0]
        top_score = result.scores[0]
        top1.append(top_score)
        if tiles_by_id[top.id].steps[0].params["style"] == wanted:
            top1_matching.append(top_score)
        else:
            top1_wrong.append(top_score)
    return {
        "matching": matching,
        "mismatching": mismatching,
        "top1": top1,
        "top1_matching": top1_matching,
        "top1_wrong": top1_wrong,
    }


def retrieval_per_context(contexts_list, front, n_plays):
    """The front's answer for every context, computed once.

    The τ sweep needs the top-1 tile and its score for every context; the
    front is deterministic, so asking once and thresholding the answers is
    the same computation as asking again for every τ — and it makes the
    sweep cheap enough to read at a fine granularity.
    """
    rows = []
    for context in contexts_list[:n_plays]:
        result = front.retrieve(context)
        rows.append(
            {
                "tile_id": result.candidates[0].id if result.candidates else "",
                "score": result.top_score,
            }
        )
    return rows


def tau_sweep(per_context, bandit_picks, contexts_list, n_plays, by_id, taus):
    """The offline τ sweep: coverage, win rate and agreement, per threshold.

    Computed from the recorded scores, so the band's policy can be re-read
    without running anything again.
    """
    rows = []
    for tau in taus:
        fired = 0
        wins = 0
        picks: list[str] = []
        for index, row in enumerate(per_context):
            context = contexts_list[index]
            use_fast = bool(row["tile_id"]) and row["score"] >= tau
            if use_fast:
                fired += 1
                tile_id = row["tile_id"]
            else:
                tile_id = bandit_picks[index]
            picks.append(tile_id)
            outcome = play_outcome(
                by_id[tile_id], context, bucket_of(context), index
            )
            wins += outcome.result == "win"
        plays = len(per_context)
        rows.append(
            {
                "tau": tau,
                "coverage": round(fired / plays, 4) if plays else 0.0,
                "wins": wins,
                "n": plays,
                "win_rate": round(wins / plays, 4) if plays else None,
                "agreement_with_bandit": agreement(picks, bandit_picks),
            }
        )
    return rows


def _frozen_bandit_pick(chooser: ContextualBandit):
    """The bandit's final argmax for a context — a frozen policy."""

    def pick(context, candidates):
        bucket = chooser.bucket(context)
        return min(
            candidates, key=lambda tile_id: (-chooser.estimate(bucket, tile_id), tile_id)
        )

    return pick


def _retrieval_pick(front: RetrievalFront):
    """The top tile by meaning — a deterministic policy of the context."""

    def pick(context, candidates):
        result = front.retrieve(context)
        if not result.candidates:
            return ""
        top = result.candidates[0].id
        return top if top in candidates else ""

    return pick


def _fastpath_pick(front: RetrievalFront, tau_hi: float, fallback):
    """The frozen fast-path policy: the retrieved tile when it clears τ."""

    def pick(context, candidates):
        result = front.retrieve(context)
        if result.candidates and result.top_score >= tau_hi:
            top = result.candidates[0].id
            return top if top in candidates else ""
        return fallback(context, candidates)

    return pick


def ope_on_log(records, target_pick, name):
    """The estimators' reading of a frozen policy, from the log alone."""
    target = DeterministicTarget(pick=target_pick, name=name)
    out: dict[str, Any] = {}
    for method in ("ips", "snips"):
        try:
            estimate = evaluate(records, target, method=method)
        except Exception as exc:  # the estimator refuses rather than guesses
            out[method] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        out[method] = {
            "value": round(estimate.value, 6),
            "ci_low": round(estimate.ci_low, 6),
            "ci_high": round(estimate.ci_high, 6),
            "stderr": round(estimate.stderr, 6),
            "n": estimate.n,
            "n_offered": estimate.n_offered,
            "effective_n": round(estimate.effective_n, 2),
            "max_weight": round(estimate.max_weight, 4),
            "coverage": round(estimate.coverage, 4),
            "support": round(estimate.support, 4),
            "warnings": list(estimate.warnings),
        }
    return out


# ------------------------------------------------------------------- main ----


def rule(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plays", type=int, default=N_PLAYS)
    parser.add_argument("--k", type=int, default=K_SHORTLIST)
    parser.add_argument("--embedder", default="default", choices=("default", "hashing"))
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).parent / "results" / "tiles-retrieval-e1.json"
        ),
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    registry = VocabularyRegistry(default_entries())
    ledger = InMemoryLedger()
    library = TileLibrary(registry=registry, ledger=ledger)
    tiles = author_tiles(library, registry)
    by_id = {tile.id: tile for tile in tiles}
    contexts_list = contexts(args.plays)

    embedder = (
        HashingEmbedder() if args.embedder == "hashing" else default_embedder()
    )
    index = TileIndex(embedder)
    for tile in tiles:
        index.add(tile)
    front = RetrievalFront(index=index, k=args.k)

    result: dict[str, Any] = {
        "experiment": "E1 — the embedding fast path against the bandit",
        "brief": "docs/research/pincher-fit.md §E1; the seeds' D1",
        "rig": (
            "tests/tiles/test_acceptance_learning.py's, verbatim in shape: "
            "6 tiles, 600 plays, p_match=0.85/p_miss=0.15, sha256-seeded draws"
        ),
        "started": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "box": box_state(),
        "embedder": embedder_record(embedder),
        "n_plays": args.plays,
        "k_shortlist": args.k,
        "tau_hi": TAU_HI,
        "tau_lo": TAU_LO,
        "context_seed": CONTEXT_SEED,
        "bandit_seed": BANDIT_SEED,
    }

    # -- the arms -----------------------------------------------------------
    # The bandit runs first: the fast path is a replay over *its* log, and
    # the τ sweep needs its picks to score the thresholds.
    arm_bandit = run_bandit(tiles, contexts_list, args.plays, library)

    # -- the scores, and the thresholds they support ----------------------
    calibration = score_calibration(contexts_list, front, by_id, args.plays)
    per_context = retrieval_per_context(contexts_list, front, args.plays)
    taus = [round(0.20 + 0.01 * step, 2) for step in range(41)] + [TAU_HI]
    sweep = tau_sweep(
        per_context, arm_bandit["picks"], contexts_list, args.plays, by_id, taus
    )

    # The calibrated execute line: the **most selective** threshold whose
    # coverage still reaches E1's own 30 % bar. It is calibrated against
    # E1's criterion rather than picked, because a threshold picked by
    # looking at the win rate would be a threshold fitted to the answer.
    calibrated_tau_hi = max(
        (row["tau"] for row in sweep if row["coverage"] >= COVERAGE_BAR), default=TAU_HI
    )
    # The calibrated compile line: the score at which a *wrong* tile is
    # typically as close as the right ones — the point below which the
    # front can no longer tell the two apart, so the library has nothing
    # for the request and a new tile is compiled.
    mismatching = calibration["mismatching"]
    calibrated_tau_lo = percentile(mismatching, 50) if mismatching else 0.0
    calibrated_tau_lo = min(calibrated_tau_lo, calibrated_tau_hi - 0.06)

    arm_retrieval = run_retrieval_only(
        tiles, contexts_list, args.plays, library, front
    )
    arm_retrieval_bandit = run_retrieval_bandit(
        tiles, contexts_list, args.plays, library, front
    )
    arm_fastpath = replay_fastpath(
        arm_bandit, contexts_list, args.plays, by_id, front, calibrated_tau_hi
    )

    arm_reference = run_always_matching(tiles, contexts_list, args.plays, by_id)

    arms = {
        "bandit": arm_bandit,
        "retrieval_only": arm_retrieval,
        "retrieval_bandit": arm_retrieval_bandit,
        "fastpath": arm_fastpath,
        "always-matching (reference)": arm_reference,
    }

    rule("1. the arms' win rates, with their denominators")
    for name, arm in arms.items():
        wins_count, plays, win_rate = rate(arm["wins"])
        low, high = wilson_interval(wins_count, plays)
        print(
            f"{name:17s} {wins_count:4d}/{plays:4d}  win rate {win_rate:.4f}  "
            f"95% CI [{low:.4f}, {high:.4f}]"
        )
    print(
        f"the fast path's arm is read at the calibrated execute line "
        f"τ = {calibrated_tau_hi:.2f}"
    )
    result["win_rates"] = {
        name: {
            "wins": rate(arm["wins"])[0],
            "n": rate(arm["wins"])[1],
            "win_rate": round(rate(arm["wins"])[2], 6),
        }
        for name, arm in arms.items()
    }
    # The settling comparison: each arm against the bandit, with the
    # interval on the difference of two rates.
    result["against_the_bandit"] = {}
    band_wins, band_n, band_rate = rate(arm_bandit["wins"])
    for name, arm in arms.items():
        if name == "bandit":
            continue
        wins_count, plays, win_rate = rate(arm["wins"])
        low, high = newcombe_difference(wins_count, plays, band_wins, band_n)
        z, p_value = two_proportion_z(wins_count, plays, band_wins, band_n)
        print(
            f"{name:17s} − bandit  {win_rate - band_rate:+.4f}  "
            f"95% CI [{low:+.4f}, {high:+.4f}]  p = {p_value:.4f}"
        )
        result["against_the_bandit"][name] = {
            "difference": round(win_rate - band_rate, 6),
            "ci": [round(low, 6), round(high, 6)],
            "z": round(z, 4),
            "p_value": round(p_value, 6),
        }

    rule("2. the latency of the fast path, per play")
    for name in ("retrieval_only", "retrieval_bandit", "fastpath"):
        values = arms[name]["latencies_ms"]
        print(
            f"{name:17s} p50 {percentile(values, 50):7.3f} ms  "
            f"p90 {percentile(values, 90):7.3f} ms  "
            f"p95 {percentile(values, 95):7.3f} ms  "
            f"max {max(values):7.3f} ms"
        )
    result["latency_ms"] = {
        name: {
            "p50": round(percentile(arms[name]["latencies_ms"], 50), 4),
            "p90": round(percentile(arms[name]["latencies_ms"], 90), 4),
            "p95": round(percentile(arms[name]["latencies_ms"], 95), 4),
            "max": round(max(arms[name]["latencies_ms"]), 4),
        }
        for name in ("retrieval_only", "retrieval_bandit", "fastpath")
    }

    # -- the scores ---------------------------------------------------------
    rule("3. the score calibration — what our scores do to pincher's bands")
    for label, key in (
        ("the matching tile's score", "matching"),
        ("the mismatching tile's score", "mismatching"),
        ("the top-1's score", "top1"),
        ("the top-1's score, when right", "top1_matching"),
        ("the top-1's score, when wrong", "top1_wrong"),
    ):
        values = calibration[key]
        if not values:
            continue
        print(
            f"{label:33s} n {len(values):5d}  p10 {percentile(values, 10):.4f}  "
            f"p50 {percentile(values, 50):.4f}  p90 {percentile(values, 90):.4f}  "
            f"max {max(values):.4f}"
        )
    print(
        f"pincher's execute line is {TAU_HI}: "
        f"{sum(1 for s in calibration['top1'] if s >= TAU_HI)} of "
        f"{len(calibration['top1'])} contexts clear it."
    )
    top1_total = len(calibration["top1"])
    top1_right = len(calibration["top1_matching"])
    print(
        f"the front's top-1 was the tile whose style the context asked for, "
        f"in {top1_right} of {top1_total} contexts."
    )
    result["score_calibration"] = {
        key: {
            "n": len(values),
            "p10": round(percentile(values, 10), 6) if values else None,
            "p50": round(percentile(values, 50), 6) if values else None,
            "p90": round(percentile(values, 90), 6) if values else None,
            "max": round(max(values), 6) if values else None,
        }
        for key, values in calibration.items()
    }
    result["front_top1_accuracy"] = {
        "right": top1_right,
        "n": top1_total,
        "share": round(top1_right / top1_total, 6) if top1_total else None,
    }

    # -- the τ sweep, and the calibrated thresholds -------------------------
    rule("4. the τ sweep, computed offline from the recorded scores")
    for row in sweep:
        if round(row["tau"] * 100) % 5:
            continue
        print(
            f"τ {row['tau']:.2f}  coverage {row['coverage']:.4f}  "
            f"win rate {row['win_rate']:.4f}  "
            f"agreement with the bandit {row['agreement_with_bandit']:.4f}"
        )
    result["tau_sweep"] = sweep

    print()
    print(
        f"calibrated execute line  {calibrated_tau_hi:.2f}  "
        f"(the most selective threshold still covering {COVERAGE_BAR:.0%})"
    )
    print(
        f"calibrated compile line  {calibrated_tau_lo:.2f}  "
        f"(the median score of a tile that does not match the context)"
    )
    result["calibrated"] = {
        "tau_hi": calibrated_tau_hi,
        "tau_lo": round(calibrated_tau_lo, 6),
        "rule_hi": (
            "the most selective threshold whose coverage still reaches E1's "
            "30 % bar"
        ),
        "rule_lo": (
            "the median score of a tile that does not match the context: "
            "below it the front cannot tell the two apart"
        ),
    }

    # -- E1's three bars ----------------------------------------------------
    def bars_at(tau: float, label: str) -> dict[str, Any]:
        """E1's three bars, at one execute threshold."""
        arm = replay_fastpath(
            arm_bandit, contexts_list, args.plays, by_id, front, tau
        )
        fast_wins, fast_n, fast_rate = rate(arm["wins"])
        band_wins, band_n, band_rate = rate(arm_bandit["wins"])
        coverage = sum(arm["fired"]) / len(arm["fired"])
        diff = fast_rate - band_rate
        diff_low, diff_high = newcombe_difference(
            fast_wins, fast_n, band_wins, band_n
        )
        z, p_value = two_proportion_z(fast_wins, fast_n, band_wins, band_n)
        latency = percentile(arm["latencies_ms"], 95)
        print(f"  {label} (τ = {tau:.2f})")
        print(
            f"    coverage      {coverage:.4f}   (bar: ≥ {COVERAGE_BAR})  "
            f"{'PASS' if coverage >= COVERAGE_BAR else 'FAIL'}"
        )
        print(
            f"    reward gap    {diff:+.4f}  95% CI [{diff_low:+.4f}, {diff_high:+.4f}]  "
            f"p = {p_value:.4f}  (ε = {EPSILON})  "
            f"{'PASS' if diff >= -EPSILON else 'FAIL'}"
        )
        print(
            f"    p95 latency   {latency:.3f} ms  (bar: < {P95_BAR_MS})  "
            f"{'PASS' if latency < P95_BAR_MS else 'FAIL'}"
        )
        return {
            "tau": tau,
            "coverage": round(coverage, 6),
            "coverage_bar": COVERAGE_BAR,
            "coverage_pass": coverage >= COVERAGE_BAR,
            "reward_gap": round(diff, 6),
            "reward_gap_ci": [round(diff_low, 6), round(diff_high, 6)],
            "z": round(z, 4),
            "p_value": round(p_value, 6),
            "epsilon": EPSILON,
            "reward_pass": diff >= -EPSILON,
            "p95_ms": round(latency, 4),
            "p95_bar_ms": P95_BAR_MS,
            "latency_pass": latency < P95_BAR_MS,
            "win_rate": round(fast_rate, 6),
        }

    rule("5. E1's three bars, at pincher's execute line")
    result["e1_bars_pincher"] = bars_at(TAU_HI, "pincher's thresholds")

    rule("6. E1's three bars, at the calibrated execute line")
    result["e1_bars_calibrated"] = bars_at(calibrated_tau_hi, "calibrated thresholds")

    rule("7. the three bands, over the rig's contexts")
    result["bands"] = {}
    for label, tau_hi, tau_lo in (
        ("pincher", TAU_HI, TAU_LO),
        ("calibrated", calibrated_tau_hi, calibrated_tau_lo),
    ):
        bands, per_ctx = band_distribution(
            contexts_list, front, by_id, args.plays, tau_hi, tau_lo
        )
        total = sum(bands.values()) or 1
        print(f"  {label} thresholds (τ_hi {tau_hi:.2f}, τ_lo {tau_lo:.2f}):")
        for band in ("execute", "confirm", "compile"):
            share = bands.get(band, 0) / total
            print(
                f"    {band:9s} {bands.get(band, 0):4d}  {share:.4f}"
                + ("  ← nothing is played here" if band == "compile" else "")
            )
        result["bands"][label] = {
            "tau_hi": tau_hi,
            "tau_lo": round(tau_lo, 6),
            "counts": bands,
            "shares": {band: round(bands.get(band, 0) / total, 6) for band in bands},
            "per_context": per_ctx,
        }

    rule("8. how fast each arm improves with use (win rate by 50 plays)")
    for name, arm in arms.items():
        line = "  ".join(
            f"{bucket['win_rate']:.2f}"
            for bucket in curve(arm["wins"])
            if bucket["win_rate"] is not None
        )
        print(f"{name:17s} {line}")
    result["curve"] = {name: curve(arm["wins"]) for name, arm in arms.items()}

    rule("9. the log alone: the OPE estimators' reading of the frozen policies")
    print(
        "the targets here are FROZEN policies — the retrieval pick, and the "
        "fast path falling back to the bandit's FINAL argmax. That is the "
        "policy-swap question: what would a policy that is fixed from now on "
        "have earned on the bandit's log? Section 1's arms are the live runs, "
        "where the fallback is the band's logged choice at that moment."
    )
    records = arm_bandit["records"]
    frozen_bandit = _bandit()
    frozen_bandit.fit(records)
    frozen = _frozen_bandit_pick(frozen_bandit)
    direct_retrieval = replay_policy(
        lambda context: _retrieval_pick(front)(context, list(by_id)),
        contexts_list,
        args.plays,
        by_id,
    )
    direct_fastpath = replay_policy(
        lambda context: _fastpath_pick(front, calibrated_tau_hi, frozen)(
            context, list(by_id)
        ),
        contexts_list,
        args.plays,
        by_id,
    )
    estimates = {
        "retrieval_only": ope_on_log(
            records, _retrieval_pick(front), "retrieval-only"
        ),
        "fastpath": ope_on_log(
            records, _fastpath_pick(front, calibrated_tau_hi, frozen), "fastpath"
        ),
    }
    for name, estimate in estimates.items():
        direct = direct_retrieval if name == "retrieval_only" else direct_fastpath
        wins_count, plays, win_rate = rate(direct)
        print(f"{name}: direct replay {win_rate:.4f} ({wins_count}/{plays})")
        for method in ("ips", "snips"):
            row = estimate.get(method, {})
            if "error" in row:
                print(f"  {method:5s} refused: {row['error']}")
                continue
            print(
                f"  {method:5s} {row['value']:.4f}  "
                f"CI [{row['ci_low']:.4f}, {row['ci_high']:.4f}]  "
                f"ESS {row['effective_n']:.1f}  max w {row['max_weight']:.3f}  "
                f"support {row['support']:.3f}"
            )
    result["ope"] = {
        "estimates": estimates,
        "direct_replay": {
            "retrieval_only": round(rate(direct_retrieval)[2], 6),
            "fastpath": round(rate(direct_fastpath)[2], 6),
        },
    }

    rule("10. the propensities the arms recorded")
    for name in ("bandit", "retrieval_bandit"):
        values = [r.propensity for r in arms[name]["records"] if r.propensity is not None]
        print(
            f"{name:17s} {len(values)} plays with a propensity  "
            f"min {min(values):.4f}  max {max(values):.4f}"
        )
    result["propensities"] = {
        name: {
            "n": len([r for r in arms[name]["records"] if r.propensity is not None]),
            "min": round(min([r.propensity for r in arms[name]["records"] if r.propensity is not None]), 6),
            "max": round(max([r.propensity for r in arms[name]["records"] if r.propensity is not None]), 6),
        }
        for name in ("bandit", "retrieval_bandit")
    }

    rule("11. the paraphrase probe — the request that is not the style's name")
    probes = paraphrase_probe(front, by_id)
    print(
        f"{'kind':11s} {'style':10s} {'request':26s} {'margin':>9s}  "
        f"{'right style on top'}"
    )
    for row in probes:
        margin = f"{row['margin']:+.4f}" if row["margin"] is not None else "—"
        print(
            f"{row['kind']:11s} {row['style']:10s} {row['request']:26s} "
            f"{margin:>9s}  {'yes' if row['right_style_on_top'] else 'NO'}"
        )
    for kind in ("literal", "paraphrase"):
        rows = [row for row in probes if row["kind"] == kind]
        on_top = sum(1 for row in rows if row["right_style_on_top"])
        margins = [row["margin"] for row in rows if row["margin"] is not None]
        print(
            f"{kind:11s} the right style is on top in {on_top} of {len(rows)}; "
            f"mean margin {sum(margins) / len(margins):+.4f}"
            if margins
            else f"{kind:11s} no margins"
        )
    result["paraphrase_probe"] = {
        "rows": probes,
        "summary": {
            kind: {
                "right_style_on_top": sum(
                    1
                    for row in probes
                    if row["kind"] == kind and row["right_style_on_top"]
                ),
                "n": len([row for row in probes if row["kind"] == kind]),
                "mean_margin": round(
                    sum(
                        row["margin"]
                        for row in probes
                        if row["kind"] == kind and row["margin"] is not None
                    )
                    / max(
                        1,
                        len(
                            [
                                row
                                for row in probes
                                if row["kind"] == kind and row["margin"] is not None
                            ]
                        ),
                    ),
                    6,
                ),
            }
            for kind in ("literal", "paraphrase")
        },
    }

    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print()
    print(f"results written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
