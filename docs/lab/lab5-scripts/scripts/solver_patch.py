# lab5 (round 5, IDEAS #4) — batch the solver's proposals.
#
# What this file is
# -----------------
# `SimulatedAnnealingSolver.retry_attempt_proposals` copied out of
# infinigen/core/constraints/example_solver/annealing.py (thor-spike branch,
# identical in the v2 venv's checkout) and changed so one annealing step can
# score **N** candidates instead of one. It is swapped in at runtime by
# `install()`; the infinigen checkouts and the venv it runs from are imported
# read-only and never written.
#
# Arms
# ----
# baseline : upstream semantics unchanged — the *first applicable* move from
#            the generator is applied, evaluated and returned (timing probes
#            added, decisions identical). The control arm.
# batch    : draw up to N applicable candidates from the same move generator,
#            score each one (apply → evaluate → revert), then pick:
#              best     fewest violations, then lowest loss — the same
#                       lexicographic order the annealer's accept rule uses
#              sample   ∝ exp(-loss/T) over the scored set (Boltzmann at the
#                       current annealing temperature)
#              uniform  uniformly — provably the same proposal kernel as
#                       baseline (the picked candidate is a draw from the
#                       same generator), a harness control
#            The picked move is (re)applied and returned with its EvalResult;
#            `step` — untouched — then runs the ordinary Metropolis accept,
#            so the accept/reject decision stays sequential exactly as
#            upstream. What changes is only *which* single candidate the
#            annealer gets to judge.
#
# Moves whose apply() is stochastic (Addition, Resample, ReinitPose,
# RelationPlaneChange — they sample a placeholder/pose inside apply) cannot
# be re-applied bit-identically after the batch's revert, so for those the
# picked candidate is re-applied and re-evaluated and the *fresh* result is
# what the annealer sees (state and score always agree; the batch's score
# selected the move's type+arguments, its realization is resampled once).
# Deterministic moves (Translate, Rotate, Deletion) reuse the cached batch
# result — the re-apply reproduces the exact scored state.
#
# Probes: every scored candidate appends a row to CANDIDATES (times for
# apply/eval/revert, ok, loss, viol); every batched step appends one row to
# STEPS (N scored, n_invalid, chosen index, chosen loss). An optional
# node-impl profiler (enable_profile) splits evaluate() time by impl module
# — the "GPU-portable fraction" of the scoring, per round 2's finding that
# the geometry impls are the ported part.

from __future__ import annotations

import logging
import time

import numpy as np

from infinigen.core.constraints.evaluator import eval_memo

logger = logging.getLogger(__name__)

# ---- state set by install()/set_stage(); drained by the driver ------------

CANDIDATES: list[dict] = []  # one row per candidate scored (all arms)
STEPS: list[dict] = []       # one row per *batched* step (batch arm only)
PROFILE: dict[str, dict] = {}  # impl-module → {t, n} when profile enabled

_arm = "baseline"
_N = 1
_mode = "best"
_stage = ""


def install(arm: str, N: int = 1, mode: str = "best"):
    """Swap the solver's proposal retry method for lab5's copy."""
    global _arm, _N, _mode
    from infinigen.core.constraints.example_solver.annealing import (
        SimulatedAnnealingSolver,
    )

    _arm = arm
    _N = int(N)
    _mode = mode
    if arm == "baseline":
        fn = baseline_retry_attempt_proposals
    elif arm == "batch":
        fn = batched_retry_attempt_proposals
    else:
        raise ValueError(f"unknown arm {arm!r}")
    SimulatedAnnealingSolver.retry_attempt_proposals = fn
    logger.info("lab5: installed %s retry_attempt_proposals (N=%s mode=%s)", arm, N, mode)


def set_stage(label: str):
    global _stage
    _stage = label


