"""Replay the liquid study's real d1 traces through core.hysteresis.

The traces are `.traces/exp_c_trace_{model}.json` — 240 recorded decisions
per model (6 trials × 40 steps of the sea-state task, §4.3), each with the
probability vector, the model's confidence and the ground truth the study
recorded. This script is the offline half of Part 3 item 3: no GPU, no
server, redo it any time.

What it measures per configuration (upper τ, lower exit = τ − band, dwell):

* **transitions** — standing changes per 240 ticks (pooled over trials,
  the gate reset at each trial boundary, one subject per recording);
* **flickers** — changes reversed within `WINDOW` ticks (the
  `core.hysteresis.metrics` definition, in ticks not seconds);
* **drop / act latency** — ticks from the signal genuinely crossing to the
  standing following, per direction (act→escalate is the drop);
* **agreement** — the standing against the recorded ground truth, two
  ways: against what the model was *shown* (the model's own misreadings —
  the E1-style calibration question) and against the study's `truth`
  (which the perceptual noise moves, so no confidence threshold can
  fully catch it — §4.3's finding).

The controls:

* **the raw τ gate** — `core.judge`'s `ConfidencePolicy.decision` applied
  per tick, which is what ships today;
* **the single threshold** — the same gate with the band collapsed to a
  point and no dwell; it must come out identical to the raw τ gate,
  because that is what the current policy is.

The choice rule (the brief's, made mechanical):

> **τ is not the sweep's to choose** — a rule that minimised flickers
> over τ would elect the silent gate, and a gate that never speaks looks
> exactly like a gate with nothing to say (exp-hysteresis-gate §4.3).
> τ* is the task's calibration: the τ with the best raw-gate catch of
> the model's misreadings (against what it was shown — the E1-style
> reading) **subject to the raw gate still acting on at least half the
> ticks**, because an escalation standing whose rung never acts is not a
> cascade. Then, at τ*, the standing's shape (band, dwell_up, dwell_down):
> **fewest flickers subject to a drop latency of at most `BOUND_DOWN`
> ticks, an act latency of at most `BOUND_UP` ticks, and to keeping the
> raw τ gate's own work at the same τ — its catch and its agreement**;
> ties by fewest transitions, then least mean latency, then widest band.

The keep-the-work constraint is what stops the bounds from being gamed:
widening the band and the dwells removes flickers by refusing to speak,
which loses exactly the wrong judgments the standing exists to escalate.

Run it:

    PYTHONPATH=. .venv/bin/python docs/lab/hysteresis-scripts/replay_d1_traces.py

Writes `results/hysteresis-d1-sweep.json` beside this script and prints
every number the experiment note cites.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from core.hysteresis import HysteresisGate, Level  # noqa: E402
from core.judge.gate import ConfidencePolicy  # noqa: E402

TRACES = REPO / ".traces"
MODELS = ("d1-2B", "d1-3B")

#: The letter of the ground truth / shown condition in the trace.
LETTERS = "ABCDE"

#: The sweep. τ covers the trace's crossing range — for the 2B that is
#: nowhere near E1's 0.5 (the recorded confidence never dips below 0.522,
#: so τ = 0.5 never fires on this task); the band and the two dwells are
#: in ticks of the caller's clock (one tick = one decision).
TAUS = (0.5, 0.6, 0.7, 0.8, 0.9)
BANDS = (0.0, 0.05, 0.10, 0.15, 0.20)
DWELLS = (0, 1, 2, 3)

#: The flicker window, in ticks: a standing change reversed within two
#: decisions of the change is a flicker.
WINDOW = 2

#: The latency bounds of the choice rule, in ticks. Escalation is the
#: safety direction, so its bound is the tight one; earning `act` back
#: may take one tick more. Two ticks on the 2B recording is ~64 ms of
#: decision time, on the 3B ~101 ms.
BOUND_DOWN = 2
BOUND_UP = 3

#: An escalation standing whose rung never acts is not a cascade: the
#: calibration τ* must keep the raw gate acting on at least this share
#: of ticks.
MIN_ACT_RATE = 0.5


@dataclass(frozen=True)
class Config:
    tau: float
    band: float
    dwell_up: int
    dwell_down: int


@dataclass
class Metrics:
    transitions: int = 0
    flickers: int = 0
    drop_latencies: list = field(default_factory=list)
    act_latencies: list = field(default_factory=list)
    tp_shown: int = 0
    fp_shown: int = 0
    tn_shown: int = 0
    fn_shown: int = 0
    tp_truth: int = 0
    fp_truth: int = 0
    tn_truth: int = 0
    fn_truth: int = 0
    n: int = 0

    def add(self, other: "Metrics") -> None:
        for name in (
            "transitions", "flickers", "tp_shown", "fp_shown", "tn_shown",
            "fn_shown", "tp_truth", "fp_truth", "tn_truth", "fn_truth", "n",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.drop_latencies.extend(other.drop_latencies)
        self.act_latencies.extend(other.act_latencies)

    @property
    def act_rate(self) -> float:
        return (self.tp_shown + self.fp_shown) / self.n if self.n else 0.0

    def agreement(self, correct: str) -> float:
        tp = getattr(self, f"tp_{correct}")
        tn = getattr(self, f"tn_{correct}")
        return (tp + tn) / self.n if self.n else 0.0

    def catch(self, correct: str) -> float | None:
        """Wrong judgments the standing escalated, over all wrong ones."""
        fp = getattr(self, f"fp_{correct}")
        tn = getattr(self, f"tn_{correct}")
        return tn / (fp + tn) if fp + tn else None

    def tax(self, correct: str) -> float | None:
        """Right judgments the standing escalated, over all right ones."""
        tp = getattr(self, f"tp_{correct}")
        fn = getattr(self, f"fn_{correct}")
        return fn / (tp + fn) if tp + fn else None

    def summary(self) -> dict:
        drop = self.drop_latencies or [0]
        act = self.act_latencies or [0]
        return {
            "transitions": self.transitions,
            "flickers": self.flickers,
            "drop_latency_ticks": {"mean": round(sum(drop) / len(drop), 3), "max": max(drop)},
            "act_latency_ticks": {"mean": round(sum(act) / len(act), 3), "max": max(act)},
            "act_rate": round(self.act_rate, 4),
            "agreement_vs_shown": round(self.agreement("shown"), 4),
            "agreement_vs_truth": round(self.agreement("truth"), 4),
            "catch_vs_shown": _round(self.catch("shown")),
            "catch_vs_truth": _round(self.catch("truth")),
            "tax_vs_shown": _round(self.tax("shown")),
            "tax_vs_truth": _round(self.tax("truth")),
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def load_trace(model: str) -> tuple[list[dict], dict]:
    with open(TRACES / f"exp_c_trace_{model}.json") as handle:
        data = json.load(handle)
    trials: dict[int, list[dict]] = {}
    for row in data["trace"]:
        trials.setdefault(row["trial"], []).append(row)
    return data["trace"], trials


def judgments(trial: list[dict]) -> tuple[list[bool], list[bool]]:
    """Per tick: was the argmax right against what was shown / against truth."""
    shown, truth = [], []
    for row in trial:
        argmax = max(row["probs"], key=lambda key: row["probs"][key])
        shown.append(argmax == LETTERS[row["shown"]])
        truth.append(argmax == LETTERS[row["truth"]])
    return shown, truth


def replay(trials: dict[int, list[dict]], config: Config) -> Metrics:
    """One configuration over the whole trace, one gate per trial.

    Each trial is a subject of its own: the standing resets at a trial
    boundary the way a fresh recording would, and the counts pool.
    """
    total = Metrics()
    for rows in trials.values():
        gate = HysteresisGate(
            (
                Level("escalate", enter=config.tau - config.band, exit=float("-inf")),
                Level("act", enter=config.tau, exit=config.tau - config.band),
            ),
            dwell_up=config.dwell_up,
            dwell_down=config.dwell_down,
        )
        shown, truth = judgments(rows)
        metrics = Metrics()
        changes: list[tuple[int, str, str]] = []
        previous = gate.state
        for tick, row in enumerate(rows):
            transition = gate.step(row["confidence"], tick)
            state = transition.state
            if state != previous:
                metrics.transitions += 1
                changes.append((tick, previous, state))
                if transition.latency is not None:
                    if state == "escalate":
                        metrics.drop_latencies.append(transition.latency)
                    else:
                        metrics.act_latencies.append(transition.latency)
            acted = state == "act"
            for flag, correct in ((shown[tick], "shown"), (truth[tick], "truth")):
                key = "tp" if acted else "fn"
                if not flag:
                    key = "fp" if acted else "tn"
                setattr(metrics, f"{key}_{correct}", getattr(metrics, f"{key}_{correct}") + 1)
            metrics.n += 1
            previous = state
        # metrics.py's flicker definition, in ticks: a change reversed
        # within WINDOW ticks of itself.
        for index, (when, was, _) in enumerate(changes):
            for later_when, _, back in changes[index + 1 :]:
                if later_when - when > WINDOW:
                    break
                if back == was:
                    metrics.flickers += 1
                    break
        total.add(metrics)
    return total


def raw_policy(trials: dict[int, list[dict]], tau: float) -> Metrics:
    """core.judge's current gate — `ConfidencePolicy.decision`, per tick."""
    policy = ConfidencePolicy()
    total = Metrics()
    for rows in trials.values():
        shown, truth = judgments(rows)
        metrics = Metrics()
        changes: list[tuple[int, str, str]] = []
        previous = "escalate"
        for tick, row in enumerate(rows):
            state = policy.decision(confidence=row["confidence"], tau=tau)
            if state != previous:
                metrics.transitions += 1
                changes.append((tick, previous, state))
            acted = state == "act"
            for flag, correct in ((shown[tick], "shown"), (truth[tick], "truth")):
                key = "tp" if acted else "fn"
                if not flag:
                    key = "fp" if acted else "tn"
                setattr(metrics, f"{key}_{correct}", getattr(metrics, f"{key}_{correct}") + 1)
            metrics.n += 1
            previous = state
        for index, (when, was, _) in enumerate(changes):
            for later_when, _, back in changes[index + 1 :]:
                if later_when - when > WINDOW:
                    break
                if back == was:
                    metrics.flickers += 1
                    break
        total.add(metrics)
    return total


