#!/usr/bin/env python3
"""refit drift: does the nightly whole-log refit drift the old contexts' value estimates?

The nightly retrain refits the chooser over the **whole log**, so every night's
refit re-derives every (context bucket, tile) estimate from scratch. The
question this answers is the one the sleep-dreaming toy left open: does that
refit, over a growing log, move the **old** contexts' value estimates - and
if it does, what does it cost?

Three arms, all running the repo's own code (``core.tiles.chooser``,
``core.tiles.plays``, ``core.tiles.retrain``, ``core.tiles.ope``):

* **refit** - the chooser is refitted on the growing log every night, and the
  library is held fixed at the six tiles the real nights authored. This
  isolates the refit: nothing else changes, so any drift is the refit's.
* **refit_grow** - the real loop: the refit, plus the retrain retiring the
  tiles that lost and the cloud author writing new ones. The library grows,
  and a new tile arrives in every old bucket with no history in it.
* **refit_moved** - arm ``refit``, but the **context definition moves** at
  night 4: the bucketing features change, so every old play is re-bucketed
  and the counts under the old definition are split. This is the substrate
  risk the toy pointed at: a context definition is a versioned thing, and
  changing one invalidates what was counted under it.

What is measured, per night, against the log **as it stood at the end of the
previous night** (so the log is fixed and only the policy moves):

* **estimate drift** - how far each old (bucket, tile) estimate moved, split
  into the buckets that received new plays and the ones that did not. The
  latter must not move at all: the refit is a fold, so a bucket that received
  nothing new keeps exactly the estimate it had.
* **estimate error** - the estimate against the truth, which is known
  exactly here.
* **choice flips** - how often the chooser would now pick a different tile in
  an old context, split by whether the option set changed underneath it.
* **the OPE value** - ``core.tiles.ope`` scores the chooser snapshot against
  the old log: what the chooser as it stands would have earned on the plays
  that were logged before it changed. That is the number with an interval,
  and the truth for it is computable in closed form here, so the estimate can
  be checked rather than trusted.

The outcome model is stated, not measured: see ``OutcomeModel`` below. The
tile set, the context vocabulary and the code are real; the outcomes are a
stand-in, and the doc says which is which.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "docs" / "lab" / "lab3-scripts"))

from boxstate import box_state, format_box_state  # noqa: E402
from core.night.ledger import InMemoryLedger  # noqa: E402
from core.tiles import (  # noqa: E402
    ContextualBandit,
    Outcome,
    ScriptedAuthor,
    Tile,
    TileAuthor,
    TileLibrary,
    TileStep,
    build_tile,
    evaluate,
    record_play,
    retrain,
)
from core.tiles.models import PlayRecord  # noqa: E402
from core.tiles.ope import OPEError  # noqa: E402
from core.vocab.registry import VocabularyRegistry  # noqa: E402
from core.vocab.words import default_entries  # noqa: E402

# ---------------------------------------------------------------- the vocabulary

#: The crates family's style enum, from the real vocabulary schema
#: (``core/vocab/words.py``: ``CRATES_PARAMS``).
CRATE_STYLES = ("plain", "weathered", "stained")
#: The weathering family's tone enum, from the real vocabulary schema
#: (``WEATHERING_PARAMS``).
WEATHERING_TONES = ("pale", "gray", "dark")
#: Every style a context can ask for, across both families.
ALL_STYLES = CRATE_STYLES + WEATHERING_TONES
#: The phases the context can carry. ``phase`` is one of the four real
#: context keys (``docs/design/tiles.md`` §"The context").
PHASES = ("build", "edit")
#: The builders. The real ones (CLAUDE.md: "Casey and Magnus are the two
#: builders").
BUILDERS = ("casey", "magnus")

#: Every context bucket the chooser can branch on: a style and a phase.
ALL_BUCKETS = tuple((style, phase) for style in ALL_STYLES for phase in PHASES)

#: Which family a style belongs to. A context asks for a style; a tile sets
#: one; whether the tile can serve the request is a family question first and
#: a style question second.
STYLE_FAMILY = {
    **{style: "props" for style in CRATE_STYLES},
    **{tone: "material" for tone in WEATHERING_TONES},
}

#: The real words, and the word each real family writes in.
WORD_FOR_FAMILY = {
    "courtyard.props.harbor.crates": "props.harbor.crates",
    "courtyard.material.wood.weathering": "material.wood.weathering",
    "courtyard.props.harbor.racks": "props.harbor.racks",
}


def tile_style(tile: Tile) -> tuple[str | None, str | None]:
    """The (family group, style) a tile sets, or (None, None) if it sets none."""
    for step in tile.steps:
        params = step.params
        if "style" in params:
            return "props", str(params["style"])
        if "tone" in params:
            return "material", str(params["tone"])
    return None, None


# ---------------------------------------------------------------- the outcome model


@dataclass(frozen=True)
class OutcomeModel:
    """The stated stand-in for the world.

    A play's win probability is decided by the tile against the context, and
    the truth is therefore known exactly - which is what makes the estimate
    error computable and the drift interpretable. These are the tiles seat's
    own acceptance-run numbers (0.85 / 0.15 for a style that matches the one
    the context asked for), with one level added so a tile of the right kind
    but the wrong look is neither the same as a match nor the same as a
    mismatch.
    """

    p_match: float = 0.85
    p_same_family: float = 0.40
    p_other: float = 0.15

    def p_win(self, tile: Tile, context: Mapping[str, Any]) -> float:
        group, style = tile_style(tile)
        want = str(context.get("wanted_style", ""))
        want_group = STYLE_FAMILY.get(want)
        if group is None or want_group is None or group != want_group:
            return self.p_other
        if style == want:
            return self.p_match
        return self.p_same_family

    def truth(self, tile: Tile, bucket_style: str) -> float:
        """The true win rate of a tile in a bucket, from the bucket's style."""
        want_group = STYLE_FAMILY.get(bucket_style)
        group, style = tile_style(tile)
        if group is None or want_group is None or group != want_group:
            return self.p_other
        if style == bucket_style:
            return self.p_match
        return self.p_same_family


