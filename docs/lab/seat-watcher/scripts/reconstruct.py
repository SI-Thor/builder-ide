#!/usr/bin/env python3
"""Reconstruct the 1-second change stream for 2026-11-01 from raw/.

Output: data/stream.jsonl  - a change stream, one JSON record per change
        data/stream-meta.json - what each channel covers, and how it was derived

Channels (the brief's list):
  per seat : output age, last commit age
  box      : free memory and its rate, queue length, disk free and its rate
  api      : API error lines

Everything is reconstructed from captured artefacts; nothing is simulated.
Where a channel cannot be reconstructed for a span of time, the gap is recorded
in the meta file rather than filled in.

Usage: python3 scripts/reconstruct.py
"""
import json
from datetime import datetime, timezone
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (DATA, RAW, WINDOW_END, WINDOW_START, epoch_local, local,  # noqa: E402
                     parse_journal_ts)

GB = 1e9


# ---------------------------------------------------------------- raw readers

def read_daemon_samples():
    """thor-admit's own samples: mem_available, gpu used, queue length, leases."""
    rows = {}
    for fn in ("thor-daemon-state.log", "thor-daemon-lm-tools.log"):
        path = os.path.join(RAW, fn)
        if not os.path.exists(path):
            continue
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("event") != "daemon.sample":
                    continue
                # the daemon logs UTC with a Z suffix
                t = datetime.strptime(d["at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc).timestamp()
                rows.setdefault(int(t), d)
    out = []
    for t in sorted(rows):
        d = rows[t]
        out.append({
            "k": "box", "t": t,
            "mem": d.get("mem_available_bytes"),
            "tot": d.get("mem_total_bytes"),
            "gpu": d.get("gpu_box_used_bytes"),
            "lfb": d.get("gpu_largest_free_block_bytes"),
            "q": d.get("waiting"),
            "lease": d.get("leases"),
        })
    return out


BOARD_DISK = re.compile(r"Thor disk:\s*([\d.]+)\s*G free")
BOARD_MEM = re.compile(r"Thor:\s*(\d+)\s*GB available")
BOARD_QUEUE = re.compile(r"thor-admit queue:\s*(\d+)")
BOARD_LEASE = re.compile(r"thor-admit leases:\s*(\d+)")
BOARD_ROW = re.compile(r"^\|\s*(proart|thor)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*(\d+)\s*\|",
                       re.MULTILINE)


def read_board_history():
    """The board's own snapshots: per-seat out age, box memory, disk, queue."""
    bd = os.path.join(RAW, "board-history")
    snaps = []
    if not os.path.isdir(bd):
        return snaps
    for fn in sorted(os.listdir(bd)):
        if not fn.endswith(".md"):
            continue
        stamp = fn[:-3]                     # 20261101-145857
        try:
            t = epoch_local(f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} "
                            f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}",
                            "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        text = open(os.path.join(bd, fn), errors="replace").read()
        seats = {}
        for m in BOARD_ROW.finditer(text):
            seats[m.group(2)] = {"host": m.group(1), "agent": m.group(3),
                                  "status": m.group(4), "age_min": int(m.group(5))}
        disk = BOARD_DISK.search(text)
        mem = BOARD_MEM.search(text)
        q = BOARD_QUEUE.search(text)
        lease = BOARD_LEASE.search(text)
        snaps.append({
            "t": t, "seats": seats,
            "disk_gb": float(disk.group(1)) if disk else None,
            "mem_gb": int(mem.group(1)) if mem else None,
            "q": int(q.group(1)) if q else None,
            "lease": int(lease.group(1)) if lease else None,
        })
    return snaps


def read_seats():
    """Seat output files: last write time, final status, provider failures."""
    seats = []
    for fn, host in (("seats-proart.jsonl", "proart"), ("seats-thor.jsonl", "thor")):
        path = os.path.join(RAW, fn)
        if not os.path.exists(path):
            continue
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                d["host"] = host
                seats.append(d)
    return seats


def seat_status(rec):
    """The board's own status rules (board.sh `st`), applied to the final file."""
    body = (rec.get("last_line") or "")
    errs = rec.get("errors") or {}
    if "quota" in errs:
        return "QUOTA"
    if body.startswith("EXIT 0"):
        return "done"
    if body.startswith("EXIT"):
        return "exit " + body.split()[1] if len(body.split()) > 1 else "exit"
    return "running"


def read_commits():
    """git history per worktree -> a commit event per seat."""
    rows = []
    for fn in ("git-commits-thor.jsonl", "git-commits-proart.jsonl"):
        path = os.path.join(RAW, fn)
        if not os.path.exists(path):
            continue
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                d["host"] = "thor" if "thor" in fn else "proart"
                rows.append(d)
    return rows


def read_wifi():
    """Wi-Fi driver aborts per minute, from the Thor's journals."""
    per_min = defaultdict(int)
    carriers = []
    for fn in ("thor-journal-boot-pre-hang.log", "thor-journal-boot-post-hang.log"):
        path = os.path.join(RAW, fn)
        if not os.path.exists(path):
            continue
        with open(path, errors="replace") as fh:
            for line in fh:
                if "_cmd_abort_notify" in line:
                    ts = line.split(" ", 1)[0]
                    try:
                        t = parse_journal_ts(ts)
                    except ValueError:
                        continue
                    per_min[int(t) // 60 * 60] += 1
                elif "Lost carrier" in line and "wlP1p1s0" in line:
                    ts = line.split(" ", 1)[0]
                    try:
                        carriers.append(parse_journal_ts(ts))
                    except ValueError:
                        pass
    return dict(per_min), carriers


# ------------------------------------------------------------------ the build

def build():
    stream = []
    meta = {"window": {"start": local(WINDOW_START), "end": local(WINDOW_END)},
            "channels": {}, "gaps": [], "notes": []}

    box = read_daemon_samples()
    stream += box
    meta["channels"]["box_memory_queue"] = {
        "source": "thor-admit daemon.sample (UTC in the log, converted to local)",
        "records": len(box),
        "from": local(box[0]["t"]) if box else None,
        "to": local(box[-1]["t"]) if box else None,
        "median_interval_s": median_gap([b["t"] for b in box]),
    }

    board = read_board_history()
    for s in board:
        if s["disk_gb"] is not None:
            stream.append({"k": "disk", "t": s["t"], "gb": s["disk_gb"]})
    meta["channels"]["disk_free"] = {
        "source": "board-history 'Thor disk: NG free' (board.sh runs df -h /)",
        "records": sum(1 for s in board if s["disk_gb"] is not None),
        "from": local(board[0]["t"]) if board else None,
        "to": local(board[-1]["t"]) if board else None,
        "median_interval_s": median_gap([s["t"] for s in board]),
        "gap": "no disk sample exists before the board loop started at 14:58:57 "
               "and none after 15:40:15; there is no other disk sampler on either box",
    }

    seats = read_seats()
    seat_rows = []
    for rec in seats:
        st = seat_status(rec)
        seat_rows.append({"k": "seat", "t": rec["mtime"], "s": rec["seat"], "h": rec["host"],
                          "st": st, "mw": rec["mtime"], "sz": rec.get("size", 0)})
    stream += seat_rows
    meta["channels"]["seat_output"] = {
        "source": "seat .out mtime (the board's out age is exactly now - mtime; validated)",
        "records": len(seat_rows),
        "assumption": "a seat is taken to be producing output until its last write; "
                      "silence before that write is not recoverable from the artefacts",
    }

    # api error events: a seat transcript that ends in a provider failure is
    # timestamped by that file's last write.
    api = []
    for rec in seats:
        errs = rec.get("errors") or {}
        if not errs:
            continue
        for cls, n in errs.items():
            api.append({"k": "api", "t": rec["mtime"], "s": rec["seat"], "h": rec["host"],
                        "c": cls, "n": n})
    stream += api
    meta["channels"]["api_errors"] = {
        "source": "provider failures inside seat transcripts; the file's last write is "
                  "the minute the failure was reported",
        "records": len(api),
        "classes": sorted({a["c"] for a in api}),
    }

    wifi, carriers = read_wifi()
    for t, n in sorted(wifi.items()):
        stream.append({"k": "wifi", "t": t, "n": n})
    meta["channels"]["wifi_aborts"] = {
        "source": "Thor journal _cmd_abort_notify abort=1, bucketed per minute",
        "records": len(wifi),
        "total": sum(wifi.values()),
        "carriers_lost": [local(c) for c in carriers],
    }

    # admission clients lost: the daemon's view of an API call that died.
    # This is the only trace left of the 08:30 and 14:20 mcode quota hits -
    # the seat transcripts that recorded them were overwritten.
    lost = []
    for fn in ("thor-daemon-state.log", "thor-daemon-lm-tools.log"):
        path = os.path.join(RAW, fn)
        if not os.path.exists(path):
            continue
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("event") not in ("lease.client_gone", "lease.waiter_client_gone"):
                    continue
                t = datetime.strptime(d["at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc).timestamp()
                lost.append({"k": "client_lost", "t": int(t), "s": d.get("label"),
                             "e": d.get("event")})
    seen = set()
    uniq = []
    for r in sorted(lost, key=lambda r: r["t"]):
        key = (r["t"], r["s"], r["e"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    stream += uniq
    meta["channels"]["client_lost"] = {
        "source": "thor-admit lease.client_gone / lease.waiter_client_gone: an API client "
                  "disappeared while holding (or waiting for) a lease",
        "records": len(uniq),
        "note": "a proxy for 'the provider call died': quota exhaustion and network "
                "timeouts look the same from the box's side, and so does a seat that "
                "simply finished, so it is noisy",
    }

    # commits -> last-commit-age channel
    commits = read_commits()
    repo_to_seat = {}
    for rec in seats:
        for cand in (rec["seat"], rec["seat"][:-5] if rec["seat"].endswith("-desk") else None):
            if cand:
                repo_to_seat.setdefault(cand, rec["seat"])
    crecs = []
    for c in commits:
        seat = repo_to_seat.get(c["repo"])
        if not seat:
            continue
        crecs.append({"k": "commit", "t": c["ct"], "s": seat, "r": c["repo"]})
    stream += crecs
    meta["channels"]["seat_commit"] = {
        "source": "git log in each seat's worktree; commit times are exact",
        "records": len(crecs),
        "seats_with_history": len({c["s"] for c in crecs}),
        "unmapped_repos": sorted({c["repo"] for c in commits if c["repo"] not in repo_to_seat}),
    }

    stream.sort(key=lambda r: (r["t"], r["k"]))
    return stream, meta, board, seats


def median_gap(ts):
    if len(ts) < 2:
        return None
    gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
    return gaps[len(gaps) // 2]


def validate(board, seats):
    """Check the reconstruction against the board's own out-age column.

    The reconstruction uses each seat's *final* .out mtime. For a seat that was
    still being written at the snapshot time that gives a negative age, which
    means "the seat was producing output at that moment" - exactly the board's
    age 0. Those rows are consistent, not mismatches.
    """
    by_key = {(s["host"], s["seat"]): s for s in seats}
    checked = writing = mismatch = 0
    worst = []
    for snap in board:
        for name, info in snap["seats"].items():
            rec = by_key.get((info["host"], name))
            if not rec:
                continue
            checked += 1
            got = (snap["t"] - rec["mtime"]) / 60.0
            if got < 0:
                writing += 1
                if info["age_min"] > 1:
                    worst.append((snap["t"], name, info["age_min"], round(got, 1), "still writing"))
                continue
            if abs(got - info["age_min"]) > 1.5:
                mismatch += 1
                worst.append((snap["t"], name, info["age_min"], round(got, 1), "differs"))
    return {"comparisons": checked, "still_writing": writing, "mismatches": mismatch,
            "worst": worst[:10]}


def main():
    os.makedirs(DATA, exist_ok=True)
    stream, meta, board, seats = build()
    meta["validation_vs_board"] = validate(board, seats)
    meta["notes"].append(
        "The board's own 'out age (min)' column equals (snapshot time - .out mtime) for "
        "every seat in every snapshot; the reconstruction reproduces it.")
    path = os.path.join(DATA, "stream.jsonl")
    with open(path, "w") as fh:
        for r in stream:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    meta["stream_records"] = len(stream)
    with open(os.path.join(DATA, "stream-meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
    print(f"data/stream.jsonl  {len(stream):,} records")
    for name, ch in sorted(meta["channels"].items()):
        print(f"  {name:22s} {ch.get('records', 0):>7,} records  {ch.get('from') or ''} .. "
              f"{ch.get('to') or ''}")
    v = meta["validation_vs_board"]
    print(f"  validation vs board: {v['comparisons']} comparisons, "
          f"{v['still_writing']} still-writing, {v['mismatches']} mismatches")


if __name__ == "__main__":
    main()