def rule_key(metrics: Metrics, config: Config) -> tuple:
    """The choice rule's sort key: flickers, then transitions, then mean
    latency, then the widest band."""
    drop = metrics.drop_latencies or [0]
    act = metrics.act_latencies or [0]
    mean_latency = (sum(drop) / len(drop) + sum(act) / len(act)) / 2
    return (
        metrics.flickers,
        metrics.transitions,
        round(mean_latency, 6),
        -config.band,
        config.dwell_up,
    )


def eligible(metrics: Metrics) -> bool:
    drop = metrics.drop_latencies or [0]
    act = metrics.act_latencies or [0]
    return max(drop) <= BOUND_DOWN and max(act) <= BOUND_UP


def not_worse_than_raw(metrics: Metrics, raw: Metrics) -> bool:
    """The keep-the-work constraint: the gated standing must not lose the
    raw τ gate's catch or its agreement (both against what was shown)."""
    if metrics.agreement("shown") + 1e-9 < raw.agreement("shown"):
        return False
    raw_catch, gated_catch = raw.catch("shown"), metrics.catch("shown")
    if raw_catch is not None and (gated_catch is None or gated_catch + 1e-9 < raw_catch):
        return False
    return True


def calibrated_tau(raws: dict[float, Metrics]) -> float:
    """τ*: the task's calibration — best catch of the model's misreadings
    subject to the raw gate still acting on at least `MIN_ACT_RATE` of the
    ticks. Ties prefer the τ that acts on more of them (the lesser tax)."""
    candidates = [
        (tau, metrics)
        for tau, metrics in raws.items()
        if metrics.act_rate >= MIN_ACT_RATE and metrics.catch("shown") is not None
    ]
    if not candidates:
        raise AssertionError("no τ in the sweep keeps the rung acting; the grid is too narrow")
    candidates.sort(key=lambda item: (-item[1].catch("shown"), -item[1].act_rate, item[0]))
    return candidates[0][0]