# ---------------------------------------------------------------- the config


@dataclass(frozen=True)
class Config:
    """Every knob the run has, so the numbers can be re-derived."""

    nights: int = 10
    contexts_per_night: int = 250
    buckets_per_night: int = 4
    feature_keys: tuple[str, ...] = ("wanted_style", "phase")
    moved_feature_keys: tuple[str, ...] = ("wanted_style", "phase", "builder")
    move_at_night: int = 4
    min_plays: int = 3
    retire_below: float = 0.34
    epsilon: float = 0.25
    prior: float = 1.0
    outcome: OutcomeModel = field(default_factory=OutcomeModel)
    arms: tuple[str, ...] = ("refit", "refit_grow", "refit_moved")


# ---------------------------------------------------------------- the world


def load_real_tiles(path: Path) -> list[Tile]:
    """The tiles the real nights authored, as ``Tile`` objects.

    The bodies are read back out of the real ledgers (see
    ``extract_real_tiles.py``), so the option set is the one our nights
    produced. The library's own door still checks every one of them against
    the real vocabulary.
    """
    payload = json.loads(path.read_text())
    author = TileAuthor(
        model="scripted/night-v3-tiles-v1",
        provider="local",
        prompt_hash="sha256:" + "0" * 64,
        cost_cents=0,
    )
    tiles: list[Tile] = []
    for entry in payload["tiles"]:
        body = entry["body"]
        steps = tuple(
            TileStep(
                word=step["word"],
                path=step["path"],
                op=step.get("op", "set"),
                params=dict(step.get("params") or {}),
            )
            for step in body["steps"]
        )
        tiles.append(
            build_tile(
                family=body["family"],
                kind=body["kind"],
                title=body["title"],
                steps=steps,
                author=author,
                preconditions=tuple(body.get("preconditions") or ()),
                created_at=entry.get("authored_at"),
            )
        )
    return tiles