def drain() -> tuple[list[dict], list[dict], dict]:
    global CANDIDATES, STEPS, PROFILE
    out = (CANDIDATES, STEPS, PROFILE)
    CANDIDATES, STEPS, PROFILE = [], [], {}
    return out


# ---- revert helper ----------------------------------------------------------
#
# (An earlier revision carried a workaround for what looked like a broken
# Deletion.revert tail — that line actually belongs to reassignment.py's
# RelationTargetChange; Deletion.revert is fine. No workaround needed.)

def _safe_revert(move, state) -> None:
    move.revert(state)


def _deterministic_apply(move) -> bool:
    from infinigen.core.constraints.example_solver import moves

    return isinstance(move, (moves.TranslateMove, moves.RotateMove, moves.Deletion))


def _record(move, ok, t_apply, t_eval, t_revert, result) -> None:
    CANDIDATES.append(
        dict(
            stage=_stage,
            move=type(move).__name__,
            ok=bool(ok),
            t_apply=t_apply,
            t_eval=t_eval,
            t_revert=t_revert,
            loss=(result.loss() if result is not None else None),
            viol=(result.viol_count() if result is not None else None),
        )
    )


# ---- the baseline arm: upstream, verbatim, plus probes ---------------------

def baseline_retry_attempt_proposals(self, propose_func, consgraph, state, temp, filter_domain):
    move_gen = propose_func(consgraph, state, filter_domain, temp)

    move = None
    retry = None
    for retry, move in enumerate(move_gen):
        if retry == self.max_invalid_candidates:
            logger.debug(
                f"{move_gen=} reached {self.max_invalid_candidates=} without succeeding an apply()"
            )
            break

        t0 = time.perf_counter()
        succeeded = move.apply(state)
        t_apply = time.perf_counter() - t0

        if succeeded:
            eval_memo.evict_memo_for_move(consgraph, state, self.eval_memo, move)
            t0 = time.perf_counter()
            result = self._move(consgraph, state, move, filter_domain)
            t_eval = time.perf_counter() - t0
            _record(move, True, t_apply, t_eval, 0.0, result)
            return move, result, retry

        logger.debug(f"{retry=} reverting {move=}")
        t0 = time.perf_counter()
        eval_memo.evict_memo_for_move(consgraph, state, self.eval_memo, move)
        _safe_revert(move, state)
        _record(move, False, t_apply, 0.0, time.perf_counter() - t0, None)

    else:
        logger.debug(f"{move_gen=} produced {retry} attempts and none were valid")

    return move, None, retry


# ---- the batched arm: N candidates, one sequential decision ----------------

