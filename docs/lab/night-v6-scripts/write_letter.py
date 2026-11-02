#!/usr/bin/env python3
"""The morning's letter: to Casey, from the night.

Reads the night's `morning.json` and writes `letter.md`: at most 150 words,
one surprise, one open question. Every number in the letter is read out of
the morning, which is folded from the ledger, so every fact in it has a
receipt behind it.

**The decision numbers come from the ledger.** The night-v5 letter said
"1 of 5 decisions answered locally (4 went to the cloud)" while the same
morning's measurements said 251 decisions, 245 on the local d1-3B: the
morning's `decisions` block held the JudgeSeat's own five finished
decisions (the routed decoy cell's 240 verdicts and two refusals never
reached it, and a local try that escalated collapsed into one row blaming
the cloud). The fix is order: the letter counts `judge.verdict` rows from
the night's `ledger.db` — one row per attempt, refusals included, the same
split `measure.py` prints — through the one shared counter
(`decision_counts.py`, beside this script), and only falls back to the
morning's block when no ledger sits beside it. A test pins the letter's
numbers to the ledger's (tests/night/test_letter_ledger.py).

The surprise and the question are chosen by rule from the night's own
measurements, not written in advance: the surprise is the largest thing the
night measured that the night did not expect, and the question is the
decision that number leaves open.

`--facts` reads a facts file in the same shape instead — used when the
night itself did not run and the letter has to be written from the seat's
other receipts. The facts file names the receipt behind each block, and
the letter says which one it is.

Run on the Thor, from the night-v6 worktree, after the night:

    PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v6-scripts/write_letter.py --out artifacts/night-v6

    PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v6-scripts/write_letter.py --out artifacts/night-v6 \
        --facts docs/lab/night-v6-scripts/letter-facts.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_counts import count_ledger  # noqa: E402

WORD_LIMIT = 150


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"no such file: {path}")
    return json.loads(path.read_text())


def decision_facts(m: dict, ledger: Path | None) -> dict:
    """The decision counts, from the receipt the ledger is.

    In order: the morning's own ledger-derived block (the runner folds one
    in), the ledger file beside the morning, and only then — a letter
    written before the night ran — the morning's decisions block as given.
    """
    block = (m.get("decisions", {}) or {}).get("ledger") or {}
    if block:
        return dict(block)
    if ledger is not None and ledger.exists():
        counted = count_ledger(ledger)
        return {key: counted[key] for key in
                ("count", "local", "escalated", "unattributed",
                 "surfaced", "act", "escalate", "rungs")}
    decisions = m.get("decisions", {}) or {}
    return {key: decisions.get(key, 0) for key in
            ("count", "local", "escalated", "unattributed", "surfaced")}


def facts(m: dict, ledger: Path | None = None) -> dict:
    """The night's measurements, pulled out of the morning."""
    props = m.get("props", {}) or {}
    winners = props.get("winners", []) or []
    decisions = decision_facts(m, ledger)
    judge = m.get("judge", {}) or {}
    critic = m.get("critic", {}) or {}
    probe = judge.get("route_probe", {}) or {}
    signals = critic.get("signals", []) or []
    pictures = [s for s in signals if s.get("stage") == "image"]
    meshes = [s for s in signals if s.get("stage") == "mesh"]
    fired = [s for s in pictures if s.get("fired")]
    ghosts = [s for s in meshes if s.get("ghost")]
    fired_classes: dict[str, int] = {}
    for note in fired:
        for name in note.get("fired", []):
            fired_classes[name] = fired_classes.get(name, 0) + 1
    prior = critic.get("prior", {}) or {}
    return {
        "ran": bool(winners) or bool(props.get("kept")),
        "kept": props.get("kept", 0),
        "names": ", ".join(str(w.get("request", "?")) for w in winners) or "none",
        "wall": m.get("wall_minutes"),
        "local": decisions.get("local", 0),
        "escalated": decisions.get("escalated", 0),
        "unattributed": decisions.get("unattributed", 0),
        "surfaced": decisions.get("surfaced", 0),
        "count": decisions.get("count", 0),
        "model": judge.get("model", "?"),
        "probe_accuracy": probe.get("accuracy"),
        "probe_steps": probe.get("steps", 0),
        "pictures": len(pictures),
        "fired": len(fired),
        "fired_classes": fired_classes,
        "ghosts": len(ghosts),
        "props_scored": len(meshes),
        "prior_groups": prior.get("groups"),
        "prior_largest": prior.get("largest_group"),
        "prior_smallest": prior.get("smallest_group"),
        "prior_threshold": prior.get("ghost_threshold"),
        "prior_gate_live": prior.get("gate_live"),
        "library_approved": (m.get("critic", {}) or {}).get("library", {})
                             .get("approved"),
        "lease_wait_s": (m.get("memory", {}) or {}).get("lease_wait_s"),
        "status_note": str(m.get("status_note") or "").strip(),
    }


def the_gate_note(f: dict) -> str:
    """What the prior's ghost gate can do tonight, from the ledger.

    The gate is a rank against a group, and a group of n cannot score below
    0.5/(n+1), so the gate at 0.05 needs a group of ten. The library's ten
    crates put one there, and the ledger's own ``gate_live`` flag says so —
    the letter must not claim the gate is unreachable when the night's own
    row says it is reachable.
    """
    if f["prior_gate_live"] and f["prior_smallest"]:
        floor = 0.5 / (f["prior_smallest"] + 1)
        return (f"the prior's ghost gate can reach below "
                f"{f['prior_threshold']} for the first time — the library's "
                f"{f['library_approved']} approved objects make a group of "
                f"{f['prior_smallest']}, and that group's floor is "
                f"{floor:.4f}")
    if f["prior_largest"] is not None:
        return (f"the plausibility prior's ghost gate cannot fire at all — "
                f"its largest group holds {f['prior_largest']} and a group of "
                f"n cannot score below 0.5/(n+1), so the gate needs ten")
    return "the plausibility prior's ghost gate had nothing to say"