def scripted_cloud_author(counter: dict[str, int]) -> ScriptedAuthor:
    """The cloud author: a new tile for every family that lost.

    The author is the repo's own ``ScriptedAuthor``; the script is ours, and
    it writes real vocabulary-legal tiles in the losing family's own word, so
    the library grows the way the real loop grows it.
    """

    def script(request: Any) -> list[Mapping[str, Any]]:
        specs: list[Mapping[str, Any]] = []
        for packet in request.feedback:
            family = packet.family
            word = WORD_FOR_FAMILY.get(family)
            if word is None:
                continue
            n = counter.get(family, 0)
            counter[family] = n + 1
            if word == "props.harbor.crates":
                style = CRATE_STYLES[n % len(CRATE_STYLES)]
                params = {
                    "count": 2 + (n % 5),
                    "style": style,
                    "from_library": 0,
                    "seed": 4100 + n,
                }
                title = f"crates.{style}.v{n}"
            elif word == "material.wood.weathering":
                tone = WEATHERING_TONES[n % len(WEATHERING_TONES)]
                # ``seed`` is not a parameter of this word in the real
                # vocabulary schema (only the crates word takes one), and the
                # library's door refuses a tile that says otherwise.
                params = {"wear": n % 6, "tone": tone}
                title = f"weathering.{tone}.v{n}"
            else:
                params = {"count": 1 + (n % 4), "length_m": 1.0 + 0.5 * (n % 6)}
                title = f"racks.v{n}"
            specs.append(
                {
                    "family": family,
                    "kind": packet.kind,
                    "title": title,
                    "steps": [{"word": word, "path": word, "op": "set", "params": params}],
                    "preconditions": [],
                }
            )
        return specs

    return ScriptedAuthor(
        script,
        model="scripted/night-v3-tiles-v1",
        provider="local",
        prompt_hash="sha256:" + "0" * 64,
    )


def bucket_of(context: Mapping[str, Any], feature_keys: Sequence[str]) -> str:
    """The context bucket, exactly as ``ContextualBandit.bucket`` computes it."""
    if not feature_keys:
        return ""
    parts = []
    for key in feature_keys:
        if key not in context:
            parts.append(f"{key}=<none>")
        else:
            parts.append(f"{key}={context[key]}")
    return "|".join(parts)


def style_of_bucket(bucket: str) -> str:
    """The style a bucket asks for, read back out of the bucket string."""
    for part in bucket.split("|"):
        if part.startswith("wanted_style="):
            return part.split("=", 1)[1]
    return ""


def greedy_pick(
    chooser: ContextualBandit,
    bucket: str,
    candidates: Sequence[str],
    overall: Mapping[str, Mapping[str, Any]],
) -> str:
    """The tile the chooser would pick, greedily, out of the candidates.

    The ordering is the chooser's own (``core/tiles/chooser.py``): the bucket
    estimate, then the overall mean, then the tile id, so a tie breaks the
    same way every time.
    """
    return min(
        candidates,
        key=lambda t: (
            -chooser.estimate(bucket, t),
            -overall.get(t, {}).get("mean", 0.0),
            t,
        ),
    )


class BanditTarget:
    """A chooser snapshot, as an off-policy target.

    It reproduces the chooser's own choice distribution: epsilon-greedy over
    the eligible set, with the greedy arm picked outright with probability
    ``1 - eps`` and every eligible tile in the exploration pool with
    probability ``eps / |eligible|``. The epsilon is the one the snapshot had
    when it was fitted, because the exploration rate decays with the number
    of plays and a snapshot is a moment.
    """

    def __init__(self, chooser: ContextualBandit, feature_keys: Sequence[str], name: str):
        self.chooser = chooser
        self.feature_keys = tuple(feature_keys)
        self.epsilon = chooser.current_epsilon()
        self.name = name
        self._overall = chooser.stats()["overall"]

    def probability(
        self,
        context: Mapping[str, Any],
        tile_id: str,
        candidates: Sequence[str],
    ) -> float:
        if not candidates:
            raise OPEError("no_candidates", "the snapshot has no eligible set")
        if tile_id not in candidates:
            return 0.0
        if len(candidates) == 1:
            return 1.0
        bucket = bucket_of(context, self.feature_keys)
        best = greedy_pick(self.chooser, bucket, candidates, self._overall)
        n = len(candidates)
        if tile_id == best:
            return (1.0 - self.epsilon) + self.epsilon / n
        return self.epsilon / n


@dataclass
class NightState:
    """What one night left behind."""

    night: int
    feature_keys: tuple[str, ...]
    active: tuple[str, ...]
    plays: int
    library_total: int
    library_retired: int


@dataclass
class Run:
    """One seed's whole run: the log, the snapshots, the per-night states."""

    records: list[PlayRecord]
    snapshots: dict[int, ContextualBandit]
    snapshot_keys: dict[int, tuple[str, ...]]
    nights: list[NightState]
    tiles: dict[str, Tile]
    tile_first_night: dict[str, int]


