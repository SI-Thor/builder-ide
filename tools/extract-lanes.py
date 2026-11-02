#!/usr/bin/env python3
"""Reconstruct the director's lanes of 2026-11-01..02 into jobs with actuals.

The general contractor needs a track record before it can bid. This script
builds one from the history that already exists:

  ProArt side (read directly)
    ~/lm-ops/board-history/*.md   the board's minute-by-minute picture of
                                  which lane was running, and on which seat
    ~/lm-ops/wt/*.out             each seat's output file: its birth time
                                  (the launch), its mtime (the exit) and the
                                  `EXIT n` line it ends with
    ~/lm-ops/zqueue.txt           the queue: which seat a lane was launched
                                  on, when, and what happened to it

  Thor side (read over ssh)
    ~/lm-wt/*.out                 the same three facts for the lanes that ran
                                  on the Thor itself

What is measured and what is not
--------------------------------
  * The wall time of a lane is measured: launch to exit, from file times.
  * The promise is NOT in the history. No lane wrote down a crew-time
    estimate before it ran, so the "estimate" in the calibration pairs is the
    seat's plan allowance (mcode's 240-minute timeout, zcode's five-hour
    plan window). It is a proxy, it is labelled as one, and it is not a
    promise.
  * A pi seat is billed in tokens. Its plan window is unknown, so it
    contributes no calibration pair; it still appears in the record.

Usage (on the ProArt, which can see both sides):

    python3 tools/extract-lanes.py -o seed/lanes-2026-11-02.jsonl
    python3 tools/extract-lanes.py --summary

Every number in the output can be traced back to a file and a line, and the
`evidence` field on each lane lists the sources it came from.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

LM_OPS = os.path.expanduser("~/lm-ops")
BOARD = os.path.join(LM_OPS, "board-history")
WT = os.path.join(LM_OPS, "wt")
ZQUEUE = os.path.join(LM_OPS, "zqueue.txt")

THOR_HOST = "thor-lan"

# The seat a lane ran on, as it is written in the queue: "zcode", "mcode",
# "zflash", "zmain" or "pi". Word boundaries only, so "pipeline" is not "pi".
SEAT_RE = re.compile(r"(?<![a-z])(zcode|mcode|zflash|zmain|pi)(?![a-z])")

# The time a lane was launched, as the queue writes it: "LAUNCHED 23:00".
LAUNCHED_RE = re.compile(r"LAUNCHED\s+(\d{1,2}:\d{2})")

# The window this reconstruction covers.
WINDOW_DAYS = (datetime(2026, 11, 1, tzinfo=timezone.utc),
               datetime(2026, 11, 2, 23, 59, tzinfo=timezone.utc))

# The plan allowance of each seat, in crew-minutes, and where it comes from.
# zcode and mcode are flat plans on a five-hour window; mcode's own run
# timeout is 240 minutes (desk.sh, launch-m.sh). A pi seat reports tokens,
# so it has no minute allowance we can reconstruct.
ALLOWANCE = {
    "mcode": (240.0, "mcode exec --timeout 240m (desk.sh, launch-m.sh)"),
    "zcode": (300.0, "flat plan on a five-hour window (Casey's brief)"),
    "zflash": (300.0, "flat plan on a five-hour window (Casey's brief)"),
    "zmain": (300.0, "flat plan on a five-hour window (Casey's brief)"),
    "pi": (None, "a pi seat reports tokens, not minutes: no allowance to reconstruct"),
}

# The job class of each lane (Casey's classes), and the goal line as it can
# be reconstructed. The class is a reading of what the lane was asked to do;
# the goal line is what "done" meant to that lane.
#
#   lab-experiment      run something, measure it, write the note
#   merge-fix           fix a thing and get it merged
#   research-read       read someone else's work and report on it
#   build-feature       build a thing that has to keep working
#   long-run-babysit    sit with a long run and report on it
CLASSES = {
    # --- the Thor's own lanes -------------------------------------------
    "agent-world": ("build-feature", "the Minecraft proof of concept runs and is committed"),
    "cad-bakeoff": ("lab-experiment", "the SolidCraft bakeoff is measured and written up"),
    "coldshelf-bakeoff": ("lab-experiment", "the cold-shelf bakeoff round completes under a lease"),
    "critic-delegate": ("build-feature", "the delegate runs and its results are recorded"),
    "critic-shells": ("build-feature", "the critic's geometry checks are committed and tested"),
    "d1dec-native": ("build-feature", "the native d1 server reaches its decisions-per-second target"),
    "judge-prompt-fix": ("merge-fix", "the judge's prompt ordering is fixed and the effect re-measured"),
    "judge-reversed-replay": ("lab-experiment", "the reversed replay is measured and written up"),
    "missionA-mcode": ("build-feature", "the batched decision path is measured against the target"),
    "missionA-zcode": ("build-feature", "the native decision path is measured against the target"),
    "physag-lite": ("lab-experiment", "the props pass their action check and the numbers are written up"),
    "scenebloom-eval": ("lab-experiment", "the SceneBloom evaluation is measured on the sample set"),
    "seed-oss-fp4": ("lab-experiment", "the fp4 seeds are measured on the Thor"),
    "simready-survey": ("research-read", "the SimReady survey is read and summarised"),
    "syzygy-keyframes": ("build-feature", "the keyframe sampler is committed and runs"),
    "thor-admit": ("build-feature", "the admission daemon builds and its tests pass"),
    "warp-infinigen": ("lab-experiment", "the warp stage is measured and written up"),
    # --- the ProArt's desk lanes ----------------------------------------
    "agent-world-desk": ("build-feature", "the Minecraft proof of concept runs and is committed"),
    "agent-world-gym-desk": ("build-feature", "the Gymnasium environment runs against the live world"),
    "agent-world-reward-desk": ("merge-fix", "the constant-reward bug is found, fixed and committed"),
    "autopilot-study-desk": ("research-read", "the Autopilot approach is read and mapped onto ours"),
    "batched-sim-desk": ("build-feature", "the batched-simulator interface builds and its tests pass"),
    "cad-bakeoff-desk": ("lab-experiment", "the SolidCraft bakeoff is measured and written up"),
    "coldshelf-bakeoff-desk": ("lab-experiment", "the cold-shelf bakeoff round completes under a lease"),
    "crafter-lab-desk": ("lab-experiment", "the Crafter baseline is measured and written up"),
    "crafter-r2": ("lab-experiment", "the Crafter round two is measured and written up"),
    "critic-selfx-desk": ("lab-experiment", "the critic's self-critique is measured against its judge"),
    "drift-detector-desk": ("lab-experiment", "the drift detector is measured on its corpus"),
    "drift-pause-desk": ("merge-fix", "the auto-pause path is fixed, tested and merged"),
    "first-mile": ("research-read", "the voice-first mile is read and its parts mapped"),
    "googl1-digest": ("research-read", "the googleidea write-ups are digested part by part"),
    "ingame-building": ("research-read", "the in-game building ideas are read and mapped"),
    "ingame-phase2-desk": ("research-read", "the second phase of the building work is read and mapped"),
    "judge-calibration": ("lab-experiment", "the judge's calibration is measured against the truth"),
    "judge-prompt-fix-desk": ("merge-fix", "the judge's prompt ordering is fixed and the effect re-measured"),
    "judge-recorder-fix-desk": ("merge-fix", "the recorder names the truth once, and the re-recording is merged"),
    "lab-cascade-desk": ("lab-experiment", "the cascade is measured and the lab note is written"),
    "lab-motion-desk": ("lab-experiment", "the motion bricks are evaluated and rebuilt"),
    "nitrogen-study-desk": ("research-read", "the NitroGen paper and code are read and judged"),
    "open3d-critic-desk": ("lab-experiment", "Open3D is compared with our geometry numbers"),
    "orin-edge": ("research-read", "the Orin edge reflex is read and mapped"),
    "physag-lite-desk": ("lab-experiment", "the props pass their action check and the numbers are written up"),
    "posestream-net-desk": ("build-feature", "the pose-stream network trains and is committed"),
    "precedent-store-desk": ("build-feature", "the precedent store builds and its tests pass"),
    "refit-drift-desk": ("lab-experiment", "the drift refit is measured and written up"),
    "return-ux-desk": ("build-feature", "the return screen reads the community's state"),
    "rewind-select-desk": ("build-feature", "the rewind and select path builds and its tests pass"),
    "rolling-harmony-desk": ("lab-experiment", "the rolling harmony is measured and written up"),
    "roundup-2026-11-01": ("research-read", "the AI search roundup is triaged"),
    "seat-watch-live-desk": ("lab-experiment", "the seat watcher replays the live interventions"),
    "seat-watch-tune-desk": ("lab-experiment", "the seat watcher's thresholds are tuned and measured"),
    "seat-watcher": ("lab-experiment", "the seat watcher replays the day's interventions"),
    "seedbank": ("research-read", "the seed bank is read and written up"),
    "sleep-dreaming-desk": ("research-read", "the SLEEP procedure is read and tried"),
    "stratego-desk": ("research-read", "the Stratego repository is read and mapped onto our simulators"),
    "thor-admit-desk": ("build-feature", "the admission daemon builds and its tests pass"),
    "thor-fp4-desk": ("lab-experiment", "the fp4 sweep is measured and written up"),
    "vibe-sandbox-desk": ("build-feature", "the sandbox skills build and their scripts verify"),
    "vibecode-design-desk": ("research-read", "the vibecode design is read and mapped"),
    "voyager-port-desk": ("research-read", "Voyager's loop is read and mapped onto our system"),
    "warp-infinigen-desk": ("lab-experiment", "the warp stage is measured and written up"),
    "world-snapshot-desk": ("build-feature", "the snapshot and restore path builds and its tests pass"),
    "xp-batch": ("lab-experiment", "the xp batch is measured and written up"),
    "ecology-device": ("lab-experiment", "the ecology device is measured and written up"),
    "missionB-zcode": ("research-read", "the second mission is read and mapped"),
    "missionB-mcode": ("research-read", "the second mission is read and mapped"),
    "general-contractor-desk": ("build-feature", "the general contractor builds and its tests pass"),
}

# A break in the board's presence longer than this counts as the seat having
# exited and been relaunched.
GAP_SECONDS = 180


def iso(t):
    if t is None:
        return None
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except Exception as exc:  # noqa: BLE001 - a missing remote must not stop the extraction
        print(f"warn: {' '.join(cmd)} failed: {exc}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------- board ---

def read_board():
    """lane -> {agent, seen: [timestamps]}"""
    lanes = {}
    if not os.path.isdir(BOARD):
        return lanes
    for name in sorted(os.listdir(BOARD)):
        if not name.endswith(".md"):
            continue
        stamp = datetime.strptime(name[:-3], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
        path = os.path.join(BOARD, name)
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 5 or parts[1] not in ("proart", "thor"):
                    continue
                where, lane, agent = parts[1], parts[2], parts[3]
                if not lane:
                    continue
                key = (where, lane)
                entry = lanes.setdefault(key, {"agents": [], "seen": []})
                if agent not in entry["agents"]:
                    entry["agents"].append(agent)
                entry["seen"].append(stamp)
    return lanes


def presence(seen):
    """first, last, and the number of breaks longer than GAP_SECONDS."""
    if not seen:
        return None, None, 0
    seen = sorted(seen)
    first, last = seen[0], seen[-1]
    breaks = 0
    for a, b in zip(seen, seen[1:]):
        if (b - a).total_seconds() > GAP_SECONDS:
            breaks += 1
    return first, last, breaks


# ------------------------------------------------------------ out files ---

def read_out_stats():
    """file -> {birth, mtime, size}, one stat call for the whole directory.

    %W is the file's birth time (the moment the seat's output file was
    created, which is the launch) and %Y is the last write (the exit).
    """
    files = sorted(glob.glob(os.path.join(WT, "*.out")))
    if not files:
        return {}
    out = run(["stat", "-c", "%n|%W|%Y|%s"] + files)
    stats = {}
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        path, b, m, size = parts
        try:
            birth = datetime.fromtimestamp(int(b), timezone.utc) if int(b) > 0 else None
            mtime = datetime.fromtimestamp(int(m), timezone.utc)
        except ValueError:
            continue
        stats[path] = {"birth": birth, "mtime": mtime, "size": int(size)}
    return stats


def read_out(path, stats):
    """birth, mtime, exit code of a seat's output file."""
    stat = stats.get(path)
    if stat is None:
        return None
    exit_code = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("EXIT "):
                    try:
                        exit_code = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass
    except OSError:
        pass
    return {
        "birth": stat["birth"],
        "mtime": stat["mtime"],
        "exit": exit_code,
        "size": stat["size"],
    }