def choose(trials: dict[int, list[dict]], raws: dict[float, Metrics]) -> dict:
    """The rule: the shape at the task's calibrated τ."""
    tau_star = calibrated_tau(raws)
    raw = raws[tau_star]
    candidates = []
    for band in BANDS:
        for dwell_up in DWELLS:
            for dwell_down in DWELLS:
                config = Config(tau=tau_star, band=band, dwell_up=dwell_up, dwell_down=dwell_down)
                metrics = replay(trials, config)
                if eligible(metrics) and not_worse_than_raw(metrics, raw):
                    candidates.append((rule_key(metrics, config), config, metrics))
    if not candidates:
        raise AssertionError(f"no shape keeps the raw gate's work at τ*={tau_star} within the bounds")
    candidates.sort(key=lambda item: item[0])
    _, config, metrics = candidates[0]
    return {
        "tau_star": tau_star,
        "config": asdict(config),
        "raw_at_tau_star": raw.summary(),
        "metrics": metrics.summary(),
    }


def main() -> int:
    out: dict = {"window_ticks": WINDOW, "bound_down_ticks": BOUND_DOWN, "bound_up_ticks": BOUND_UP, "models": {}}
    for model in MODELS:
        trace, trials = load_trace(model)
        wall = sorted(row["wall_ms"] for row in trace)
        tick_ms = wall[len(wall) // 2]
        model_out: dict = {"n": len(trace), "tick_p50_ms": tick_ms, "taus": {}}

        with_work: list[float] = []
        raws: dict[float, Metrics] = {}
        for tau in TAUS:
            control_policy = raw_policy(trials, tau)
            raws[tau] = control_policy
            control_single = replay(trials, Config(tau=tau, band=0.0, dwell_up=0, dwell_down=0))
            if control_policy.summary() != control_single.summary():
                raise AssertionError(
                    f"{model} τ={tau}: the single threshold and the raw τ gate "
                    "disagree — the control is broken"
                )
            if control_policy.flickers > 0:
                with_work.append(tau)
            grid = {}
            for band in BANDS:
                for dwell_up in DWELLS:
                    for dwell_down in DWELLS:
                        config = Config(tau=tau, band=band, dwell_up=dwell_up, dwell_down=dwell_down)
                        grid[json.dumps(asdict(config))] = replay(trials, config).summary()
            model_out["taus"][str(tau)] = {
                "raw_tau_gate": control_policy.summary(),
                "grid": grid,
            }

        model_out["taus_with_work"] = [str(tau) for tau in with_work]
        model_out["chosen"] = choose(trials, raws)
        out["models"][model] = model_out

        print(f"\n== {model} — {len(trace)} ticks, 1 tick ≈ {tick_ms} ms (p50 wall)")
        print(f"   τ where the raw gate flickers: {with_work}")
        for tau in TAUS:
            control = raws[tau].summary()
            print(
                f"   raw τ={tau}: {control['transitions']:3d} changes, "
                f"{control['flickers']:3d} flickers, act {control['act_rate']:.3f}, "
                f"catch/shown {control['catch_vs_shown']}, agreement/shown {control['agreement_vs_shown']}"
            )
            if tau in with_work:
                winners = []
                for band in BANDS:
                    for dwell_up in DWELLS:
                        for dwell_down in DWELLS:
                            config = Config(tau=tau, band=band, dwell_up=dwell_up, dwell_down=dwell_down)
                            metrics = replay(trials, config)
                            if eligible(metrics) and not_worse_than_raw(metrics, raws[tau]):
                                winners.append((rule_key(metrics, config), config, metrics))
                if winners:
                    winners.sort(key=lambda item: item[0])
                    _, best, metrics = winners[0]
                    summary = metrics.summary()
                    print(
                        f"      winner by the rule: band={best.band} dwell_up={best.dwell_up} "
                        f"dwell_down={best.dwell_down} -> {summary['flickers']} flickers "
                        f"({control['flickers']} raw), drop max {summary['drop_latency_ticks']['max']}, "
                        f"act max {summary['act_latency_ticks']['max']}, act rate {summary['act_rate']}, "
                        f"catch/shown {summary['catch_vs_shown']}, agreement/shown {summary['agreement_vs_shown']}"
                    )
                else:
                    print("      no config keeps the raw gate's work within the bounds at this τ")
        chosen = model_out["chosen"]
        print(f"   τ* = {chosen['tau_star']} (best catch subject to acting on ≥ {MIN_ACT_RATE} of ticks)")
        print(f"   chosen shape at τ*: {chosen['config']}")
        print(f"   chosen at τ*: {json.dumps(chosen['metrics'], sort_keys=True)}")
        print(f"   raw at τ*:    {json.dumps(chosen['raw_at_tau_star'], sort_keys=True)}")

    results = HERE / "results"
    results.mkdir(exist_ok=True)
    path = results / "hysteresis-d1-sweep.json"
    with open(path, "w") as handle:
        json.dump(out, handle, indent=1, sort_keys=True)
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