def run_once(
    config: Config,
    arm: str,
    seed: int,
    real_tiles: Sequence[Tile],
) -> Run:
    """One seed of one arm: the nights, the log, the snapshots."""
    rng = random.Random(seed)
    ledger = InMemoryLedger()
    registry = VocabularyRegistry(default_entries())
    library = TileLibrary(registry=registry, ledger=ledger)
    for tile in real_tiles:
        library.add(tile)

    counter: dict[str, int] = {}
    author = scripted_cloud_author(counter) if arm == "refit_grow" else None
    outcome_model = config.outcome

    def keys_for(night: int) -> tuple[str, ...]:
        if arm == "refit_moved" and night >= config.move_at_night:
            return config.moved_feature_keys
        return config.feature_keys

    chooser = ContextualBandit(
        feature_keys=config.feature_keys,
        epsilon=config.epsilon,
        prior=config.prior,
        seed=seed,
    )
    records: list[PlayRecord] = []
    nights: list[NightState] = []
    snapshots: dict[int, ContextualBandit] = {}
    snapshot_keys: dict[int, tuple[str, ...]] = {}
    tile_first_night: dict[str, int] = {t.id: 0 for t in real_tiles}
    known = set(tile_first_night)

    for night in range(1, config.nights + 1):
        keys = keys_for(night)
        # The chooser as the night finds it: the refit of the log so far.
        chooser.feature_keys = keys
        chooser.fit(records)

        # The night works on a **subset** of the context space, the way a
        # real night works on some styles and phases and leaves the rest
        # alone. Without this every bucket is touched every night and the
        # question "did the quiet old contexts move?" has no answer.
        night_buckets = rng.sample(ALL_BUCKETS, config.buckets_per_night)
        for _ in range(config.contexts_per_night):
            style, phase = rng.choice(night_buckets)
            context = {
                "wanted_style": style,
                "phase": phase,
                "budget_left": rng.randint(0, 3),
                "builder": rng.choice(BUILDERS),
            }
            eligible = library.eligible(context)
            if not eligible:
                continue
            choice = chooser.choose(context, eligible)
            tile = library.require(choice.tile_id)
            p_win = outcome_model.p_win(tile, context)
            won = rng.random() < p_win
            record = record_play(
                ledger=ledger,
                library=library,
                tile=tile,
                context=context,
                outcome=Outcome(result="win" if won else "lose", measure="critic"),
                chooser=chooser.name,
                chooser_version=chooser.version,
                night=f"night-{night}",
                propensity=choice.propensity,
                candidates=choice.candidates,
                scope=f"night-{night}",
            )
            records.append(record)
            # The chooser learns from the play it just made, exactly as the
            # canonical loop in ``core/tiles/__init__.py`` does. Without this
            # the exploration rate would be frozen for the whole night while
            # the snapshot's own rate kept decaying, and the two policies
            # would disagree about far more than they really do.
            chooser.update(record)

        # The night's retrain over the whole log.
        retrain(
            events=ledger.events(),
            library=library,
            ledger=ledger,
            chooser=chooser,
            author=author,
            measure="critic",
            min_plays=config.min_plays,
            retire_below=config.retire_below,
            retire=(arm == "refit_grow"),
            goal="write a better tile for the families that lost",
        )

        # A snapshot: the chooser as it stands at the end of the night.
        snap = ContextualBandit(
            feature_keys=keys,
            epsilon=config.epsilon,
            prior=config.prior,
            seed=seed,
        )
        snap.fit(records)
        snapshots[night] = snap
        snapshot_keys[night] = keys
        for tile in library.tiles():
            if tile.id not in known:
                known.add(tile.id)
                tile_first_night[tile.id] = night
        all_tiles = library.tiles()
        nights.append(
            NightState(
                night=night,
                feature_keys=keys,
                active=tuple(t.id for t in library.active()),
                plays=len(records),
                library_total=len(all_tiles),
                library_retired=sum(1 for t in all_tiles if t.status == "retired"),
            )
        )

    return Run(
        records=records,
        snapshots=snapshots,
        snapshot_keys=snapshot_keys,
        nights=nights,
        tiles={t.id: t for t in library.tiles()},
        tile_first_night=tile_first_night,
    )


