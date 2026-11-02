#!/usr/bin/env python3
"""replay.py: the dry run.

Two modes, both read-only:

* **the recorded day** (``--stream``): replay the lab's own change stream
  through this watcher's engine and check that the result is the lab's
  result.  The lab's fixture is the recorded day of 2026-11-01, so this is
  the dry run the brief asks for: the same numbers out of the live engine.

* **the board's own history** (``--board-history``): read the snapshots the
  board wrote to ``~/lm-ops/board-history/`` and run the box conditions over
  them.  The board is a coarser series than the daemon's (~60 s apart, and
  whole-GB disk figures), so this is the weaker of the two, and the report
  says what it can and cannot reproduce.

Usage:

    python3 tools/seat-watch/replay.py --verify
    python3 tools/seat-watch/replay.py --verify --json /tmp/replay.json
    python3 tools/seat-watch/replay.py --board-history ~/lm-ops/board-history
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LAB = os.path.join(ROOT, "docs", "lab", "seat-watcher")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(LAB, "scripts"))

import seatwatch  # noqa: E402
from seatwatch import Engine, DEFAULTS, local_str  # noqa: E402


def load_stream(path):
    rows = []
    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    rows.sort(key=lambda r: r.get("t", 0))
    return rows


def replay_gates(rows, window, params=None, gates=("a", "b", "ab", "bplus", "abplus")):
    """Walk the stream one second at a time, exactly as the lab's gates.py does.

    One engine per gate, because a gate's latches belong to that gate: the
    lab creates a fresh set of latches for each of its six gates.

    ``params`` is the lab's own parameter set (from its events.json), so the
    replay runs the lab's gate with the lab's thresholds -- including its
    30 GB disk floor, which the live watcher lowers to the brief's 20 GB.
    """
    p = dict(DEFAULTS)
    if params:
        p.update(params)
    out = {}
    for which in gates:
        engine = Engine(p)
        events = []
        i = 0
        t = int(window[0])
        t_end = int(window[1])
        while t <= t_end:
            while i < len(rows) and rows[i].get("t", 0) <= t:
                engine.feed(rows[i])
                i += 1
            events.extend(engine.step(t, which=which))
            t += 1
        for e in events:
            e["time"] = local_str(e["t"])
        out[which] = events
    # the lab's (a') variant: the level gate restricted to seats still alive
    out["a_live"] = [e for e in out["a"]
                     if e["cond"] != "seat_output_stale" or e.get("alive")]
    return out


def key_of(e):
    """The physics of a speech: when, what, which seat, what value."""
    return (e["t"], e["cond"], e.get("seat"), e.get("value"))


def compare(mine, theirs):
    """How the replay's speeches differ from the lab's.

    The comparison is on the physics of a speech -- when, which condition,
    which seat, what value -- and not on the order the speeches came in: the
    lab's scorer matches each help point to the earliest speech, so the order
    of the list does not change a score.
    """
    a = [key_of(e) for e in mine]
    b = [key_of(e) for e in theirs]
    only_mine = [x for x in a if x not in b]
    only_theirs = [x for x in b if x not in a]
    return {
        "mine": len(a),
        "theirs": len(b),
        "same": sorted(a) == sorted(b),
        "same_order": a == b,
        "only_mine": only_mine[:10],
        "only_theirs": only_theirs[:10],
    }


def verify(args):
    """Replay the recorded day and check it against the lab's own outputs."""
    import common
    import labels
    import score as score_mod

    stream_path = args.stream or os.path.join(LAB, "data", "stream.jsonl")
    events_path = args.events or os.path.join(LAB, "data", "events.json")
    result_path = args.result or os.path.join(LAB, "RESULT.json")

    rows = load_stream(stream_path)
    window = (common.WINDOW_START, common.WINDOW_END)
    theirs = json.load(open(events_path))
    # the lab's own parameters, so the replay is the lab's gate and not ours
    mine = replay_gates(rows, window, params=theirs.get("params"))

    # The lab's (abplus) gate: its gates.py runs the level gate for "a" and
    # "ab" only, so its "abplus" carries no level condition at all -- it is
    # its "bplus" with a different label.  The replay computes the gate the
    # label says.  The defect is recorded here and in the report, not hidden.
    level_conds = {"box_memory_low", "box_disk_low", "seat_output_stale"}
    defects = []
    lab_abplus = theirs["gates"]["abplus"]["events"]
    if not any(e["cond"] in level_conds for e in lab_abplus):
        defects.append({
            "gate": "abplus",
            "what": "the lab's abplus gate has no level condition: its gates.py "
                    "runs the level block for 'a' and 'ab' only, so abplus is "
                    "bplus with a different label",
            "lab_speeches": len(lab_abplus),
            "lab_bplus_speeches": len(theirs["gates"]["bplus"]["events"]),
            "lab_ab_speeches": len(theirs["gates"]["ab"]["events"]),
            "replay_speeches": len(mine["abplus"]),
        })

    report = {"stream": stream_path, "events": events_path, "result": result_path,
              "records": len(rows), "defects": defects, "gates": {}}
    all_ok = True
    for which, events in mine.items():
        lab_events = theirs["gates"][which]["events"]
        cmp_ = compare(events, lab_events)
        report["gates"][which] = cmp_
        if which == "abplus" and defects:
            # the lab's abplus is missing the level conditions, so the replay
            # is checked against what the gate should be: the lab's "ab" plus
            # the telemetry-dark events of its "bplus".
            expect = list(theirs["gates"]["ab"]["events"])
            expect += [e for e in theirs["gates"]["bplus"]["events"]
                       if e["cond"] == "telemetry_dark"]
            cmp_ = compare(mine["abplus"], expect)
            cmp_["note"] = ("compared with the lab's ab plus its bplus's "
                            "telemetry-dark events, because the lab's abplus "
                            "is missing its level conditions")
            report["gates"][which] = cmp_
        if not report["gates"][which]["same"]:
            all_ok = False

    # the lab's own scorer, run on the replay's events
    episodes = sorted(labels.EPISODES, key=lambda e: e["t_help"])
    report["scores"] = {}
    for which, events in mine.items():
        s = score_mod.score_gate(which, events, episodes)
        lab_score = json.load(open(result_path))["gates"][which]
        row = {}
        defective = (which == "abplus" and defects)
        for rule in ("time_only", "kind_aware", "episode"):
            r = s[rule]
            lr = lab_score[rule]
            row[rule] = {
                "speaks": [r["speaks"], lr["speaks"]],
                "tp": [r["tp"], lr["tp"]],
                "fp": [r["fp"], lr["fp"]],
                "fn": [r["fn"], lr["fn"]],
                "precision": [r["precision"], lr["precision"]],
                "recall": [r["recall"], lr["recall"]],
                "false_positive_rate": [r["false_positive_rate"], lr["false_positive_rate"]],
                "false_alarms_per_hour": [r["false_alarms_per_hour"], lr["false_alarms_per_hour"]],
            }
            for k in row[rule]:
                if row[rule][k][0] != row[rule][k][1] and not defective:
                    all_ok = False
        if defective:
            # the lab scored its defective abplus, so its numbers cannot match
            # and are reported rather than compared
            row["note"] = ("the lab's abplus is missing its level conditions, "
                           "so its score is the score of its bplus")
        else:
            row["lead_minutes"] = [s["episode"]["lead_minutes"],
                                   lab_score["episode"]["lead_minutes"]]
            row["stall_minutes_saved"] = [s["episode"]["stall_minutes_saved"],
                                          lab_score["episode"]["stall_minutes_saved"]]
            if s["episode"]["lead_minutes"] != lab_score["episode"]["lead_minutes"]:
                all_ok = False
            if s["episode"]["stall_minutes_saved"] != lab_score["episode"]["stall_minutes_saved"]:
                all_ok = False
        report["scores"][which] = row

    report["ok"] = all_ok
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=1)
    print("replay of %s: %d records, window %s -> %s"
          % (stream_path, len(rows), local_str(window[0]), local_str(window[1])))
    print("%-8s %-16s %-16s %s" % ("gate", "speeches (mine)", "speeches (lab)", "same?"))
    for which in ("a", "b", "ab", "bplus", "abplus", "a_live"):
        g = report["gates"][which]
        print("%-8s %-16d %-16d %s" % (which, g["mine"], g["theirs"],
                                       "yes" if g["same"] else "NO"))
        if not g["same"]:
            for x in g["only_mine"][:5]:
                print("      only in the replay:", x)
            for x in g["only_theirs"][:5]:
                print("      only in the lab:   ", x)
    print()
    if report["defects"]:
        for d in report["defects"]:
            print("DEFECT in the lab's own gate: %s" % d["what"])
            print("  the lab's abplus has %d speeches (its bplus has %d, its ab has %d); the replay computes %d, which is the gate the label names."
                  % (d["lab_speeches"], d["lab_bplus_speeches"],
                     d["lab_ab_speeches"], d["replay_speeches"]))
        print()
    b = report["scores"].get("b", {})
    if b:
        ep = b.get("episode", {})
        print("rate gate (b), the lab's own scorer on the replay's events:")
        print("  speeches %s (lab %s)   caught %s/%s   recall %s (lab %s)"
              % (ep["speaks"][0], ep["speaks"][1], ep["tp"][0], ep["tp"][0] + ep["fn"][0],
                 ep["recall"][0], ep["recall"][1]))
        print("  mean lead %s min (lab %s)   stall saved %s min (lab %s)"
              % (b["lead_minutes"][0]["mean"], b["lead_minutes"][1]["mean"],
                 b["stall_minutes_saved"][0]["total"], b["stall_minutes_saved"][1]["total"]))
    print()
    print("VERDICT:", "the replay reproduces the lab" if all_ok else "MISMATCH")
    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# the board's own history