def the_surprise(f: dict, *, ran: bool = True) -> str:
    """The thing the night measured that it did not expect.

    Before the night ran there are no props' scores to surprise anyone, and
    the largest thing measured is the prior's gate: it cannot fire at all.
    """
    if not ran and f["prior_largest"] is not None:
        return the_gate_note(f)
    if f["ghosts"]:
        return (f"the plausibility prior called {f['ghosts']} of "
                f"{f['props_scored']} props ghosts")
    if f["fired"]:
        classes = ", ".join(
            f"{name} on {count}" for name, count in
            sorted(f["fired_classes"].items(), key=lambda kv: -kv[1]))
        return (f"the d1-2B delegate flagged {f['fired']} of "
                f"{f['pictures']} pictures ({classes})")
    if f["prior_largest"] is not None:
        return the_gate_note(f)
    if f["probe_accuracy"] is not None:
        return (f"the routed decoy cell answered {f['probe_accuracy']:.0%} "
                f"right on this box")
    return "the night's own numbers were the only ones it had"


def the_question(f: dict) -> str:
    """The decision the night's numbers leave open."""
    if f["ghosts"]:
        return ("what should the night do with a prop the prior calls a ghost "
                "— drop it, or send it to the cloud for a second look?")
    if f["fired"]:
        return ("should the delegate be allowed to reject a picture outright "
                "on the product-picture domain, or keep its vote as it is now "
                "— a signal that decides which sibling wins?")
    if f["prior_gate_live"]:
        return ("should the library approve a second kind as well, or is one "
                "kind of ten enough for the gate to be worth anything?")
    if f["prior_largest"] is not None:
        return ("should the library approve ten objects of one kind, so the "
                "prior's ghost gate can express itself at all?")
    if f["probe_accuracy"] is not None:
        return ("should the courtyard's own decisions also go to the 3B, or "
                "only the cell that names a decoy?")
    return "what should the night do differently with the box it has?"


def the_decision_sentence(f: dict) -> str:
    """Where the night's judgments ran, in the ledger's own units.

    The units are attempts (one `judge.verdict` row per attempt, refusals
    included), because that is what the ledger holds and the letter now
    equals the ledger. The refusal clause only speaks when there were
    refusals.
    """
    refusal = (f", {f['unattributed']} were refusals"
               if f.get("unattributed") else "")
    return (f"{f['local']} of {f['count']} judgments answered locally "
            f"({f['escalated']} went to the cloud{refusal})")


def the_letter(m: dict, ledger: Path | None = None) -> str:
    """The letter, from the morning's numbers and the ledger's counts."""
    f = facts(m, ledger)
    # The library is tonight's wiring, and it belongs in the wiring sentence:
    # the prior now carries the approved objects, so its ghost gate is
    # within reach for the first time.
    library_clause = ""
    if f["prior_gate_live"] and f["library_approved"]:
        library_clause = (f" The library's {f['library_approved']} approved "
                          f"crates are in the prior, so its ghost gate can "
                          f"reach below {f['prior_threshold']}.")
    if f["ran"]:
        lines = [
            "Casey —",
            "",
            f"The night kept {f['kept']} props ({f['names']}) in {f['wall']} "
            f"minutes. The judge's decision model is the {f['model']} now, "
            f"the options go to it in the neutral order, and "
            f"{the_decision_sentence(f)}.{library_clause}",
            "",
            f"What surprised the night: {the_surprise(f)}.",
            "",
            f"One question for you: {the_question(f)}",
            "",
            "The night,",
        ]
    else:
        lines = [
            "Casey —",
            "",
            f"The wiring is in and measured: the decision model is the "
            f"{f['model']} now, the options go to it in the neutral order, "
            f"and the prior and the delegate answer for the props."
            f"{library_clause} "
            f"{f['status_note'] or 'The night itself did not run.'}",
            "",
            f"What surprised me: {the_surprise(f, ran=False)}.",
            "",
            f"One question for you: {the_question(f)}",
            "",
            "The night,",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True,
                        help="where the letter is written")
    parser.add_argument("--morning", type=Path, default=None,
                        help="the night's morning.json (the default)")
    parser.add_argument("--ledger", type=Path, default=None,
                        help="the night's ledger.db (the default is the one "
                             "beside the letter)")
    parser.add_argument("--facts", type=Path, default=None,
                        help="a facts file in the morning's shape, for the "
                             "letter written before the night ran")
    args = parser.parse_args()
    out = args.out.resolve()
    source = args.facts or args.morning or (out / "morning.json")
    ledger = args.ledger or (out / "ledger.db")
    morning = load(Path(source).resolve())
    letter = the_letter(morning, ledger=ledger)
    words = len(letter.split())
    if words > WORD_LIMIT:
        raise SystemExit(f"the letter is {words} words; the limit is {WORD_LIMIT}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "letter.md").write_text(letter.rstrip() + "\n")
    print(f"wrote {out / 'letter.md'} ({words} words) from {source}")
    print(f"decisions counted from {ledger if ledger.exists() else source}")
    print(letter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