# ---------------------------------------------------------------- the measurement


def truth_value(
    chooser: ContextualBandit,
    keys: Sequence[str],
    records: Sequence[PlayRecord],
    tiles: Mapping[str, Tile],
    outcome_model: OutcomeModel,
) -> float | None:
    """What the snapshot would have earned on these plays, exactly.

    The world here has a known truth, so the expected reward of the snapshot
    over the logged contexts is computable in closed form: for each play, the
    snapshot's own choice distribution over that play's eligible set, times
    the known win probability of each tile in that context. The average of
    that over the plays is the number the off-policy estimate is estimating.
    """
    if not records:
        return None
    overall = chooser.stats()["overall"]
    epsilon = chooser.current_epsilon()
    total = 0.0
    counted = 0
    for record in records:
        candidates = record.candidates
        if not candidates:
            continue
        bucket = bucket_of(record.context, keys)
        best = greedy_pick(chooser, bucket, candidates, overall)
        n = len(candidates)
        expected = 0.0
        for tile_id in candidates:
            probability = (1.0 - epsilon) + epsilon / n if tile_id == best else epsilon / n
            tile = tiles.get(tile_id)
            if tile is None:
                continue
            expected += probability * outcome_model.p_win(tile, record.context)
        total += expected
        counted += 1
    return total / counted if counted else None


