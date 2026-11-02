"""The labels: every director intervention of 2026-11-01.

Each entry is one *episode*: a problem of one kind, from the moment it began
(onset) through the director's first action on it (t_help, the help point the
gate has to beat) to the last action on it (t_end).

Times are Alaska local (the boxes' own zone: AKDT = UTC-8 before 2026-11-01
02:00 local, AKST = UTC-9 after). Two entries fall inside the repeated 01:00
hour, so they carry an exact UTC instant instead; `t_utc` wins over `t_local`.

Sources, verbatim where they exist:
  TEAM.md  = raw/team.md                (ProArt director log)
  LMO      = raw/thor-last-mile-ops.md  (Thor director log)
  DAEMON   = raw/thor-daemon-state.log  (thor-admit, UTC)
  JOURNAL  = raw/thor-journal-*.log     (Thor kernel/systemd, local)
  SEAT     = a seat .out file on ProArt or the Thor
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import epoch_local, epoch_utc  # noqa: E402


def _local(s, tz=None):
    """'2026-11-01 04:11' (or '... 10:46:47') -> epoch seconds, Alaska local.

    Alaska fell back at 2026-11-01 02:00 local, so the local hour 01:00-02:00
    occurs twice; zoneinfo resolves the fold. Every local time used below is
    outside that hour except E01/E03's onsets, which carry an exact UTC
    instant instead.
    """
    fmt = "%Y-%m-%d %H:%M:%S" if s.count(":") == 2 else "%Y-%m-%d %H:%M"
    return epoch_local(s, fmt)


def _utc(s):
    """'2026-11-01T13:11:00Z' -> epoch seconds."""
    return epoch_utc(s)


EPISODES = [
    {
        "id": "E01", "kind": "gpu-floor-block",
        "t_onset":  _utc("2026-11-01T10:23:23Z"),   # 01:23:23 AKST (repeated hour)
        "t_help":   _local("2026-11-01 04:11"),
        "t_end":    _local("2026-11-01 04:11"),
        "what": "thor-admit's 2 GiB lfb floor blocked queued leases while ~100 GB of system "
                "memory was free; the director restarted the daemon with --gpu-floor 0",
        "detail": "daemon lease.waiting_for_gpu_memory at 01:23:23, 01:38:59, 01:43:25, "
                  "01:46:39 with gpu_floor_bytes=2147483648 and gpu_free_bytes 0.51-5.5 GB; "
                  "the fix shows as daemon.started at 04:12:10 with gpu_floor_bytes=0",
        "source": "LMO 04:11; DAEMON lease.waiting_for_gpu_memory; TEAM 04:18",
    },
    {
        "id": "E02", "kind": "quota-exhausted",
        "t_onset":  _local("2026-11-01 02:25"),
        "t_help":   _local("2026-11-01 02:29"),
        "t_end":    _local("2026-11-01 02:29"),
        "what": "mcode Token Plan quota exhausted again; 9 seats had burned it in ~75 min",
        "detail": "TEAM 02:29 'mcode quota hit again 02:25 (9 seats burned it in ~75 min)'; "
                  "the Thor seat seed-oss-fp4.out ends in 'mcode exec failed: ... Token Plan "
                  "usage limit reached ... (2056)' with mtime 02:26",
        "source": "TEAM 02:29; SEAT thor:seed-oss-fp4.out 02:26",
    },
    {
        "id": "E03", "kind": "hung-seat",
        "t_onset":  _utc("2026-11-01T09:28:00Z"),   # '01:28' local, ambiguous hour
        "t_help":   _local("2026-11-01 02:48"),
        "t_end":    _local("2026-11-01 02:48"),
        "what": "hung zcode seats killed: ecology-device, night-v3 (ProArt), coldshelf-bakeoff "
                "(Thor, ETIMEDOUT since 01:28)",
        "detail": "TEAM 02:48 'Killed hung zcode seats: ecology-device, night-v3 (ProArt), "
                  "coldshelf-bakeoff (Thor, ETIMEDOUT since 01:28)'; the ProArt seat "
                  "ecology-device.out has mtime 02:48, the minute the director killed it",
        "source": "TEAM 02:48; SEAT proart:ecology-device.out 02:48",
    },
    {
        "id": "E04", "kind": "duplicate-download",
        "t_onset":  _local("2026-11-01 02:29"),
        "t_help":   _local("2026-11-01 03:21"),
        "t_end":    _local("2026-11-01 04:25"),
        "what": "two fetch_bf16 copies of the Seed-OSS BF16 download ran at once (the seat's "
                "orphan plus the director's own); the orphan was stopped and the download "
                "corrupted from the 02:30-03:30 overlap",
        "detail": "TEAM 03:21 'two fetch_bf16 copies were running (the seat's orphan + mine); "
                  "stopped the orphan and its old single-stream curls; 85 GB free'; "
                  "LMO 02:29 resumed the download, LMO 04:25 stopped it and removed the "
                  "oversized chunks",
        "source": "TEAM 03:21; LMO 02:29 and 04:25",
    },
    {
        "id": "E05", "kind": "lock-starvation",
        "t_onset":  _local("2026-10-31 22:29"),   # 03:53 minus the 5.4 h the lock was held
        "t_help":   _local("2026-11-01 03:53"),
        "t_end":    _local("2026-11-01 03:53"),
        "what": "an orphaned syzygy gt_batch.sh held heavy.lock for 5.4 h and starved the "
                "night-v3 run B; a second job (ecology-device rerun-extra.sh) queued behind it",
        "detail": "LMO 03:53 'It had held heavy.lock for 5.4 h re-rendering canyon, which "
                  "gt_batch2 (thor-admit) had already done at 02:51, and it starved the "
                  "night-v3 run B'; LMO 03:53 also stopped ecology-device rerun-extra.sh "
                  "'waiting on heavy.lock'",
        "source": "LMO 03:53",
    },
    {
        "id": "E06", "kind": "lock-starvation",
        "t_onset":  _local("2026-11-01 06:21"),
        "t_help":   _local("2026-11-01 06:35"),
        "t_end":    _local("2026-11-01 12:15"),
        "what": "the admission FIFO held 8 small requests behind one 58 GB serve.glide lease "
                "that had reserved 40 GB and used 85 MB (head-of-line blocking on the "
                "construct-bind lock); round 11 (backfill, serve coalescing, shrinking "
                "reservations) was queued and went live at 12:15",
        "detail": "the daemon's own queue count starts growing at 06:21:56 with 64-102 GB "
                  "of memory free (waiting 0 -> 1 -> 4 -> 10 by 06:36), so the observable "
                  "onset is 06:21; TEAM 06:35 'thor-admit queue: strict FIFO held 8 small "
                  "requests behind a 58 GB serve.glide (night-v3.heavy reserved 40 GB, used "
                  "85 MB)'; "
                  "LMO 12:15 'daemon swapped to round 11 (backfill, phase/shrink)'",
        "source": "TEAM 06:35; LMO 05:28 and 12:15",
    },
    {
        "id": "E07", "kind": "quota-exhausted",
        "t_onset":  _local("2026-11-01 08:30"),
        "t_help":   _local("2026-11-01 08:33"),
        "t_end":    _local("2026-11-01 08:33"),
        "what": "mcode Token Plan quota exhausted again with 6 seats running; next reset "
                "capped at 4",
        "detail": "TEAM 08:33 'mcode quota hit ~08:30 with 6 seats (~2 h after reset)'; the "
                  "Thor seats cad-bakeoff.out (08:31) and judge-prompt-fix.out (08:34) both "
                  "end in the (2056) quota failure",
        "source": "TEAM 08:33; SEAT thor:cad-bakeoff.out 08:31, thor:judge-prompt-fix.out 08:34",
    },
    {
        "id": "E08", "kind": "quota-exhausted",
        "t_onset":  _local("2026-11-01 09:00"),
        "t_help":   _local("2026-11-01 09:05"),
        "t_end":    _local("2026-11-01 09:05"),
        "what": "the z.ai weekly limit (error 1310) emptied the last-mile zcode session",
        "detail": "LMO 09:05 'the old one emptied when the zcode seats hit the z.ai weekly "
                  "limit at 09:00'; TEAM 09:30 'zcode is out until 2026-11-07 06:37'; the "
                  "ProArt seat night-v3.out holds the error with provider request id "
                  "202611020200016a8d780e46994bc8 (z.ai ids are Beijing time) = 09:00 local",
        "source": "LMO 09:05; TEAM 09:30; SEAT proart:night-v3.out 09:00",
    },
    {
        "id": "E09", "kind": "jax-runaway-hang",
        "t_onset":  _utc("2026-11-01T19:28:50Z"),   # 10:28:50 AKST, first memory decline
        "t_help":   _local("2026-11-01 11:04"),
        "t_end":    _local("2026-11-01 11:04"),
        "what": "lab-motion's MJX/JAX run preallocated the Thor's unified memory; the box "
                "hung, needed a power cycle, and the director's kill was blocked by the "
                "safety classifier",
        "detail": "DAEMON: mem_available 74.6 GB at 10:28:50 -> 32.3 GB at 10:34:52 "
                  "(~7.1 GB/min), 0.5 GB at 10:36:23, watchdog.pressure_outside_leases from "
                  "10:36:50; JOURNAL: desktop greeter restart 10:46:13, wlP1p1s0 Lost carrier "
                  "10:46:47, journal stops 10:49:53; TEAM 11:04 'INCIDENT: lab-motion's "
                  "MJX/JAX run ... the likely cause of the 10:45 hang'; Casey's power cycle "
                  "~10:59; back up 11:07",
        "source": "TEAM 11:04; docs/lab/incident-2026-11-01-jax-hang.md; DAEMON; JOURNAL",
        "cap_t": _local("2026-11-01 10:46:47"),   # the box stopped answering here
    },
    {
        "id": "E10", "kind": "hung-seat",
        "t_onset":  _local("2026-11-01 10:45"),
        "t_help":   _local("2026-11-01 11:47"),
        "t_end":    _local("2026-11-01 11:47"),
        "what": "pi seats thor-admit, coldshelf and syzygy stalled while the Thor was hung; "
                "moved back to mcode",
        "detail": "TEAM 11:47 'pi seats thor-admit, coldshelf, syzygy stalled since the Thor "
                  "hang -> back to mcode (with warp-infinigen: 4 mcode seats)'",
        "source": "TEAM 11:47",
    },
    {
        "id": "E11", "kind": "api-timeout-wifi",
        "t_onset":  _local("2026-11-01 11:49"),
        "t_help":   _local("2026-11-01 13:07"),
        "t_end":    _local("2026-11-01 13:35"),
        "what": "one seat's parallel downloads (scenebloom: checkpoints + torch wheels, "
                "6 MB/s) saturated the Thor's weak Wi-Fi (-78 dBm) and every other seat's API "
                "calls timed out",
        "detail": "JOURNAL: _cmd_abort_notify abort=1 per hour 12:00 278, 13:00 169, "
                  "14:00 137 against a 13-55/h baseline (726 in the pre-hang boot, 705 in the "
                  "next); the 5-minute rolling count leaves the day's median of 8 at 11:49 "
                  "(26) and stays at 20-28 from then on, so 11:49 is the observable onset; TEAM 13:07 'mcode request timeouts: warp-infinigen and thor-admit "
                  "r12 (both relaunched)', 13:17 'Thor-hosted mcode seats all timed out on "
                  "Wi-Fi -> moved to ProArt mcode desks', 13:35 'NETWORK: the Thor is on weak "
                  "Wi-Fi (-78 dBm, 961 driver abort events/hour) ... Rule: large downloads one "
                  "at a time'",
        "source": "TEAM 13:07, 13:17, 13:35; JOURNAL",
    },
    {
        "id": "E12", "kind": "quota-exhausted",
        "t_onset":  _local("2026-11-01 14:20"),
        "t_help":   _local("2026-11-01 14:38"),
        "t_end":    _local("2026-11-01 14:38"),
        "what": "mcode quota hit again (3rd time today); coldshelf, scenebloom and thor-admit "
                "r13 moved to pi desks",
        "detail": "TEAM 14:38 'mcode quota hit again (~14:20, 3rd time today). coldshelf, "
                  "scenebloom, thor-admit r13 -> pi desks'",
        "source": "TEAM 14:38",
    },
    {
        "id": "E13", "kind": "disk-under-floor",
        "t_onset":  _local("2026-11-01 14:58"),
        "t_help":   _local("2026-11-01 15:10"),
        "t_end":    _local("2026-11-01 15:22"),
        "what": "the Thor's disk fell to 27 GB; the external drive was remounted rw at "
                "/mnt/toshiba, thor-bench (18 GB) was archived there, scenebloom was told to "
                "move its 42 GB of downloads, and a hardlink dedupe of 53 venvs freed 77 GB",
        "detail": "board snapshots: Thor disk 32G free at 14:58:57 -> 21G at 15:14:25 "
                  "(-42.6 GB/h), then 49G at 15:20:34, 86G at 15:21:36, 93G at 15:22:37 "
                  "after the dedupe; TEAM 15:10 'DISK 27 GB', 15:22 'hardlink dedupe of 53 "
                  "venvs saved 77 GB (21 -> 93 GB free)'; LMO 15:09, 15:10, 15:21",
        "source": "TEAM 15:10, 15:22; LMO 15:09, 15:10, 15:21; board-history",
    },
]

KINDS = [
    "hung-seat", "quota-exhausted", "api-timeout-wifi", "jax-runaway-hang",
    "lock-starvation", "gpu-floor-block", "disk-under-floor", "duplicate-download",
]

# Which gate conditions could legitimately speak about which kind of problem.
# A speech on the wrong kind of problem is not a catch, however close it falls
# to the director's action: a stale-seat alarm that happens to land two minutes
# before a quota exhaustion is a coincidence, not a catch.
SIGNALS = {
    # the 2 GiB lfb floor held leases back; the queue grew while memory was free
    "E01": ["queue_growing_headroom"],
    # the quota error is a provider failure in the seat transcript
    "E02": ["api_error_burst", "client_lost_burst"],
    # a hung seat stops writing and its API calls fail
    "E03": ["seat_output_stale", "api_error_burst", "client_lost_burst"],
    # two downloads at once fill the disk and saturate the network
    "E04": ["disk_falling_fast", "network_error_burst"],
    # heavy.lock is a file on the box: nothing in the change stream sees it
    "E05": [],
    # the admission FIFO held requests behind one lease while memory was free
    "E06": ["queue_growing_headroom"],
    "E07": ["api_error_burst", "client_lost_burst"],
    "E08": ["api_error_burst", "client_lost_burst"],
    # a runaway allocation takes the memory down, fast
    "E09": ["memory_falling_fast", "box_memory_low", "telemetry_dark"],
    "E10": ["seat_output_stale", "api_error_burst", "client_lost_burst"],
    "E11": ["api_error_burst", "network_error_burst", "client_lost_burst"],
    "E12": ["api_error_burst", "client_lost_burst"],
    "E13": ["box_disk_low", "disk_falling_fast"],
}

# The seats each episode is about, where the director named them.
SEATS = {
    "E03": ["ecology-device", "night-v3", "coldshelf-bakeoff"],
    "E09": ["lab-motion-desk"],
    "E10": ["thor-admit-desk", "coldshelf-bakeoff-desk", "syzygy-keyframes-desk"],
    "E13": ["scenebloom-eval-desk"],
}

for _ep in EPISODES:
    _ep["signals"] = SIGNALS.get(_ep["id"], [])
    _ep["seats"] = SEATS.get(_ep["id"], [])
    _ep["observable"] = bool(_ep["signals"])

if __name__ == "__main__":


    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from common import local_hm
    for e in EPISODES:
        print(f"{e['id']} {e['kind']:20s} onset {local_hm(e['t_onset'])} "
              f"help {local_hm(e['t_help'])} end {local_hm(e['t_end'])}  {e['what'][:60]}")