# ---------------------------------------------------------------------------
BOARD_FILE = re.compile(r"^(\d{8})-(\d{6})\.md$")
BOARD_MEM = re.compile(r"^- Thor:\s+([\d.]+)\s*GB available")
BOARD_DISK = re.compile(r"^- Thor disk:\s+([\d.]+)\s*G free")
BOARD_SEAT = re.compile(r"^\|\s*(proart|thor)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
                        r"\s*([^|]+?)\s*\|\s*(\d+)\s*\|")


def board_epochs(path):
    """A board snapshot's name -> its epoch seconds (the box's local time)."""
    m = BOARD_FILE.match(os.path.basename(path))
    if not m:
        return None
    import datetime
    stamp = m.group(1) + m.group(2)
    dt = datetime.datetime.strptime(stamp, "%Y%m%d%H%M%S")
    try:
        from zoneinfo import ZoneInfo
        return dt.replace(tzinfo=ZoneInfo("America/Anchorage")).timestamp()
    except Exception:
        return dt.timestamp()


def board_series(directory):
    """The board's own box series: (t, mem_bytes, disk_gb) per snapshot."""
    out = []
    for name in sorted(os.listdir(directory)):
        if not BOARD_FILE.match(name):
            continue
        path = os.path.join(directory, name)
        t = board_epochs(path)
        if t is None:
            continue
        mem = disk = None
        try:
            with open(path, errors="replace") as fh:
                for line in fh:
                    m = BOARD_MEM.match(line)
                    if m:
                        mem = float(m.group(1)) * 1e9
                        continue
                    m = BOARD_DISK.match(line)
                    if m:
                        disk = float(m.group(1))
        except OSError:
            continue
        out.append({"t": t, "mem": mem, "disk_gb": disk, "file": name})
    return out