def analyse(config: Config, arm: str, seed: int, run: Run) -> list[dict[str, Any]]:
    """The per-night measurements for one run."""
    rows: list[dict[str, Any]] = []
    outcome_model = config.outcome

    for night in range(2, config.nights + 1):
        prev_keys = run.snapshot_keys[night - 1]
        keys = run.snapshot_keys[night]
        prev = run.snapshots[night - 1]
        snap = run.snapshots[night]
        prev_end = run.nights[night - 2].plays
        prev_log = run.records[:prev_end]
        night_log = run.records[prev_end : run.nights[night - 1].plays]

        # The pairs the previous night knew about, under the definition the
        # previous night used.
        prev_pairs: dict[tuple[str, str], float] = {}
        for record in prev_log:
            bucket = bucket_of(record.context, prev_keys)
            prev_pairs[(bucket, record.tile_id)] = prev.estimate(bucket, record.tile_id)

        # The same pairs under the definition in force now: the re-bucketed
        # view, which is what the system would actually use after a move.
        now_pairs: dict[tuple[str, str], float] = {}
        for record in prev_log:
            bucket = bucket_of(record.context, keys)
            now_pairs[(bucket, record.tile_id)] = snap.estimate(bucket, record.tile_id)

        # The chooser's own buckets, read once: they say which arms still
        # exist after the refit.
        snap_stats = snap.stats()["buckets"]

        # Which buckets got new plays at night `night`, in the previous
        # night's definition (the one the pairs are keyed by).
        touched = {bucket_of(record.context, prev_keys) for record in night_log}

        drifts: list[float] = []
        untouched_drifts: list[float] = []
        touched_drifts: list[float] = []
        err_prev: list[float] = []
        err_now_old_view: list[float] = []
        err_now_new_view: list[float] = []
        collapsed = 0
        for (bucket, tile_id), old_estimate in prev_pairs.items():
            new_estimate = snap.estimate(bucket, tile_id)
            drift = new_estimate - old_estimate
            drifts.append(drift)
            (touched_drifts if bucket in touched else untouched_drifts).append(drift)
            # A pair whose count is gone: the chooser has no arm for it any
            # more, so its estimate fell back to the prior. Read from the
            # chooser's own stats, not from the number - a pair can sit on
            # the prior by accident (two wins in two plays is exactly 0.5).
            arms = snap_stats.get(bucket, {})
            if tile_id not in arms:
                collapsed += 1
            tile = run.tiles.get(tile_id)
            if tile is None:
                continue
            truth = outcome_model.truth(tile, style_of_bucket(bucket))
            err_prev.append(abs(old_estimate - truth))
            err_now_old_view.append(abs(new_estimate - truth))
        for (bucket, tile_id), new_estimate in now_pairs.items():
            tile = run.tiles.get(tile_id)
            if tile is None:
                continue
            truth = outcome_model.truth(tile, style_of_bucket(bucket))
            err_now_new_view.append(abs(new_estimate - truth))

        # How stale the old contexts are: the nights since each bucket last
        # received a play. A bucket that has been quiet for a night keeps
        # exactly the estimate it had - frozen, not wrong.
        last_play: dict[str, int] = {}
        for record in prev_log:
            last_play[bucket_of(record.context, prev_keys)] = night - 1
        ages = [night - 1 - last_play[b] for b in last_play]

        # The choice in every old bucket, before and after the refit.
        prev_overall = prev.stats()["overall"]
        now_overall = snap.stats()["overall"]
        old_buckets = sorted({bucket for bucket, _ in prev_pairs})
        flips = 0
        flips_same_options = 0
        same_options = 0
        options_changed = 0
        picks_new_tile = 0
        for bucket in old_buckets:
            sample = next(
                (r.context for r in prev_log if bucket_of(r.context, prev_keys) == bucket),
                None,
            )
            if sample is None:
                continue
            before_pool = [t for t in run.nights[night - 2].active]
            after_pool = [t for t in run.nights[night - 1].active]
            if not before_pool or not after_pool:
                continue
            before = greedy_pick(prev, bucket, before_pool, prev_overall)
            after = greedy_pick(snap, bucket, after_pool, now_overall)
            if before != after:
                flips += 1
            if set(before_pool) == set(after_pool):
                same_options += 1
                if before != after:
                    flips_same_options += 1
            else:
                options_changed += 1
            if run.tile_first_night.get(after, 0) > 1:
                picks_new_tile += 1
        compared = same_options + options_changed

        # The off-policy value of both snapshots on the log as it stood at the
        # end of the previous night. The records are the same; only the
        # policy moved, so the difference of the two is a paired comparison
        # and the estimator's noise largely cancels.
        ope_prev = _ope(prev, prev_keys, prev_log, f"{arm}/seed{seed}/n{night-1}")
        ope_now = _ope(snap, keys, prev_log, f"{arm}/seed{seed}/n{night}")
        ope_prev_c = _ope(prev, prev_keys, prev_log, f"{arm}/seed{seed}/n{night-1}", clip=OPE_CLIP)
        ope_now_c = _ope(snap, keys, prev_log, f"{arm}/seed{seed}/n{night}", clip=OPE_CLIP)
        ope_full = _ope(snap, keys, run.records, f"{arm}/seed{seed}/n{night}/full", clip=OPE_CLIP)
        # The same quantity computed exactly: the world here has a known
        # truth, so the snapshot's expected reward on the logged contexts is
        # computable in closed form and the estimator can be judged against
        # it rather than trusted.
        truth_now = truth_value(snap, keys, prev_log, run.tiles, outcome_model)
        truth_prev = truth_value(prev, prev_keys, prev_log, run.tiles, outcome_model)

        rows.append(
            {
                "arm": arm,
                "seed": seed,
                "night": night,
                "n_old_buckets": len(old_buckets),
                "n_old_pairs": len(prev_pairs),
                "n_touched_buckets": len(touched),
                "drift_mean_abs": _mean(drifts),
                "drift_max_abs": max((abs(d) for d in drifts), default=0.0),
                "untouched_max_abs": max((abs(d) for d in untouched_drifts), default=0.0),
                "untouched_n": len(untouched_drifts),
                "untouched_mean_abs": _mean(untouched_drifts),
                "touched_mean_abs": _mean(touched_drifts),
                "touched_max_abs": max((abs(d) for d in touched_drifts), default=0.0),
                "touched_n": len(touched_drifts),
                "n_pairs_collapsed": collapsed,
                "context_age_nights": _mean([float(a) for a in ages]),
                "error_prev_view": _mean(err_prev),
                "error_now_old_view": _mean(err_now_old_view),
                "error_now_new_view": _mean(err_now_new_view),
                "choice_flips": flips,
                "choice_buckets_compared": compared,
                "choice_flip_rate": flips / compared if compared else None,
                "choice_flip_rate_same_options": (
                    flips_same_options / same_options if same_options else None
                ),
                "choice_same_options": same_options,
                "choice_options_changed": options_changed,
                "pick_new_tile_rate": picks_new_tile / compared if compared else None,
                "ope_prev_value": ope_prev["value"],
                "ope_prev_lo": ope_prev["lo"],
                "ope_prev_hi": ope_prev["hi"],
                "ope_now_value": ope_now["value"],
                "ope_now_lo": ope_now["lo"],
                "ope_now_hi": ope_now["hi"],
                "ope_drift": (
                    ope_now["value"] - ope_prev["value"]
                    if ope_now["value"] is not None and ope_prev["value"] is not None
                    else None
                ),
                "ope_clipped_prev_value": ope_prev_c["value"],
                "ope_clipped_now_value": ope_now_c["value"],
                "ope_clipped_drift": (
                    ope_now_c["value"] - ope_prev_c["value"]
                    if ope_now_c["value"] is not None and ope_prev_c["value"] is not None
                    else None
                ),
                "ope_full_value": ope_full["value"],
                "ope_full_lo": ope_full["lo"],
                "ope_full_hi": ope_full["hi"],
                "ope_truth_now": truth_now,
                "ope_truth_prev": truth_prev,
                "value_drift_exact": (
                    truth_now - truth_prev
                    if truth_now is not None and truth_prev is not None
                    else None
                ),
                "ope_error_now": (
                    abs(ope_now_c["value"] - truth_now)
                    if ope_now_c["value"] is not None and truth_now is not None
                    else None
                ),
                "ope_n": ope_now["n"],
                "ope_effective_n": ope_now_c["effective_n"],
                "ope_max_weight": ope_now_c["max_weight"],
                "ope_effective_n_unclipped": ope_now["effective_n"],
                "ope_max_weight_unclipped": ope_now["max_weight"],
                "library_active": len(run.nights[night - 1].active),
                "library_total": run.nights[night - 1].library_total,
                "library_retired": run.nights[night - 1].library_retired,
                "plays_total": run.nights[night - 1].plays,
            }
        )
    return rows