def read_thor_outs():
    """lane -> out facts, read over ssh from the Thor."""
    script = (
        "for f in $HOME/lm-wt/*.out; do "
        "b=$(stat -c %W $f 2>/dev/null); "
        "if [ -z \"$b\" ] || [ \"$b\" = 0 ]; then b=$(stat -c %Z $f); fi; "
        "m=$(stat -c %Y $f); "
        "e=$(grep -a '^EXIT ' $f 2>/dev/null | tail -1 | awk '{print $2}'); "
        "printf '%s %s %s %s\\n' \"$(basename $f .out)\" \"$b\" \"$m\" \"$e\"; done"
    )
    out = {}
    for line in run(["ssh", "-o", "BatchMode=yes", THOR_HOST, script]).splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        lane, b, m = parts[0], parts[1], parts[2]
        exit_code = None
        if len(parts) > 3 and parts[3].strip():
            try:
                exit_code = int(parts[3])
            except ValueError:
                exit_code = None
        out[lane] = {
            "birth": datetime.fromtimestamp(int(b), timezone.utc) if b.isdigit() else None,
            "mtime": datetime.fromtimestamp(int(m), timezone.utc) if m.isdigit() else None,
            "exit": exit_code,
        }
    return out


# -------------------------------------------------------------- zqueue ---