def batched_retry_attempt_proposals(self, propose_func, consgraph, state, temp, filter_domain):
    N, mode = _N, _mode
    move_gen = propose_func(consgraph, state, filter_domain, temp)

    scored = []  # (move, EvalResult) — state already reverted for each
    n_invalid = 0
    # Invalid-apply allowance: upstream gives up a *step* after
    # max_invalid_candidates failed applies; a batch of N wanted candidates
    # gets N× that allowance, so an equal-budget batched step spends the same
    # number of apply() attempts as the baseline steps it replaces (measured:
    # ~77% of applies fail validity on the singleroom scene).
    invalid_budget = N * max(1, self.max_invalid_candidates)
    last_move = None

    for move in move_gen:
        if len(scored) >= N or n_invalid >= invalid_budget:
            break

        t0 = time.perf_counter()
        succeeded = move.apply(state)
        t_apply = time.perf_counter() - t0

        if not succeeded:
            t0 = time.perf_counter()
            eval_memo.evict_memo_for_move(consgraph, state, self.eval_memo, move)
            _safe_revert(move, state)
            _record(move, False, t_apply, 0.0, time.perf_counter() - t0, None)
            n_invalid += 1
            last_move = move
            continue

        eval_memo.evict_memo_for_move(consgraph, state, self.eval_memo, move)
        t0 = time.perf_counter()
        result = self._move(consgraph, state, move, filter_domain)
        t_eval = time.perf_counter() - t0

        # score is in hand; restore the state for the next candidate
        t0 = time.perf_counter()
        eval_memo.evict_memo_for_move(consgraph, state, self.eval_memo, move)
        _safe_revert(move, state)
        t_revert = time.perf_counter() - t0

        _record(move, True, t_apply, t_eval, t_revert, result)
        scored.append((move, result))
        last_move = move

    if not scored:
        return last_move, None, n_invalid

    if mode == "best":
        j = min(
            range(len(scored)),
            key=lambda i: (scored[i][1].viol_count(), scored[i][1].loss()),
        )
    elif mode == "sample":
        losses = np.array([res.loss() for _, res in scored])
        viols = np.array([res.viol_count() for _, res in scored])
        # Boltzmann on the loss at the current temperature; a candidate that
        # raises violations cannot survive the accept rule anyway, so weight
        # only by loss (the annealer's own ordering of concerns).
        w = np.exp(-(losses - losses.min()) / max(temp, 1e-12))
        if not np.isfinite(w).all() or w.sum() <= 0:
            j = int(np.argmin(viols * 1e6 + losses))
        else:
            j = int(np.random.choice(len(scored), p=w / w.sum()))
    elif mode == "uniform":
        j = int(np.random.randint(len(scored)))
    else:
        raise ValueError(f"unknown lab5 mode {mode!r}")

    move, result = scored[j]

    if _deterministic_apply(move):
        # re-apply reproduces the exact scored state; cached result is valid
        t0 = time.perf_counter()
        ok = move.apply(state)
        eval_memo.evict_memo_for_move(consgraph, state, self.eval_memo, move)
        if not ok:  # cannot happen for a deterministic move that applied once
            _safe_revert(move, state)
            STEPS.append(dict(stage=_stage, n_scored=len(scored), n_invalid=n_invalid,
                              chosen=j, mode=mode, reapplied=False))
            return move, None, n_invalid
        t_reapply = time.perf_counter() - t0
    else:
        # stochastic apply: re-applying resamples the realization, so score
        # the realization the annealer will actually judge
        t0 = time.perf_counter()
        ok = move.apply(state)
        eval_memo.evict_memo_for_move(consgraph, state, self.eval_memo, move)
        if ok:
            result = self._move(consgraph, state, move, filter_domain)
        t_reapply = time.perf_counter() - t0
        if not ok:
            _safe_revert(move, state)
            STEPS.append(dict(stage=_stage, n_scored=len(scored), n_invalid=n_invalid,
                              chosen=j, mode=mode, reapplied=False))
            return move, None, n_invalid

    STEPS.append(dict(stage=_stage, n_scored=len(scored), n_invalid=n_invalid,
                      chosen=j, mode=mode, reapplied=True, t_reapply=t_reapply,
                      chosen_loss=result.loss(), chosen_viol=result.viol_count()))
    return move, result, n_invalid


# ---- optional node-impl profiler -------------------------------------------
#
# Wraps every registered constraint impl with a timer that accumulates into
# PROFILE keyed by the impl's module. evaluate()'s own bookkeeping (the
# graph walk, memo copies) is *not* attributed to any impl — that split is
# exactly what this measures: impl time (the numerics round 2 ported) vs
# the rest (the graph walk round 2 called "bookkeeping").

def enable_profile() -> None:
    from infinigen.core.constraints.evaluator import node_impl

    def timed(fn, key):
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            res = fn(*args, **kwargs)
            dt = time.perf_counter() - t0
            slot = PROFILE.setdefault(key, dict(t=0.0, n=0))
            slot["t"] += dt
            slot["n"] += 1
            return res

        return wrapper

    for node_cls, fn in list(node_impl.node_impls.items()):
        key = getattr(fn, "__module__", "?").rsplit(".", 1)[-1]
        node_impl.node_impls[node_cls] = timed(fn, key)