#: The clip the off-policy weights are capped at. The module's own remedy
#: for a log with one enormous weight ("clip caps the weights ... trading
#: the bias for the variance and says so in the warnings"). The level is
#: chosen on the diagnostics, not on the error against the truth: at 10 the
#: effective sample size passes a third of the plays once the logger has
#: converged, and the largest weight is ten.
OPE_CLIP = 10.0


def _ope(
    chooser: ContextualBandit,
    keys: Sequence[str],
    records: Sequence[PlayRecord],
    name: str,
    clip: float | None = None,
) -> dict[str, Any]:
    """The SNIPS value of a chooser snapshot on a set of plays.

    The diagnostics come back with it: an estimate whose effective sample
    size is a small fraction of the plays is mostly the logger's own value,
    and the reader has to be able to see that.
    """
    empty = {
        "value": None,
        "lo": None,
        "hi": None,
        "n": len(records),
        "effective_n": None,
        "max_weight": None,
        "warnings": (),
    }
    if not records:
        return empty
    target = BanditTarget(chooser, keys, name)
    try:
        estimate = evaluate(records, target, method="snips", clip=clip)
    except OPEError:
        return empty
    return {
        "value": estimate.value,
        "lo": estimate.ci_low,
        "hi": estimate.ci_high,
        "n": estimate.n,
        "effective_n": estimate.effective_n,
        "max_weight": estimate.max_weight,
        "warnings": estimate.warnings,
    }


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


# ---------------------------------------------------------------- the statistics

#: The two-sided 95% critical values of Student's t, df 1..30.
_T95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def t_critical(df: int) -> float:
    """The two-sided 95% t critical value."""
    if df <= 0:
        return float("nan")
    if df <= len(_T95):
        return _T95[df - 1]
    return 1.96


def mean_ci(values: Sequence[float | None]) -> dict[str, Any]:
    """The mean over the seeds, with a 95% interval from Student's t."""
    clean = [v for v in values if v is not None]
    if not clean:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "sd": None}
    n = len(clean)
    mean = sum(clean) / n
    if n == 1:
        return {"n": 1, "mean": mean, "lo": mean, "hi": mean, "sd": 0.0}
    var = sum((v - mean) ** 2 for v in clean) / (n - 1)
    sd = math.sqrt(var)
    half = t_critical(n - 1) * sd / math.sqrt(n)
    return {
        "n": n,
        "mean": mean,
        "lo": mean - half,
        "hi": mean + half,
        "sd": sd,
        "min": min(clean),
        "max": max(clean),
    }