def read_zqueue():
    """lane -> list of {seat, launched, done, mentions_quota, mentions_relaunch}"""
    lanes = {}
    if not os.path.exists(ZQUEUE):
        return lanes
    with open(ZQUEUE, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            tokens = line.split()
            if len(tokens) < 2:
                continue
            lane = tokens[1]
            entry = lanes.setdefault(lane, {"seats": [], "launches": 0, "done": False,
                                            "quota": 0, "relaunch": 0, "text": line,
                                            "launch_times": []})
            seat = None
            for token in tokens[2:]:
                found = SEAT_RE.search(token)
                if found:
                    seat = found.group(1)
                    break
            if seat and seat not in entry["seats"]:
                entry["seats"].append(seat)
            if "LAUNCHED" in tokens:
                entry["launches"] += 1
                if seat and seat not in entry["seats"]:
                    entry["seats"].append(seat)
                stamp = LAUNCHED_RE.search(line)
                if stamp:
                    entry["launch_times"].append(stamp.group(1))
            if "DONE" in tokens:
                entry["done"] = True
            low = line.lower()
            if "quota" in low or "2056" in low:
                entry["quota"] += 1
            if "relaunch" in low:
                entry["relaunch"] += 1
    return lanes


# ------------------------------------------------------------- merging ---

def seat_for(lane, agents, zq):
    for seat in zq.get("seats", []):
        if seat in ("zcode", "mcode", "zflash", "zmain", "pi"):
            return seat
    for seat in agents:
        if seat in ("zcode", "mcode", "zflash", "zmain", "pi"):
            return seat
    if lane.endswith("-desk"):
        return "zcode"
    return "unknown"


def queued_launch(times, end_hint=None):
    """The earliest plausible launch time the queue records for a lane.

    The queue writes "LAUNCHED 23:00" without a date, so each time is tried
    on both days of the window and the earliest one that is not after the
    lane's last known moment is taken.
    """
    if not times:
        return None
    best = None
    for raw in times:
        try:
            hh, mm = raw.split(":")
            hh, mm = int(hh), int(mm)
        except ValueError:
            continue
        for day in WINDOW_DAYS:
            stamp = day.replace(hour=hh, minute=mm, second=0)
            if end_hint and stamp > end_hint:
                continue
            if best is None or stamp < best:
                best = stamp
    return best


def read_thor_briefs(names):
    """lane -> (title, scope) taken from the lane's own brief on the Thor.

    The brief is what was asked. The queue line is the director's shorthand;
    where both exist the brief wins, and where only the queue exists, the
    queue line is used.
    """
    if not names:
        return {}
    quoted = " ".join("'%s'" % n for n in names)
    script = (
        "for n in %s; do "
        "echo \"@@@ $n\"; "
        "sed -n '1,16p' $HOME/lm-wt/$n/BRIEF.md 2>/dev/null; "
        "done" % quoted
    )
    text = run(["ssh", "-o", "BatchMode=yes", THOR_HOST, script])
    briefs = {}
    current = None
    buf = []
    for line in text.splitlines():
        if line.startswith("@@@ "):
            if current:
                briefs[current] = buf
            current = line[4:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current:
        briefs[current] = buf

    out = {}
    for lane, lines in briefs.items():
        title = ""
        body = []
        for line in lines:
            stripped = line.strip()
            if not title and stripped.startswith("#"):
                title = stripped.lstrip("# ").strip()
                continue
            if stripped and not stripped.startswith("#"):
                body.append(stripped)
        scope = " ".join(body)
        if len(scope) > 400:
            scope = scope[:400].rstrip() + " ..."
        out[lane] = (title, scope)
    return out


def build_lanes():
    board = read_board()
    stats = read_out_stats()
    thor = read_thor_outs()
    zq = read_zqueue()

    lanes = {}

    # ProArt lanes: the board knows them, and the out file knows the exit.
    for (where, name), info in board.items():
        first, last, breaks = presence(info["seen"])
        out = read_out(os.path.join(WT, name + ".out"), stats)
        lanes[name] = {
            "where": where,
            "agents": info["agents"],
            "board_first": first,
            "board_last": last,
            "board_breaks": breaks,
            "out": out,
            "side": "proart",
        }

    # Thor lanes: the out file on the Thor knows the launch and the exit.
    for name, out in thor.items():
        if name in lanes:
            continue
        lanes[name] = {
            "where": "thor",
            "agents": [],
            "board_first": None,
            "board_last": None,
            "board_breaks": 0,
            "out": out,
            "side": "thor",
        }

    briefs = read_thor_briefs(sorted(CLASSES.keys()))

    records = []
    for name, info in sorted(lanes.items()):
        if name not in CLASSES:
            continue
        job_class, goal = CLASSES[name]
        out = info["out"] or {}
        if out.get("exit") is None:
            # Still running when the snapshot was taken: no outcome, no
            # final wall time. Left out of the track record.
            continue
        z = zq.get(name, {})

        seat = seat_for(name, info["agents"], z)
        start_candidates = [info["board_first"]]
        if out.get("birth"):
            start_candidates.append(out["birth"])
        queued = queued_launch(z.get("launch_times", []), end_hint=info["board_last"] or (out or {}).get("mtime"))
        if queued:
            start_candidates.append(queued)
        end_candidates = []
        if out.get("mtime"):
            end_candidates.append(out["mtime"])
        if info["board_last"]:
            end_candidates.append(info["board_last"])
        start = min([c for c in start_candidates if c], default=None)
        end = max([c for c in end_candidates if c], default=None)
        if not start or not end or end < start:
            continue

        wall_min = (end - start).total_seconds() / 60.0
        exit_code = out.get("exit")
        still_running = exit_code is None
        if still_running:
            outcome = "running"
            crossed = False
        elif exit_code == 0:
            outcome = "passed"
            crossed = True
        elif exit_code == 4:
            outcome = "quota-stop"
            crossed = False
        elif exit_code == 143:
            outcome = "killed"
            crossed = False
        else:
            outcome = "failed"
            crossed = False

        launches = z.get("launches", 0)
        relaunches = max(info["board_breaks"], max(0, launches - 1), z.get("relaunch", 0))
        quota_stops = z.get("quota", 0) + (1 if exit_code == 4 else 0)

        allowance, allowance_basis = ALLOWANCE.get(seat, (None, "unknown seat"))

        # The crew-time we can measure for a historical lane is the wall time
        # of its LAST run: the seat's output file is recreated at every
        # launch, so its birth is the last launch and its last write is the
        # exit. The lane's total occupancy (first launch to exit, including
        # the waits between relaunches) is recorded separately, because waits
        # are not work and must not be calibrated against.
        last_run_min = None
        if out.get("birth") and out.get("mtime") and out["mtime"] >= out["birth"]:
            last_run_min = (out["mtime"] - out["birth"]).total_seconds() / 60.0
        crew_min = last_run_min if last_run_min is not None else wall_min
        if allowance is None:
            method = "wall clock of the last run (a pi seat reports tokens, not minutes)"
        else:
            method = "wall clock of the last run: launch to exit"

        evidence = []
        if info["side"] == "proart":
            evidence.append(f"~/lm-ops/board-history/*.md (presence {iso(info['board_first'])}..{iso(info['board_last'])})")
            evidence.append(f"~/lm-ops/wt/{name}.out (exit {exit_code})")
        else:
            evidence.append(f"thor-lan:~/lm-wt/{name}.out (exit {exit_code})")
        if name in zq:
            evidence.append("~/lm-ops/zqueue.txt")

        records.append({
            "lane": name,
            "where": info["where"],
            "seat": seat,
            "class": job_class,
            "title": name,
            "scope": (briefs.get(name, ("", ""))[1] or z.get("text", "")[:400].strip()),
            "brief_title": briefs.get(name, ("", ""))[0],
            "goal_line": goal,
            "acceptance": {"kind": "report", "cmd": "", "metric": "", "threshold": None,
                           "note": "reconstructed: the seat's own report and its exit code"},
            "allowance_min": allowance,
            "estimate_basis": allowance_basis,
            "actual_crew_min": round(crew_min, 1),
            "actual_job_min": round(crew_min, 1),
            "lane_span_min": round(wall_min, 1),
            "crew_time_method": method,
            "tokens": None,
            "late_days": 0,
            "relaunches": relaunches,
            "quota_stops": quota_stops,
            "exit_code": exit_code if exit_code is not None else -1,
            "outcome": outcome,
            "crossed_goal_line": crossed,
            # A run that finished its work without being cut short is clean
            # enough to calibrate a bid from. The interrupted runs stay in
            # the record — they are the debt — but they do not set the bid.
            "calibratable": bool(crossed and relaunches == 0 and quota_stops == 0),
            "reconstructed": True,
            "start": iso(start),
            "end": iso(end),
            "evidence": evidence,
            "notes": (f"crew-time is the wall time of the last run ({crew_min:.1f} min); the lane's "
                       f"total occupancy, including the waits between relaunches, was {wall_min:.1f} min"),
        })
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", help="write JSONL here (default: stdout)")
    parser.add_argument("--summary", action="store_true", help="print a summary table instead")
    args = parser.parse_args()

    records = build_lanes()
    records.sort(key=lambda r: (r["start"] or "", r["lane"]))

    if args.summary:
        print(f"{'lane':<32} {'seat':<7} {'class':<20} {'wall(min)':>9} {'exit':>5} {'relaunch':>8} outcome")
        for r in records:
            print(f"{r['lane']:<32} {r['seat']:<7} {r['class']:<20} {r['actual_crew_min']:>9.1f} "
                  f"{r['exit_code']:>5} {r['relaunches']:>8} {r['outcome']}")
        print(f"\n{len(records)} lanes")
        return

    text = "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {len(records)} lanes to {args.out}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