def board_history(directory):
    """Run the box conditions over the board's own history."""
    series = board_series(directory)
    if not series:
        print("no board snapshots in", directory)
        return 1
    engine = Engine(DEFAULTS)
    events = []
    t0 = int(series[0]["t"])
    t1 = int(series[-1]["t"])
    i = 0
    t = t0
    while t <= t1:
        while i < len(series) and series[i]["t"] <= t:
            s = series[i]
            if s["mem"] is not None:
                engine.feed({"k": "box", "t": s["t"], "mem": s["mem"]})
            if s["disk_gb"] is not None:
                engine.feed({"k": "disk", "t": s["t"], "gb": s["disk_gb"]})
            i += 1
        events.extend(engine.step(t, which="live"))
        t += 1
    span = (t1 - t0) / 3600.0
    print("board history: %d snapshots, %s -> %s (%.2f h)"
          % (len(series), local_str(t0), local_str(t1), span))
    gaps = [b["t"] - a["t"] for a, b in zip(series, series[1:])]
    if gaps:
        print("  snapshot spacing: min %.0fs max %.0fs median %.0fs"
              % (min(gaps), max(gaps), sorted(gaps)[len(gaps) // 2]))
    print("  box conditions fired %d times" % len(events))
    for e in events:
        print("    %s  %-22s value=%s  %s"
              % (local_str(e["t"]), e["cond"], e.get("value"), e["say"]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true",
                    help="replay the recorded day and compare with the lab")
    ap.add_argument("--stream", default=None, help="the lab's stream.jsonl")
    ap.add_argument("--events", default=None, help="the lab's events.json")
    ap.add_argument("--result", default=None, help="the lab's RESULT.json")
    ap.add_argument("--board-history", default=None,
                    help="a directory of board snapshots to replay")
    ap.add_argument("--json", default=None, help="write the verification report here")
    args = ap.parse_args(argv)
    if args.board_history:
        return board_history(args.board_history)
    if args.verify:
        return verify(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