def summarise(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The per-arm, per-night summary: the means and their intervals."""
    out: list[dict[str, Any]] = []
    arms = sorted({row["arm"] for row in rows})
    nights = sorted({row["night"] for row in rows})
    metrics = (
        "n_old_buckets",
        "n_old_pairs",
        "n_touched_buckets",
        "drift_mean_abs",
        "drift_max_abs",
        "untouched_max_abs",
        "untouched_mean_abs",
        "untouched_n",
        "touched_n",
        "n_pairs_collapsed",
        "context_age_nights",
        "touched_mean_abs",
        "touched_max_abs",
        "error_prev_view",
        "error_now_old_view",
        "error_now_new_view",
        "choice_flip_rate",
        "choice_flip_rate_same_options",
        "choice_options_changed",
        "pick_new_tile_rate",
        "ope_prev_value",
        "ope_now_value",
        "ope_drift",
        "ope_full_value",
        "ope_truth_now",
        "ope_truth_prev",
        "value_drift_exact",
        "ope_clipped_now_value",
        "ope_clipped_drift",
        "ope_error_now",
        "ope_effective_n",
        "ope_max_weight",
        "ope_effective_n_unclipped",
        "ope_max_weight_unclipped",
        "library_active",
        "library_total",
        "library_retired",
        "plays_total",
    )
    for arm in arms:
        for night in nights:
            subset = [r for r in rows if r["arm"] == arm and r["night"] == night]
            if not subset:
                continue
            entry: dict[str, Any] = {
                "arm": arm,
                "night": night,
                "seeds": len(subset),
                "metrics": {m: mean_ci([r[m] for r in subset]) for m in metrics},
            }
            # The OPE's own intervals, unioned over the seeds.
            for prefix, lo_key, hi_key in (
                ("ope_now", "ope_now_lo", "ope_now_hi"),
                ("ope_prev", "ope_prev_lo", "ope_prev_hi"),
                ("ope_full", "ope_full_lo", "ope_full_hi"),
            ):
                los = [r[lo_key] for r in subset if r[lo_key] is not None]
                his = [r[hi_key] for r in subset if r[hi_key] is not None]
                entry[f"{prefix}_interval_lo"] = min(los) if los else None
                entry[f"{prefix}_interval_hi"] = max(his) if his else None
            out.append(entry)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=24)
    parser.add_argument("--nights", type=int, default=10)
    parser.add_argument("--contexts", type=int, default=250)
    parser.add_argument("--buckets", type=int, default=4)
    parser.add_argument("--arms", default="refit,refit_grow,refit_moved")
    parser.add_argument(
        "--tiles",
        default=str(Path(__file__).resolve().parent / "real_tiles.json"),
        help="the real tiles, as extracted from the night ledgers",
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "results" / "refit_drift.json"),
    )
    args = parser.parse_args()

    config = Config(
        nights=args.nights,
        contexts_per_night=args.contexts,
        buckets_per_night=args.buckets,
    )
    real_tiles = load_real_tiles(Path(args.tiles))
    if not real_tiles:
        raise SystemExit(f"no tiles in {args.tiles}; run extract_real_tiles.py first")

    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    started = box_state()
    rows: list[dict[str, Any]] = []
    for arm in arms:
        for seed in range(args.seeds):
            run = run_once(config, arm, seed, real_tiles)
            rows.extend(analyse(config, arm, seed, run))
            print(
                f"  {arm:12s} seed {seed:3d}  plays={len(run.records):4d} "
                f"library={run.nights[-1].library_total:3d} tiles "
                f"({run.nights[-1].library_retired} retired, "
                f"{len(run.nights[-1].active)} active)",
                flush=True,
            )
    finished = box_state()

    payload = {
        "experiment": "refit drift",
        "when": started.get("time"),
        "config": {
            **asdict(config),
            "outcome": asdict(config.outcome),
            "arms": arms,
            "seeds": args.seeds,
        },
        "tiles": [
            {
                "id": t.id,
                "title": t.title,
                "family": t.family,
                "style": tile_style(t)[1],
            }
            for t in real_tiles
        ],
        "box_state_before": started,
        "box_state_after": finished,
        "rows": rows,
        "summary": summarise(rows),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"\n{len(rows)} rows -> {out}")
    print(format_box_state(finished))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
